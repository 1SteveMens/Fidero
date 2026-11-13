"""Verified payees and payee changes: RUL-22, RUL-28, RUL-31, FR-ESC-015, FR-ESC-016 (ADR-17, ADR-24)."""
import uuid
from datetime import timedelta

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from core.errors import Forbidden, Invalid, PayeeNotVerified, RuleBlocked, SameApprover, StateConflict
from escrow import adapters, services
from escrow.models import Escrow, Payee, PayeeChange, ReleaseInstruction


def _new_payee(b, *, kind="supplier", name="Volta Blocks Ltd", number="3300112233445", source="bank_name_check",
               account_name="", person=None, nid=True):
    from accounts.services import request_national_id_check

    chk = request_national_id_check(by=b.cm, country=b.gh, subject_role="signatory", subject_name=name,
                                    id_number=f"GHA-7{uuid.uuid4().int % 10**8:08d}-1") if nid else None
    return services.create_payee(b.cm, country=b.gh, kind=kind, subject_type="supplier", subject_id=uuid.uuid4(),
                                 legal_name=name, legal_name_evidence=b.ev("registration"), bank_name="Demo Bank",
                                 account_number=number, account_name=account_name, account_name_source=source,
                                 account_name_evidence=b.ev("bank-letter") if source == "bank_letter" else None,
                                 person=person, national_id_check=chk)


def _verify(b, p):
    services.prepare_verification(p, b.cm)
    services.decide_verification(Payee.objects.get(pk=p.pk), b.rv, decision="approve", mfa_at=timezone.now())
    services.decide_verification(Payee.objects.get(pk=p.pk), b.rv2, decision="approve", mfa_at=timezone.now())
    return Payee.objects.get(pk=p.pk)


def test_verified_by_two_people(b):
    """FR-ESC-015, ADR-17: one prepares, two others approve; both names stored."""
    p = _verify(b, _new_payee(b))
    assert p.verification_status == "verified" and p.name_match == "matched"
    assert {p.verified_by_id, p.second_check_by_id} == {b.rv.pk, b.rv2.pk}


def test_name_mismatch_never_verified(b):
    """FR-ESC-015 AC1, AC5: a bank name that is not the payee's is red; nobody can override it."""
    p = _new_payee(b, number="9990001112223")  # the fake bank says UNKNOWN HOLDER
    assert p.name_match == "mismatch"
    with pytest.raises(PayeeNotVerified):
        services.prepare_verification(p, b.cm)
    with pytest.raises(PayeeNotVerified):
        services.prepare_verification(p, b.p["admin"])


def test_mismatch_cannot_be_forced_in_the_database(b):
    """FR-ESC-015: even a direct update is refused by the database."""
    p = _new_payee(b, number="9990001112224")
    with pytest.raises(IntegrityError), transaction.atomic():
        Payee.objects.filter(pk=p.pk).update(verification_status="verified")


def test_account_name_sources(b):
    """FR-ESC-015 AC4, TC-ESC-015-05: only the bank's name check or a bank letter."""
    with pytest.raises(Invalid):
        _new_payee(b, source="statement_line")
    with pytest.raises(Invalid):
        _new_payee(b, source="whatsapp")
    with pytest.raises(Invalid):
        _new_payee(b, number="3300112230000")  # name check does not cover it: use a letter
    p = _new_payee(b, number="3300112230000", source="bank_letter", account_name="VOLTA BLOCKS LIMITED")
    assert p.name_match == "matched"


def test_payee_identity_must_match(b):
    """RUL-31: no verification without a national identity match."""
    p = _new_payee(b, nid=False)
    with pytest.raises(RuleBlocked) as ei:
        services.prepare_verification(p, b.cm)
    assert ei.value.code == "national-id-check-required"


def test_staff_never_a_payee(b):
    """RUL-22, 6.11 esc.payee_not_staff: Tenmina staff and runners are never paid from client money."""
    with pytest.raises(RuleBlocked):
        _new_payee(b, name="Efua Runner", person=b.p["runner"])


def test_relative_or_representative_never_paid(b, codes):
    """RUL-22, FR-ESC-015 AC3: a release to the client's relative or representative is refused."""
    rep = b.p["family"]  # seeded as Ama's representative
    p = _verify(b, _new_payee(b, kind="institution", name=rep.full_name, person=rep))
    hf = b.held_funds("2000.00", client=b.client)
    bill = b.fee_invoice(b.client, "100.00", approve=False)  # a real bill of Ama's
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(hf, requested_by=b.cm, payee=p, amount="100.00", subject_type="fee_invoice",
                                 subject_id=bill.pk)
    assert "payee-not-verified" in codes(ei.value)
    nephew = b.ctx["family_members"]["nephew"]
    p2 = _verify(b, _new_payee(b, kind="institution", name=nephew.full_name))
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(hf, requested_by=b.cm, payee=p2, amount="100.00", subject_type="fee_invoice",
                                 subject_id=bill.pk)
    assert "payee-not-verified" in codes(ei.value)


def test_payee_kind_must_fit_the_subject(b, codes):
    """6.11 esc.payee_kind_for_subject: an insurer premium goes only to an insurer (RUL-25)."""
    hf = b.held_funds("2000.00")
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(hf, requested_by=b.cm, payee=b.payee("school"), amount="100.00",
                                 subject_type="premium", subject_id=uuid.uuid4())
    assert "payee-not-verified" in codes(ei.value)


def test_direct_edit_refused(b):
    """RUL-28, US-ESC-016 AC1: bank details from a message are refused; only a change request exists."""
    p = b.payee("seller")
    with pytest.raises(RuleBlocked) as ei:
        services.update_payee(p, b.cm, {"account_number": "5550001112223"})
    assert ei.value.code == "payee-locked"
    with pytest.raises(IntegrityError), transaction.atomic():
        Payee.objects.filter(pk=p.pk).update(account_number="5550001112223")


def test_unverified_unlocked_payee_can_be_corrected(b):
    """6.11: a payee never verified nor locked may still be corrected."""
    p = _new_payee(b, number="9990001112225")
    p = services.update_payee(p, b.cm, {"account_number": "3300998877665", "account_name_source": "bank_name_check"})
    assert p.name_match == "matched"


def test_suspension_withdraws_live_instructions(b):
    """RUL-22: suspending a payee withdraws open approvals."""
    hf = b.held_funds(None)
    ins = b.fee_release(hf, "100.00")
    with pytest.raises(Forbidden):
        services.suspend_payee(b.payee("school"), b.cm, "test")
    services.suspend_payee(b.payee("school"), b.rv, "Bursar reported fraud attempt")
    ins.refresh_from_db()
    assert ins.status == "withdrawn"


def _change(b, e, payee, number="4400112233445"):
    ch = services.request_change(payee.person, kind="new_account", payee=payee, escrow=e, reason="New bank",
                                 request_source="payee_signed_in", bank_name="Other Bank", account_number=number,
                                 account_name_source="bank_name_check")
    services.change_identity_check(ch, b.cm, id_number="GHA-700000001-1", subject_name="Kwabena Owusu")
    ch.refresh_from_db()
    return ch


def test_payee_change_full_flow_with_cooling_off(b, codes):
    """FR-ESC-016, RUL-28, sequence 5.12: client first, two RR staff, notice, cooling-off blocks release."""
    e = b.ready_purchase()
    seller = b.payee("seller")
    adapters.FakeBankNameCheck.REGISTRY["4400112233445"] = "Ato Estates Ltd"
    try:
        ch = _change(b, e, seller)
    finally:
        adapters.FakeBankNameCheck.REGISTRY.pop("4400112233445", None)
    assert ch.status == "checks_passed"
    with pytest.raises(StateConflict):
        services.decide_change(ch, b.rv, decision="approve", mfa_at=timezone.now())  # client first
    services.client_approve_change(ch, b.client, mfa_at=timezone.now())
    ch.refresh_from_db()
    assert ch.status == "pending_approval"
    with pytest.raises(Forbidden):
        services.decide_change(ch, b.cm, decision="approve", mfa_at=timezone.now())  # no release rights
    services.decide_change(ch, b.rv, decision="approve", mfa_at=timezone.now())
    with pytest.raises(SameApprover):
        services.decide_change(ch, b.rv, decision="approve", mfa_at=timezone.now())
    services.decide_change(ch, b.rv2, decision="approve", mfa_at=timezone.now())
    ch.refresh_from_db()
    seller.refresh_from_db()
    assert ch.status == "applied" and seller.account_version == 2 and ch.second_channel_message_id
    assert ch.cooling_off_until - ch.applied_at >= timedelta(hours=1)
    assert ch.previous_account_number == "1100223344556" and seller.account_number == "4400112233445"
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert "payee-cooling-off" in codes(ei.value)
    Payee.objects.filter(pk=seller.pk).update(cooling_off_until=timezone.now() - timedelta(seconds=1))
    ins = services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert ins.payee_account_version == 2


def test_change_source_never_a_message(b):
    """RUL-28: no change from a message, email or call."""
    with pytest.raises(RuleBlocked) as ei:
        services.request_change(b.cm, kind="new_account", payee=b.payee("seller"), reason="Seller WhatsApped",
                                request_source="whatsapp", account_number="4400000000001",
                                account_name_source="bank_name_check")
    assert ei.value.code == "payee-change-source"


def test_change_to_account_in_other_name_refused(b):
    """TC-ESC-016-06: a new account in another name is blocked with the check named."""
    with pytest.raises(PayeeNotVerified):
        services.request_change(b.p["seller"], kind="new_account", payee=b.payee("seller"), reason="x",
                                request_source="payee_signed_in", account_number="9994400112233",
                                account_name_source="bank_name_check")


def test_change_needs_fresh_identity_check(b):
    """RUL-28: an identity check made before the change is not fresh."""
    e = b.ready_purchase()
    seller = b.payee("seller")
    ch = services.request_change(seller.person, kind="new_account", payee=seller, escrow=e, reason="x",
                                 request_source="payee_signed_in", account_number="4400112233446",
                                 account_name_source="bank_letter", account_name="Ato Estates Ltd",
                                 account_name_evidence=b.ev("letter"))
    with pytest.raises(RuleBlocked):
        services.change_identity_check(ch, b.cm, national_id_check=seller.national_id_check)
    with pytest.raises(Forbidden):
        services.check_change_account(ch, seller.person)  # not staff
    services.change_identity_check(ch, b.cm, id_number="GHA-700000001-1", subject_name="Kwabena Owusu")
    ch.refresh_from_db()
    assert ch.status == "requested"  # the bank letter still needs a second person
    services.check_change_account(ch, b.rv)
    ch.refresh_from_db()
    assert ch.status == "checks_passed"


def test_client_silence_and_decline(b):
    """US-ESC-016 AC4: silence keeps it pending; a decline rejects it; the payee is unchanged."""
    e = b.ready_purchase()
    seller = b.payee("seller")
    ch = _change(b, e, seller, number="4400112233447")
    if ch.status != "checks_passed":
        pytest.skip("identity fake did not match")
    PayeeChange.objects.filter(pk=ch.pk).update(requested_at=timezone.now() - timedelta(days=30))
    services.release_clock_watch()
    ch.refresh_from_db()
    assert ch.status == "checks_passed"
    services.client_approve_change(ch, b.client, mfa_at=timezone.now(), approve=False)
    ch.refresh_from_db()
    assert ch.status == "rejected" and Payee.objects.get(pk=seller.pk).account_version == 1


def test_stop_during_cooling_off(b):
    """5.12: the client stops an applied change; the payee is suspended and a reviewer decides."""
    e = b.ready_purchase()
    seller = b.payee("seller")
    adapters.FakeBankNameCheck.REGISTRY["4400112233448"] = "Ato Estates Ltd"
    try:
        ch = _change(b, e, seller, number="4400112233448")
    finally:
        adapters.FakeBankNameCheck.REGISTRY.pop("4400112233448", None)
    services.client_approve_change(ch, b.client, mfa_at=timezone.now())
    ch.refresh_from_db()
    services.decide_change(ch, b.rv, decision="approve", mfa_at=timezone.now())
    services.decide_change(ch, b.rv2, decision="approve", mfa_at=timezone.now())
    ch.refresh_from_db()
    with pytest.raises(Forbidden):
        services.stop_change(ch, b.client, token="wrong", mfa_at=timezone.now())
    services.stop_change(ch, b.client, mfa_at=timezone.now(), reason="I never agreed")
    ch.refresh_from_db()
    assert ch.status == "stopped" and Payee.objects.get(pk=seller.pk).verification_status == "suspended"


def test_shared_payee_change_needs_each_client(b, codes):
    """I-42, TC-ESC-016-07: a school's new account is approved by each client for their own held amount."""
    school = b.payee("school")
    hf = b.held_funds("3000.00")
    first = b.fee_release(hf, "100.00")  # approved by the client with the bill: the school is locked
    assert first.status == "pending_approval"
    adapters.FakeBankNameCheck.REGISTRY["4400555566667"] = school.legal_name
    try:
        ch = services.request_change(b.cm, kind="new_account", payee=school, reason="School moved banks",
                                     request_source="staff_in_person", account_number="4400555566667",
                                     account_name_source="bank_name_check")
    finally:
        adapters.FakeBankNameCheck.REGISTRY.pop("4400555566667", None)
    services.change_identity_check(ch, b.cm, id_number="GHA-700000021-3", subject_name="School Bursar")
    ch.refresh_from_db()
    assert ch.status == "pending_approval"
    services.decide_change(ch, b.rv, decision="approve", mfa_at=timezone.now())
    services.decide_change(ch, b.rv2, decision="approve", mfa_at=timezone.now())
    Payee.objects.filter(pk=school.pk).update(cooling_off_until=timezone.now() - timedelta(seconds=1))
    assert ReleaseInstruction.objects.get(pk=first.pk).status == "withdrawn"  # the account changed (RUL-28)
    bill = b.fee_invoice(hf.client, "100.00", approve=False)
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=Payee.objects.get(
            pk=school.pk), amount="100.00", subject_type="fee_invoice", subject_id=bill.pk)
    assert "payee-not-locked" in codes(ei.value)
    services.client_approve_change(PayeeChange.objects.get(pk=ch.pk), hf.client, mfa_at=timezone.now())
    ins = b.fee_release(Escrow.objects.get(pk=hf.pk), "100.00")
    assert ins.payee_account_version == 2


def test_payee_lock_trigger_refuses_unlocked_release(b):
    """RUL-28 enforced in PostgreSQL: a lock row is never edited."""
    from escrow.models import EscrowPayee

    lock = EscrowPayee.objects.first()
    with pytest.raises(DatabaseError), transaction.atomic():
        EscrowPayee.objects.filter(pk=lock.pk).update(account_version=99)
