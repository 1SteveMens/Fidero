"""Monthly random re-checks (FR-RPT-012, RUL-32, ADR-25) and their incidents."""
from datetime import date

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.models import AuditEvent
from cases.tests.helpers import accepted_case, licensed
from core.errors import DomainError
from core.ids import uuid7
from core.models import OutboxEvent
from reports import services
from reports.models import Incident, Recheck, RecheckCandidate, RecheckDraw
from reports.seed import release_demo_case

NEXT = date(2031, 1, 1)


def _released(api, people, gh):
    case = accepted_case(api, people, gh)
    r = release_demo_case(case, gh, people)
    RecheckCandidate.objects.filter(subject_id=r.pk).update(sample_month=NEXT)
    return r


def _draw_one(api, people, gh):
    r = _released(api, people, gh)
    d = services.draw(gh, NEXT, by=people["reviewer2"])
    return r, d, d.rechecks.get()


def test_monthly_draw_is_recorded_and_cannot_be_redrawn(seeded, api, people, gh):
    """US-RPT-012 AC1, TC-RUL-32-01, TC-RUL-32-04, TC-RUL-32-05: the share is drawn at random with the seed
    and population hash recorded, at least one item; a second draw is refused and audited; nobody is told."""
    from notifications.models import Message

    r = _released(api, people, gh)
    services.note_condition_closed({"condition_id": str(uuid7()), "report_id": str(r.pk),
                                    "closed_at": timezone.now().replace(year=2031, month=1, day=10).isoformat(),
                                    "closed_by_id": str(people["cm"].pk)})
    before = Message.objects.filter(person__in=[people["lawyer"], people["surveyor"]]).count()
    resp = api(people["reviewer2"]).post("/v1/rechecks/draws", {"month": "2031-01-01", "country": "GH"},
                                         format="json")
    assert resp.status_code == 201, resp.content
    d = RecheckDraw.objects.get(pk=resp.json()["id"])
    assert d.population_count == 2 and d.selected_count == 1 and len(d.seed) == 64 and len(d.population_sha256) == 64
    assert Message.objects.filter(person__in=[people["lawyer"], people["surveyor"]]).count() == before
    again = api(people["reviewer2"]).post("/v1/rechecks/draws", {"month": "2031-01-01", "country": "GH"},
                                          format="json")
    assert again.status_code == 409
    assert AuditEvent.objects.filter(action="recheck.redraw_refused").exists()
    with pytest.raises(Exception), transaction.atomic():
        RecheckDraw.objects.filter(pk=d.pk).update(selected_count=0)
    empty = services.draw(gh, date(2030, 6, 1))
    assert empty.population_count == 0 and empty.selected_count == 0
    assert services._pick(bytes.fromhex(d.seed), ["a", "b", "c"], 2) == services._pick(bytes.fromhex(d.seed),
                                                                                         ["a", "b", "c"], 2)


def test_assignment_refused_for_linked_or_unlicensed_people(seeded, api, people, gh):
    """US-RPT-012 AC2, TC-RUL-32-02: the signing lawyer, a professional who worked on the case, a person sharing
    an organisation, an expired licence are refused; an unlinked licensed lawyer is accepted."""
    from accounts.models import Membership, Organisation

    _r, _d, rc = _draw_one(api, people, gh)
    rv = api(people["reviewer2"])
    resp = rv.post(f"/v1/rechecks/{rc.pk}/assignments", {"person_id": str(people["lawyer"].pk), "role": "LW"},
                   format="json")
    assert resp.status_code == 409 and resp.json()["code"] == "recheck-linked"
    expired = licensed(gh, "LW", "old.lawyer@example.com", "Old Lawyer", days=-3)
    resp = rv.post(f"/v1/rechecks/{rc.pk}/assignments", {"person_id": str(expired.pk), "role": "LW"}, format="json")
    assert resp.status_code == 409 and resp.json()["code"] == "licence-invalid"
    colleague = licensed(gh, "SV", "colleague@example.com", "Firm Colleague")
    org = Organisation.objects.create(name="Survey Partners", kind="survey_firm", country=gh)
    Membership.objects.create(organisation=org, person=colleague)
    Membership.objects.create(organisation=org, person=people["surveyor"])
    resp = rv.post(f"/v1/rechecks/{rc.pk}/assignments", {"person_id": str(colleague.pk), "role": "SV"},
                   format="json")
    assert resp.status_code == 409
    fresh = licensed(gh, "LW", "fresh.lawyer@example.com", "Unlinked Lawyer")
    resp = rv.post(f"/v1/rechecks/{rc.pk}/assignments", {"person_id": str(fresh.pk), "role": "LW"}, format="json")
    assert resp.status_code == 200 and resp.json()["status"] == "assigned"
    with pytest.raises(IntegrityError), transaction.atomic():
        Recheck.objects.filter(pk=rc.pk).update(assignee=people["lawyer"])


def test_hidden_from_original_team(seeded, api, people, gh):
    """02 6.15: re-checks are hidden from the case's original team (the reviewer who approved it)."""
    _r, _d, rc = _draw_one(api, people, gh)
    seen = api(people["reviewer"]).get("/v1/rechecks?month=2031-01&country=GH").json()["items"]
    assert str(rc.pk) not in {x["id"] for x in seen}
    seen = api(people["reviewer2"]).get("/v1/rechecks?month=2031-01&country=GH").json()["items"]
    assert str(rc.pk) in {x["id"] for x in seen}
    assert api(people["lawyer"]).get(f"/v1/rechecks/{rc.pk}").status_code == 404


def test_passed_recheck_is_stored_and_paid(seeded, api, people, gh):
    """US-RPT-012 AC4, TC-RPT-012-05: stored with the case and in the month's summary; work.accepted for the
    re-checker with no result field."""
    _r, _d, rc = _draw_one(api, people, gh)
    p = licensed(gh, "SV", "sv2@example.com", "Unlinked Surveyor")
    services.assign_recheck(rc, people["reviewer2"], p, role="SV")
    resp = api(p).post(f"/v1/rechecks/{rc.pk}/results", {"result": "confirmed"}, format="json")
    assert resp.status_code == 200 and resp.json()["status"] == "done"
    assert services.month_summary(gh, NEXT)["confirmed"] == 1
    w = OutboxEvent.objects.get(topic="work.accepted", aggregate_id=rc.pk).payload
    assert w["work_type"] == "recheck" and w["person_id"] == str(p.pk) and "result" not in w
    assert not Incident.objects.filter(recheck=rc).exists()


def test_failed_recheck_opens_incident_until_correction_released(seeded, api, people, gh):
    """US-RPT-012 AC3, TC-RUL-32-03, TC-RPT-012-03: recheck.failed and incident.opened (ESC freezes on them);
    the incident closes only after the correction is released and the client told; incident.closed follows."""
    r, _d, rc = _draw_one(api, people, gh)
    p = licensed(gh, "LW", "lw3@example.com", "Re-check Lawyer")
    services.assign_recheck(rc, people["reviewer2"], p, role="LW")
    services.record_recheck_result(rc, p, result="correction_needed", findings="Consent of one family head missing.")
    inc = Incident.objects.get(recheck=rc)
    opened = OutboxEvent.objects.get(topic="incident.opened", aggregate_id=inc.pk).payload
    assert opened["report_id"] == str(r.pk) and str(r.pk) in opened["report_ids"]
    assert OutboxEvent.objects.filter(topic="recheck.failed", aggregate_id=rc.pk).exists()
    rv = api(people["reviewer2"])
    assert rv.post(f"/v1/report-incidents/{inc.pk}/close", {"note": "x"}, format="json").status_code == 409
    resp = api(people["cm"]).post(f"/v1/reports/{r.pk}/corrections",
                                  {"reason": "Re-check found a missing consent", "incident_id": str(inc.pk)},
                                  format="json")
    assert resp.status_code == 201
    from reports.models import Report

    v2 = Report.objects.get(pk=resp.json()["id"])
    services.update_section(v2, 8, people["lawyer"], findings={"text": "Consent of every head now recorded."})
    services.sign_sections(v2, people["lawyer"])
    services.sign_sections(v2, people["surveyor"])
    services.submit_review(v2, people["cm"])
    assert rv.post(f"/v1/report-incidents/{inc.pk}/close", {"note": "x"}, format="json").status_code == 409
    now = timezone.now()
    services.approve(v2, people["lawyer"], mfa_at=now)
    services.approve(v2, people["reviewer"], mfa_at=now)
    inc.refresh_from_db()
    assert inc.correction_report_id == v2.pk and inc.client_notified_at
    resp = rv.post(f"/v1/report-incidents/{inc.pk}/close", {"note": "Corrected and the client told."},
                   format="json")
    assert resp.status_code == 200 and resp.json()["status"] == "closed"
    assert OutboxEvent.objects.filter(topic="incident.closed", aggregate_id=inc.pk).exists()


def test_skip_carries_into_next_draw(seeded, api, people, gh):
    """02 6.15: a skipped item joins next month's population."""
    _r, _d, rc = _draw_one(api, people, gh)
    resp = api(people["reviewer2"]).post(f"/v1/rechecks/{rc.pk}/skips", {"reason": "No unlinked surveyor this month"},
                                         format="json")
    assert resp.status_code == 200 and resp.json()["status"] == "skipped"
    d2 = services.draw(gh, date(2031, 2, 1))
    assert d2.population_count == 1 and d2.rechecks.get().carried_from_id == rc.pk
    with pytest.raises(DomainError):
        services.skip_recheck(rc, people["reviewer2"], "")
