"""Release rules: RUL-05, 06, 07, 11, 15, 22, 32, 33, 34; FR-ESC-006 to 009, 018."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.errors import DomainError, Forbidden, MfaRequired, RuleBlocked, SameApprover, StateConflict
from escrow import services
from escrow.models import Escrow, ReleaseInstruction


def test_create_escrow_copies_report_conditions(b):
    """FR-ESC-001, US-ESC-001 AC1: section 11 conditions are copied as open conditions."""
    e = b.purchase(conditions=2)
    assert e.status == "proposed"
    assert e.conditions.filter(status="open").count() == 2
    assert e.parties.filter(role="seller").exists()


def test_red_report_refused(b):
    """US-ESC-001 AC2: an escrow cannot be created on a red report."""
    with pytest.raises(RuleBlocked) as ei:
        services.create_escrow(b.cm, kind="purchase", client=b.client, country=b.gh, agreed_amount="1000.00",
                               report_id=b.report(verdict="red"))
    assert ei.value.code == "report-red"


def test_price_currency_is_the_countrys(b):
    """RUL-35, Q-32: prices in Ghana are in cedis."""
    with pytest.raises(RuleBlocked):
        services.create_escrow(b.cm, kind="purchase", client=b.client, country=b.gh, agreed_amount="1000.00",
                               currency="USD", report_id=b.report())


def test_held_back_share_needs_legal_answer(b):
    """FR-ESC-020 AC4: no held-back share until Q-30 is answered for the country."""
    with pytest.raises(RuleBlocked) as ei:
        b.purchase(held_back="10000.00", held_back_condition="Registration lodged")
    assert ei.value.code == "held-back-not-allowed"


def test_agreement_needs_every_acceptance_and_virtual_account(b):
    """FR-ESC-002, RUL-34: agreed only when all accept and the bank issued the virtual account."""
    e = b.purchase()
    services.accept_terms(e, b.client)
    assert Escrow.objects.get(pk=e.pk).status == "proposed"
    e = b.agree(e)
    assert e.status == "agreed"
    assert e.locked_payees.filter(payee=b.payee("seller"), source="terms_agreed").exists()


def test_new_terms_version_needs_new_acceptances(b):
    """US-ESC-002 AC2: earlier acceptances stay on the old version."""
    from administration import services as adm
    from administration.models import LockedTextVersion

    e = b.purchase()
    services.accept_terms(e, b.client)
    old = e.terms_version
    v2 = LockedTextVersion.objects.create(country=b.gh, kind="escrow_terms", version=old.version + 50,
                                          text="New terms [test]", text_sha256="x" * 64, status="published")
    services.set_terms_version(e, b.cm, v2)
    e.refresh_from_db()
    blockers = {r["code"] for r in services.agreement_blockers(e)}
    assert "acceptance-missing" in blockers
    assert e.acceptances.filter(terms_version=old).count() == 1
    assert adm is not None


def test_open_condition_blocks_and_is_named(b, codes):
    """RUL-06, US-ESC-006 AC1: blocked with the open condition named."""
    e = b.agree(b.purchase(conditions=2))
    b.deposit(e, "100000.00")
    b.fresh(e)
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert ei.value.code == "release-blocked"
    msgs = [r["message"] for r in ei.value.blocking_reasons if r["code"] == "condition-open"]
    assert len(msgs) == 2 and "Condition 1" in msgs[0]


def test_condition_needs_evidence_and_staff(b):
    """FR-ESC-005, US-ESC-005 AC2: no evidence, or a client, cannot close a condition."""
    from core.errors import Invalid

    e = b.purchase()
    c = e.conditions.first()
    with pytest.raises(Invalid):
        services.close_condition(c, b.cm, evidence_ids=[])
    with pytest.raises(Forbidden):
        services.close_condition(c, b.client, evidence_ids=[b.ev().pk])
    services.close_condition(c, b.cm, evidence_ids=[b.ev().pk])
    c.refresh_from_db()
    assert c.status == "closed" and c.closed_by_id == b.cm.pk


def test_condition_close_db_trigger_needs_evidence(b):
    """FR-ESC-005 enforced again in PostgreSQL."""
    e = b.purchase()
    c = e.conditions.first()
    c.status, c.closed_by, c.closed_at = "closed", b.cm, timezone.now()
    with pytest.raises(IntegrityError), transaction.atomic():
        c.save()


def test_fresh_search_missing_or_stale_blocks_purchase(b, codes):
    """RUL-07, US-ESC-006 AC3: missing, then 15 days old with a 14-day window."""
    e = b.agree(b.purchase())
    b.deposit(e, "100000.00")
    e = Escrow.objects.get(pk=e.pk)
    b.close_all(e)
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert "fresh-search-missing" in codes(ei.value)
    window = int(services.setting("fresh_search_window_days", b.gh, 14))
    b.fresh(e, days_ago=window + 1)
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert "fresh-search-stale" in codes(ei.value)
    b.fresh(e, days_ago=window)  # day N counts
    assert services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm).status == "awaiting_client"


def test_held_funds_need_no_fresh_search(b):
    """US-ESC-006 AC5: payments to institutions need no fresh search."""
    hf = b.held_funds("3000.00")
    ins = services.request_release(hf, requested_by=b.cm, payee=b.payee("school"), amount="500.00",
                                   subject_type="fee_invoice", subject_id=hf.pk)
    assert ins.status == "awaiting_client"


def test_full_purchase_journey(b):
    """J-02, FR-ESC-006 to 009, RUL-33: client, two staff, sent the same day, bank confirms, released."""
    e = b.ready_purchase()
    assert e.status == "ready_to_release"
    ins = services.request_release(e, requested_by=b.cm)
    assert ins.amount == Decimal("100000.00") and ins.payee == b.payee("seller")
    services.client_approve(ins, b.client, timezone.now())
    assert Escrow.objects.get(pk=e.pk).status == "client_approved"
    services.staff_approve(ins, b.rv, mfa_at=timezone.now())
    ins.refresh_from_db()
    assert ins.status == "pending_approval"
    services.staff_approve(ins, b.rv2, mfa_at=timezone.now())
    ins.refresh_from_db()
    assert ins.status == "sent", ins.last_send_error
    assert ins.document_sha256 and ins.kms_signature and ins.sent_channel
    assert ins.send_due_on >= timezone.localdate() - timedelta(days=1)
    assert ins.bank_pay_due_on is not None
    assert Escrow.objects.get(pk=e.pk).status == "release_approved"
    b.confirm(ins)
    assert ins.status == "confirmed"
    e.refresh_from_db()
    assert e.status == "released"
    assert services.selectors.held_at_bank(e) == 0


def test_client_approves_first_silence_is_never_approval(b):
    """RUL-11, US-ESC-006 AC2: staff cannot approve before the client; the clock watch only reminds."""
    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    with pytest.raises(RuleBlocked):
        services.staff_approve(ins, b.rv, mfa_at=timezone.now())
    ReleaseInstruction.objects.filter(pk=ins.pk).update(created_at=timezone.now() - timedelta(days=30))
    out = services.release_clock_watch()
    ins.refresh_from_db()
    assert out["client_reminded"] >= 1 and ins.status == "awaiting_client" and ins.client_approved_at is None


def test_two_different_staff_with_release_rights_and_mfa(b):
    """RUL-05, US-ESC-007: same person twice, no MFA, no release rights, the preparer: all refused."""
    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    services.client_approve(ins, b.client, timezone.now())
    with pytest.raises(MfaRequired):
        services.staff_approve(ins, b.rv, mfa_at=None)
    with pytest.raises(Forbidden):
        services.staff_approve(ins, b.p["admin3"], mfa_at=timezone.now())  # AD without RR
    with pytest.raises(SameApprover):
        services.staff_approve(ins, b.cm, mfa_at=timezone.now())  # the preparer
    services.staff_approve(ins, b.rv, mfa_at=timezone.now())
    with pytest.raises(SameApprover):
        services.staff_approve(ins, b.rv, mfa_at=timezone.now())
    ins.refresh_from_db()
    assert ins.status == "pending_approval"


def test_client_needs_fresh_mfa_or_code(b):
    """RUL-11: press and hold with MFA or an authenticator code."""
    import pyotp

    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    with pytest.raises(MfaRequired):
        services.client_approve(ins, b.client, timezone.now() - timedelta(minutes=30))
    with pytest.raises(MfaRequired):
        services.client_approve(ins, b.client, code="000000")
    if not b.client.mfa_secret:
        b.client.mfa_secret = "JBSWY3DPEHPK3PXP"
        b.client.save(update_fields=["mfa_secret"])
    services.client_approve(ins, b.client, code=pyotp.TOTP(b.client.mfa_secret).now())
    ins.refresh_from_db()
    assert ins.client_approval_method == "totp_code"


def test_reopened_condition_voids_client_approval(b):
    """TC-ESC-006-06: a reopened condition sends the release back to the client."""
    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    services.client_approve(ins, b.client, timezone.now())
    c = e.conditions.first()
    services.reopen_condition(c, b.rv, reason="Consent letter looks altered")
    ins.refresh_from_db()
    assert ins.status == "awaiting_client" and ins.client_approved_at is None
    with pytest.raises(RuleBlocked):
        services.client_approve(ins, b.client, timezone.now())


def test_purchase_amount_cannot_be_held_back_without_terms(b):
    """RUL-33, FR-ESC-020 AC3: holding back part of a release needs a share in the terms."""
    e = b.ready_purchase()
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(e, requested_by=b.cm, amount="90000.00")
    assert ei.value.code == "release-amount"
    with pytest.raises(RuleBlocked):
        services.request_release(e, requested_by=b.cm, release_part="held_back")


def test_held_back_share_released_on_its_own_condition(b, monkeypatch):
    """FR-ESC-020 AC1, AC2: the main release ignores the share's condition; the share follows."""
    real = services.cfg
    monkeypatch.setattr(services, "cfg", lambda c, k, d=None: True if k == "escrow.held_back_share_allowed"
                        else real(c, k, d))
    e = b.agree(b.purchase(price="100000.00", held_back="10000.00", held_back_condition="Registration lodged"))
    b.deposit(e, "100000.00")
    e = Escrow.objects.get(pk=e.pk)
    b.close_all(e)
    b.fresh(e)
    main = services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert main.amount == Decimal("90000.00")
    b.confirm(b.approve_all(main))
    e.refresh_from_db()
    assert e.status == "partly_released" and services.selectors.held_at_bank(e) == Decimal("10000.00")
    with pytest.raises(RuleBlocked):
        services.request_release(e, requested_by=b.cm, release_part="held_back")
    b.close_all(e, part="held_back")
    share = services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm, release_part="held_back")
    b.confirm(b.approve_all(share))
    e.refresh_from_db()
    assert e.status == "released"


def test_freeze_blocks_and_lifts(b, codes):
    """RUL-32, RUL-15: an incident or dispute freezes releases; closing it restores the state."""
    import uuid

    e = b.ready_purchase()
    inc = uuid.uuid4()
    services.on_incident({"incident_id": str(inc), "report_id": str(e.report_id)}, opened=True)
    e.refresh_from_db()
    assert e.status == "frozen" and e.prior_status == "ready_to_release"
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(e, requested_by=b.cm)
    assert "escrow-frozen" in codes(ei.value)
    d = uuid.uuid4()
    services.on_dispute({"dispute_id": str(d), "escrow_id": str(e.pk)}, opened=True)
    services.on_incident({"incident_id": str(inc)}, opened=False)
    assert Escrow.objects.get(pk=e.pk).status == "frozen"  # the dispute still holds it
    services.on_dispute({"dispute_id": str(d), "escrow_id": str(e.pk)}, opened=False)
    assert Escrow.objects.get(pk=e.pk).status == "ready_to_release"


def test_reviewer_hold_lifted_by_another_reviewer(b):
    """US-ESC-006 AC4: a reviewer's hold blocks release; a different reviewer lifts it."""
    e = b.ready_purchase()
    f = services.place_hold(e, b.rv, reason="Seller's brother called about the price")
    with pytest.raises(Forbidden):
        services.lift_hold(f, b.rv, note="ok")
    services.lift_hold(f, b.rv2, note="Checked with the family head")
    assert Escrow.objects.get(pk=e.pk).status == "ready_to_release"


def test_freeze_after_approval_stops_dispatch(b, settings):
    """5.3: if a freeze opens after approval but before sending, the dispatcher stops."""
    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                          "bank_instructions": "escrow.adapters.DownBankInstructions"}}
    from core.adapters import _cls

    _cls.cache_clear()
    try:
        e = b.ready_purchase()
        ins = b.approve_all(services.request_release(e, requested_by=b.cm))
        assert ins.status == "approved" and ins.last_send_error
        services.place_hold(Escrow.objects.get(pk=e.pk), b.rv, reason="Late objection")
    finally:
        settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                              "bank_instructions":
                                                                  "escrow.adapters.ManualBankInstructions"}}
        _cls.cache_clear()
    services.dispatch(ins)
    ins.refresh_from_db()
    assert ins.status == "approved" and "hold" in ins.last_send_error


def test_send_failure_stays_approved_and_retries_once(b, settings):
    """TC-ESC-008-03, US-ESC-008b AC2: alerted, stays approved, sent once when the channel returns."""
    from core.adapters import _cls

    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                          "bank_instructions": "escrow.adapters.DownBankInstructions"}}
    _cls.cache_clear()
    e = b.ready_purchase()
    ins = b.approve_all(services.request_release(e, requested_by=b.cm))
    assert ins.status == "approved" and ins.send_attempts == 1
    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                          "bank_instructions": "escrow.adapters.ManualBankInstructions"}}
    _cls.cache_clear()
    assert services.retry_unsent() >= 1
    ins.refresh_from_db()
    assert ins.status == "sent" and ins.send_attempts == 2
    services.dispatch(ins)
    ins.refresh_from_db()
    assert ins.send_attempts == 2


def test_tampered_instruction_is_not_sent(b, settings):
    """TC-ESC-008-02: a stored instruction whose signature no longer verifies is blocked."""
    from core.adapters import _cls

    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                          "bank_instructions": "escrow.adapters.DownBankInstructions"}}
    _cls.cache_clear()
    e = b.ready_purchase()
    ins = b.approve_all(services.request_release(e, requested_by=b.cm))
    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                          "bank_instructions": "escrow.adapters.ManualBankInstructions"}}
    _cls.cache_clear()
    ReleaseInstruction.objects.filter(pk=ins.pk).update(kms_signature="forged")
    services.dispatch(ins)
    ins.refresh_from_db()
    assert ins.status == "approved" and "no longer matches" in ins.last_send_error


def test_instructions_paused(b, codes):
    """06 2.6 kill switch: no instruction while escrow.instructions_paused is on."""
    from administration.models import FeatureFlag

    e = b.ready_purchase()
    FeatureFlag.objects.update_or_create(name="escrow.instructions_paused", country=None,
                                         defaults={"enabled": True})
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(e, requested_by=b.cm)
    assert "instructions-paused" in codes(ei.value)


def test_escrow_flag_off(b):
    """06 2.6: everything sits behind escrow.enabled."""
    from administration.models import FeatureFlag
    from core.errors import FeatureOff

    FeatureFlag.objects.filter(name="escrow.enabled").update(enabled=False)
    with pytest.raises(FeatureOff):
        b.purchase()


def test_confirmation_needs_sent_instruction_and_matching_amount(b):
    """US-ESC-009 AC2, TC-ESC-009-02."""
    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    with pytest.raises(StateConflict):
        b.confirm(ins)
    ins = b.approve_all(ins)
    with pytest.raises(RuleBlocked) as ei:
        b.confirm(ins, amount="99999.00")
    assert ei.value.code == "confirmation-mismatch"


def test_db_trigger_refuses_unapproved_send(b):
    """RUL-05 enforced again in PostgreSQL: no status change to approved without approvals."""
    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    ins.status, ins.last_approval_at, ins.send_due_on = "approved", timezone.now(), timezone.localdate()
    with pytest.raises(IntegrityError), transaction.atomic():
        ins.save()


def test_release_clock_alerts(b):
    """FR-ESC-018, NFR-PERF-06: send overdue and bank overdue are raised once, never approve anything."""
    from core.models import OutboxEvent

    e = b.ready_purchase()
    ins = b.approve_all(services.request_release(e, requested_by=b.cm))
    assert ins.status == "sent"
    ReleaseInstruction.objects.filter(pk=ins.pk).update(bank_pay_due_on=timezone.localdate() - timedelta(days=1))
    out = services.release_clock_watch()
    assert out["bank_overdue"] == 1
    assert OutboxEvent.objects.filter(topic="release.bank_overdue", aggregate_id=ins.pk).count() == 1
    assert services.release_clock_watch()["bank_overdue"] == 0
    clock = services.clock(ReleaseInstruction.objects.get(pk=ins.pk))
    assert clock["state"] == "bank_overdue"


def test_no_waiting_period_setting_exists(b):
    """RUL-33, ADR-26: no setting adds a delay after the last approval."""
    from administration.registry import REGISTRY

    assert not [k for k in REGISTRY if "wait" in k or "delay" in k or "dispute_window" in k]


def test_errors_are_problem_codes(b):
    """7.2: release-blocked carries every blocking reason."""
    e = b.agree(b.purchase(conditions=1))
    try:
        services.request_release(e, requested_by=b.cm)
    except DomainError as exc:
        assert exc.code == "release-blocked"
        assert {"condition-open", "fresh-search-missing"} <= {r["code"] for r in exc.blocking_reasons}
    else:
        pytest.fail("not blocked")
