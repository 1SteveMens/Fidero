"""The interface the family and property lines use, and the registries ESC plugs into (FR-ESC-010, 014; RUL-11, RUL-23)."""
import uuid
from decimal import Decimal

import pytest
from django.utils import timezone

from core.errors import RuleBlocked
from core.events import publish
from core.models import OutboxEvent
from escrow import registry, services
from escrow.models import Escrow, ReleaseInstruction


def _care(b, monkeypatch):
    """CARE's own test builder on the seeded client, mother and carer, with a known confirmation code."""
    from care.tests.conftest import Care
    from notifications import services as ntf

    monkeypatch.setattr(ntf.secrets, "randbelow", lambda n: 123456)
    return Care(b.ctx)


def test_line_subject_check_blocks(b, codes, monkeypatch):
    """RUL-23 via the registry: a line's own evidence rule blocks the release with its reason (a real CARE visit,
    checked out but not yet confirmed by the family)."""
    calls = []

    def also_checked(ins):
        calls.append(ins.subject_id)
        return []

    care = _care(b, monkeypatch)
    plan = care.plan()
    v = care.checked_out(plan)
    registry.register_subject_check("care_visit", also_checked)
    try:
        hf = b.held_funds("2000.00", client=b.client)
        with pytest.raises(RuleBlocked) as ei:
            services.request_release(hf, requested_by=b.cm, payee=b.payee("carer"), amount=str(v.fee_amount),
                                     subject_type="care_visit", subject_id=v.pk)
        assert "visit-not-confirmed" in codes(ei.value)
        assert v.pk in calls  # every registered check runs
    finally:
        registry.unregister_subject_check("care_visit", also_checked)


def test_unknown_line_subject_is_refused(b, codes):
    """RUL-06, RUL-22: a release naming a bill, visit or stage the line module does not know is refused."""
    hf = b.held_funds("2000.00")
    for subject_type, payee in (("fee_invoice", "school"), ("care_visit", "carer")):
        with pytest.raises(RuleBlocked) as ei:
            services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=b.payee(payee),
                                     amount="100.00", subject_type=subject_type, subject_id=uuid.uuid4())
        assert codes(ei.value) & {"invoice-unknown", "visit-not-confirmed"}


def test_standing_approval_covers_care_visits_up_to_the_month(b, monkeypatch):
    """RUL-11: a standing approval replaces the client's per-payment approval up to the monthly amount
    (real CARE visits, confirmed by the family, prepared by CARE)."""
    from care.services import prepare_payment

    care = _care(b, monkeypatch)
    plan = care.plan()
    hf = b.held_funds("2000.00", client=b.client)
    assert plan.escrow_id == hf.pk
    sa = services.create_standing_approval(hf, hf.client, subject_kind="care_plan", subject_id=plan.pk,
                                           monthly_max="250.00", mfa_at=timezone.now())
    # The care line locks the carer when the client approves the carer assignment; a standing approval never does.
    services.lock_payee(hf, b.payee("carer"), client_approved_at=timezone.now())
    first = prepare_payment(care.confirm(care.checked_out(plan)), b.cm)
    assert first.standing_approval_id == sa.pk
    assert first.status == "pending_approval" and first.client_approval_method == "standing"
    first = b.approve_all(first, client=False)
    assert first.status == "sent", first.last_send_error
    second = prepare_payment(care.confirm(care.checked_out(plan, minutes_ago=50)), b.cm)
    assert second.status == "awaiting_client"  # above the month's limit the client approves it alone


def _bld(b):
    from construction.tests.helpers import Builder

    return Builder(b.ctx)


def test_construction_partial_releases_never_exceed_funds(b, codes):
    """FR-ESC-010 AC1, AC3: milestone payments are partial releases, never more than the funded amount (a real
    BLD project on the escrow route)."""
    bld = _bld(b)
    p = bld.project("escrow")
    pay = bld.mobilise(p)
    assert pay.instruction.kind == "partial_release" and pay.instruction.status == "confirmed"
    e = Escrow.objects.get(pk=p.escrow_id)
    assert e.status == "partly_released"
    left = services.available_to_instruct(e)
    assert Decimal("0") < left < p.budget_amount
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(e, requested_by=b.cm, payee=p.contractor.payee, amount=str(left + 1),
                                 subject_type="milestone", subject_id=bld.ms(p, "foundation").pk)
    assert "held-funds-insufficient" in codes(ei.value)


def test_unlocked_payee_refused_on_line_escrow(b, codes):
    """RUL-28: a construction escrow pays only the payees agreed in its terms."""
    bld = _bld(b)
    p = bld.project("escrow")
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=p.escrow_id), requested_by=b.cm, payee=b.payee("developer"),
                                 amount="100.00", subject_type="milestone", subject_id=bld.ms(p, "foundation").pk)
    assert "payee-not-locked" in codes(ei.value)


def test_one_live_instruction_per_subject(b):
    """02 6.5: one live instruction per invoice, visit or milestone."""
    from core.errors import StateConflict

    hf = b.held_funds("2000.00")
    ins = b.fee_release(hf, "100.00")  # FEE prepares the one instruction for its bill
    with pytest.raises(StateConflict):
        services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=b.payee("school"),
                                 amount="100.00", subject_type="fee_invoice", subject_id=ins.subject_id)


def test_release_confirmed_event_names_the_subject(b):
    """The event lines subscribe to: release.confirmed with subject_type and subject_id."""
    hf = b.held_funds(None)
    ins = b.fee_release(hf, "100.00")
    sid = ins.subject_id
    b.confirm(b.approve_all(ins))
    ev = OutboxEvent.objects.filter(topic="release.confirmed", aggregate_id=ins.pk).first()
    assert ev.payload["subject_type"] == "fee_invoice" and ev.payload["subject_id"] == str(sid)
    assert ev.payload["client_id"] == str(hf.client_id) and ev.payload["amount"] == "100.00"
    assert OutboxEvent.objects.filter(topic="held_funds.deposit_confirmed", aggregate_id=hf.pk).exists()


def test_report_released_snapshot_and_fresh_search_event(b):
    """report.released and fresh_search.completed by topic: the escrow learns the facts it needs."""
    rid = uuid.uuid4()
    publish("report.released", rid, {"report_id": str(rid), "country": "GH", "verdict": "green",
                                     "conditions": [{"text": "Survey pillars confirmed"}]})
    e = services.create_escrow(b.cm, kind="purchase", client=b.client, country=b.gh, agreed_amount="5000.00",
                               report_id=rid, asset_id=uuid.uuid4())
    assert e.conditions.filter(text="Survey pillars confirmed").exists()
    today = timezone.localdate().isoformat()
    publish("fresh_search.completed", rid, {"escrow_id": str(e.pk), "case_id": str(uuid.uuid4()),
                                            "registry_result_date": today, "site_check_date": today})
    e.refresh_from_db()
    assert e.fresh_search_result_date is not None


def test_registries(b):
    """FR-ACC-012 home, evidence access for escrow subjects, open matters blocking deletion (FR-APP-004)."""
    from accounts import home
    from dataprotection import registry as dpr
    from evidence import access

    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    items = home.items_for(b.client)
    assert any(i["kind"] == "release_approval" and i["id"] == str(ins.pk) and i["needs_action"] for i in items)
    assert any(m["kind"] == "escrow" and m["id"] == str(e.pk) for m in dpr.collect_open_matters(b.client))
    c = e.conditions.first()
    assert access.can_view_subject(b.client, "escrow_condition", c.pk)
    assert not access.can_view_subject(b.new_client(), "escrow_condition", c.pk)
    assert dpr.collect_export(b.client)["escrow"]


def test_dispute_resolved_for_refund_starts_cancellation(b):
    """01 C8: Frozen to Cancelled when a dispute is resolved in favour of a refund; refunds go to source."""
    e = b.ready_purchase()
    did = uuid.uuid4()
    publish("dispute.opened", did, {"dispute_id": str(did), "escrow_id": str(e.pk)})
    assert Escrow.objects.get(pk=e.pk).status == "frozen"
    publish("dispute.resolved", did, {"dispute_id": str(did), "escrow_id": str(e.pk), "outcome": "refund"})
    e.refresh_from_db()
    assert e.cancel_requested_at is not None
    refund = ReleaseInstruction.objects.get(escrow=e, kind="cancel_refund")
    assert refund.amount == Decimal("100000.00") and refund.status == "pending_approval"


def test_held_funds_available_for_lines(b):
    """held_funds_for() and available_to_instruct() for the family lines."""
    hf = b.held_funds("700.00")
    assert services.held_funds_for(hf.client, b.gh, "GHS").pk == hf.pk
    assert services.available_to_instruct(hf) == Decimal("700.00")
    b.fee_release(hf, "200.00")
    assert services.available_to_instruct(Escrow.objects.get(pk=hf.pk)) == Decimal("500.00")
    assert ReleaseInstruction.objects.filter(escrow=hf).count() == 1
