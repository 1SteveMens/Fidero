"""One Tenmina account per client per country, with commitments inside it (decision 2026-11-17; FR-ESC-025 to
FR-ESC-028, RUL-29, RUL-34; 05 TC-ESC-025 to TC-ESC-028). Every rule of the escrow module still holds on the new
structure: a commitment's money pays only that commitment's verified, locked payee."""
from decimal import Decimal

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from core.errors import Invalid, MfaRequired, RuleBlocked, StateConflict
from escrow import selectors, services
from escrow.models import BankEvent, ClientAccount, Escrow, ReleaseInstruction

D = Decimal


def _purchase(b, client, price="100000.00"):
    seller = b.payee("seller")
    return services.create_escrow(
        b.cm, kind="purchase", client=client, country=b.gh, agreed_amount=price, title="Account test plot",
        report_id=b.report(conditions=1),
        parties=[{"role": "seller", "person": b.p["seller"], "name": "Ato Estates Ltd", "payee": seller,
                  "national_id_check": seller.national_id_check}])


def _construction(b, client, amount="60000.00"):
    import uuid

    return services.open_line_escrow(kind="construction", client=client, country=b.gh, agreed_amount=amount, by=b.cm,
                                     title="Account test build", asset_id=uuid.uuid4(), project_id=uuid.uuid4(),
                                     payees=[b.payee("contractor")])


def _agree_line(b, e):
    from escrow.models import Party

    for party in Party.objects.filter(escrow=e, must_accept=True):
        if party.role == "tenmina":
            services.accept_terms(e, b.cm, party=party)
        elif party.person_id:
            services.accept_terms(e, party.person, party=party)
    if not Escrow.objects.get(pk=e.pk).virtual_account_ref:
        services.record_virtual_account(e, b.cm, virtual_account_ref=f"VA-SUB-{e.reference}")
    return Escrow.objects.get(pk=e.pk)


@pytest.fixture
def acct(b):
    """A fresh client with an open account and GHS 200,000 in its free balance."""
    client = b.new_client()
    free = b.held_funds("200000.00", client=client)
    return client, free


# ----------------------------------------------------------------- the account (FR-ESC-025, FR-ESC-026)

def test_one_account_per_client_per_country(b, acct):
    """TC-ESC-025-01: the free balance and every commitment are lines of one account with one pay-in reference."""
    client, free = acct
    e = _purchase(b, client)
    again = services.open_held_funds(client, b.gh, "GHS", by=client)
    assert free.account_id == e.account_id == again.account_id and again.pk == free.pk
    assert ClientAccount.objects.filter(client=client).count() == 1
    usd = services.record_fx_account(free, b.cm, currency="USD", virtual_account_ref=free.account.virtual_account_ref)
    assert usd.virtual_account_ref == free.virtual_account_ref == free.account.virtual_account_ref
    b.deposit(free, "500.00", currency="USD", va=free.virtual_account_ref)
    from escrow.accounts import balances

    assert [r["currency"] for r in balances(free.account)] == ["GHS", "USD"]
    assert selectors.held_at_bank(free, "USD") == D("500.00")
    with pytest.raises(IntegrityError), transaction.atomic():
        ClientAccount.objects.create(country=b.gh, client=client, reference="ACC-DUP", bank_partner=free.bank_partner,
                                     created_by=b.cm)


def test_pay_in_details_are_one_set_for_the_account(b, acct):
    """TC-ESC-025-02, RUL-01: one reference, the bank's programme account per currency; never a sub-ledger."""
    client, free = acct
    services.record_fx_account(free, b.cm, currency="USD", virtual_account_ref=free.account.virtual_account_ref)
    e = _agree_line(b, _purchase(b, client))
    pay = services.account_for(client, b.gh)
    from escrow.accounts import pay_in_details

    pi = pay_in_details(pay)
    assert pi["available"] and pi["reference"] == free.virtual_account_ref
    assert {x["currency"] for x in pi["lines"]} == {"GHS", "USD"}
    assert e.virtual_account_ref not in {x["virtual_account_ref"] for x in pi["lines"]}
    assert all("Tenmina" not in x["account_name"].replace("Tenmina Partner", "") for x in pi["lines"])


def test_line_belongs_to_its_own_clients_account_db(b, acct):
    """FR-ESC-025 enforced again in PostgreSQL: a line cannot move to another client's account."""
    client, free = acct
    other = b.held_funds(amount=None)
    with pytest.raises(IntegrityError), transaction.atomic():
        Escrow.objects.filter(pk=free.pk).update(account=other.account)


def test_commitment_pay_in_reference_is_never_the_accounts(b, acct):
    """RUL-34: a commitment keeps its own sub-ledger at the bank, distinct from the client's pay-in reference."""
    client, free = acct
    e = _purchase(b, client)
    with pytest.raises(StateConflict) as ei:
        services.record_virtual_account(e, b.cm, virtual_account_ref=free.virtual_account_ref)
    assert ei.value.code == "virtual-account-duplicate"


# ----------------------------------------------------------------- setting money aside (FR-ESC-027)

def test_fund_commitment_needs_the_clients_second_factor(b, acct):
    """TC-ESC-027-01, RUL-11: no fresh step-up and no code, or a wrong code: refused. Silence is never approval."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    with pytest.raises(MfaRequired):
        services.fund_commitment(e, client, amount="1000.00")
    with pytest.raises(MfaRequired):
        services.fund_commitment(e, client, amount="1000.00", code="000000")
    with pytest.raises(Exception):
        services.fund_commitment(e, b.cm, amount="1000.00", mfa_at=timezone.now())  # only the client


def test_commitment_counts_only_when_the_bank_confirms(b, acct):
    """TC-ESC-027-02: no staff approvals, sent to the bank at once; the commitment is funded on confirmation."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    ins = b.fund(e, "100000.00", confirm=False, deposit=False)
    assert ins.kind == "commitment_fund" and ins.approval_request_id is None and ins.status == "sent"
    assert ins.client_approved_by_id == client.pk and ins.payee_id is None
    e.refresh_from_db()
    assert e.status == "agreed" and selectors.held_at_bank(e) == 0
    assert selectors.available_to_instruct(free) == D("100000.00")  # reserved while the bank moves it
    b.confirm(ins)
    e.refresh_from_db()
    assert e.status == "funded" and selectors.held_at_bank(e) == D("100000.00")
    assert selectors.held_at_bank(free) == D("100000.00")
    credit = BankEvent.objects.get(escrow=e, kind="commitment_credit")
    assert credit.instruction_id == ins.pk and credit.virtual_account_ref == e.virtual_account_ref
    from escrow.accounts import balances

    row = balances(free.account)[0]
    assert row["held_at_bank"]["amount"] == "200000.00" and row["set_aside"]["amount"] == "100000.00"
    assert row["free_balance"]["amount"] == "100000.00"


def test_fund_cannot_exceed_free_balance_or_what_is_left_to_set_aside(b, acct, codes):
    """TC-ESC-027-03, RUL-34: never more than the free balance's own confirmed funds, never more than agreed."""
    client, free = acct
    small = _agree_line(b, _purchase(b, client, "50000.00"))
    with pytest.raises(RuleBlocked) as ei:
        services.fund_commitment(small, client, amount="60000.00", mfa_at=timezone.now())
    assert "commitment-overfunded" in codes(ei.value)
    big = _agree_line(b, _purchase(b, client, "500000.00"))
    with pytest.raises(RuleBlocked) as ei:
        services.fund_commitment(big, client, amount="300000.00", mfa_at=timezone.now())
    assert "held-funds-insufficient" in codes(ei.value)
    proposed = _purchase(b, client)
    with pytest.raises(RuleBlocked) as ei:
        services.fund_commitment(proposed, client, amount="1000.00", mfa_at=timezone.now())
    assert "commitment-not-agreed" in codes(ei.value)


def test_credit_leg_is_never_recorded_by_hand(b, acct):
    """ADR-18: the credit leg follows from the bank's one confirmation of the move."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    with pytest.raises(Invalid):
        services.record_bank_event(e, kind="commitment_credit", amount="10.00", bank_reference="X", by=b.cm,
                                   proof_evidence=b.ev())


def test_transfer_without_client_approval_refused_db(b, acct):
    """FR-ESC-027, RUL-11 enforced again in PostgreSQL: a move needs the client's approval to be sent."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    ins = ReleaseInstruction.objects.create(country=b.gh, escrow=free, to_escrow=e, kind="commitment_fund",
                                            amount="10.00", currency="GHS", prepared_by=client,
                                            status="awaiting_client")
    ins.status, ins.last_approval_at, ins.send_due_on = "approved", timezone.now(), timezone.localdate()
    with pytest.raises(IntegrityError), transaction.atomic():
        ins.save()


def test_release_cannot_skip_staff_like_a_transfer_db(b):
    """RUL-05: only a move inside the account may go from awaiting the client to approved."""
    e = b.ready_purchase()
    ins = services.request_release(e, requested_by=b.cm)
    ins.client_approved_at, ins.client_approved_by = timezone.now(), e.client
    ins.status, ins.last_approval_at, ins.send_due_on = "approved", timezone.now(), timezone.localdate()
    with pytest.raises(IntegrityError), transaction.atomic():
        ins.save()


def test_transfer_only_between_lines_of_one_account_db(b, acct):
    """FR-ESC-027 enforced again in PostgreSQL: never into another client's commitment."""
    client, free = acct
    other = b.new_client()
    b.held_funds(amount=None, client=other)
    theirs = _agree_line(b, _purchase(b, other))
    with pytest.raises(IntegrityError), transaction.atomic():
        ReleaseInstruction.objects.create(country=b.gh, escrow=free, to_escrow=theirs, kind="commitment_fund",
                                          amount="10.00", currency="GHS", prepared_by=client, status="awaiting_client")


# ----------------------------------------------------------------- the bank keeps each commitment apart (RUL-34)

def test_one_commitments_money_never_pays_another_commitments_payee(b, acct, codes):
    """TC-ESC-026-01, RUL-28, RUL-34: the account holds money for a purchase; a build's contractor cannot be paid
    from it, and the purchase cannot pay the contractor."""
    client, free = acct
    plot = _agree_line(b, _purchase(b, client, "120000.00"))
    b.fund(plot, "120000.00", deposit=False)
    build = _agree_line(b, _construction(b, client))
    assert selectors.held_at_bank(build) == 0 and selectors.held_at_bank(plot) == D("120000.00")
    # the build's own money is short, whatever the account holds for the plot

    import uuid

    ins = ReleaseInstruction(country=b.gh, escrow=build, kind="partial_release", subject_type="milestone",
                             subject_id=uuid.uuid4(), payee=b.payee("contractor"),
                             payee_account_version=b.payee("contractor").account_version, amount=D("10000.00"),
                             currency="GHS", prepared_by=b.cm)
    from escrow.blockers import funds_reasons, payee_reasons

    assert {r["code"] for r in funds_reasons(ins, "prepare")} == {"held-funds-insufficient"}
    # the plot's money cannot go to the contractor: not locked on the plot, wrong kind for a purchase release
    wrong = ReleaseInstruction(country=b.gh, escrow=plot, kind="partial_release", subject_type="milestone",
                               subject_id=uuid.uuid4(), payee=b.payee("contractor"),
                               payee_account_version=b.payee("contractor").account_version, amount=D("10000.00"),
                               currency="GHS", prepared_by=b.cm)
    assert "payee-not-locked" in {r["code"] for r in payee_reasons(wrong, "staff")}
    with pytest.raises(RuleBlocked):
        services.request_release(plot, payee=b.payee("contractor"), amount="10000.00", subject_type="milestone",
                                 subject_id=uuid.uuid4(), requested_by=b.cm)


def test_db_refuses_paying_another_commitments_payee(b, acct):
    """RUL-28, RUL-34 enforced again in PostgreSQL: a fully approved instruction on the plot naming the build's
    contractor is refused at sending."""
    import uuid

    from core import approvals

    client, free = acct
    plot = _agree_line(b, _purchase(b, client, "120000.00"))
    b.fund(plot, "120000.00", deposit=False)
    _agree_line(b, _construction(b, client))
    c = b.payee("contractor")
    req = approvals.request_approval("escrow_release", uuid.uuid4(), b.cm, required=2, country=b.gh, summary="t")
    from escrow.seed import _approve

    _approve(req, b.rv, b.rv2)
    req.refresh_from_db()
    ins = ReleaseInstruction.objects.create(
        country=b.gh, escrow=plot, kind="partial_release", subject_type="milestone", subject_id=uuid.uuid4(),
        payee=c, payee_account_version=c.account_version, amount="10000.00", currency="GHS", prepared_by=b.cm,
        approval_request=req, status="pending_approval", client_approved_at=timezone.now(), client_approved_by=client)
    ins.status, ins.last_approval_at, ins.send_due_on = "approved", timezone.now(), timezone.localdate()
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        ins.save()


def test_purchase_released_from_its_commitment(b, acct):
    """J-02 on the new structure: set aside, conditions, client and two staff, the bank pays the seller."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client, "100000.00"))
    b.fund(e, "100000.00", deposit=False)
    e = Escrow.objects.get(pk=e.pk)
    b.close_all(e)
    b.fresh(e)
    e = services.sync_status(Escrow.objects.get(pk=e.pk))
    assert e.status == "ready_to_release"
    ins = b.approve_all(services.request_release(e, requested_by=b.cm))
    b.confirm(ins)
    e.refresh_from_db()
    assert e.status == "released" and selectors.held_at_bank(e) == 0
    assert selectors.held_at_bank(free) == D("100000.00")  # the free balance is untouched


# ----------------------------------------------------------------- cancelled commitments (FR-ESC-028, RUL-29)

def test_cancelled_commitment_goes_back_to_the_source_of_the_deposit(b, acct):
    """TC-ESC-028-01, RUL-29: the refund names the client's deposit into the account and goes to its source."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    b.fund(e, "100000.00", deposit=False)
    services.request_cancellation(Escrow.objects.get(pk=e.pk), b.cm, reason="The seller withdrew")
    refund = ReleaseInstruction.objects.get(escrow=e, kind="cancel_refund")
    dep = refund.refund_source_event
    assert dep.escrow_id == free.pk and dep.kind == "deposit"
    refund = b.approve_all(refund, client=False)
    assert refund.status == "sent"
    b.confirm(refund)
    e.refresh_from_db()
    assert e.status == "cancelled" and selectors.held_at_bank(e) == 0
    assert selectors.held_at_bank(free) == D("100000.00")


def test_client_may_keep_a_cancelled_commitment_in_the_account(b, acct):
    """TC-ESC-028-02: only the client chooses, with their second factor; refunds not yet sent are withdrawn and the
    money returns to the free balance when the bank confirms it."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    b.fund(e, "100000.00", deposit=False)
    with pytest.raises(StateConflict):
        services.keep_in_account(Escrow.objects.get(pk=e.pk), client, mfa_at=timezone.now())
    services.request_cancellation(Escrow.objects.get(pk=e.pk), b.cm, reason="Changed plans")
    with pytest.raises(MfaRequired):
        services.keep_in_account(Escrow.objects.get(pk=e.pk), client)
    ins = services.keep_in_account(Escrow.objects.get(pk=e.pk), client, mfa_at=timezone.now())
    ins.refresh_from_db()
    assert ins.kind == "commitment_return" and ins.status == "sent" and ins.to_escrow_id == free.pk
    assert ReleaseInstruction.objects.get(escrow=e, kind="cancel_refund").status == "withdrawn"
    b.confirm(ins)
    e.refresh_from_db()
    assert e.status == "cancelled"
    assert selectors.held_at_bank(free) == D("200000.00") and selectors.available_to_instruct(free) == D("200000.00")


def test_return_only_from_a_cancelled_commitment_db(b, acct):
    """FR-ESC-028 enforced again in PostgreSQL."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    b.fund(e, "100000.00", deposit=False)
    with pytest.raises(IntegrityError), transaction.atomic():
        ReleaseInstruction.objects.create(country=b.gh, escrow=e, to_escrow=free, kind="commitment_return",
                                          amount="10.00", currency="GHS", prepared_by=client, status="awaiting_client")


def test_free_balance_still_pays_family_bills_by_the_old_rules(b, acct, codes):
    """FR-ESC-014 on the new structure: school fees are released from the free balance; client first, two staff."""
    client, free = acct
    ins = b.fee_release(free, "2500.00")
    assert ins.escrow_id == free.pk and ins.approval_request_id is not None and ins.payee.kind == "institution"
    if ins.status == "awaiting_client":
        with pytest.raises(RuleBlocked):
            services.staff_approve(ins, b.rv, mfa_at=timezone.now())
    ins = b.approve_all(ReleaseInstruction.objects.get(pk=ins.pk))
    assert ins.status == "sent"


# ----------------------------------------------------------------- the API (02 7.4)

def test_account_api_for_the_client(b, acct, api, mfa):
    """GET /v1/account, the commitments list and detail, and setting money aside with a fresh step-up."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    c = api(client)
    r = c.get("/v1/account")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["pay_in"]["available"] and body["pay_in"]["reference"] == free.virtual_account_ref
    assert body["seal"] == "Held at the bank · Released on proof"
    assert body["balances"][0]["free_balance"]["amount"] == "200000.00"
    assert [x["id"] for x in body["commitments"]] == [str(e.pk)]
    r = c.post("/v1/account/commitments", {"commitment_id": str(e.pk), "amount": {"amount": "40000.00",
                                                                                  "currency": "GHS"}},
               format="json")
    assert r.status_code == 401  # no step-up
    mfa(c, client)
    r = c.post("/v1/account/commitments", {"commitment_id": str(e.pk), "amount": {"amount": "40000.00",
                                                                                  "currency": "GHS"}},
               format="json")
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "commitment_fund" and r.json()["status"] == "sent"
    r = c.get("/v1/account/commitments")
    assert r.json()[0]["on_its_way_in"]["amount"] == "40000.00"
    r = c.get(f"/v1/account/commitments/{e.pk}")
    assert r.status_code == 200 and r.json()["transfers"][0]["to_escrow"] == str(e.pk)
    other = api(b.new_client())
    assert other.get(f"/v1/account/commitments/{e.pk}").status_code == 404
    assert other.get("/v1/account").status_code == 404
    assert c.get("/v1/accounts").status_code == 403


def test_account_api_for_staff(b, acct, api):
    """The back office sees the account, its commitments and the bank's position per account and per commitment."""
    client, free = acct
    e = _agree_line(b, _purchase(b, client))
    b.fund(e, "50000.00", deposit=False)
    s = api(b.cm)
    r = s.get("/v1/accounts", {"client": str(client.pk)})
    assert r.status_code == 200, r.content
    rows = r.json()["items"] if isinstance(r.json(), dict) else r.json()
    assert rows[0]["reference"] == free.account.reference and rows[0]["open_commitments"] == 1
    r = s.get(f"/v1/accounts/{free.account_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["commitments"][0]["set_aside"]["amount"] == "50000.00"
    assert "bank_position" in body["balances"][0] and "bank_position" in body["commitments"][0]


def test_open_account_over_the_api(b, api):
    """POST /v1/account opens the account and its free balance; the client accepts the terms."""
    client = b.new_client()
    c = api(client)
    r = c.post("/v1/account", {"country": "GH"}, format="json")
    assert r.status_code == 201, r.content
    assert ClientAccount.objects.filter(client=client).count() == 1
    assert Escrow.objects.get(client=client, kind="held_funds").status in ("proposed", "agreed")
