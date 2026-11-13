"""EP-INS: insurer partner lines (FR-INS-001 to FR-INS-004, RUL-25)."""
import base64
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.errors import Forbidden, NotFound, RuleBlocked
from core.ids import uuid7

pytestmark = pytest.mark.django_db


def _doc(person, gh, name="doc.pdf"):
    from evidence.services import store

    return store(data=b"%PDF-1.4 " + name.encode() + uuid7().bytes, country=gh, uploaded_by=person,
                 content_type="application/pdf", original_name=name)


def _b64():
    return base64.b64encode(b"%PDF-1.4 policy " + uuid7().bytes).decode()


def _product(kind="health"):
    from insurance.models import Product

    return Product.objects.get(kind=kind, status="published")


def _mother(people):
    return people["client"].family_members.get(full_name="Akosua Mensah")


def test_products_show_insurer_and_statement(seeded, api, people):
    """US-INS-001 AC1, TC-INS-001-01, TC-RUL-25-04: each product shows the insurer's name, its terms and that
    Tenmina is not the insurer."""
    r = api(people["client"]).get("/v1/insurance/products?country=GH")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 2
    for p in items:
        assert p["insurer_name"] in p["statement"] and "Tenmina is not the insurer" in p["statement"]
        assert p["terms_evidence"]


def test_line_hidden_without_intermediary_licence(seeded, api, people, gh):
    """US-INS-001 AC2: no intermediary licence for the country: the line is not shown."""
    from insurance.models import IntermediaryLicence

    IntermediaryLicence.objects.filter(country=gh).update(status="withdrawn")
    r = api(people["client"]).get("/v1/insurance/products?country=GH")
    assert r.json()["items"] == []
    assert api(people["client"]).get("/v1/insurance/products/line-status?country=GH").json()["open"] is False


def test_publish_refused_for_unlicensed_insurer(seeded, people, gh):
    """TC-INS-001-02: a product of an insurer with no licence on record is not published."""
    from insurance import services
    from insurance.models import Insurer

    ins = Insurer.objects.get(country=gh)
    Insurer.objects.filter(pk=ins.pk).update(licence_number="")
    ins.refresh_from_db()
    p = services.create_product(people["cm"], insurer=ins, kind="funeral", name="Unlicensed cover",
                                terms_evidence=_doc(people["cm"], gh), premium_amount="10.00")
    with pytest.raises(RuleBlocked) as e:
        services.publish_product(p, people["admin"])
    assert e.value.code == "insurer-not-licensed"


def test_application_to_policy_and_direct_premium_api(seeded, api, people, gh):
    """US-INS-002 AC1, AC2, US-INS-003 AC1, TC-INS-002-01: the application goes to the insurer (Sent to insurer);
    the insurer returns the policy; the premium is paid to the insurer's verified account only."""
    from insurance.adapters import FakeInsurer
    from insurance.models import Policy, Premium

    c = api(people["client"])
    r = c.post("/v1/insurance/applications", {"product_id": str(_product().pk),
                                              "family_member_id": str(_mother(people).pk),
                                              "answers": {"date_of_birth": "1958-03-14"}, "submit": True,
                                              "consent": True}, format="json")
    assert r.status_code == 201, r.content
    app = r.json()
    assert app["status_text"] == "Sent to insurer." and app["insurer_reference"]
    assert any(s[1] == app["id"] for s in FakeInsurer.sent)
    ins_user = api(people["insurer"])
    start = timezone.localdate()
    r = ins_user.post(f"/v1/insurance/applications/{app['id']}/outcomes", {
        "outcome": "accepted", "policy_number": "FHC-T-1", "document_base64": _b64(), "starts_on": str(start),
        "renews_on": str(start + timedelta(days=365)), "claim_contact": "claims@insurer.example"}, format="json")
    assert r.status_code == 200, r.content
    pol = Policy.objects.get(policy_number="FHC-T-1")
    assert pol.insurer_payee.kind == "insurer"
    pm = Premium.objects.get(policy=pol)
    r = c.get(f"/v1/insurance/premiums/{pm.pk}")
    pay_to = r.json()["pay_to"]
    assert pay_to["account_name"] == pol.insurer_payee.account_name and "Tenmina" not in pay_to["account_holder"]
    r = c.post(f"/v1/insurance/premiums/{pm.pk}/client-payment", {"reference": "TRF-77"}, format="json")
    assert r.json()["status"] == "client_reported"
    r = ins_user.post(f"/v1/insurance/premiums/{pm.pk}/insurer-confirmation", {"received": True}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "paid"
    assert c.get(f"/v1/insurance/policies/{pol.pk}").json()["claim_contact"] == "claims@insurer.example"


def test_other_insurer_cannot_see_application(seeded, api, people, gh):
    """TC-INS-002-03: an insurer user of another insurer does not see the application."""
    from accounts.models import Person, RoleGrant
    from insurance.models import Application

    other = Person.objects.create_user("other-insurer@example.com", "tenmina-dev-123", full_name="Other Insurer")
    RoleGrant.objects.create(person=other, role="IS")
    app = Application.objects.filter(status="submitted").first()
    assert api(other).get(f"/v1/insurance/applications/{app.pk}").status_code == 404
    assert api(people["insurer"]).get(f"/v1/insurance/applications/{app.pk}").status_code == 200


def test_held_funds_premium_goes_only_to_insurer(seeded, people, gh):
    """TC-INS-002-04, TC-RUL-25-01: the held-funds route instructs the insurer's verified payee only; any other
    payee is refused; the client approves first and two staff after."""
    from escrow import services as esc
    from escrow.models import Payee
    from insurance.models import Premium

    pm = Premium.objects.filter(route="held_funds_to_insurer", status="instructed").first()
    ins = pm.release_instruction
    assert ins.payee_id == pm.policy.insurer_payee_id and ins.status == "awaiting_client"
    with pytest.raises(RuleBlocked):
        esc.staff_approve(ins, people["reviewer"], mfa_at=timezone.now())
    seller = Payee.objects.get(kind="seller")
    esc.withdraw_instruction(ins, people["cm"], reason="test")
    pm.refresh_from_db()
    assert pm.status in ("due", "overdue") and pm.release_instruction_id is None
    with pytest.raises(RuleBlocked) as e:
        esc.request_release(ins.escrow, payee=seller, amount=pm.amount, subject_type="premium", subject_id=pm.pk,
                            requested_by=people["cm"])
    assert any(r.get("code") == "premium-not-to-insurer" for r in e.value.blocking_reasons)


def test_held_funds_premium_paid_on_bank_confirmation(seeded, people, gh):
    """FR-INS-002: the bank pays the insurer; the premium is paid when the bank confirms."""
    from escrow import services as esc
    from escrow.seed import _confirm
    from insurance.models import Premium

    pm = Premium.objects.filter(route="held_funds_to_insurer", status="instructed").first()
    ins = pm.release_instruction
    esc.client_approve(ins, people["client"], timezone.now())
    esc.staff_approve(ins, people["reviewer"], mfa_at=timezone.now())
    esc.staff_approve(ins, people["reviewer2"], mfa_at=timezone.now())
    ins.refresh_from_db()
    assert ins.status == "sent"
    _confirm(ins, people["cm"], people["reviewer"], "PAY-PREM-1")
    pm.refresh_from_db()
    assert pm.status == "paid"


def test_premium_never_to_a_tenmina_or_other_account(seeded, people, gh):
    """TC-INS-002-02, TC-RUL-25-02: the premium account cannot be set to anything but the insurer's payee; there is
    no Tenmina order kind for a premium; the database refuses a policy paying a non-insurer payee."""
    from escrow.models import Payee
    from insurance import services
    from insurance.models import Insurer, Policy
    from orders import catalogue

    ins = Insurer.objects.get(country=gh)
    seller = Payee.objects.get(kind="seller")
    with pytest.raises(RuleBlocked):
        services.set_insurer_payee(ins, people["admin"], seller)
    assert not any("premium" in k for k in catalogue.PRODUCTS)
    pol = Policy.objects.first()
    with pytest.raises(IntegrityError), transaction.atomic():
        Policy.objects.filter(pk=pol.pk).update(insurer_payee=seller)


def test_claim_tracked_never_decided_by_tenmina(seeded, api, people, gh):
    """US-INS-004, TC-RUL-25-03, TC-INS-004-02: the client starts a claim (Sent); staff cannot record a decision;
    the insurer's response is shown; responses are append-only."""
    from insurance import services
    from insurance.models import ClaimUpdate, Policy

    pol = Policy.objects.get(policy_number="FHC-DEMO-000101")
    r = api(people["client"]).post(f"/v1/insurance/policies/{pol.pk}/claims",
                                   {"description": "Clinic visit and medicines"}, format="json")
    assert r.status_code == 201 and r.json()["status_text"] == "Sent to the insurer."
    from insurance.models import Claim

    claim = Claim.objects.get(pk=r.json()["id"])
    for staff in ("cm", "reviewer", "admin"):
        with pytest.raises(Forbidden):
            services.record_claim_update(claim, people[staff], insurer_status="paid")
    assert api(people["cm"]).post(f"/v1/insurance/claims/{claim.pk}/updates", {"insurer_status": "paid"},
                                  format="json").status_code == 403
    r = api(people["insurer"]).post(f"/v1/insurance/claims/{claim.pk}/updates",
                                    {"insurer_status": "paid", "note": "Paid to the hospital"}, format="json")
    assert r.status_code == 200 and r.json()["insurer_status"] == "paid"
    assert not any(f.name in ("decision", "decided_by", "tenmina_decision") for f in Claim._meta.get_fields())
    u = ClaimUpdate.objects.filter(claim=claim).first()
    with pytest.raises(Exception), transaction.atomic():
        ClaimUpdate.objects.filter(pk=u.pk).update(note="changed")


def test_renewal_reminder_and_lapse(seeded, people):
    """US-INS-003 AC2, TC-INS-003-02: a reminder before renewal; past the date with no renewal the policy shows
    lapsed and Tenmina implies no cover; the insurer can renew it."""
    from insurance import services
    from insurance.models import Policy

    pol = Policy.objects.get(policy_number="FHC-DEMO-000101")
    out = services.renewal_reminders()
    pol.refresh_from_db()
    assert out["reminded"] >= 1 and pol.renewal_reminded_for == pol.renews_on
    out = services.renewal_reminders(on=pol.renews_on + timedelta(days=1))
    pol.refresh_from_db()
    assert pol.status == "lapsed" and "cannot say whether you are covered" in pol.status_note
    with pytest.raises(NotFound):
        services.record_renewal(pol, people["cm"], renews_on=pol.renews_on + timedelta(days=365))
    services.record_renewal(pol, people["insurer"], renews_on=pol.renews_on + timedelta(days=365))
    pol.refresh_from_db()
    assert pol.status == "active"


def test_premium_due_job(seeded, people):
    """FR-INS-002 insurance.premium_due: the next premium falls due before its date; overdue ones are marked."""
    from insurance import services
    from insurance.models import Policy

    pol = Policy.objects.get(policy_number="FHC-DEMO-000101")
    first = pol.premiums.order_by("due_on").first()
    out = services.premium_due(on=first.due_on + timedelta(days=40))
    assert out["created"] >= 1 and out["overdue"] >= 1
    assert pol.premiums.count() >= 2


def test_flag_off_closes_insurance(seeded, people, settings):
    """06 2.6: lines.ins off: nothing is offered."""
    from core.errors import FeatureOff
    from insurance import services

    settings.TENMINA_FLAG_OVERRIDES = {"lines.ins": False}
    with pytest.raises(FeatureOff):
        services.apply(people["client"], product=_product(), family_member=_mother(people))
