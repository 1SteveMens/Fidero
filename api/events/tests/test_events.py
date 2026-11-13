from datetime import timedelta

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from core.errors import DomainError, PayeeNotVerified, RuleBlocked
from events import services
from events.models import Event, VendorPayment
from events.seed import _doc, _photo, _vendor

FUTURE = (timezone.localdate() + timedelta(days=30)).isoformat()


@pytest.fixture
def event(gh, people, seeded):
    def make(budget="20000.00", confirmer=True):
        return services.create_event(people["client"], country=gh, kind="wedding", name="Test wedding",
                                     event_date=timezone.localdate() + timedelta(days=30),
                                     budget={"amount": budget, "currency": "GHS"},
                                     confirmer_family_member_id=seeded["family_members"]["mother"].pk
                                     if confirmer else None)

    return make


_n = {"i": 0}


@pytest.fixture
def vendor(people):
    def make(e, name="Golden Plate Caterers", quote="8000.00", verify=True):
        _n["i"] += 1
        i = _n["i"]
        return _vendor(e, people, kind="caterer", name=name, quote=quote, number=f"T-{i}",
                       account=f"11009{i:03d}0001", signatory=f"Signer {i}", nid_number=f"GHA-7009{i:05d}-1",
                       verify=verify)

    return make


@pytest.fixture
def funded(people):
    from escrow import services as esc

    def make(e, amount="20000.00"):
        escrow = services.open_escrow(e, people["client"])
        for party in escrow.parties.filter(must_accept=True, role="tenmina"):
            esc.accept_terms(escrow, people["cm"], party=party)
        esc.record_virtual_account(escrow, people["cm"], virtual_account_ref=f"VA-GH-EVT-T{escrow.pk.hex[-8:]}")
        ev = esc.record_bank_event(escrow, kind="deposit", amount=amount, bank_reference=f"DEP-{escrow.pk.hex[-10:]}",
                                   by=people["cm"], source="manual",
                                   proof_evidence=_doc(e.country, people["cm"], "advice.txt"),
                                   source_bank_name="NatWest", source_account_number="GB29NWBK60161331926819",
                                   source_account_name="AMA MENSAH")
        esc.check_bank_event(ev, people["reviewer"])
        e.refresh_from_db()
        return e

    return make


# --------------------------------------------------------------------------- FR-EVT-001

def test_create_event_api(api, people, settings):
    """FR-EVT-001, US-EVT-001: a client creates an event with a budget and a date; past dates and a closed
    line are refused."""
    c = api(people["client"])
    body = {"country": "GH", "kind": "funeral", "name": "One-week celebration", "event_date": FUTURE,
            "budget": {"amount": "12000.00", "currency": "GHS"}}
    r = c.post("/v1/events", body, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "planning" and r.json()["budget"] == {"amount": "12000.00", "currency": "GHS"}
    past = c.post("/v1/events", {**body, "event_date": "2020-01-01"}, format="json")
    assert past.status_code == 422
    assert api(people["client2"]).get(f"/v1/events/{r.json()['id']}").status_code == 404
    settings.TENMINA_FLAG_OVERRIDES = {"lines.evt": False}
    assert c.post("/v1/events", body, format="json").json()["code"] == "feature-off"


def test_vendor_unverified_until_two_staff_check(api, people, event, vendor):
    """FR-EVT-001, US-EVT-001 AC1, TC-EVT-001-01: a vendor is unverified until its registration case and its
    account name are checked by two staff."""
    e = event()
    c = api(people["client"])
    r = c.post(f"/v1/events/{e.pk}/vendors", {"kind": "printer", "name": "Quick Print Ltd",
                                              "quote": {"amount": "900.00", "currency": "GHS"}}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "verifying" and r.json()["verification_case"]
    assert {b["code"] for b in r.json()["blockers"]} == {"vendor-check-open", "payee-missing"}
    v = vendor(e)
    assert v.status == "verified" and v.payee.verification_status == "verified"
    assert v.payee.verified_by_id != v.payee.second_check_by_id


def test_relative_is_never_a_vendor(people, event, seeded):
    """RUL-22: a family member of the client cannot be added as a vendor."""
    e = event()
    with pytest.raises(PayeeNotVerified):
        services.add_vendor(e, people["client"], kind="caterer", name="Akosua Mensah")


def test_no_payment_to_unverified_vendor(people, event, vendor):
    """TC-EVT-001-02: an unverified vendor is listed as unverified and no payment is possible."""
    e = event()
    v = vendor(e, verify=False)
    with pytest.raises(PayeeNotVerified):
        services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="deposit",
                                 amount={"amount": "100.00", "currency": "GHS"})
    with pytest.raises(RuleBlocked) as x:
        services.open_escrow(e, people["client"])
    assert x.value.code == "vendor-not-verified"


def test_budget_warning_before_approval(api, mfa, people, event, vendor, funded):
    """US-EVT-001 AC2: when vendor quotes exceed the budget the client is warned before approving."""
    e = event(budget="10000.00")
    v = vendor(e, quote="8000.00")
    vendor(e, name="Second Caterer", quote="7000.00")
    e = funded(e, "10000.00")
    assert api(people["client"]).get(f"/v1/events/{e.pk}").json()["warnings"][0]["code"] == "quotes-over-budget"
    p = services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="deposit",
                                 amount={"amount": "2000.00", "currency": "GHS"})
    c = api(people["client"])
    mfa(c, people["client"])
    r = c.post(f"/v1/vendor-payments/{p.pk}/client-approval", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "budget-warning"
    r = c.post(f"/v1/vendor-payments/{p.pk}/client-approval", {"acknowledge_budget_warning": True}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "instructed", r.content


# --------------------------------------------------------------------------- FR-EVT-002

def test_deposit_rules(people, event, vendor, funded):
    """FR-EVT-002, US-EVT-002 AC1: a deposit needs a signed quote and stays within the configured share; the
    budget is never exceeded."""
    e = event(budget="20000.00")
    v = vendor(e, quote="8000.00")
    with pytest.raises(RuleBlocked) as x:
        services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="deposit",
                                 amount={"amount": "5000.00", "currency": "GHS"})
    assert x.value.code == "deposit-too-large"
    v.quote_evidence = None
    v.save(update_fields=["quote_evidence"])
    with pytest.raises(RuleBlocked) as x:
        services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="deposit",
                                 amount={"amount": "1000.00", "currency": "GHS"})
    assert x.value.code == "quote-missing"
    with pytest.raises(RuleBlocked) as x:
        services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="full",
                                 amount={"amount": "25000.00", "currency": "GHS"})
    assert x.value.code == "budget-exceeded"


def test_balance_without_delivery_evidence_cannot_be_approved(api, mfa, people, event, vendor, funded):
    """FR-EVT-002, TC-EVT-002-02: no invoice, delivery evidence or family confirmation, no approval."""
    e = event()
    v = vendor(e)
    e = funded(e)
    p = services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="full",
                                 amount={"amount": "8000.00", "currency": "GHS"})
    assert p.status == "proposed"
    assert {m["code"] for m in services.evidence_missing(p)} == {"invoice-missing", "delivery-evidence-missing",
                                                                "visit-not-confirmed"}
    c = api(people["client"])
    mfa(c, people["client"])
    assert c.post(f"/v1/vendor-payments/{p.pk}/client-approval", {}, format="json").status_code == 409


def test_balance_needs_confirmer(people, event, vendor):
    e = event(confirmer=False)
    v = vendor(e)
    with pytest.raises(DomainError) as x:
        services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="full",
                                 amount={"amount": "100.00", "currency": "GHS"})
    assert x.value.code == "confirmer-missing"


def test_full_payment_journey_with_family_code(api, mfa, people, event, vendor, funded, seeded, monkeypatch):
    """FR-EVT-002, FR-EVT-003, US-EVT-002 AC2, US-EVT-003, TC-EVT-002-01, TC-EVT-003-01: a deposit against the
    signed quote and a balance against an invoice, delivery photos and the family member's code, each released to
    the vendor's verified account through the client and two staff; budget against actual and receipts."""
    from accounts.models import FamilyMember
    from escrow import services as esc
    from notifications import services as ntf

    auntie = people["family"]
    fm = FamilyMember.objects.create(country=seeded["gh"], client=people["client"], person=auntie,
                                     full_name=auntie.full_name, relationship="aunt", phone=auntie.phone,
                                     may_confirm_visits=True)
    e = event()
    services.set_confirmer(e, people["client"], fm.pk)
    v = vendor(e, quote="8000.00")
    e = funded(e)
    assert e.status == "funded"
    cm, client = api(people["cm"]), api(people["client"])
    mfa(client, people["client"])

    def release(pid):
        p = VendorPayment.objects.get(pk=pid)
        ins = p.release_instruction
        assert ins.payee_id == v.payee_id and ins.subject_type == "event_vendor_payment"
        esc.staff_approve(ins, people["reviewer"], mfa_at=timezone.now())
        esc.staff_approve(ins, people["reviewer2"], mfa_at=timezone.now())
        ins.refresh_from_db()
        bev = esc.record_bank_event(e.escrow, kind="release_confirmed", amount=ins.amount,
                                    bank_reference=f"BANK-{ins.pk.hex[-10:]}", by=people["cm"], source="manual",
                                    instruction=ins, proof_evidence=_doc(e.country, people["cm"], "debit.txt"))
        esc.check_bank_event(bev, people["reviewer"])

    r = cm.post(f"/v1/events/{e.pk}/vendor-payments", {"vendor_id": str(v.pk), "kind": "deposit",
                                                         "amount": {"amount": "4000.00", "currency": "GHS"}},
                format="json")
    assert r.status_code == 201 and r.json()["status"] == "evidenced", r.content
    dep = r.json()["id"]
    r = client.post(f"/v1/vendor-payments/{dep}/client-approval",
                    {"confirm_amount": {"amount": "4000.00", "currency": "GHS"}}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "instructed", r.content
    release(dep)
    assert VendorPayment.objects.get(pk=dep).status == "paid"

    monkeypatch.setattr(ntf.secrets, "randbelow", lambda n: 123456)
    r = cm.post(f"/v1/events/{e.pk}/vendor-payments", {
        "vendor_id": str(v.pk), "kind": "balance", "amount": {"amount": "4000.00", "currency": "GHS"},
        "invoice_evidence_id": str(_doc(e.country, people["cm"], "invoice.txt").pk),
        "delivery_evidence_ids": [str(_photo(e.country, people["cm"], f"served-{e.pk}").pk)]}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "proposed" and r.json()["confirmation_status"] == "pending"
    bal = r.json()["id"]
    fam = api(auntie)
    bad = fam.post(f"/v1/vendor-payments/{bal}/family-confirmations", {"code": "000000"}, format="json")
    assert bad.status_code == 422 and bad.json()["code"] == "confirmation-code-invalid"
    ok = fam.post(f"/v1/vendor-payments/{bal}/family-confirmations", {"code": "123456"}, format="json")
    assert ok.status_code == 200 and ok.json()["status"] == "evidenced", ok.content
    r = client.post(f"/v1/vendor-payments/{bal}/client-approval", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "instructed", r.content
    release(bal)
    e.refresh_from_db()
    assert e.status == "in_progress"
    receipts = client.get(f"/v1/events/{e.pk}/receipts").json()
    assert len(receipts) == 2 and all(x["account_last4"] == v.payee.last4 for x in receipts)
    bva = client.get(f"/v1/events/{e.pk}").json()["budget_vs_actual"]
    assert bva["paid"]["amount"] == "8000.00" and bva["remaining"]["amount"] == "12000.00"
    assert bva["vendors"][0]["payments"][0]["receipt"]["bank_reference"]
    assert client.post(f"/v1/events/{e.pk}/close", {}, format="json").json()["status"] == "closed"


def test_payment_to_a_relative_or_other_payee_is_blocked(people, event, vendor, funded, seeded):
    """TC-EVT-002-02, RUL-22: a release for a vendor payment naming any payee but the vendor's is blocked."""
    from escrow import services as esc

    e = event()
    v = vendor(e)
    e = funded(e)
    p = services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="deposit",
                                 amount={"amount": "1000.00", "currency": "GHS"})
    other = seeded["escrow"]["payees"]["carer"]
    with pytest.raises(RuleBlocked) as x:
        esc.request_release(e.escrow, payee=other, amount="1000.00", subject_type="event_vendor_payment",
                            subject_id=p.pk, requested_by=people["cm"], kind="partial_release")
    assert "payee-not-verified" in {b["code"] for b in x.value.blocking_reasons}


def test_database_keeps_payments_within_budget(people, event, vendor):
    """evt.budget_not_exceeded enforced twice."""
    e = event(budget="10000.00")
    v = vendor(e, quote="8000.00")
    p = services.propose_payment(e, people["cm"], vendor_id=v.pk, kind="deposit",
                                 amount={"amount": "3000.00", "currency": "GHS"})
    with pytest.raises(DatabaseError), transaction.atomic():
        VendorPayment.objects.filter(pk=p.pk).update(amount="12000.00")
    with pytest.raises(RuleBlocked):
        services.change_budget(e, people["client"], budget={"amount": "2000.00", "currency": "GHS"},
                               reason="Smaller")
    services.change_budget(e, people["client"], budget={"amount": "15000.00", "currency": "GHS"}, reason="More guests")
    e.refresh_from_db()
    assert e.budget_history[-1]["to"] == "15000.00"


def test_home_shows_payment_waiting_for_client(people, seeded):
    """The seeded funeral's caterer payment waits for the client: orange on the home screen."""
    from accounts import home

    items = [i for i in home.items_for(people["client"]) if i["kind"] == "event"]
    funeral = next(i for i in items if i["title"].startswith("Funeral"))
    assert funeral["needs_action"]
    assert Event.objects.get(pk=funeral["id"]).payments.filter(status="evidenced").exists()
