"""EP-FEE institutions: verification, contacts, eligibility (FR-FEE-001, FR-FEE-006, RUL-22)."""
import pytest
from django.db import IntegrityError, transaction

from core.errors import FeatureOff, NotFound, PayeeNotVerified, RuleBlocked, SameApprover

from .helpers import contact_person, doc, new_institution

pytestmark = pytest.mark.django_db


def test_register_verify_journey_api(seeded, api, people, gh):
    """US-FEE-001 AC1, AC2, TC-FEE-001-01: a client registers an institution; it is Unverified until the case,
    the account in its own name (two staff) and a named contact are all done; then Verified."""
    from fees import services
    from fees.models import Institution
    from fees.seed import complete_case, verify_payee

    c = api(people["client"])
    r = c.post("/v1/institutions", {"country": "GH", "type": "clinic", "legal_name": "Labone Family Clinic",
                                    "registration_number": "HEFRA/T/1001", "proposed_account_number": "1234567"},
               format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "pending" and body["eligible_for_direct_payment"] is False
    assert {i["key"]: i["done"] for i in body["checklist"]} == {"registration": False, "bank_account": False,
                                                                 "named_contact": False, "look_alike": True}
    inst = Institution.objects.get(pk=body["id"])
    assert inst.verification_case.product_line == "institution_verification"
    cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
    complete_case(inst.verification_case, cm, rv)
    s = api(cm)
    r = s.post(f"/v1/institutions/{inst.pk}/payee", {"bank_name": "Demo Bank", "account_number": "1288776655441",
                                                    "account_name_source": "bank_name_check",
                                                    "legal_name_evidence_id": str(doc(cm, gh).pk),
                                                    "signatory_name": "Clinic Director",
                                                    "signatory_id_number": "GHA-712345678-3"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["name_match"] == "matched"
    inst.refresh_from_db()
    verify_payee(inst.payee, cm, rv, rv2)
    inst.refresh_from_db()
    assert inst.status == "pending"  # no named contact yet
    r = s.post(f"/v1/institutions/{inst.pk}/contacts", {"full_name": "Kwame Accounts", "phone": "+233302111222"},
               format="json")
    assert r.status_code == 201, r.content
    inst.refresh_from_db()
    assert inst.status == "verified" and inst.eligible_for_direct_payment
    assert services.verification_checklist(inst) and all(i["done"] for i in services.verification_checklist(inst))
    r = c.get(f"/v1/institutions/{inst.pk}")
    assert r.json()["status"] == "verified" and r.json()["contacts"] == []  # contacts are staff-only
    assert c.get(f"/v1/institutions/{inst.pk}").json()["payee"]["account_last4"] == "5441"


def test_duplicate_links_and_look_alike_flagged(seeded, api, people, gh):
    """TC-FEE-001-04, TC-SEC-33: a duplicate registration number links to the existing record; a name one
    letter different is flagged for a reviewer and cannot be verified while open."""
    from fees.models import ClientInstitution, Institution

    school = Institution.objects.get(legal_name="Accra Hills School (demo)")
    c2 = api(people["client2"])
    r = c2.post("/v1/institutions", {"country": "GH", "type": "school", "legal_name": "Some Other Name",
                                     "registration_number": "GES/DEMO/0042"}, format="json")
    assert r.status_code == 200 and r.json()["id"] == str(school.pk)
    assert ClientInstitution.objects.filter(client=people["client2"], institution=school).exists()
    look = Institution.objects.get(legal_name="Accra Hilis School (demo)")
    assert look.look_alike_of_id == school.pk and look.look_alike_status == "open"
    from fees import services

    assert any(i["key"] == "look_alike" and not i["done"] for i in services.verification_checklist(look))
    with pytest.raises(Exception):
        services.review_look_alike(look, people["cm"], decision="confirmed", note="x")
    services.review_look_alike(look, people["reviewer"], decision="confirmed", note="Copied name, other account")
    look.refresh_from_db()
    assert look.status == "not_verified"


def test_account_in_another_name_cannot_be_verified(seeded, people, gh):
    """TC-RUL-22-02, TC-E2E-J09-03: a bank letter in a person's name never matches; nobody can verify it."""
    from fees import services

    cm = people["cm"]
    inst, _ = services.register_institution(cm, country=gh, type="pharmacy", legal_name="Osu Pharmacy Ltd",
                                            registration_evidence=doc(cm, gh), client=people["client"])
    p = services.create_payee(inst, cm, bank_name="Demo Bank", account_number="1299887766551",
                              account_name="KOFI ASARE", account_name_source="bank_letter",
                              account_name_evidence=doc(cm, gh, "letter.pdf"), signatory_name="Kofi Asare",
                              signatory_id_number="GHA-712345679-4")
    assert p.name_match == "mismatch"
    with pytest.raises(PayeeNotVerified):
        services.prepare_payee_verification(inst, cm)
    inst.refresh_from_db()
    assert inst.status == "pending" and not inst.eligible_for_direct_payment


def test_contact_who_is_a_relative_is_refused(seeded, people, gh):
    """TC-RUL-22-03: a named contact whose phone matches a family member of a paying client is refused."""
    from fees import services

    inst = new_institution(gh, people, contact=False)
    mother = people["client"].family_members.get(full_name="Akosua Mensah")
    with pytest.raises(RuleBlocked) as e:
        services.add_contact(inst, people["cm"], full_name="Front desk", phone=mother.phone)
    assert e.value.code == "contact-refused"
    with pytest.raises(RuleBlocked):
        services.add_contact(inst, people["cm"], full_name="Runner", person=people["runner"])
    inst.refresh_from_db()
    assert inst.status == "pending"


def test_case_not_verified_marks_institution(seeded, people, gh):
    """TC-FEE-001-03: a failed registration check leaves the institution not verified, with the reason."""
    from fees import services
    from fees.seed import complete_case

    inst, _ = services.register_institution(people["client"], country=gh, type="school",
                                            legal_name="Phantom Academy")
    complete_case(inst.verification_case, people["cm"], people["reviewer"], outcome="not_verified",
                  note="The registration number belongs to another body.")
    inst.refresh_from_db()
    assert inst.status == "not_verified" and "another body" in inst.status_reason


def test_payee_suspended_and_account_changed(seeded, people, gh):
    """US-FEE-001 AC3, TC-RUL-22-04: a suspended account suspends the institution; a changed account sends it
    back to Unverified with a new verification case."""
    from escrow import services as esc
    from fees import services

    inst = new_institution(gh, people)
    esc.suspend_payee(inst.payee, people["reviewer"], "Bank reported fraud [test]")
    inst.refresh_from_db()
    assert inst.status == "suspended"
    inst2 = new_institution(gh, people)
    old_case = inst2.verification_case_id
    services.on_payee_account_changed(inst2.payee_id)
    inst2.refresh_from_db()
    assert inst2.status == "pending" and inst2.verification_case_id != old_case


def test_not_eligible_two_people_and_no_cash_route(seeded, api, people, gh):
    """US-FEE-006 AC1, AC2, TC-FEE-006-01: a case manager proposes, a different reviewer confirms; the client is
    told plainly; no invoice for it can be submitted, checked, approved or instructed."""
    from fees import services

    inst, _ = services.register_institution(people["client"], country=gh, type="pharmacy",
                                            legal_name="Cash Only Chemist")
    services.propose_not_eligible(inst, people["cm"], "Cash only")
    with pytest.raises(Exception):
        services.decide_not_eligible(inst, people["cm"], confirm=True)
    services.decide_not_eligible(inst, people["reviewer"], confirm=True)
    inst.refresh_from_db()
    assert inst.status == "not_eligible" and inst.not_eligible_reason == "Cash only"
    r = api(people["client"]).get(f"/v1/institutions/{inst.pk}")
    assert r.json()["status_text"] == ("This institution cannot receive a bank transfer, so Tenmina cannot pay it. "
                                       "We never pay in cash.")
    fm = people["client"].family_members.filter(status="active").first()
    with pytest.raises(RuleBlocked) as e:
        services.submit_invoice(people["client"], institution=inst, family_member=fm, institution_reference="X1",
                                amount="10.00", evidence=doc(people["client"], gh))
    assert e.value.code == "institution-not-eligible"
    import fees.views as v

    assert not [n for n in dir(v) if "cash" in n.lower() or "voucher" in n.lower()]


def test_same_reviewer_cannot_propose_and_confirm(seeded, people, gh):
    """FR-FEE-006: the checker is not the proposer."""
    from core.permissions import has_role
    from fees import services

    assert has_role(people["cm"], "CM")
    inst, _ = services.register_institution(people["client"], country=gh, type="clinic", legal_name="Slow Clinic")
    services.propose_not_eligible(inst, people["cm"], "No account")
    inst.eligibility_proposed_by = people["reviewer"]
    inst.save(update_fields=["eligibility_proposed_by"])
    with pytest.raises(SameApprover):
        services.decide_not_eligible(inst, people["reviewer"], confirm=True)


def test_database_refuses_verified_without_verified_payee(seeded, people, gh):
    """RUL-22, 02 6.12 trigger: the database refuses 'verified' without a verified institution payee."""
    from fees.models import Institution

    inst = Institution.objects.get(legal_name="Tema Community Clinic (demo)")
    from escrow.models import Payee

    payee = Payee.objects.filter(kind="institution", verification_status="verified").exclude(
        pk__in=Institution.objects.filter(payee__isnull=False).values("payee")).first() or \
        Payee.objects.filter(kind="seller").first()
    with pytest.raises(IntegrityError), transaction.atomic():
        Institution.objects.filter(pk=inst.pk).update(payee=payee, status="verified")


def test_flag_off_closes_the_line(seeded, people, gh, settings):
    """06 2.6: everything is behind lines.fee."""
    from fees import services

    settings.TENMINA_FLAG_OVERRIDES = {"lines.fee": False}
    with pytest.raises(FeatureOff):
        services.register_institution(people["client"], country=gh, type="school", legal_name="Closed School")


def test_contact_sees_only_own_institution(seeded, api, people, gh):
    """TC-FEE-002-02: an institution contact sees only its own institution's bills."""
    from fees.models import Institution, Invoice

    hosp = Institution.objects.get(legal_name="Komfo Anokye Teaching Hospital (demo)")
    inv = Invoice.objects.filter(institution=hosp).first()
    bursar = api(people["institution"])
    assert bursar.get(f"/v1/invoices/{inv.pk}").status_code == 404
    ids = {i["id"] for i in bursar.get("/v1/invoices").json()["items"]}
    assert ids and all(Invoice.objects.get(pk=i).institution.legal_name == "Accra Hills School (demo)" for i in ids)
    with pytest.raises(NotFound):
        from fees import services

        services.contact_confirm(inv, people["institution"])
    assert contact_person  # helper import used elsewhere
