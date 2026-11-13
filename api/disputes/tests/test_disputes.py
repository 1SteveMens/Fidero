"""DSP: opening, freezing, deadlines, decisions by two staff, mediation and withdrawal
(FR-DSP-001 to FR-DSP-005, RUL-15, J-07, 01 C8 Dispute)."""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.errors import DomainError, Forbidden, NotFound, StateConflict
from core.models import OutboxEvent
from disputes import services
from disputes.models import Dispute
from disputes.seed import funded_escrow
from escrow.models import Escrow


@pytest.fixture
def escrow(seeded, gh, people):
    import uuid

    key = uuid.uuid4().hex[:6]
    return funded_escrow(gh, people, f"t{key}", f"Test plot {key}", "50000.00", f"VA-GH-T{key}")


def _open(escrow, people, **kw):
    return services.open_dispute(people["client"], subject_type="escrow", subject_id=escrow.pk,
                                 reason=kw.pop("reason", "The seller changed the boundary."), **kw)


def _to_decision(d, people):
    services.add_statement(d, people["seller"], text="We disagree.")
    d.refresh_from_db()
    services.confirm_evidence_complete(d, people["client"])
    services.confirm_evidence_complete(d, people["seller"])
    d.refresh_from_db()
    assert d.status == "decision"
    return d


def test_party_opens_and_releases_freeze(escrow, api, people):
    """US-DSP-001 AC1, US-DSP-002 AC1, TC-DSP-001-01, TC-RUL-15-01, TC-STM-DSP-01."""
    from notifications.models import Message

    r = api(people["client"]).post("/v1/disputes", {"subject_type": "escrow", "subject_id": str(escrow.pk),
                                                    "reason": "The pillars were moved.", "category": "misrepresentation"},
                                   format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "awaiting_response" and body["response_due"] and body["decision_due"]
    assert {p["side"] for p in body["parties"]} == {"raised_by", "respondent"}
    assert {(x["subject_type"], x["prior_status"]) for x in body["links"]} >= {("escrow", "funded")}
    e = Escrow.objects.get(pk=escrow.pk)
    assert e.status == "frozen"
    assert Message.objects.filter(person=people["seller"], subject_id=body["id"]).exists()
    ev = OutboxEvent.objects.filter(topic="dispute.opened", aggregate_id=body["id"]).get()
    assert ev.payload["escrow_id"] == str(escrow.pk)
    from escrow import services as esc

    with pytest.raises(DomainError):  # TC-DSP-002-02: no release while frozen
        esc.request_release(e, requested_by=people["cm"])


def test_non_party_or_no_reason_refused(escrow, api, people):
    """US-DSP-001 AC2, TC-DSP-001-02."""
    body = {"subject_type": "escrow", "subject_id": str(escrow.pk), "reason": "x"}
    assert api(people["client2"]).post("/v1/disputes", body, format="json").status_code == 404
    assert api(people["client"]).post("/v1/disputes", {**body, "reason": ""}, format="json").status_code == 400
    d = _open(escrow, people)
    assert api(people["client2"]).get(f"/v1/disputes/{d.pk}").status_code == 404


def test_deadlines_in_working_days_from_configuration(escrow, people, gh):
    """US-DSP-003 AC1, TC-DSP-003-01: response, evidence and decision dues counted in working days."""
    from administration.models import Setting
    from countries.selectors import add_working_days
    from escrow.common import local_today

    Setting.objects.update_or_create(key="dispute_deadlines", country=gh, defaults={
        "value": {"response_days": 3, "evidence_days": 7, "decision_days": 4}})
    d = _open(escrow, people)
    today = local_today(gh)
    assert d.response_due == add_working_days(gh, today, 3)
    assert d.evidence_due == add_working_days(gh, d.response_due, 7)
    assert d.decision_due == add_working_days(gh, d.evidence_due, 4)
    assert d.response_due.weekday() < 5


def test_deadline_tick_moves_on_and_escalates(escrow, people):
    """US-DSP-003 AC2, TC-DSP-003-02, TC-STM-DSP-03, -04, -07, TC-E2E-J07-02."""
    d = _open(escrow, people)
    services.deadline_tick(today=d.response_due)
    assert Dispute.objects.get(pk=d.pk).status == "awaiting_response"  # the due day still counts
    services.deadline_tick(today=d.response_due + timedelta(days=1))
    d.refresh_from_db()
    assert d.status == "evidence" and d.parties.get(side="respondent").missed_response
    services.deadline_tick(today=d.evidence_due + timedelta(days=1))
    d.refresh_from_db()
    assert d.status == "decision"
    out = services.deadline_tick(today=d.decision_due + timedelta(days=1))
    d.refresh_from_db()
    assert d.status == "decision" and d.escalated_at and out["escalated"] >= 1
    assert OutboxEvent.objects.filter(topic="dispute.escalated", aggregate_id=d.pk).exists()


def test_early_move_needs_every_party(escrow, people):
    """TC-STM-DSP-05, -11: one confirmation is not enough; all parties move it early, recorded."""
    d = _open(escrow, people)
    services.add_statement(d, people["seller"], text="Our survey attached.")
    d.refresh_from_db()
    assert d.status == "evidence"
    services.confirm_evidence_complete(d, people["client"])
    assert Dispute.objects.get(pk=d.pk).status == "evidence"
    services.confirm_evidence_complete(d, people["seller"])
    d.refresh_from_db()
    assert d.status == "decision" and "confirmed" in d.early_move_note


def test_decide_before_decision_stage_refused(escrow, people):
    """TC-STM-DSP-10."""
    d = _open(escrow, people)
    with pytest.raises(StateConflict):
        services.propose_decision(d, people["cm"], outcome="continue", in_favour_of="respondent", reasons="x")


def test_decision_by_two_staff_then_release_resumes(escrow, api, mfa, people):
    """US-DSP-004, TC-DSP-004-01, TC-STM-DSP-06, -12, TC-E2E-J07-01, US-DSP-002 AC2."""
    d = _to_decision(_open(escrow, people), people)
    cm = api(people["cm"])
    url = f"/v1/disputes/{d.pk}/decisions"
    assert cm.post(url, {"outcome": "continue", "in_favour_of": "respondent", "reasons": ""},
                   format="json").status_code == 400
    r = cm.post(url, {"outcome": "continue", "in_favour_of": "raised_by",
                      "reasons": "The seller must restore the pillars before release."}, format="json")
    assert r.status_code == 201, r.content
    client = api(people["client"])
    mfa(client, people["client"])
    assert client.post(f"/v1/disputes/{d.pk}/decision-approvals", {}, format="json").status_code in (403, 409)
    for who in ("reviewer", "reviewer2"):
        c = api(people[who])
        assert c.post(f"/v1/disputes/{d.pk}/decision-approvals", {}, format="json").status_code == 401
        mfa(c, people[who])
        assert c.post(f"/v1/disputes/{d.pk}/decision-approvals", {}, format="json").status_code == 200
    d.refresh_from_db()
    assert d.status == "closed" and d.decided_by == people["cm"] and d.decision.startswith("The seller must")
    assert Escrow.objects.get(pk=escrow.pk).status == "funded"
    closed = OutboxEvent.objects.get(topic="dispute.closed", aggregate_id=d.pk)
    assert {p["side"] for p in closed.payload["parties"]} == {"raised_by", "respondent"}
    from ratings.models import Outcome

    assert Outcome.objects.filter(kind="dispute_lost", source_id=d.pk, subject_type="organisation").exists()
    with pytest.raises(StateConflict):  # TC-STM-DSP-14
        services.refer(d, people["reviewer"], mediator="X", reason="y")


def test_rejected_decision_stays_in_decision(escrow, people):
    d = _to_decision(_open(escrow, people), people)
    services.propose_decision(d, people["cm"], outcome="continue", in_favour_of="none", reasons="Unclear.")
    services.approve_decision(d, people["reviewer"], decision="reject", mfa_at=timezone.now(), note="Weak reasons")
    d.refresh_from_db()
    assert d.status == "decision" and d.decisions.get().status == "rejected"


def test_refund_decision_cancels_escrow(escrow, people):
    """01 C8 Escrow: Frozen to Cancelled when the dispute is resolved for a refund (outcome='refund')."""
    d = _to_decision(_open(escrow, people), people)
    services.propose_decision(d, people["cm"], outcome="refund", in_favour_of="raised_by",
                              reasons="The seller cannot give title.")
    now = timezone.now()
    services.approve_decision(d, people["reviewer"], mfa_at=now)
    services.approve_decision(d, people["reviewer2"], mfa_at=now)
    ev = OutboxEvent.objects.get(topic="dispute.resolved", aggregate_id=d.pk)
    assert ev.payload["outcome"] == "refund"
    assert Escrow.objects.get(pk=escrow.pk).cancel_requested_at is not None


def test_conflicted_decider_blocked(seeded, people):
    """TC-DSP-004-02, TC-STM-DSP-13: a reviewer who approved the disputed release cannot decide."""
    e = Escrow.objects.get(title="Plot at Prampram (released)")
    d = services.open_dispute(people["client"], subject_type="escrow", subject_id=e.pk,
                              reason="The plot was smaller than agreed.")
    d = _to_decision(d, people)
    with pytest.raises(DomainError) as exc:
        services.propose_decision(d, people["reviewer"], outcome="continue", in_favour_of="none", reasons="x")
    assert exc.value.code == "conflict-of-interest"
    from accounts.models import Person, RoleGrant

    cm2 = Person.objects.create_user("cm2@tenmina.test", "tenmina-dev-123", full_name="Second CM",
                                     home_country=e.country)
    RoleGrant.objects.create(person=cm2, role="CM", country=e.country)
    services.propose_decision(d, cm2, outcome="continue", in_favour_of="none", reasons="Measured.")
    with pytest.raises(DomainError):
        services.approve_decision(d, people["reviewer2"], mfa_at=timezone.now())


def test_mediation_keeps_freeze_until_outcome(escrow, api, mfa, people):
    """US-DSP-005, TC-DSP-005-01, TC-STM-DSP-08, -09, TC-E2E-J07-03."""
    d = _open(escrow, people)
    assert api(people["cm"]).post(f"/v1/disputes/{d.pk}/referrals", {"mediator": "ADR", "reason": "family"},
                                  format="json").status_code == 403
    r = api(people["reviewer"]).post(f"/v1/disputes/{d.pk}/referrals",
                                     {"mediator": "Ghana ADR Centre", "reason": "Customary family matter"},
                                     format="json")
    assert r.status_code == 200 and r.json()["status"] == "referred"
    assert Escrow.objects.get(pk=escrow.pk).status == "frozen"
    r = api(people["cm"]).post(f"/v1/disputes/{d.pk}/mediation-outcomes", {
        "outcome": "continue", "in_favour_of": "split", "reasons": "Agreed at mediation.",
        "mediation_reference": "ADR/2026/114"}, format="json")
    assert r.status_code == 201, r.content
    now = timezone.now()
    services.approve_decision(d, people["reviewer"], mfa_at=now)
    services.approve_decision(d, people["reviewer2"], mfa_at=now)
    d.refresh_from_db()
    assert d.status == "closed" and d.mediation_reference == "ADR/2026/114"
    assert Escrow.objects.get(pk=escrow.pk).status == "funded"


def test_only_raiser_withdraws_before_decision(escrow, api, people):
    """US-DSP-002 AC3, TC-DSP-002-03, TC-STM-DSP-15, -16, -17."""
    d = _open(escrow, people)
    assert api(people["seller"]).post(f"/v1/disputes/{d.pk}/withdrawals", {}, format="json").status_code == 403
    with pytest.raises(Forbidden):
        services.withdraw(d, people["reviewer"])
    with pytest.raises(NotFound):
        services.withdraw(d, people["client2"])
    r = api(people["client"]).post(f"/v1/disputes/{d.pk}/withdrawals", {"reason": "Sorted out."}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert Escrow.objects.get(pk=escrow.pk).status == "funded"
    with pytest.raises(StateConflict):
        services.withdraw(Dispute.objects.get(pk=d.pk), people["client"])
    d2 = _to_decision(_open(escrow, people), people)
    with pytest.raises(StateConflict):
        services.withdraw(d2, people["client"])


def test_buyer_disputes_reserved_listing(seeded, people):
    """FR-DSP-001 on a listing: the buyer holding a reservation; the listing is suspended and restored."""
    from listings.models import Listing

    x = Listing.objects.get(pk=seeded["listings"]["reserved"].pk)
    d = services.open_dispute(people["client"], subject_type="listing", subject_id=x.pk,
                              reason="The seller is showing the plot to other buyers.")
    assert Listing.objects.get(pk=x.pk).status == "suspended"
    assert d.parties.filter(side="respondent", organisation=x.organisation).exists()
    with pytest.raises(NotFound):
        services.open_dispute(people["client2"], subject_type="listing", subject_id=x.pk, reason="x")
    services.withdraw(d, people["client"])
    assert Listing.objects.get(pk=x.pk).status == "reserved"


def test_seeded_disputes_in_each_state(seeded):
    states = {k: Dispute.objects.get(pk=seeded["disputes"][k].pk).status
              for k in ("evidence", "decision", "closed", "referred")}
    assert states == {"evidence": "evidence", "decision": "decision", "closed": "closed", "referred": "referred"}
    assert Dispute.objects.filter(status="withdrawn").exists()
