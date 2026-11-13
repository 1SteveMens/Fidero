"""Bank events, confirmed funds and refunds: FR-ESC-004, 011, 013, 014, 017, 019; RUL-29, RUL-34 (ADR-18, ADR-26)."""
import uuid
from decimal import Decimal

import pytest
from django.db import DatabaseError, IntegrityError, transaction

from core.errors import Forbidden, Invalid, PayeeNotVerified, RuleBlocked, StateConflict
from escrow import selectors, services
from escrow.models import BankEvent, BankPosition, Escrow, ReleaseInstruction


def test_manual_deposit_needs_proof_and_second_person(b):
    """FR-ESC-004 AC1, TC-ESC-004-03: no proof refused; the same person cannot check; funded only after the check."""
    e = b.agree(b.purchase())
    with pytest.raises(Invalid):
        services.record_bank_event(e, kind="deposit", amount="100000.00", bank_reference="X1", by=b.cm,
                                   source_account_number="1", source_account_name="A")
    ev = b.deposit(e, "100000.00", check=False)
    assert ev.status == "pending_check" and Escrow.objects.get(pk=e.pk).status == "agreed"
    assert selectors.held_at_bank(e) == 0
    with pytest.raises(Forbidden):
        services.check_bank_event(ev, b.cm)
    services.check_bank_event(ev, b.rv)
    assert Escrow.objects.get(pk=e.pk).status == "funded"
    assert selectors.held_at_bank(e) == Decimal("100000.00")


def test_deposit_records_source_account(b):
    """FR-ESC-017 AC1: the source account from the bank's confirmation is stored; none means refused."""
    e = b.agree(b.purchase())
    with pytest.raises(Invalid):
        services.record_bank_event(e, kind="deposit", amount="10.00", bank_reference="X2", by=b.cm,
                                   proof_evidence=b.ev())
    ev = b.deposit(e, "10.00", known=False)
    assert ev.source_account_known is False


def test_duplicate_confirmation_counts_once(b):
    """FR-ESC-019 AC2: a duplicate confirmation counts once."""
    e = b.agree(b.purchase())
    b.deposit(e, "500.00", ref="DUP-1")
    again = b.deposit(e, "500.00", ref="DUP-1", check=False)
    assert again.status == "confirmed"
    assert selectors.held_at_bank(e) == Decimal("500.00")


def test_wrong_virtual_account_is_not_this_escrows(b):
    """RUL-34, US-ESC-019 AC4: a line under another reference never counts here."""
    e1 = b.agree(b.purchase())
    e2 = b.agree(b.purchase())
    with pytest.raises(RuleBlocked) as ei:
        b.deposit(e1, "500.00", va=e2.virtual_account_ref)
    assert ei.value.code == "virtual-account-mismatch"


def test_misdirected_deposit_cannot_be_released(b, codes):
    """US-ESC-019 AC4: credited by mistake, it cannot pay this escrow; the bank's correction moves it."""
    hf = b.held_funds(amount=None)
    b.deposit(hf, "900.00", misdirected=True)
    assert selectors.held_at_bank(hf) == Decimal("900.00")
    assert selectors.available_to_instruct(hf) == 0
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=b.payee("school"),
                                 amount="100.00", subject_type="fee_invoice", subject_id=uuid.uuid4())
    assert "held-funds-insufficient" in codes(ei.value)


def test_release_larger_than_confirmed_funds_blocked(b):
    """RUL-34, FR-ESC-014 AC2, FR-ESC-019 AC3: shortfall named; no override."""
    hf = b.held_funds("1000.00")
    first = services.request_release(hf, requested_by=b.cm, payee=b.payee("school"), amount="800.00",
                                     subject_type="fee_invoice", subject_id=uuid.uuid4())
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=hf.pk), requested_by=b.cm, payee=b.payee("school"),
                                 amount="300.00", subject_type="fee_invoice", subject_id=uuid.uuid4())
    assert ei.value.code == "held-funds-insufficient"
    assert ei.value.blocking_reasons[0]["shortfall"]["amount"] == "100.00"
    assert first.status == "awaiting_client"


def test_held_funds_statement_from_bank_events_only(b):
    """FR-ESC-014 AC1, ADR-18: deposits, releases and held at the bank, from bank-confirmed events only."""
    hf = b.held_funds("1000.00")
    fm = b.ctx["family_members"]["mother"]
    ins = services.request_release(hf, requested_by=b.cm, payee=b.payee("school"), amount="250.00",
                                   subject_type="fee_invoice", subject_id=uuid.uuid4(), family_member_id=fm.pk)
    b.confirm(b.approve_all(ins))
    funds = selectors.confirmed_funds(Escrow.objects.get(pk=hf.pk))[0]
    held_before = funds["held_at_bank"]
    pending = b.deposit(Escrow.objects.get(pk=hf.pk), "75.00", check=False)
    assert selectors.held_at_bank(hf) == held_before  # unconfirmed entry changes nothing
    st = selectors.statement(hf, family_member_id=fm.pk)
    assert any(r["kind"] == "release_confirmed" and r["amount"] == Decimal("-250.00") for r in st["lines"])
    assert any(r["id"] == str(pending.pk) and not r["counts"] for r in st["lines"])


def test_held_funds_one_per_client_country_currency(b):
    """FR-ESC-014: one held amount per client, country and currency."""
    a = b.held_funds(None, client=b.client)
    assert services.open_held_funds(b.client, b.gh, "GHS", by=b.client).pk == a.pk


def test_bank_position_mismatch_blocks_until_resolved_by_two(b, codes):
    """FR-ESC-019, RB-47: a mismatch blocks releases; a reviewer and a second staff member resolve it."""
    e = b.ready_purchase()
    pos = services.record_bank_position(e, as_of=e.created_at.date(), reported_held_amount="90000.00", by=b.cm,
                                        proof_evidence=b.ev("daily"))
    with pytest.raises(Forbidden):
        services.check_bank_position(pos, b.cm)
    pos = services.check_bank_position(pos, b.rv)
    assert pos.status == "mismatch"
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    assert "bank-position-mismatch" in codes(ei.value)
    services.resolve_position(pos, b.rv, note="Bank's report was a day early", evidence=b.ev("bank-letter"))
    with pytest.raises(Forbidden):
        services.check_resolution(pos, b.rv)
    services.check_resolution(pos, b.rv2)
    assert BankPosition.objects.get(pk=pos.pk).status == "resolved"
    assert services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)


def test_virtual_account_unique_and_never_tenmina(b):
    """US-ESC-019 AC1, TC-ESC-019-02: a duplicate or a Tenmina operating account is refused."""
    from administration.models import Partner

    e1 = b.agree(b.purchase())
    e2 = b.purchase()
    with pytest.raises(StateConflict):
        services.record_virtual_account(e2, b.cm, virtual_account_ref=e1.virtual_account_ref)
    op = Partner.objects.filter(kind="operating_bank").exclude(account_number="").first()
    if op is not None:
        with pytest.raises(RuleBlocked):
            services.record_virtual_account(e2, b.cm, virtual_account_ref=op.account_number)


def test_payment_instructions_are_the_banks_only(b):
    """FR-ESC-003, RUL-01: only the bank's programme account and the escrow's own reference."""
    e = b.purchase()
    assert services.payment_instructions(e)["available"] is False
    e = b.agree(e)
    pi = services.payment_instructions(e)
    assert pi["virtual_account_ref"] == e.virtual_account_ref
    assert pi["account_number"] == e.programme_account.account_number


def test_bank_facts_never_edited(b):
    """ADR-18: the database refuses edits to a bank event's facts."""
    e = b.agree(b.purchase())
    ev = b.deposit(e, "10.00")
    with pytest.raises(IntegrityError), transaction.atomic():
        BankEvent.objects.filter(pk=ev.pk).update(amount="1000.00")
    with pytest.raises(DatabaseError), transaction.atomic():
        BankEvent.objects.filter(pk=ev.pk).delete()


def test_cancellation_refunds_each_deposit_to_its_source(b):
    """FR-ESC-013, FR-ESC-017 AC2, TC-ESC-017-02: two deposits, two refunds, two staff approvals each."""
    e = b.agree(b.purchase(price="1000.00"))
    d1 = b.deposit(e, "600.00", number="SRC-ONE-0001", name="AMA MENSAH")
    d2 = b.deposit(e, "400.00", number="SRC-TWO-0002", name="AMA MENSAH")
    services.request_cancellation(Escrow.objects.get(pk=e.pk), b.cm, reason="Seller withdrew")
    refunds = list(ReleaseInstruction.objects.filter(escrow=e, kind="cancel_refund"))
    assert {(r.refund_source_event_id, r.amount) for r in refunds} == {(d1.pk, Decimal("600.00")),
                                                                       (d2.pk, Decimal("400.00"))}
    for r in refunds:
        r = b.approve_all(r, client=False)
        assert r.status == "sent"
        b.confirm(r)
    e.refresh_from_db()
    assert e.status == "cancelled" and selectors.held_at_bank(e) == 0


def test_refund_cannot_exceed_its_deposit(b):
    """RUL-29, TC-ESC-019-05: a refund is never larger than what is left of its deposit."""
    e = b.agree(b.purchase(price="1000.00"))
    d1 = b.deposit(e, "600.00")
    b.deposit(e, "400.00")
    with pytest.raises(RuleBlocked) as ei:
        services.prepare_refund(Escrow.objects.get(pk=e.pk), b.cm, deposit=d1, amount="700.00")
    assert "refund-exceeds-deposit" in {r["code"] for r in ei.value.blocking_reasons}


def test_refund_without_source_needs_exception_path(b, codes):
    """FR-ESC-017 AC3, RUL-29: no source account means the exception path; account in the client's own name."""
    e = b.agree(b.purchase(price="1000.00"))
    dep = b.deposit(e, "1000.00", known=False)
    services.request_cancellation(Escrow.objects.get(pk=e.pk), b.cm, reason="Buyer changed mind")
    r = ReleaseInstruction.objects.get(escrow=e, kind="cancel_refund")
    with pytest.raises(RuleBlocked) as ei:
        services.staff_approve(r, b.rv, mfa_at=b.now())
    assert "refund-exception-required" in codes(ei.value)
    with pytest.raises(PayeeNotVerified):
        services.request_change(b.cm, kind="refund_destination", reason="Relative's account", escrow=e,
                                deposit_event=dep, request_source="staff_in_person",
                                account_number="7700112233445", account_name="Kojo Mensah",
                                account_name_source="bank_letter", account_name_evidence=b.ev("letter"))
    ch = services.request_change(b.cm, kind="refund_destination", reason="Cash deposit at branch", escrow=e,
                                 deposit_event=dep, request_source="staff_in_person", account_number="7700112233445",
                                 account_name_source="bank_name_check")
    services.change_identity_check(ch, b.cm, id_number="GHA-712345678-1", subject_name=b.client.full_name)
    ch.refresh_from_db()
    assert ch.status == "checks_passed"
    services.client_approve_change(ch, b.client, mfa_at=b.now())
    ch.refresh_from_db()
    services.decide_change(ch, b.rv, decision="approve", mfa_at=b.now())
    services.decide_change(ch, b.rv2, decision="approve", mfa_at=b.now())
    r.refresh_from_db()
    assert r.refund_change_id == ch.pk
    with pytest.raises(RuleBlocked) as ei:
        services.staff_approve(r, b.rv, mfa_at=b.now())
    assert "payee-cooling-off" in codes(ei.value)
    from datetime import timedelta

    from escrow.models import PayeeChange

    PayeeChange.objects.filter(pk=ch.pk).update(cooling_off_until=b.now() - timedelta(seconds=1),
                                                applied_at=b.now() - timedelta(hours=73))
    r = b.approve_all(r, client=False)
    assert r.status == "sent"


def test_unused_money_refunded_after_last_release(b):
    """RUL-36, FR-ESC-022 AC4: money above the price goes back to its source; then released."""
    e = b.agree(b.purchase(price="1000.00"))
    b.deposit(e, "1000.00")
    b.deposit(e, "50.00", number="SRC-EXTRA")
    e = Escrow.objects.get(pk=e.pk)
    b.close_all(e)
    b.fresh(e)
    ins = services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    b.confirm(b.approve_all(ins))
    e.refresh_from_db()
    assert e.status == "partly_released"
    refund = ReleaseInstruction.objects.get(escrow=e, kind="cancel_refund")
    assert refund.amount == Decimal("50.00")
    b.confirm(b.approve_all(refund, client=False))
    e.refresh_from_db()
    assert e.status == "released"


def test_cannot_close_while_money_is_held(b):
    """esc.unused_funds: the database refuses released or cancelled while money is held."""
    e = b.ready_purchase()
    with pytest.raises(IntegrityError), transaction.atomic():
        Escrow.objects.filter(pk=e.pk).update(status="released")


def test_statement_import(b):
    """FR-ESC-011: matched lines confirm deposits and releases; unmatched listed; the same file never twice."""
    e = b.agree(b.purchase(price="2000.00"))
    csv = ("booked_on,kind,amount,currency,virtual_account_ref,bank_reference,counterparty_bank,"
           "counterparty_account,counterparty_name,narrative\n"
           f"2026-11-12,credit,2000.00,GHS,{e.virtual_account_ref},ST-1,NatWest,GB1234567,AMA MENSAH,deposit\n"
           "2026-11-12,credit,55.00,GHS,VA-NOBODY,ST-2,Bank,123,SOMEONE,unknown\n"
           f"2026-11-12,position,2000.00,GHS,{e.virtual_account_ref},POS-1,,,,daily figure\n")
    sf = services.import_statement(b.cm, country=b.gh, data=csv.encode(), original_name="day.csv")
    assert (sf.matched_count, sf.unmatched_count) == (2, 1)
    assert Escrow.objects.get(pk=e.pk).status == "funded"
    assert [ln.virtual_account_ref for ln in services.unmatched_lines(sf)] == ["VA-NOBODY"]
    assert BankPosition.objects.get(escrow=e).status == "matched"
    with pytest.raises(StateConflict):
        services.import_statement(b.cm, country=b.gh, data=csv.encode())
    e = Escrow.objects.get(pk=e.pk)
    b.close_all(e)
    b.fresh(e)
    ins = b.approve_all(services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm))
    debit = ("booked_on,kind,amount,currency,virtual_account_ref,bank_reference,counterparty_bank,"
             "counterparty_account,counterparty_name,narrative\n"
             f"2026-11-13,debit,2000.00,GHS,{e.virtual_account_ref},ST-3,,,,{ins.pk}\n")
    services.import_statement(b.cm, country=b.gh, data=debit.encode(), original_name="day2.csv")
    assert ReleaseInstruction.objects.get(pk=ins.pk).status == "confirmed"
    assert Escrow.objects.get(pk=e.pk).status == "released"


def test_bad_statement_refused(b):
    """FR-ESC-011: a file in another format is refused with the reason."""
    with pytest.raises(Invalid):
        services.import_statement(b.cm, country=b.gh, data=b"date,amount\n2026-01-01,5\n")
