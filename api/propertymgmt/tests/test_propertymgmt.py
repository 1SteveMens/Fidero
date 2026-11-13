from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from core.errors import DomainError, RuleBlocked, SameApprover
from core.models import OutboxEvent
from propertymgmt import services
from propertymgmt.models import Inspection, ManagedProperty, RentPeriod, Repair

from .conftest import statement

GHS = {"amount": "6400.00", "currency": "GHS"}


def topics(*names):
    return list(OutboxEvent.objects.filter(topic__in=names).values_list("topic", flat=True))


# --------------------------------------------------------------------------- FR-PMG-001 onboarding

def test_register_opens_case_and_condition_inspection(api, gh, people, doc):
    """FR-PMG-001, US-PMG-001 AC1, TC-PMG-001-01: registering a house with ownership documents opens the
    onboarding case and an inspection task for a field inspector."""
    c = api(people["client"])
    r = c.post("/v1/managed-properties", {"country": "GH", "title": "House at Sakumono", "locality": "Sakumono",
                                          "ownership_evidence_ids": [str(doc(people["client"], "indenture").pk)]},
               format="json")
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "onboarding" and body["onboarding_case"] and body["onboarding_inspection"]
    assert {b["code"] for b in body["blockers"]} == {"inspection-required", "ownership-not-checked",
                                                     "rent-account-missing"}
    prop = ManagedProperty.objects.get(pk=body["id"])
    assert prop.onboarding_case.product_line == "property_onboarding"
    assert prop.asset.type == "building" and prop.asset.owner_id == people["client"].pk
    assert "managed_property.registered" in topics("managed_property.registered")


def test_register_needs_ownership_documents_and_flag(api, gh, people, settings):
    """FR-PMG-001: no ownership document, no registration; the line is behind lines.pmg."""
    c = api(people["client"])
    r = c.post("/v1/managed-properties", {"country": "GH", "title": "X", "locality": "Y",
                                          "ownership_evidence_ids": []}, format="json")
    assert r.status_code == 400
    settings.TENMINA_FLAG_OVERRIDES = {"lines.pmg": False}
    r = c.post("/v1/managed-properties", {"country": "GH", "title": "X", "locality": "Y",
                                          "ownership_evidence_ids": [str(people["client"].pk)]}, format="json")
    assert r.status_code == 404 and r.json()["code"] == "feature-off"


def test_tenancy_blocked_until_condition_inspection(people, new_property, seeded, doc):
    """TC-PMG-001-02: management cannot start without the condition inspection."""
    prop = new_property()
    services.set_rent_account(prop, prop.owner, seeded["bank_accounts"]["rent"].pk)
    with pytest.raises(RuleBlocked) as e:
        services.record_tenancy(prop, people["cm"], tenant_email="t1@example.com", tenant_name="T One",
                                agreement_evidence_id=doc(people["cm"]).pk, rent={"amount": "100", "currency": "GHS"},
                                period="monthly", due_day=1, starts_on=timezone.localdate())
    assert e.value.code == "inspection-required"


def test_inspection_needs_licensed_inspector_and_app_photos(people, new_property, pmg, doc):
    """RUL-20, RUL-08, US-PMG-001 AC2: only a licensed inspector; photos per room taken in the app."""
    prop = new_property()
    insp = services.onboarding_inspection(prop)
    with pytest.raises(DomainError) as e:
        services.assign_inspector(insp, people["cm"], people["inspector"])  # licence not verified
    assert e.value.code == "licence-invalid"
    services.assign_inspector(insp, people["cm"], pmg["inspector"])
    uploaded = doc(pmg["inspector"], "phone-gallery", image=True)
    with pytest.raises(DomainError) as e:
        services.record_inspection(insp, pmg["inspector"], outcome="pass", condition_rating="good",
                                   rooms=[{"room": "Front", "evidence_ids": [str(uploaded.pk)]}])
    assert e.value.code == "evidence-rejected"
    with pytest.raises(DomainError):
        services.record_inspection(insp, pmg["inspector"], outcome="pass", condition_rating="", rooms=[])


def test_property_managed_after_inspection_case_and_account(people, new_property, onboard):
    """US-PMG-001 AC2: with the inspection, the ownership check and the rent account, the property is Managed;
    the inspector's work goes to PRO with no outcome field (RUL-26)."""
    prop = onboard(new_property())
    assert prop.status == "managed" and prop.next_inspection_due_on
    ev = OutboxEvent.objects.filter(topic="work.accepted", payload__work_kind="property_inspection").last()
    assert ev and "outcome" not in ev.payload and ev.payload["person_id"]
    assert "property.onboarded" in topics("property.onboarded")
    case = prop.onboarding_case
    case.refresh_from_db()
    assert case.status == "completed" and case.tasks.get(step_key="site_visit").status == "done"


def test_field_app_inspection_records_the_condition(people, new_property, pmg, phone, seeded):
    """FR-PMG-001, FR-MOB-006/007: the inspector's photos and inspection from Tenmina Field record the visit."""
    from mobile import inbox
    from mobile import services as mob
    from propertymgmt.seed import capture

    prop = new_property()
    services.set_rent_account(prop, prop.owner, seeded["bank_accounts"]["rent"].pk)
    insp = services.onboarding_inspection(prop)
    services.assign_inspector(insp, people["cm"], pmg["inspector"])
    item = inbox.find(pmg["inspector"], "property_inspection", insp.pk)
    assert item is not None and {e["key"] for e in item.required_evidence} >= {"room_front", "room_living"}
    front, living = capture(phone, insp, "room_front", "fa-front"), capture(phone, insp, "room_living", "fa-living")
    mob.submit(pmg["inspector"], client_submission_id="pmg-fa-1", subject_type="property_inspection",
               subject_id=insp.pk, items=[{"requirement_key": "room_front", "evidence_id": str(front.pk)},
                                          {"requirement_key": "room_living", "evidence_id": str(living.pk)},
                                          {"requirement_key": "condition_rating", "value": "fair"}])
    mob.submit_inspection(pmg["inspector"], client_submission_id="pmg-fa-2", subject_type="property_inspection",
                          subject_id=insp.pk, outcome="pass", checklist=[{"key": c["key"], "result": "ok"}
                                                                         for c in item.checklist])
    insp.refresh_from_db()
    assert insp.status == "submitted" and insp.condition_rating == "fair" and len(insp.photo_ids) == 2
    assert {r["room"] for r in insp.rooms} == {"front", "living"}


# --------------------------------------------------------------------------- FR-PMG-002 tenancy and RUL-24

def test_rent_account_must_be_owners_own_verified_account(api, people, seeded, new_property):
    """RUL-24, TC-PMG-002-02, TC-RUL-24-02: an unverified account, someone else's account, or nothing at all is
    refused with rent-destination-invalid."""
    prop = new_property()
    c = api(people["client"])
    url = f"/v1/managed-properties/{prop.pk}/rent-account"
    for acct in (seeded["bank_accounts"]["wrong"], seeded["bank_accounts"]["second"]):
        r = c.put(url, {"bank_account_id": str(acct.pk)}, format="json")
        assert r.status_code == 422 and r.json()["code"] == "rent-destination-invalid", r.content
    other = new_property(owner=people["client2"], title="Kofi house")
    r = api(people["client2"]).put(f"/v1/managed-properties/{other.pk}/rent-account",
                                   {"bank_account_id": str(seeded["bank_accounts"]["rent"].pk)}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "rent-destination-invalid"
    r = c.put(url, {"bank_account_id": str(seeded["bank_accounts"]["rent"].pk)}, format="json")
    assert r.status_code == 200 and r.json()["rent_account"]["last4"] == "8901"


def test_tenmina_or_payee_account_never_a_rent_destination(people, seeded, new_property):
    """RUL-24, TC-SEC-39: an owner's 'verified' account carrying a Tenmina escrow programme or payee number is
    refused by the deny list."""
    from accounts.models import BankAccount
    from escrow.models import ProgrammeAccount

    prop = new_property()
    pa = ProgrammeAccount.objects.filter(country=prop.country).first()
    real = seeded["bank_accounts"]["rent"]
    fake = BankAccount.objects.create(country=prop.country, holder=prop.owner, bank_name="Partner Bank",
                                      account_number=pa.account_number, account_name=real.account_name,
                                      account_name_norm=real.account_name_norm, name_match="matched",
                                      verification_status="verified", approval_request=real.approval_request)
    with pytest.raises(DomainError) as e:
        services.set_rent_account(prop, prop.owner, fake.pk)
    assert e.value.code == "rent-destination-invalid"


def test_database_refuses_a_rent_account_not_the_owners(people, seeded, new_property):
    """RUL-24 enforced twice: the trigger refuses another holder's account."""
    prop = new_property(owner=people["client2"], title="Kofi house 2")
    with pytest.raises(DatabaseError), transaction.atomic():
        ManagedProperty.objects.filter(pk=prop.pk).update(rent_account=seeded["bank_accounts"]["rent"])


def test_tenancy_needs_agreement_and_shows_only_the_owners_account(api, people, new_property, onboard, doc):
    """FR-PMG-002, TC-PMG-002-01, TC-PMG-002-03, TC-RUL-24-04: the agreement is required; the tenant sees the
    owner's own account and the reference, never Tenmina's."""
    prop = onboard(new_property())
    c = api(people["cm"])
    body = {"tenant_email": "new.tenant@example.com", "tenant_name": "Abena Tenant", "rent": {"amount": "2500.00",
                                                                                              "currency": "GHS"},
            "period": "monthly", "due_day": 5, "starts_on": timezone.localdate().isoformat()}
    r = c.post(f"/v1/managed-properties/{prop.pk}/tenancies", body, format="json")
    assert r.status_code == 422, r.content
    body["agreement_evidence_id"] = str(doc(people["cm"], "agreement.txt").pk)
    r = c.post(f"/v1/managed-properties/{prop.pk}/tenancies", body, format="json")
    assert r.status_code == 201, r.content
    from accounts.models import Person

    tenant = Person.objects.get(email="new.tenant@example.com")
    assert tenant.has_tenmina_role("TN")
    r = api(tenant).get(f"/v1/tenancies/{r.json()['id']}")
    assert r.status_code == 200
    pay = r.json()["payment_details"]
    assert pay["pay_to"] == "owner" and pay["account_number"] == "0012345678901"
    assert pay["account_holder"] == people["client"].full_name and "Tenmina never receives rent" in pay["note"]
    assert api(people["client"]).post(f"/v1/managed-properties/{prop.pk}/tenancies", body,
                                      format="json").status_code == 403


def test_tenant_sees_only_own_tenancy(api, people, seeded):
    """TC-PMG-006-02: the tenant sees the agreement, the rent record and their repair reports; not the owner's
    property, timeline or other tenancies."""
    house = seeded["pmg"]["properties"]["House at Tema Community 25"]
    t = api(people["tenant"])
    assert t.get(f"/v1/managed-properties/{house.pk}").status_code == 404
    assert t.get(f"/v1/managed-properties/{house.pk}/timeline").status_code == 404
    rows = t.get("/v1/tenancies").json()["items"]
    assert rows and all(r["tenant"]["id"] == str(people["tenant"].pk) for r in rows)
    repairs = t.get("/v1/repairs").json()["items"]
    assert repairs and all(r["reported_by"]["id"] == str(people["tenant"].pk) for r in repairs)
    assert all(r["quotes"] == [] for r in repairs)
    assert api(people["client2"]).get(f"/v1/tenancies/{rows[0]['id']}").status_code == 404


# --------------------------------------------------------------------------- FR-PMG-003 rent

def test_rent_received_from_the_owners_statement_only(api, people, new_property, onboard, mandate, tenancy):
    """FR-PMG-003, TC-PMG-003-01, TC-PMG-003-03, TC-RUL-24-01: matching credits mark rent received; lines for any
    other account are refused at import and never stored."""
    from escrow.models import StatementLine

    prop = onboard(new_property())
    mandate(prop)
    t = tenancy(prop)
    first = t.periods.order_by("period_start").first()
    data = statement("0012345678901", [
        {"on": first.due_on - timedelta(days=1), "amount": "2000.00", "ref": "B-1", "text": "RENT TEST-REF-1"},
        {"on": first.due_on, "amount": "777.00", "ref": "B-2", "account": "0099999999999", "text": "OTHER"}])
    r = api(people["cm"]).post(f"/v1/managed-properties/{prop.pk}/rent-statements",
                               {"content": data, "source": "file"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["accepted_count"] == 1 and r.json()["refused_count"] == 1 and r.json()["matched_count"] == 1
    first.refresh_from_db()
    assert first.status == "received" and first.match_method == "reference" and first.statement_line_id
    assert not StatementLine.objects.filter(bank_reference="B-2").exists()
    periods = api(people["client"]).get(f"/v1/managed-properties/{prop.pk}/rent-periods").json()
    assert periods[0]["status"] == "received" and "bank's statement" in periods[0]["status_text"]
    assert "rent.received" in topics("rent.received")


def test_no_mandate_no_matching(api, people, new_property, onboard, tenancy):
    """FR-PMG-003, TC-PMG-003-04: without the written mandate nothing is read or matched; rent shows 'Not yet
    confirmed by the bank' and no late alert is raised."""
    prop = onboard(new_property())
    t = tenancy(prop)
    data = statement("0012345678901", [{"on": timezone.localdate(), "amount": "2000.00", "ref": "N-1"}])
    r = api(people["client"]).post(f"/v1/managed-properties/{prop.pk}/rent-statements", {"content": data},
                                   format="json")
    assert r.status_code == 409 and r.json()["code"] == "mandate-missing"
    services.rent_watch(timezone.localdate())
    assert not t.periods.filter(status="late").exists()
    p = t.periods.order_by("period_start").first()
    assert "Not yet confirmed by the bank" in services.rent_status_text(p, False)


def test_late_rent_alert_boundary(people, new_property, onboard, mandate, tenancy):
    """FR-PMG-003, US-PMG-003 AC2, TC-PMG-003-02: late only after the grace period; the owner, the tenant and the
    case manager are alerted once."""
    from notifications.models import Message

    prop = onboard(new_property())
    mandate(prop)
    t = tenancy(prop)
    p = t.periods.order_by("period_start").first()
    grace = 5
    services.rent_watch(p.due_on + timedelta(days=grace))
    p.refresh_from_db()
    assert p.status == "due"
    services.rent_watch(p.due_on + timedelta(days=grace + 1))
    p.refresh_from_db()
    assert p.status == "late" and p.late_alert_sent_at
    for who in (people["client"], people["tenant"]):
        assert Message.objects.filter(person=who, template__startswith="pmg_rent_late").exists()
    assert Message.objects.filter(template="pmg_rent_late", person__role_grants__role="CM").exists()
    n = OutboxEvent.objects.filter(topic="rent.late").count()
    services.rent_watch(p.due_on + timedelta(days=grace + 2))
    assert OutboxEvent.objects.filter(topic="rent.late").count() == n


def test_manual_match_needs_a_second_staff_member(api, people, new_property, onboard, mandate, tenancy):
    """US-PMG-003 AC3: an unmatched line matched by hand counts only after a different staff member checks it."""
    prop = onboard(new_property())
    mandate(prop)
    t = tenancy(prop)
    p = t.periods.order_by("period_start").first()
    data = statement("0012345678901", [{"on": p.due_on + timedelta(days=20), "amount": "1999.00", "ref": "M-1",
                                        "text": "CASH DEPOSIT"}])
    services.import_rent_statement(prop, people["cm"], data=data.encode(), source="file")
    lines = services.unmatched_lines(prop)
    assert len(lines) == 1
    cm, rv = api(people["cm"]), api(people["reviewer"])
    r = cm.post(f"/v1/rent-periods/{p.pk}/manual-matches", {"statement_line_id": str(lines[0].pk)}, format="json")
    assert r.status_code == 200 and r.json()["manual_match_pending"]
    r = cm.post(f"/v1/rent-periods/{p.pk}/manual-match-checks", {"agree": True}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    r = rv.post(f"/v1/rent-periods/{p.pk}/manual-match-checks", {"agree": True}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "partial" and r.json()["match_method"] == "manual"


# --------------------------------------------------------------------------- FR-PMG-004 repairs and quotes

@pytest.fixture
def repair(people, seeded, doc):
    house = seeded["pmg"]["properties"]["House at Tema Community 25"]

    def make():
        return services.report_repair(people["tenant"], house, title="Cracked window",
                                      description="The bedroom window is cracked.",
                                      photo_ids=[doc(people["tenant"], "window", image=True).pk])

    return make


def test_tenant_reports_repair_owner_and_cm_notified(api, people, seeded, doc):
    """FR-PMG-004, US-PMG-004 AC1: a tenant reports a repair with photos; the owner and the case manager hear."""
    from notifications.models import Message

    house = seeded["pmg"]["properties"]["House at Tema Community 25"]
    t = api(people["tenant"])
    r = t.post("/v1/repairs", {"property_id": str(house.pk), "title": "Blocked drain", "description": "Kitchen sink",
                               "photo_ids": []}, format="json")
    assert r.status_code == 400
    r = t.post("/v1/repairs", {"property_id": str(house.pk), "title": "Blocked drain", "description": "Kitchen sink",
                               "photo_ids": [str(doc(people["tenant"], "drain", image=True).pk)]}, format="json")
    assert r.status_code == 201 and r.json()["reporter_role"] == "tenant", r.content
    assert Message.objects.filter(person=people["client"], template="pmg_repair_reported").exists()
    assert Message.objects.filter(template="pmg_repair_reported", person__role_grants__role="CM").exists()
    assert api(people["client2"]).post("/v1/repairs", {"property_id": str(house.pk), "title": "x",
                                                       "description": "y", "photo_ids": [
                                                           str(doc(people["client2"], "x", image=True).pk)]},
                                       format="json").status_code == 404


def test_quotes_only_from_vetted_contractors_with_verified_payees(people, pmg, repair, doc, seeded):
    """FR-PMG-004, TC-PMG-004-02, RUL-22: an unvetted contractor, a payee that is not the contractor's, or an
    unverified payee is refused."""
    r = repair()
    roofer, roof_payee = pmg["panel"]["roof"]
    plumber, plumb_payee = pmg["panel"]["plumb"]
    kw = dict(amount={"amount": "300.00", "currency": "GHS"}, evidence_id=doc(people["cm"], "q.txt").pk)
    with pytest.raises(RuleBlocked) as e:
        services.add_quote(r, people["cm"], contractor=people["runner"], payee=roof_payee, **kw)
    assert e.value.code == "contractor-not-vetted"
    with pytest.raises(DomainError) as e:
        services.add_quote(r, people["cm"], contractor=roofer, payee=plumb_payee, **kw)
    assert e.value.code == "payee-not-verified"
    mismatch = seeded["escrow"]["payees"]["mismatch"]
    with pytest.raises(DomainError) as e:
        services.add_quote(r, people["cm"], contractor=roofer, payee=mismatch, **kw)
    assert e.value.code == "payee-not-verified"
    with pytest.raises(DomainError):
        services.add_quote(r, people["client"], contractor=roofer, payee=roof_payee, **kw)


def test_owner_needs_two_quotes_unless_reviewer_exception(api, mfa, people, pmg, repair, doc):
    """FR-PMG-004, US-PMG-004 AC2, TC-PMG-004-02: one quote blocks approval; a reviewer's exception with a reason
    allows it; a case manager cannot record the exception."""
    r = repair()
    roofer, roof_payee = pmg["panel"]["roof"]
    q1 = services.add_quote(r, people["cm"], contractor=roofer, payee=roof_payee,
                            amount={"amount": "300.00", "currency": "GHS"}, evidence_id=doc(people["cm"], "q").pk)
    owner = api(people["client"])
    mfa(owner, people["client"])
    body = {"quote_id": str(q1.pk), "confirm_amount": {"amount": "300.00", "currency": "GHS"}}
    resp = owner.post(f"/v1/repairs/{r.pk}/quote-approvals", body, format="json")
    assert resp.status_code == 409 and resp.json()["blocking_reasons"][0]["code"] == "quotes-missing"
    assert api(people["cm"]).post(f"/v1/repairs/{r.pk}/single-quote-exceptions", {"reason": "Urgent"},
                                  format="json").status_code == 403
    resp = api(people["reviewer"]).post(f"/v1/repairs/{r.pk}/single-quote-exceptions",
                                        {"reason": "Only roofer free before the rains"}, format="json")
    assert resp.status_code == 200 and resp.json()["status"] == "quotes_ready"
    resp = owner.post(f"/v1/repairs/{r.pk}/quote-approvals", body, format="json")
    assert resp.status_code == 201, resp.content


def test_database_refuses_quotes_ready_with_one_quote(people, pmg, repair, doc):
    """FR-PMG-004 enforced twice: pmg_two_quotes_before_approval()."""
    r = repair()
    roofer, roof_payee = pmg["panel"]["roof"]
    services.add_quote(r, people["cm"], contractor=roofer, payee=roof_payee,
                       amount={"amount": "300.00", "currency": "GHS"}, evidence_id=doc(people["cm"], "q").pk)
    with pytest.raises(DatabaseError), transaction.atomic():
        Repair.objects.filter(pk=r.pk).update(status="quotes_ready")


def test_quote_approval_needs_mfa_and_matching_amount(api, mfa, people, pmg, repair, doc):
    """7.11, RUL-11: MFA step-up required; confirm_amount must equal the quote (422)."""
    r = repair()
    (roofer, rp), (plumber, pp) = pmg["panel"]["roof"], pmg["panel"]["plumb"]
    q1 = services.add_quote(r, people["cm"], contractor=roofer, payee=rp, amount={"amount": "300.00",
                                                                                  "currency": "GHS"},
                            evidence_id=doc(people["cm"], "q1").pk)
    services.add_quote(r, people["cm"], contractor=plumber, payee=pp, amount={"amount": "350.00", "currency": "GHS"},
                       evidence_id=doc(people["cm"], "q2").pk)
    owner = api(people["client"])
    url = f"/v1/repairs/{r.pk}/quote-approvals"
    body = {"quote_id": str(q1.pk), "confirm_amount": {"amount": "300.00", "currency": "GHS"}}
    assert owner.post(url, body, format="json").status_code == 401
    mfa(owner, people["client"])
    bad = owner.post(url, {**body, "confirm_amount": {"amount": "299.00", "currency": "GHS"}}, format="json")
    assert bad.status_code == 422
    assert api(people["tenant"]).post(url, body, format="json").status_code == 404
    ok = owner.post(url, body, format="json")
    assert ok.status_code == 201, ok.content
    out = ok.json()
    assert out["status"] == "approved" and out["quotes_considered"] == 2
    assert out["escrow"]["status"] == "proposed" and out["approved_quote"]["amount"]["amount"] == "300.00"


# --------------------------------------------------------------------------- FR-PMG-005 paid after inspection

def _approved(people, pmg, repair, doc):
    r = repair()
    (roofer, rp), (plumber, pp) = pmg["panel"]["roof"], pmg["panel"]["plumb"]
    q1 = services.add_quote(r, people["cm"], contractor=roofer, payee=rp, amount=GHS,
                            evidence_id=doc(people["cm"], "q1").pk)
    services.add_quote(r, people["cm"], contractor=plumber, payee=pp, amount={"amount": "7000.00", "currency": "GHS"},
                       evidence_id=doc(people["cm"], "q2").pk)
    services.approve_quote(r, people["client"], quote_id=q1.pk, confirm_amount=GHS, mfa_at=timezone.now())
    r.refresh_from_db()
    return r


def _fund(r, people, ref):
    from propertymgmt.seed import _escrow_through

    _escrow_through(r.escrow, people, ref, "6400.00")
    r.refresh_from_db()
    return r


def test_repair_paid_only_after_inspection_pass_full_journey(api, mfa, people, pmg, repair, doc, snap):
    """FR-PMG-005, US-PMG-005, TC-PMG-005-01, TC-PMG-005-02: money held at the bank; no release before an
    inspection pass or after a fail; after a pass, the instruction to the contractor's verified payee goes through
    the owner and two staff, and the bank's confirmation marks the repair paid."""
    from escrow import services as esc
    from escrow.selectors import held_at_bank

    r = _fund(_approved(people, pmg, repair, doc), people, "VA-GH-PMG-T001")
    assert r.status == "funded" and held_at_bank(r.escrow) == Decimal("6400.00")
    cm = api(people["cm"])
    assert cm.post(f"/v1/repairs/{r.pk}/instructions", {}, format="json").status_code == 409
    roofer = pmg["panel"]["roof"][0]
    w = api(roofer).post(f"/v1/repairs/{r.pk}/work-done",
                         {"evidence_ids": [str(doc(roofer, "done", image=True).pk)]}, format="json")
    assert w.status_code == 200 and w.json()["status"] == "in_progress", w.content
    insp = Inspection.objects.get(repair=r, status="scheduled")
    s = cm.post(f"/v1/repairs/{r.pk}/inspections", {"inspector_id": str(pmg["inspector"].pk)}, format="json")
    assert s.status_code == 201 and s.json()["id"] == str(insp.pk) and s.json()["status"] == "assigned"
    ins_api = api(pmg["inspector"])
    fail = ins_api.post(f"/v1/pmg-inspections/{insp.pk}/results",
                        {"outcome": "fail", "photo_ids": [str(snap(insp, "work_photo").pk)],
                         "notes": "Still leaking"}, format="json")
    assert fail.status_code == 200 and fail.json()["outcome"] == "fail"
    r.refresh_from_db()
    assert r.status == "in_progress"
    assert cm.post(f"/v1/repairs/{r.pk}/instructions", {}, format="json").status_code == 409
    services.record_work_done(r, roofer, evidence_ids=[doc(roofer, "redo", image=True).pk])
    insp2 = Inspection.objects.get(repair=r, status="scheduled")
    services.assign_inspector(insp2, people["cm"], pmg["inspector"])
    ok = ins_api.post(f"/v1/pmg-inspections/{insp2.pk}/results",
                      {"outcome": "pass", "photo_ids": [str(snap(insp2, "work_photo").pk)]}, format="json")
    assert ok.status_code == 200, ok.content
    r.refresh_from_db()
    assert r.status == "inspected" and r.inspection_id == insp2.pk
    out = cm.post(f"/v1/repairs/{r.pk}/instructions", {}, format="json")
    assert out.status_code == 201, out.content
    from escrow.models import ReleaseInstruction

    ins = ReleaseInstruction.objects.get(pk=out.json()["instruction_id"])
    assert ins.payee_id == r.approved_quote.payee_id and ins.subject_type == "repair"
    from propertymgmt.seed import _pay

    _pay(ins, people, "BANK-T-PMG-1")
    r.refresh_from_db()
    assert r.status == "paid" and r.paid_at
    tl = api(people["client"]).get(f"/v1/managed-properties/{r.property_id}/timeline").json()
    assert any(i["kind"] == "repair_paid" and i["id"] == str(r.pk) for i in tl)


def test_repair_release_to_wrong_payee_is_blocked(people, pmg, repair, doc, snap):
    """TC-PMG-005-02, RUL-22: a release for the repair naming another payee is blocked by the repair's check."""
    from escrow import services as esc

    r = _fund(_approved(people, pmg, repair, doc), people, "VA-GH-PMG-T002")
    roofer = pmg["panel"]["roof"][0]
    services.record_work_done(r, roofer, evidence_ids=[doc(roofer, "done", image=True).pk])
    insp = Inspection.objects.get(repair=r, status="scheduled")
    services.assign_inspector(insp, people["cm"], pmg["inspector"])
    services.record_inspection(insp, pmg["inspector"], outcome="pass", photo_ids=[str(snap(insp, "work_photo").pk)])
    other = pmg["panel"]["plumb"][1]
    with pytest.raises(RuleBlocked) as e:
        esc.request_release(r.escrow, payee=other, amount="6400.00", subject_type="repair", subject_id=r.pk,
                            requested_by=people["cm"], kind="partial_release")
    codes = {b["code"] for b in e.value.blocking_reasons}
    assert "payee-not-verified" in codes or "payee-not-locked" in codes


def test_release_check_blocks_repair_without_inspection(people, pmg, repair, doc):
    """FR-PMG-005: the escrow subject check refuses a repair release without an inspection pass."""
    from escrow import services as esc

    r = _fund(_approved(people, pmg, repair, doc), people, "VA-GH-PMG-T003")
    with pytest.raises(RuleBlocked) as e:
        esc.request_release(r.escrow, payee=r.approved_quote.payee, amount="6400.00", subject_type="repair",
                            subject_id=r.pk, requested_by=people["cm"], kind="partial_release")
    assert "inspection-missing" in {b["code"] for b in e.value.blocking_reasons}


# --------------------------------------------------------------------------- FR-PMG-006 inspections and timeline

def test_periodic_inspections_scheduled_once_per_interval(people, new_property, onboard):
    """FR-PMG-006, US-PMG-006 AC1, TC-PMG-006-01: when the interval passes an inspection task is created once."""
    prop = onboard(new_property())
    due = prop.next_inspection_due_on
    assert services.scheduled_inspection_watch(due - timedelta(days=30)) == 0 or not \
        prop.inspections.filter(kind="periodic").exists()
    services.scheduled_inspection_watch(due)
    assert prop.inspections.filter(kind="periodic", status="scheduled").count() == 1
    services.scheduled_inspection_watch(due + timedelta(days=1))
    assert prop.inspections.filter(kind="periodic").count() == 1


def test_timeline_in_date_order_with_photos(api, people, seeded):
    """FR-PMG-006, US-PMG-006 AC2: rent, repairs and inspections in date order with photo previews."""
    house = seeded["pmg"]["properties"]["House at Tema Community 25"]
    tl = api(people["client"]).get(f"/v1/managed-properties/{house.pk}/timeline").json()
    dates = [i["date"] for i in tl]
    assert dates == sorted(dates)
    kinds = {i["kind"] for i in tl}
    assert {"inspection_onboarding", "rent", "repair_reported", "repair_paid"} <= kinds
    insp = next(i for i in tl if i["kind"] == "inspection_onboarding")
    assert insp["photos"] and insp["photos"][0]["preview"].startswith("/v1/evidence/")


def test_inbox_home_and_jobs(api, people, pmg, seeded):
    """Registries: the inspector's My jobs, the owner's and the tenant's home, the job endpoints for staff."""
    from accounts import home
    from mobile import inbox

    items = [i for i in inbox.items_for(pmg["inspector"]) if i.subject_type == "property_inspection"]
    assert items and all(i.kind == "inspection" for i in items)
    owner_items = [i for i in home.items_for(people["client"]) if i["line"] == "pmg"]
    assert any(i["kind"] == "repair" and i["needs_action"] for i in owner_items)
    tenant_items = [i for i in home.items_for(people["tenant"]) if i["kind"] == "tenancy"]
    assert tenant_items and not tenant_items[0]["needs_action"]
    assert api(people["client"]).post("/v1/pmg-jobs/rent-watch").status_code == 403
    assert api(people["cm"]).post("/v1/pmg-jobs/rent-watch").status_code == 200
