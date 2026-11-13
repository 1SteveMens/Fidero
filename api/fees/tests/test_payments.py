"""EP-FEE invoices, approval, payment on both routes, receipts, schedules, runners, statements
(FR-FEE-002 to FR-FEE-007, RUL-05, RUL-11, RUL-22)."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core.errors import Invalid, MfaRequired, NotFound, RuleBlocked, StateConflict

from .helpers import approve, b64doc, checked_invoice, contact_person, doc, fund_held, new_institution, \
    staff_approve_and_confirm

pytestmark = pytest.mark.django_db


def _mother(people):
    return people["client"].family_members.get(full_name="Akosua Mensah")


# ----------------------------------------------------------------- checks (FR-FEE-002)

def test_invoice_for_pending_institution_waits(seeded, people, gh):
    """TC-FEE-001-02: a bill for an institution not yet verified is accepted for later; its check is blocked."""
    from fees import services
    from fees.models import Institution

    clinic = Institution.objects.get(legal_name="Tema Community Clinic (demo)")
    inv = services.submit_invoice(people["client"], institution=clinic, family_member=_mother(people),
                                  institution_reference="TCC-1", amount="80.00", evidence=doc(people["client"], gh))
    assert inv.status == "submitted"
    with pytest.raises(RuleBlocked) as e:
        services.check_invoice(inv, people["cm"], outcome="checked", note="x")
    assert e.value.code == "institution-not-verified"


def test_flags_wrong_person_and_wrong_account(seeded, people, gh):
    """TC-FEE-002-03, US-FEE-002 AC3, TC-SEC-34: a bill naming another patient is flagged until staff resolve it;
    a bill naming another account can never be approved."""
    from fees import services

    inst = new_institution(gh, people)
    contact = inst.contacts.get()
    inv = services.submit_invoice(people["client"], institution=inst, family_member=_mother(people),
                                  institution_reference="W-1", amount="90.00", name_on_invoice="Yaw Darko",
                                  evidence=doc(people["client"], gh))
    assert inv.check_status == "flagged" and inv.check_flags[0]["code"] == "names-another-person"
    with pytest.raises(RuleBlocked) as e:
        services.check_invoice(inv, people["cm"], outcome="checked", contact=contact)
    assert e.value.code == "invoice-flagged"
    services.check_invoice(inv, people["cm"], outcome="checked", contact=contact, resolve_flags=True,
                           note="Hospital confirmed the patient is registered under her husband's name")
    inv.refresh_from_db()
    assert inv.status == "checked" and inv.checked_by == people["cm"]
    bad = services.submit_invoice(people["client"], institution=inst, family_member=_mother(people),
                                  institution_reference="W-2", amount="90.00", account_number_on_invoice="5555444433",
                                  evidence=doc(people["client"], gh))
    with pytest.raises(RuleBlocked) as e:
        services.check_invoice(bad, people["cm"], outcome="checked", contact=contact, resolve_flags=True, note="x")
    assert e.value.code == "payee-not-verified"


def test_reference_reused_and_contact_confirmation_required(seeded, people, gh):
    """TC-FEE-002-03: a reused reference is refused; a check needs the named contact's confirmation."""
    from fees import services

    inst = new_institution(gh, people)
    inv = services.submit_invoice(people["client"], institution=inst, family_member=_mother(people),
                                  institution_reference="R-1", amount="50.00", evidence=doc(people["client"], gh))
    with pytest.raises(StateConflict) as e:
        services.submit_invoice(people["client"], institution=inst, family_member=_mother(people),
                                institution_reference="R-1", amount="50.00", evidence=doc(people["client"], gh))
    assert e.value.code == "invoice-reference-used"
    with pytest.raises(RuleBlocked) as e:
        services.check_invoice(inv, people["cm"], outcome="checked")
    assert e.value.code == "contact-confirmation-missing"


def test_family_member_of_another_client_refused(seeded, api, people, gh):
    """The pupil or patient must be a registered family member of the client (FR-FEE-002)."""
    from fees.models import Institution

    hosp = Institution.objects.get(legal_name="Komfo Anokye Teaching Hospital (demo)")
    r = api(people["client2"]).post("/v1/invoices", {
        "institution_id": str(hosp.pk), "family_member_id": str(_mother(people).pk), "institution_reference": "Z",
        "amount": {"amount": "10.00", "currency": "GHS"}, "document_base64": b64doc()}, format="json")
    assert r.status_code == 404


def test_institution_contact_submits_to_tenmina_reference(seeded, api, people, gh):
    """US-FEE-002, TC-FEE-002-02: the institution sends a bill quoting Tenmina's reference; it is linked to the
    right client and family member and the client is told."""
    from fees.models import Beneficiary, Institution, Invoice

    school = Institution.objects.get(legal_name="Accra Hills School (demo)")
    b = Beneficiary.objects.filter(institution=school, client=people["client"]).first()
    r = api(people["institution"]).post("/v1/invoices", {
        "institution_id": str(school.pk), "tenmina_reference": b.tenmina_reference,
        "institution_reference": "AHS-2027-T2-0042", "amount": {"amount": "6500.00", "currency": "GHS"},
        "document_base64": b64doc()}, format="json")
    assert r.status_code == 201, r.content
    inv = Invoice.objects.get(pk=r.json()["id"])
    assert inv.client == people["client"] and inv.submitted_by == "institution_contact"
    assert inv.contact_confirmed_by is not None
    assert "full_name" not in r.json()["family_member"]


# ----------------------------------------------------------------- approval (FR-FEE-003, RUL-11)

def test_client_approval_refusals(seeded, people, gh):
    """7.9: wrong amount, wrong payee name, no step-up, another client's bill: refused."""
    from fees import services

    inst = new_institution(gh, people)
    inv = checked_invoice(gh, people, inst, _mother(people), amount="120.00")
    name = inst.payee.account_name
    with pytest.raises(Invalid) as e:
        services.client_approve(inv, people["client"], mfa_at=timezone.now(),
                                confirm_amount={"amount": "12.00", "currency": "GHS"}, confirm_payee_account_name=name)
    assert e.value.code == "amount-mismatch"
    with pytest.raises(Invalid) as e:
        services.client_approve(inv, people["client"], mfa_at=timezone.now(),
                                confirm_amount={"amount": "120.00", "currency": "GHS"},
                                confirm_payee_account_name="Someone Else")
    assert e.value.code == "payee-name-mismatch"
    with pytest.raises(MfaRequired):
        services.client_approve(inv, people["client"], mfa_at=timezone.now() - timedelta(hours=1),
                                confirm_amount={"amount": "120.00", "currency": "GHS"}, confirm_payee_account_name=name)
    with pytest.raises(NotFound):
        approve(inv, people["client2"])


def test_no_instruction_without_client_approval(seeded, people, gh):
    """TC-FEE-003-03, RUL-11: staff cannot prepare a payment the client has not approved."""
    from fees import services

    inst = new_institution(gh, people)
    inv = checked_invoice(gh, people, inst, _mother(people))
    services.set_route(inv, people["cm"], "held_funds")
    with pytest.raises(RuleBlocked) as e:
        services.prepare_instruction(inv, people["cm"])
    assert e.value.blocking_reasons[0]["rule"] == "RUL-11"


def test_client_direct_journey_api(seeded, api, mfa, people, gh):
    """J-09 verify and confirm (client_direct), TC-E2E-J09-01: approve, see the verified account only, pay it
    directly, the institution confirms, the receipt reaches the dashboard and the statement."""
    from fees.models import Payment

    ic = contact_person()
    inst = new_institution(gh, people, contact_person=ic, returns_confirmation=True)
    inv = checked_invoice(gh, people, inst, _mother(people), amount="1850.00")
    c = api(people["client"])
    pv = c.get(f"/v1/invoices/{inv.pk}/approval-preview").json()
    assert pv["institution"]["name_match"] == "matched"
    mfa(c, people["client"])
    r = c.post(f"/v1/invoices/{inv.pk}/client-approval", {
        "confirm_amount": {"amount": "1850.00", "currency": "GHS"},
        "confirm_payee_account_name": pv["institution"]["account_name"]}, format="json")
    assert r.status_code == 200, r.content
    out = r.json()
    assert out["status"] == "client_approved" and out["pay_to"]["account_name"] == inst.payee.account_name
    assert "Tenmina" not in out["pay_to"]["account_holder"]
    pay = Payment.objects.get(invoice=inv)
    assert pay.route == "client_direct" and pay.release_instruction_id is None
    r = c.post(f"/v1/fee-payments/{pay.pk}/client-payment", {"reference": "MY-BANK-123"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "client_reported"
    icc = api(ic)
    r = icc.post(f"/v1/fee-payments/{pay.pk}/institution-confirmation",
                 {"amount": {"amount": "1850.00", "currency": "GHS"}}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "paid"
    r = icc.post(f"/v1/fee-payments/{pay.pk}/receipts", {"document_base64": b64doc("receipt.pdf"),
                                                         "confirmation_document_base64": b64doc("discharge.pdf")},
                 format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "receipted" and r.json()["confirmation_evidence"]
    st = c.get(f"/v1/family-members/{_mother(people).pk}/statement").json()
    mine = [ln for ln in st["lines"] if ln["reference"] == inv.institution_reference]
    assert [ln["type"] for ln in mine] == ["invoice", "payment", "receipt"]
    home = c.get("/v1/home").json()
    assert any(i["kind"] == "fee_invoice" and i["needs_action"] for i in (home.get("items") or home))


def test_held_funds_journey(seeded, api, mfa, people, gh):
    """J-09 held funds, TC-FEE-003-01, TC-FEE-003-04: the client approves; the instruction names the
    institution's verified payee; two staff approve; the bank pays; the receipt follows."""
    from escrow.models import ReleaseInstruction
    from fees import services
    from fees.models import Payment

    client = people["client2"]
    client.id_check_status = "passed"
    client.save(update_fields=["id_check_status"])
    from accounts.models import FamilyMember

    fm = FamilyMember.objects.create(country=gh, client=client, full_name="Ama Boateng", relationship="mother")
    inst = new_institution(gh, people, client=client)
    fund_held(client, gh, "5000.00")
    inv = checked_invoice(gh, people, inst, fm, amount="1200.00", client=client)
    services.set_route(inv, people["cm"], "held_funds")
    c = api(client)
    mfa(c, client)
    r = c.post(f"/v1/invoices/{inv.pk}/client-approval", {
        "confirm_amount": {"amount": "1200.00", "currency": "GHS"},
        "confirm_payee_account_name": inst.payee.account_name}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "instructed"
    pay = Payment.objects.get(invoice=inv)
    ins = ReleaseInstruction.objects.get(pk=pay.release_instruction_id)
    assert ins.payee_id == inst.payee_id and ins.status == "pending_approval"
    assert str(ins.family_member_id) == str(fm.pk)
    staff_approve_and_confirm(ins, people)
    pay.refresh_from_db()
    assert pay.status == "paid" and pay.receipt_due_at
    services.add_receipt(pay, people["cm"], receipt_evidence=doc(people["cm"], gh, "receipt.pdf"))
    inv.refresh_from_db()
    assert inv.status == "receipted"
    st = services.statement(client, fm)
    assert st["held_at_bank"][0]["held_at_bank"]["amount"] == "3800.00"


def test_held_funds_short_then_deposit_prepares_instruction(seeded, people, gh):
    """US-FEE-003 AC2: approved but short, the client sees the bank's details; when the deposit is confirmed
    the instruction is prepared and waits for the client's approval of the payment."""
    from escrow.models import Escrow
    from escrow.seed import _deposit
    from fees import services

    client = people["client"]
    inst = new_institution(gh, people)
    inv = checked_invoice(gh, people, inst, _mother(people), amount="90000.00")
    services.set_route(inv, people["cm"], "held_funds")
    out = approve(inv, client)
    assert out["status"] == "client_approved" and out["top_up"]["payment_instructions"]["available"]
    assert "Tenmina" not in out["top_up"]["payment_instructions"]["account_name"].replace("Tenmina Partner", "")
    e = Escrow.objects.get(client=client, kind="held_funds", currency="GHS")
    _deposit(e, people["cm"], people["reviewer"], "90000.00", "DEP-T-BIG")
    inv.refresh_from_db()
    assert inv.status == "instructed"
    assert inv.payments.get().release_instruction.status == "awaiting_client"


def test_release_to_another_payee_blocked(seeded, people, gh):
    """TC-FEE-003-02, US-FEE-003 AC3: an instruction for a bill to any account but the institution's is blocked."""
    from escrow import services as esc
    from escrow.models import Payee

    client = people["client"]
    inst = new_institution(gh, people)
    inv = checked_invoice(gh, people, inst, _mother(people), amount="100.00")
    from fees import services

    services.set_route(inv, people["cm"], "held_funds")
    e = fund_held(client, gh, "0")
    other = Payee.objects.get(kind="institution", legal_name="Accra Hills School (demo)")
    with pytest.raises(RuleBlocked) as ex:
        esc.request_release(e, payee=other, amount="100.00", subject_type="fee_invoice", subject_id=inv.pk,
                            requested_by=people["cm"])
    codes = {r["code"] for r in ex.value.blocking_reasons}
    assert "payee-not-institution" in codes and "client-approval-missing" in codes


def test_runner_carries_paper_never_money(seeded, people, gh):
    """US-FEE-006 AC3, TC-RUL-22-07: a runner task has no amount; the collected bill goes through the normal
    checks; a runner can never be made a payee."""
    from escrow import services as esc
    from fees import services
    from fees.models import RunnerTask
    from mobile import inbox

    assert not any(f.name in ("amount", "release_instruction") for f in RunnerTask._meta.get_fields())
    inst = new_institution(gh, people)
    t = services.create_runner_task(inst, people["cm"], kind="collect_invoice", runner=people["runner"],
                                    family_member=_mother(people), due_at=timezone.now() + timedelta(days=1))
    assert inbox.find(people["runner"], "fee_runner_task", t.pk) is not None
    t = services.complete_runner_task(t, people["runner"], evidence=doc(people["runner"], gh, "bill.jpg",
                                                                         "image/jpeg"),
                                      invoice_data={"reference": "PAPER-1", "amount": "75.00"})
    assert t.status == "done" and t.invoice.submitted_by == "runner" and t.invoice.status == "submitted"
    with pytest.raises(RuleBlocked):
        esc.create_payee(people["cm"], country=gh, kind="institution", subject_type="person",
                         subject_id=people["runner"].pk, legal_name="Efua Runner",
                         legal_name_evidence=doc(people["cm"], gh), bank_name="B", account_number="12345678901",
                         account_name_source="bank_name_check", person=people["runner"])


def test_receipt_overdue_and_confirmation_only_when_agreed(seeded, people, gh):
    """US-FEE-004 AC2, TC-FEE-004-03: no receipt past the target is chased; a confirmation is refused when the
    institution has not agreed to share it."""
    from fees import services
    from fees.models import Payment

    inst = new_institution(gh, people)
    inv = checked_invoice(gh, people, inst, _mother(people))
    approve(inv, people["client"])
    pay = inv.payments.get()
    services.confirm_received(pay, people["cm"], method="contact_call", contact=inst.contacts.get(),
                              note="Credit seen")
    Payment.objects.filter(pk=pay.pk).update(receipt_due_at=timezone.now() - timedelta(hours=1))
    assert services.receipt_overdue() >= 1
    pay.refresh_from_db()
    assert pay.status == "receipt_overdue"
    with pytest.raises(Invalid) as e:
        services.add_receipt(pay, people["cm"], receipt_evidence=doc(people["cm"], gh),
                             confirmation_evidence=doc(people["cm"], gh))
    assert e.value.code == "confirmation-not-agreed"
    services.add_receipt(pay, people["cm"], receipt_evidence=doc(people["cm"], gh))
    pay.refresh_from_db()
    assert pay.status == "receipted"


def test_schedule_reminds_and_never_pays_without_approval(seeded, people, gh):
    """US-FEE-005, TC-FEE-005-01, -02: a draft bill and a reminder before the due date; past the date with no
    approval nothing is paid and the client is reminded again."""
    from fees import services
    from fees.models import Payment

    inst = new_institution(gh, people)
    s = services.create_schedule(people["client"], institution=inst, family_member=_mother(people), period="month",
                                 expected_amount="300.00", next_due_on=timezone.localdate() + timedelta(days=3),
                                 reminder_lead_days=7)
    services.schedule_due()
    s.refresh_from_db()
    draft = s.invoices.get()
    assert draft.status == "draft" and s.next_due_on > draft.due_on
    services.attach_document(draft, people["cm"], doc(people["cm"], gh), institution_reference="MONTH-1")
    services.check_invoice(draft, people["cm"], outcome="checked", contact=inst.contacts.get())
    later = timezone.localdate() + timedelta(days=10)
    out = services.schedule_due(on=later)
    assert out["reminders"] >= 1
    draft.refresh_from_db()
    assert draft.status == "checked" and not Payment.objects.filter(invoice=draft).exists()


def test_statement_other_client_404_and_pdf_hash(seeded, api, people):
    """TC-FEE-007-02, US-FEE-007 AC2."""
    mother = _mother(people)
    assert api(people["client2"]).get(f"/v1/family-members/{mother.pk}/statement").status_code == 404
    r = api(people["client"]).post(f"/v1/family-members/{mother.pk}/statement-pdfs")
    assert r.status_code == 201, r.content
    from evidence.models import Evidence

    assert Evidence.objects.get(pk=r.json()["evidence"]).sha256 == r.json()["sha256"]


def test_seeded_held_funds_bills_pass_the_escrow_check(seeded, people):
    """The escrow seed's fee_invoice instructions are real FEE bills: the subject check passes for them."""
    from escrow.models import ReleaseInstruction
    from fees import services

    ins = ReleaseInstruction.objects.filter(subject_type="fee_invoice", status="pending_approval").first()
    assert ins is not None and services.release_check(ins) == []
    assert Decimal(ins.amount) > 0
