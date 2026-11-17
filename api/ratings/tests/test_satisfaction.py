"""Client satisfaction (US-ANL metrics, issue I-07): one question, 0 to 10 with an optional comment, through the
notifications inbox after a released report, a paid family bill or a completed project; the score in analytics."""
import uuid
from datetime import date, datetime, timedelta, timezone as dt_tz

import pytest
from django.db import DatabaseError, transaction

from accounts.models import Person, RoleGrant
from analytics import metrics as m
from audit.models import AuditEvent
from core.errors import Invalid, NotFound, StateConflict
from core.events import publish
from notifications.models import Message
from ratings import services
from ratings.models import SatisfactionSurvey


def _client(gh):
    p = Person.objects.create(email=f"nps-{uuid.uuid4().hex[:10]}@example.com", full_name="Esi Nps",
                              home_country=gh)
    RoleGrant.objects.create(person=p, role="CL")
    return p


def _released(client, gh, **extra):
    rid = uuid.uuid4()
    publish("report.released", rid, {"report_id": rid, "client_id": client.pk, "country": gh.code,
                                     "reference": "RPT-GH-TEST-1", "supersedes_id": None, **extra})
    return rid


def test_released_report_asks_once_in_inbox(seeded, gh):
    """I-07: a released report asks the client the one question in the inbox; never in orange; once per item."""
    c = _client(gh)
    rid = _released(c, gh)
    sv = SatisfactionSurvey.objects.get(client=c, context_type="report", context_id=rid)
    assert sv.score is None and sv.country == gh
    msg = Message.objects.get(person=c, template="satisfaction_question", subject_id=str(sv.pk))
    assert msg.channel == "in_app" and msg.needs_action is False and "0" in msg.body and "10" in msg.body
    assert msg.link == f"/satisfaction/{sv.pk}"
    services.on_report_released_ask({"report_id": rid, "client_id": c.pk, "country": gh.code})
    assert SatisfactionSurvey.objects.filter(client=c).count() == 1


def test_corrections_and_frequent_events_do_not_ask_again(seeded, gh):
    """A corrected report is not asked again, and a client is asked at most once in the configured gap
    [TO VERIFY], so a monthly fee does not ask every month."""
    c = _client(gh)
    _released(c, gh, supersedes_id=str(uuid.uuid4()))
    assert not SatisfactionSurvey.objects.filter(client=c).exists()
    _released(c, gh)
    _released(c, gh)
    assert SatisfactionSurvey.objects.filter(client=c).count() == 1


def test_paid_family_bill_and_completed_project_ask(seeded, gh, publish_config):
    """I-07: a family payment confirmed as paid and a completed project ask the client; other payment states do
    not."""
    from construction.models import Project
    from fees.models import Payment

    publish_config(gh, ratings={"satisfaction_gap_days": 0})
    asked = SatisfactionSurvey.objects.values_list("context_id", flat=True)
    pay = Payment.objects.filter(status__in=["paid", "receipted"]).exclude(pk__in=asked).first()
    assert pay is not None
    assert services.on_fee_payment_paid_ask({"to": "receipted", "id": pay.pk}) is None
    sv = services.on_fee_payment_paid_ask({"to": "paid", "id": pay.pk})
    assert sv.client_id == pay.invoice.client_id and sv.context_type == "fee_payment"
    p = Project.objects.filter(status="completed").exclude(pk__in=asked).first()
    if p is None:
        p = Project.objects.filter(status="active").exclude(pk__in=asked).first()
        Project.objects.filter(pk=p.pk).update(status="completed", completed_at=p.started_at)
    sv = services.on_project_completed_ask({"id": p.pk})
    assert sv.client_id == p.client_id and sv.context_type == "project"


def test_answer_once_from_zero_to_ten(seeded, gh, api):
    """I-07: the client answers once, 0 to 10, with an optional comment; the answer never changes; nobody else
    can answer or see it; the audit has the score but not the comment."""
    c = _client(gh)
    _released(c, gh)
    sv = SatisfactionSurvey.objects.get(client=c)
    me = api(c)
    listed = me.get("/v1/satisfaction-surveys?open=true").json()
    assert [x["id"] for x in listed["results" if "results" in listed else "items"]] == [str(sv.pk)]
    assert me.post(f"/v1/satisfaction-surveys/{sv.pk}/answer", {"score": 11}, format="json").status_code == 400
    other = _client(gh)
    assert api(other).post(f"/v1/satisfaction-surveys/{sv.pk}/answer", {"score": 5}, format="json") \
        .status_code == 404
    r = me.post(f"/v1/satisfaction-surveys/{sv.pk}/answer", {"score": 9, "comment": "Fast and clear."},
                format="json")
    assert r.status_code == 200 and r.json()["score"] == 9 and r.json()["answered_at"]
    assert me.post(f"/v1/satisfaction-surveys/{sv.pk}/answer", {"score": 3}, format="json").status_code == 409
    a = AuditEvent.objects.get(action="satisfaction.answered", entity_id=str(sv.pk))
    assert a.data["score"] == 9 and "Fast and clear." not in str(a.data)
    with pytest.raises(DatabaseError), transaction.atomic():
        SatisfactionSurvey.objects.filter(pk=sv.pk).update(score=2)


def test_answer_refusals_in_service(seeded, gh):
    c = _client(gh)
    _released(c, gh)
    sv = SatisfactionSurvey.objects.get(client=c)
    with pytest.raises(Invalid):
        services.answer_satisfaction(sv, c, score=-1)
    with pytest.raises(NotFound):
        services.answer_satisfaction(sv, _client(gh), score=5)
    services.answer_satisfaction(sv, c, score=0)
    with pytest.raises(StateConflict):
        services.answer_satisfaction(sv, c, score=10)


def test_satisfaction_score_in_analytics(seeded, gh, api, people):
    """US-ANL metrics, I-07: asked, answers, promoters, passives, detractors and the net promoter score, by month,
    country and what was asked about; no comment ever appears."""
    at = datetime(2032, 2, 10, 9, tzinfo=dt_tz.utc)
    scores = [10, 9, 9, 8, 7, 6, 3, None]  # 7 answers, 1 open
    for s in scores:
        SatisfactionSurvey.objects.create(country=gh, client=_client(gh), context_type="report",
                                          context_id=uuid.uuid4(), asked_at=at, score=s,
                                          comment="secret words" if s is not None else "",
                                          answered_at=at + timedelta(hours=1) if s is not None else None)
    f = m.Filters(date(2032, 2, 1), date(2032, 2, 29), ["GH"])
    rows = m.METRICS["client_satisfaction"].run(f)
    assert len(rows) == 1
    r = rows[0]
    assert (r["month"], r["country"], r["context"]) == ("2032-02", "GH", "report")
    assert r["asked"] == 8 and r["answers"] == 7 and r["response_rate_pct"] == 87.5
    assert (r["promoters"], r["passives"], r["detractors"]) == (3, 2, 2)
    assert r["nps"] == round(100.0 * (3 - 2) / 7, 1) and r["average_score"] == round(52 / 7, 1)
    assert m.METRICS["client_satisfaction"].run(m.Filters(date(2032, 2, 1), date(2032, 2, 29), ["GH"],
                                                          line="family")) == []
    body = api(people["admin"]).get("/v1/analytics/metrics/client_satisfaction",
                                    {"date_from": "2032-02-01", "date_to": "2032-02-29", "country": "GH"}).json()
    assert body["rows"][0]["nps"] == r["nps"] and "secret words" not in str(body)
