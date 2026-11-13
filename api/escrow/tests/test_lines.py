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


def test_line_subject_check_blocks(b, codes):
    """RUL-23 via the registry: a line's own evidence rule blocks the release with its reason."""
    def visit_not_confirmed(ins):
        return [{"rule": "RUL-23", "code": "visit-not-confirmed", "message": "The family has not confirmed."}]

    registry.register_subject_check("care_visit", visit_not_confirmed)
    try:
        hf = b.held_funds("2000.00")
        with pytest.raises(RuleBlocked) as ei:
            services.request_release(hf, requested_by=b.cm, payee=b.payee("carer"), amount="150.00",
                                     subject_type="care_visit", subject_id=uuid.uuid4())
        assert "visit-not-confirmed" in codes(ei.value)
    finally:
        registry.unregister_subject_check("care_visit", visit_not_confirmed)


def test_standing_approval_covers_care_visits_up_to_the_month(b):
    """RUL-11: a standing approval replaces the client's per-payment approval up to the monthly amount."""
    hf = b.held_funds("2000.00")
    plan = uuid.uuid4()
    sa = services.create_standing_approval(hf, hf.client, subject_kind="care_plan", subject_id=plan,
                                           monthly_max="300.00", mfa_at=timezone.now())
    # The care line locks the carer when the client approves the carer assignment; a standing approval never does.
    services.lock_payee(hf, b.payee("carer"), client_approved_at=timezone.now())
    first = services.request_release(hf, requested_by=b.cm, payee=b.payee("carer"), amount="200.00",
                                     subject_type="care_visit", subject_id=uuid.uuid4(), standing_approval=sa)
    assert first.status == "pending_approval" and first.client_approval_method == "standing"
    first = b.approve_all(first, client=False)
    assert first.status == "sent", first.last_send_error
    second = services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=b.payee("carer"),
                                      amount="200.00", subject_type="care_visit", subject_id=uuid.uuid4(),
                                      standing_approval=sa)
    assert second.status == "awaiting_client"  # above the month's limit the client approves it alone


def test_construction_partial_releases_never_exceed_funds(b):
    """FR-ESC-010 AC1, AC3: milestone payments are partial releases, never more than the funded amount."""
    e = services.open_line_escrow(kind="construction", client=b.client, country=b.gh, agreed_amount="1000.00",
                                  by=b.cm, asset_id=uuid.uuid4(), project_id=uuid.uuid4(),
                                  payees=[b.payee("contractor")])
    e = b.agree(e)
    b.deposit(e, "1000.00")
    m1 = services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm, payee=b.payee("contractor"),
                                  amount="600.00", subject_type="milestone", subject_id=uuid.uuid4())
    assert m1.kind == "partial_release"
    b.confirm(b.approve_all(m1))
    assert Escrow.objects.get(pk=e.pk).status == "partly_released"
    with pytest.raises(RuleBlocked):
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm, payee=b.payee("contractor"),
                                 amount="500.00", subject_type="milestone", subject_id=uuid.uuid4())
    m2 = services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm, payee=b.payee("contractor"),
                                  amount="400.00", subject_type="milestone", subject_id=uuid.uuid4())
    b.confirm(b.approve_all(m2))
    assert Escrow.objects.get(pk=e.pk).status == "released"


def test_unlocked_payee_refused_on_line_escrow(b, codes):
    """RUL-28: a construction escrow pays only the payees agreed in its terms."""
    e = services.open_line_escrow(kind="construction", client=b.client, country=b.gh, agreed_amount="1000.00",
                                  by=b.cm, asset_id=uuid.uuid4(), project_id=uuid.uuid4(),
                                  payees=[b.payee("contractor")])
    e = b.agree(e)
    b.deposit(e, "1000.00")
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm, payee=b.payee("developer"),
                                 amount="100.00", subject_type="milestone", subject_id=uuid.uuid4())
    assert "payee-not-locked" in codes(ei.value)


def test_one_live_instruction_per_subject(b):
    """02 6.5: one live instruction per invoice, visit or milestone."""
    from core.errors import StateConflict

    hf = b.held_funds("2000.00")
    sid = uuid.uuid4()
    services.request_release(hf, requested_by=b.cm, payee=b.payee("school"), amount="100.00",
                             subject_type="fee_invoice", subject_id=sid)
    with pytest.raises(StateConflict):
        services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=b.payee("school"),
                                 amount="100.00", subject_type="fee_invoice", subject_id=sid)


def test_release_confirmed_event_names_the_subject(b):
    """The event lines subscribe to: release.confirmed with subject_type and subject_id."""
    hf = b.held_funds("2000.00")
    sid = uuid.uuid4()
    ins = services.request_release(hf, requested_by=b.cm, payee=b.payee("school"), amount="100.00",
                                   subject_type="fee_invoice", subject_id=sid)
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
    services.request_release(hf, requested_by=b.cm, payee=b.payee("school"), amount="200.00",
                             subject_type="fee_invoice", subject_id=uuid.uuid4())
    assert services.available_to_instruct(Escrow.objects.get(pk=hf.pk)) == Decimal("500.00")
    assert ReleaseInstruction.objects.filter(escrow=hf).count() == 1
