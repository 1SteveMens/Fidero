"""CARE: care plans, the carer panel, visits, family confirmation and pay per confirmed visit
(FR-CARE-001 to FR-CARE-006, RUL-23, RUL-11, RUL-27, ADR-20)."""
from datetime import timedelta

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from care import services
from care.models import CarePlan, Concern, Visit
from core.errors import Forbidden, Invalid, MfaRequired, RuleBlocked, SameApprover, StateConflict


def codes(exc):
    return {r.get("code") for r in getattr(exc, "blocking_reasons", [])}


# --------------------------------------------------------------------------- plans (FR-CARE-001)

def test_api_journey_plan_to_paid_visit(care, api, mfa, field_api, people, topics):
    """J-10, US-CARE-001 AC1 AC3, US-CARE-002, US-CARE-003, US-CARE-004 AC1 AC3: the client creates a plan, a
    case manager assigns a vetted carer, the client accepts and agrees the carer, the carer checks in, records
    the items and checks out in the field app, the family confirms with the code, and the visit's payment is
    instructed to the carer's verified account."""
    cl = api(care.client)
    r = cl.post("/v1/care-plans", {
        "family_member_id": str(care.mother.pk), "items": [
            {"key": "medicines", "kind": "medicine", "label": "Medicines", "photo_allowed": True},
            {"key": "blood_pressure", "kind": "reading", "reading_required": True, "reading_kind": "blood_pressure"},
            {"key": "groceries", "kind": "groceries", "photo_required": True}],
        "schedule": {"weekly": ["tue", "fri"], "window": "09:00-12:00"},
        "visit_fee": {"amount": "150.00", "currency": "GHS"}, "confirmers": [str(care.mother.pk)]}, format="json")
    assert r.status_code == 201, r.content
    plan_id = r.json()["id"]
    assert r.json()["status"] == "draft" and r.json()["point"]["lat"]
    r = api(care.cm).post(f"/v1/care-plans/{plan_id}/assignments", {"carer_id": str(care.carer.pk)}, format="json")
    assert r.status_code == 200 and r.json()["carer"]["id"] == str(care.carer.pk)
    assert r.json()["needs_client"] == "activate"
    from orders import legal

    cur = legal.current(care.gh)
    body = {"terms_version": cur["terms_version"], "scope_version": cur["scope_version"]}
    assert cl.post(f"/v1/care-plans/{plan_id}/activate", body, format="json").json()["code"] == "mfa-required"
    mfa(cl, care.client)
    r = cl.post(f"/v1/care-plans/{plan_id}/activate", body, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "active" and r.json()["carer_approved_at"] and r.json()["fee_order_id"]
    plan = CarePlan.objects.get(pk=plan_id)
    assert plan.visits.filter(status="scheduled").exists() and topics("visit.scheduled", plan_id=plan.pk)

    v = care.visit(plan)
    fc = field_api(care.carer_person)
    assert any(x["id"] == str(v.pk) for x in fc.get("/v1/mobile/visits").json()["items"])
    inbox = fc.get("/v1/mobile/inbox").json()
    item = next(i for i in inbox if i["subject_id"] == str(v.pk))
    assert item["point"] and [e["key"] for e in item["required_evidence"]] == ["groceries"]
    now = timezone.now()
    r = fc.post("/v1/mobile/check-ins", care.phone.check("checkin", "care_visit", v.pk, lat=float(plan.point_lat),
                                                         lng=float(plan.point_lng),
                                                         captured_at=now - timedelta(minutes=40)), format="json")
    assert r.status_code == 201, r.content
    assert Visit.objects.get(pk=v.pk).status == "checked_in"
    put = lambda key, body: fc.put(f"/v1/mobile/visits/{v.pk}/items/{key}", body, format="json")  # noqa: E731
    assert put("medicines", {"outcome": "done"}).status_code == 200
    r = put("blood_pressure", {"outcome": "done", "reading": {"systolic": 128, "diastolic": 82}})
    assert r.status_code == 200
    assert put("groceries", {"outcome": "done", "evidence_id": str(care.photo(v))}).status_code == 200
    r = fc.post("/v1/mobile/check-outs", care.phone.check("checkout", "care_visit", v.pk, lat=float(plan.point_lat),
                                                          lng=float(plan.point_lng),
                                                          captured_at=now - timedelta(minutes=5)), format="json")
    assert r.status_code == 201, r.content
    v.refresh_from_db()
    assert v.status == "checked_out" and v.submitted_at and v.confirmation.sent_channel == "sms"
    detail = fc.get(f"/v1/mobile/visits/{v.pk}").json()
    assert "confirmation" not in detail and "123456" not in str(detail)  # ADR-20: never in the carer's app
    assert "123456" not in str(cl.get(f"/v1/care-visits/{v.pk}").json())

    care.mother.person = people["family"]
    care.mother.save(update_fields=["person"])
    fam = api(people["family"])
    r = fam.post(f"/v1/care-visits/{v.pk}/confirmations", {"method": "app", "code": "123456"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "confirmed"
    assert r.json()["confirmation"]["confirmed_by"]["relationship"] == "mother"
    assert r.json()["confirmation"]["confirmed_by"]["method"] == "app"
    assert topics("visit.confirmed", visit_id=v.pk)

    r = api(care.cm).post(f"/v1/care-visits/{v.pk}/instructions")
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "awaiting_client" and r.json()["amount"] == {"amount": "150.00", "currency": "GHS"}
    from escrow.models import ReleaseInstruction

    ins = ReleaseInstruction.objects.get(pk=r.json()["instruction_id"])
    assert ins.payee_id == care.carer.payee_id and ins.subject_type == "care_visit"
    assert Visit.objects.get(pk=v.pk).status == "instructed"
    home = cl.get("/v1/home").json()
    assert any(i["kind"] == "care_plan" and i["id"] == plan_id for i in home["items"])


def test_plan_needs_a_confirmer_and_an_address(care, api):
    """TC-CARE-001-02: at least one confirmer and one registered address."""
    cl = api(care.client)
    base = {"family_member_id": str(care.mother.pk), "items": [{"key": "meds", "kind": "medicine"}],
            "schedule": {"weekly": ["tue"], "window": "09:00-10:00"},
            "visit_fee": {"amount": "100.00", "currency": "GHS"}}
    r = cl.post("/v1/care-plans", {**base, "confirmers": []}, format="json")
    assert r.status_code == 422
    nephew = care.ctx["family_members"]["nephew"]
    r = cl.post("/v1/care-plans", {**base, "confirmers": [str(nephew.pk)]}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "confirmer-not-allowed"
    nephew.latitude = nephew.longitude = None
    nephew.address = ""
    nephew.save()
    r = cl.post("/v1/care-plans", {**base, "family_member_id": str(nephew.pk), "confirmers": [str(care.mother.pk)]},
                format="json")
    assert r.status_code == 422 and r.json()["code"] == "address-required"
    r = cl.post("/v1/care-plans", {**base, "items": [], "confirmers": [str(care.mother.pk)]}, format="json")
    assert r.status_code == 422
    r = cl.post("/v1/care-plans", {**base, "schedule": {"weekly": [], "window": "09:00-10:00"},
                                   "confirmers": [str(care.mother.pk)]}, format="json")
    assert r.status_code == 422


def test_confirmers_checked_by_the_database(care):
    """FR-CARE-001 trigger care.confirmers_may_confirm(): a confirmer who may not confirm is refused."""
    plan = care.plan(activate=False)
    nephew = care.ctx["family_members"]["nephew"]
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        CarePlan.objects.filter(pk=plan.pk).update(confirmers=[nephew.pk])


def test_plan_change_applies_to_future_visits_only(care):
    """US-CARE-001 AC2: a new version; future visits follow it, past visits keep theirs."""
    plan = care.plan()
    past = care.checked_out(plan)
    future = plan.visits.filter(status="scheduled").order_by("window_start").first()
    items = [{"key": "medicines", "kind": "medicine", "label": "Medicines"},
             {"key": "walk", "kind": "companionship", "label": "A short walk"}]
    services.update_plan(plan, care.client, {"items": items, "visit_fee": {"amount": "180.00", "currency": "GHS"}})
    plan.refresh_from_db()
    assert plan.version == 2
    future.refresh_from_db()
    assert set(future.items.values_list("key", flat=True)) == {"medicines", "walk"}
    assert future.fee_amount == 180 and future.plan_version == 2
    assert set(past.items.values_list("key", flat=True)) == {"medicines", "blood_pressure", "groceries", "company"}
    assert Visit.objects.get(pk=past.pk).fee_amount == 150


def test_standing_approval_on_a_plan(care, api, mfa):
    """US-CARE-001 AC4, US-CARE-004 AC7, TC-CARE-001-03: within the month no client approval is asked; evidence
    and two staff approvals still are; withdrawn, the client approves each payment again."""
    plan = care.plan()
    cl = api(care.client)
    mfa(cl, care.client)
    r = cl.post(f"/v1/care-plans/{plan.pk}/standing-approvals", {"monthly_max": "200.00"}, format="json")
    assert r.status_code == 201 and r.json()["standing_approval"]["monthly_max"] == "200.00"
    v1 = care.confirm(care.checked_out(plan))
    ins = services.prepare_payment(v1, care.cm)
    assert ins.status == "pending_approval" and ins.client_approval_method == "standing"
    from escrow.services import release_blockers

    assert "staff-approvals-missing" in {r["code"] for r in release_blockers(ins, "send")}
    v2 = care.confirm(care.checked_out(plan))
    assert services.prepare_payment(v2, care.cm).status == "awaiting_client"  # above the month's amount
    assert cl.delete(f"/v1/care-plans/{plan.pk}/standing-approvals").status_code == 200
    from escrow.services import standing_approval_for

    assert standing_approval_for("care_plan", plan.pk) is None


# --------------------------------------------------------------------------- panel (FR-CARE-002)

def test_only_vetted_carers_join_the_panel_and_are_assigned(care):
    """US-CARE-002 AC1 AC2, TC-CARE-002-01, TC-CARE-002-02."""
    person, vetting = care.new_carer(vetted=False)
    with pytest.raises(RuleBlocked) as ei:
        services.add_carer(care.cm, person=person, vetting=vetting, pay_route="tenmina")
    assert ei.value.code == "carer-not-vetted"
    with pytest.raises(RuleBlocked):
        services.add_carer(care.cm, person=person, pay_route="tenmina")
    carer2, _ = care.new_carer(pay_route="tenmina")
    assert carer2.status == "active"
    with pytest.raises(Forbidden):
        services.add_carer(care.client, person=carer2.person, pay_route="tenmina")
    plan = care.plan(activate=False)
    services.suspend_carer(carer2, care.cm, reason="Complaint under review")
    with pytest.raises(RuleBlocked) as ei:
        services.assign_carer(plan, care.cm, carer2)
    assert "carer-not-active" in codes(ei.value)


def test_expired_vetting_suspends_the_carer_and_the_database_agrees(care):
    """TC-CARE-002-02, trigger care.carer_vetted(): existing assignments are suspended when a check expires."""
    from accounts.services import expire_vettings

    carer2, v = care.new_carer(pay_route="tenmina")
    plan = care.plan(carer=carer2)
    type(v).objects.filter(pk=v.pk).update(valid_until=timezone.localdate() - timedelta(days=1))
    expire_vettings()
    carer2.refresh_from_db()
    assert carer2.status == "suspended" and "vetting" in carer2.status_reason
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        type(carer2).objects.filter(pk=carer2.pk).update(status="active")
    assert not services.generate_visits(CarePlan.objects.get(pk=plan.pk))


def test_removal_reassigns_future_visits(care):
    """US-CARE-002 AC3: removal for cause moves future visits to the replacement; the reason feeds the record."""
    carer2, _ = care.new_carer(pay_route="tenmina")
    carer3, _ = care.new_carer(name="Abena Third Carer", pay_route="tenmina")
    plan = care.plan(carer=carer2)
    future = list(plan.visits.filter(status="scheduled").values_list("pk", flat=True))
    assert future
    with pytest.raises(Invalid):
        services.remove_carer(carer2, care.cm, reason="")
    services.remove_carer(carer2, care.cm, reason="Did not attend three visits", replacement=carer3)
    assert set(Visit.objects.filter(pk__in=future).values_list("carer_id", flat=True)) == {carer3.pk}
    record = services.track_record(type(carer2).objects.get(pk=carer2.pk))
    assert record["status"] == "removed" and record["status_reason"] == "Did not attend three visits"


def test_carer_cannot_be_a_confirmer(care):
    """RUL-23, ADR-20: a confirmer sharing the carer's phone is refused when the carer is assigned."""
    plan = care.plan(activate=False)
    care.mother.phone = care.carer_person.phone
    care.mother.save(update_fields=["phone"])
    carer2, _ = care.new_carer(pay_route="tenmina")
    carer2.person.phone = care.carer_person.phone
    with pytest.raises(RuleBlocked) as ei:
        services._confirmers_not_carer(plan.confirmers, care.carer)
    assert ei.value.code == "confirmer-is-carer"


# --------------------------------------------------------------------------- visits (FR-CARE-003)

def test_item_rules_photo_reading_reason_and_privacy(care):
    """US-CARE-003 AC1 AC2, TC-CARE-003-02, TC-CARE-003-03, RUL-08."""
    plan = care.plan()
    v = care.visit(plan)
    with pytest.raises(StateConflict):
        services.record_item(v, care.carer_person, "medicines", outcome="done")  # not checked in
    care.check("checkin", v)
    with pytest.raises(Invalid) as ei:
        services.record_item(v, care.carer_person, "groceries", outcome="done")
    assert ei.value.code == "photo-required"
    with pytest.raises(Invalid) as ei:
        services.record_item(v, care.carer_person, "blood_pressure", outcome="done")
    assert ei.value.code == "reading-required"
    with pytest.raises(Invalid):
        services.record_item(v, care.carer_person, "medicines", outcome="not_done")
    with pytest.raises(Invalid) as ei:
        services.record_item(v, care.carer_person, "company", outcome="done", evidence_id=care.photo(v, "company"))
    assert ei.value.code == "photo-not-agreed"
    from evidence.services import store

    gallery = store(data=b"\xff\xd8\xff gallery", country=care.gh, uploaded_by=care.carer_person,
                    content_type="image/jpeg")
    with pytest.raises(Invalid) as ei:
        services.record_item(v, care.carer_person, "groceries", outcome="done", evidence_id=gallery.pk)
    assert ei.value.code == "evidence-rejected"
    with pytest.raises(Exception):
        services.record_item(v, care.client, "medicines", outcome="done")


def test_code_goes_out_only_when_every_item_is_answered(care):
    """TC-CARE-003-02: submission is held until the items are done; check-in, items and check-out are one record."""
    plan = care.plan()
    v = care.visit(plan)
    now = timezone.now()
    care.check("checkin", v, at=now - timedelta(minutes=40))
    services.record_item(v, care.carer_person, "medicines", outcome="done")
    care.check("checkout", v, at=now - timedelta(minutes=5))
    v.refresh_from_db()
    assert v.status == "checked_out" and v.submitted_at is None and not hasattr(v, "confirmation")
    services.record_item(v, care.carer_person, "blood_pressure", outcome="done", reading={"systolic": 120,
                                                                                          "diastolic": 80})
    services.record_item(v, care.carer_person, "groceries", outcome="done", evidence_id=care.photo(v))
    services.record_item(v, care.carer_person, "company", outcome="done")
    v.refresh_from_db()
    assert v.submitted_at and v.confirmation.sent_to_family_member_id == care.mother.pk


# --------------------------------------------------------------------------- confirmation (FR-CARE-004, ADR-20)

def test_code_locks_after_five_wrong_tries(care, people, api):
    """TC-CARE-004-04: tries up to 4 count; the 5th wrong locks; the right code is then refused; the family is
    offered the app or a call. Each wrong try is counted although the request answers 422."""
    v = care.checked_out()
    care.mother.person = people["family"]
    care.mother.save(update_fields=["person"])
    fam = api(people["family"])
    url = f"/v1/care-visits/{v.pk}/confirmations"
    for n in range(4):
        r = fam.post(url, {"method": "app", "code": "000000"}, format="json")
        assert r.status_code == 422 and r.json()["code"] == "confirmation-code-invalid"
        assert r.json()["attempts_left"] == 4 - n
    r = fam.post(url, {"method": "app", "code": "000000"}, format="json")
    assert r.json()["reason"] == "locked" and "call" in r.json()["other_ways"]
    r = fam.post(url, {"method": "app", "code": "123456"}, format="json")
    assert r.status_code == 422
    v.refresh_from_db()
    assert v.status == "checked_out" and v.confirmation.locked_at
    from notifications.models import Message

    assert Message.objects.filter(template="care_code_locked", to_address=care.mother.phone).exists()


def test_carer_cannot_confirm_own_visit(care, api, people):
    """TC-RUL-23-02, TC-E2E-J10-02, TC-CARE-004-03: refused, logged as a security event, client told."""
    from audit.models import AuditEvent

    v = care.checked_out()
    r = api(care.carer_person).post(f"/v1/care-visits/{v.pk}/confirmations", {"method": "code", "code": "123456"},
                                    format="json")
    assert r.status_code in (403, 404)
    with pytest.raises(Forbidden):
        services.confirm_with_code(v, care.carer_person, code="123456")
    assert AuditEvent.objects.filter(action="security.care.carer_self_confirmation").exists()
    assert Visit.objects.get(pk=v.pk).status == "checked_out"
    with pytest.raises(Forbidden):
        services.confirm_with_code(v, people["tenant"], code="123456")  # not a named confirmer


def test_call_confirmation_needs_a_second_staff_member(care):
    """TC-CARE-004-05, US-CARE-004 AC2: not payable on A's record alone; A cannot check it; B can."""
    v = care.checked_out()
    services.record_call(v, care.cm, family_member=care.mother, note="Called Akosua; she confirmed the visit.")
    v.refresh_from_db()
    assert v.status == "checked_out"
    with pytest.raises(RuleBlocked):
        services.prepare_payment(v, care.cm)
    with pytest.raises(SameApprover):
        services.check_call(v, care.cm)
    v = services.check_call(v, care.rv)
    assert v.status == "confirmed" and v.confirmation.method == "call"
    assert v.confirmation.recorded_by_staff_id == care.cm.pk and v.confirmation.call_checked_by_id == care.rv.pk
    with pytest.raises(Invalid):
        services.record_call(care.checked_out(), care.cm, family_member=care.ctx["family_members"]["nephew"],
                             note="Nephew said yes")


def test_unconfirmed_alert_at_24_hours_and_reviewer_at_72(care, api):
    """TC-RUL-23-04, TC-CARE-004-06, TC-CARE-005-01: not paid; alert at 24 hours; to a reviewer at 72 hours;
    only 'confirmed' makes it payable; a decision without a note is refused."""
    from notifications.models import Message

    v = care.checked_out()
    out_at = v.checkout.device_time
    services.missed_and_unconfirmed(out_at + timedelta(hours=23))
    assert Visit.objects.get(pk=v.pk).status == "checked_out"
    services.missed_and_unconfirmed(out_at + timedelta(hours=25))
    v.refresh_from_db()
    assert v.status == "unconfirmed"
    assert Message.objects.filter(person=care.client, template="care_visit_unconfirmed").exists()
    with pytest.raises(RuleBlocked) as ei:
        services.prepare_payment(v, care.cm)
    assert "visit-not-confirmed" in codes(ei.value)
    with pytest.raises(StateConflict):
        services.reviewer_decide(v, care.rv, decision="confirmed", note="Too early")
    services.missed_and_unconfirmed(out_at + timedelta(hours=71))
    assert Visit.objects.get(pk=v.pk).review_queued_at is None
    services.missed_and_unconfirmed(out_at + timedelta(hours=72, minutes=1))
    v.refresh_from_db()
    assert v.review_queued_at
    queue = api(care.rv).get("/v1/care-visits?review=1").json()["items"]
    assert str(v.pk) in [x["id"] for x in queue]
    r = api(care.rv).post(f"/v1/care-visits/{v.pk}/reviewer-decisions", {"decision": "confirmed", "note": ""},
                          format="json")
    assert r.status_code == 422
    with pytest.raises(Forbidden):
        services.reviewer_decide(v, care.cm, decision="confirmed", note="Not a reviewer")
    r = api(care.rv).post(f"/v1/care-visits/{v.pk}/reviewer-decisions",
                          {"decision": "confirmed", "note": "Check-in and check-out at the house; Akosua confirmed "
                                                            "by phone."}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert services.prepare_payment(Visit.objects.get(pk=v.pk), care.cm).subject_id == v.pk


def test_reviewer_not_confirmed_means_no_payment(care):
    """FR-CARE-004: 'not confirmed' is final; the carer is not paid for that visit."""
    v = care.checked_out()
    services.missed_and_unconfirmed(v.checkout.device_time + timedelta(hours=73))
    v = services.reviewer_decide(Visit.objects.get(pk=v.pk), care.rv, decision="not_confirmed",
                                 note="Family says nobody came; check-in photo shows another house.")
    assert v.status == "unconfirmed"
    with pytest.raises(RuleBlocked):
        services.prepare_payment(v, care.cm)
    with pytest.raises(StateConflict):
        services.record_call(v, care.cm, family_member=care.mother, note="Later call")


def test_check_in_outside_the_address_goes_to_a_reviewer(care):
    """TC-RUL-23-03, trigger care.visit_confirmed_needs_confirmation(): the family confirms but the check-in was
    elsewhere: not payable until a reviewer clears the flag."""
    from mobile.models import FraudFlag
    from mobile.services import review_flag

    plan = care.plan()
    v = care.visit(plan)
    now = timezone.now()
    care.check("checkin", v, at=now - timedelta(minutes=40), lat=float(plan.point_lat) + 0.02)
    care.do_items(v)
    care.check("checkout", v, at=now - timedelta(minutes=5))
    v = care.confirm(v)
    assert v.status == "unconfirmed" and v.review_queued_at and v.confirmation.family_confirmed_at
    with pytest.raises(RuleBlocked):
        services.prepare_payment(v, care.cm)
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        Visit.objects.filter(pk=v.pk).update(status="confirmed", confirmed_at=timezone.now())
    for f in FraudFlag.objects.filter(checkin=v.checkin, status="open"):
        review_flag(f, care.rv, "clear", "GPS drift near the gate; the family confirms she was there.")
    v.refresh_from_db()
    assert v.status == "confirmed"


def test_family_dispute_goes_to_a_reviewer(care):
    """FR-CARE-004: 'no' from the family disputes the visit; it is not paid unless a reviewer confirms it."""
    from notifications.services import confirm_by_reply

    v = care.checked_out()
    confirm_by_reply(from_address=care.mother.phone, text="NO she did not come")
    v.refresh_from_db()
    assert v.status == "disputed" and v.review_queued_at
    with pytest.raises(RuleBlocked):
        services.prepare_payment(v, care.cm)


# --------------------------------------------------------------------------- alerts (FR-CARE-005)

def test_missed_visit_alerts_client_and_case_manager(care, topics):
    """US-CARE-005 AC1, TC-CARE-005-01, TC-CARE-005-02: alerted once; no alert for a good visit."""
    from notifications.models import Message

    plan = care.plan()
    missed = care.visit(plan, minutes_ago=300, hours=2)
    good = care.checked_out(plan)
    before = Message.objects.filter(template="care_visit_missed").count()
    services.missed_and_unconfirmed()
    services.missed_and_unconfirmed()
    assert Visit.objects.get(pk=missed.pk).status == "missed"
    assert Visit.objects.get(pk=good.pk).status == "checked_out"
    msgs = Message.objects.filter(template="care_visit_missed").count() - before
    assert msgs >= 2 and len(topics("visit.missed", visit_id=missed.pk)) == 1
    assert Message.objects.filter(template="care_visit_missed", person=care.client).exists()


def test_late_check_in_alerts_the_client(care):
    """TC-CARE-005-01: a check-in after the grace period is late; the client is told."""
    from notifications.models import Message

    plan = care.plan()
    v = care.visit(plan, minutes_ago=50)
    care.check("checkin", v, at=timezone.now() - timedelta(minutes=5))
    v.refresh_from_db()
    assert v.late_minutes and v.late_minutes > 30
    assert Message.objects.filter(template="care_visit_late", person=care.client).exists()


# --------------------------------------------------------------------------- concerns (FR-CARE-006)

def test_concern_reaches_client_and_reviewer_and_stays_restricted(care, api, field_api, people):
    """US-CARE-006 AC1 AC2, TC-CARE-006-01, TC-CARE-006-02."""
    from notifications.models import Message

    plan = care.plan()
    v = care.visit(plan)
    care.check("checkin", v)
    r = field_api(care.carer_person).post(f"/v1/mobile/visits/{v.pk}/concerns", {
        "kind": "health", "severity": "urgent", "narrative": "She fell this morning and her wrist is swollen."},
        format="json")
    assert r.status_code == 201, r.content
    c = Concern.objects.get(pk=r.json()["id"])
    assert c.client_notified_at and c.reviewer_notified_at and c.paged_at and c.routed_to_reviewer_id
    assert Message.objects.filter(person=care.client, template="care_concern_raised").exists()
    client_view = api(care.client).get(f"/v1/concerns/{c.pk}").json()
    assert "narrative" not in client_view
    staff_view = api(care.rv).get(f"/v1/concerns/{c.pk}").json()
    assert staff_view["narrative"].startswith("She fell")
    for who in ("tenant", "institution", "client2", "agent"):
        assert api(people[who]).get(f"/v1/concerns/{c.pk}").status_code == 404
    r = api(care.rv).post(f"/v1/concerns/{c.pk}/action", {
        "action_taken": "Ambulance called; carer stayed until it came.",
        "client_outcome": "Akosua was taken to Ridge Hospital and is resting. Her wrist is sprained."}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "actioned"
    client_view = api(care.client).get(f"/v1/concerns/{c.pk}").json()
    assert client_view["client_outcome"].startswith("Akosua") and "action_taken" not in client_view
    other = care.new_carer(pay_route="tenmina")[0]
    with pytest.raises(Exception):
        services.raise_concern(other.person, visit=v, kind="welfare", severity="low", narrative="x")


# --------------------------------------------------------------------------- pay (RUL-23, RUL-22, RUL-27)

def test_escrow_refuses_an_instruction_for_an_unconfirmed_visit(care):
    """RUL-23 through escrow.registry: the subject check blocks with visit-not-confirmed; the wrong payee too."""
    from escrow import services as esc

    v = care.checked_out()
    plan = v.plan
    with pytest.raises(RuleBlocked) as ei:
        esc.request_release(plan.escrow, payee=care.carer.payee, amount="150.00", subject_type="care_visit",
                            subject_id=v.pk, requested_by=care.cm)
    assert "visit-not-confirmed" in codes(ei.value)
    v = care.confirm(v)
    school = care.ctx["escrow"]["payees"]["school"]
    with pytest.raises(RuleBlocked):
        esc.request_release(plan.escrow, payee=school, amount="150.00", subject_type="care_visit", subject_id=v.pk,
                            requested_by=care.cm)
    with pytest.raises(RuleBlocked) as ei:
        esc.request_release(plan.escrow, payee=care.carer.payee, amount="999.00", subject_type="care_visit",
                            subject_id=v.pk, requested_by=care.cm)
    assert "visit-amount" in codes(ei.value)


def test_tenmina_contracted_carer_is_paid_under_pro_never_from_client_money(care, topics):
    """RUL-27, brief: a confirmed visit by a carer Tenmina contracts publishes work.accepted; no instruction from
    the client's held funds."""
    carer2, _ = care.new_carer(pay_route="tenmina")
    plan = care.plan(carer=carer2)
    phone2 = type(care.phone)(carer2.person, model="SM-A145F")
    phone2.register()
    v = care.visit(plan)
    now = timezone.now()
    care.check("checkin", v, at=now - timedelta(minutes=40), phone=phone2)
    for key, body in (("medicines", {}), ("blood_pressure", {"reading": {"systolic": 1, "diastolic": 1}}),
                      ("company", {})):
        services.record_item(v, carer2.person, key, outcome="done", **body)
    services.record_item(v, carer2.person, "groceries", outcome="not_done", reason="Shop closed")
    care.check("checkout", v, at=now - timedelta(minutes=5), phone=phone2)
    v = care.confirm(v)
    assert v.status == "confirmed" and v.work_accepted_at
    from core.models import OutboxEvent

    ev = OutboxEvent.objects.get(topic="work.accepted", aggregate_id=v.pk)
    assert ev.payload["person_id"] == str(carer2.person_id) and ev.payload["role"] == "CE"
    assert ev.payload["work_type"] == "care_visit" and ev.payload["subject_id"] == str(v.pk)
    with pytest.raises(StateConflict):
        services.prepare_payment(v, care.cm)
    assert services.payable_blockers(v)[0]["rule"] == "RUL-27"


def test_payment_batch_pays_confirmed_visits_only(care, api):
    """US-CARE-004 AC3 AC4, TC-CARE-004-02: unconfirmed visits are excluded and listed as awaiting confirmation."""
    plan = care.plan()
    done = care.confirm(care.checked_out(plan))
    waiting = care.checked_out(plan)
    r = api(care.cm).post("/v1/care-payment-batches")
    assert r.status_code == 201, r.content
    prepared = {x["visit_id"] for x in r.json()["prepared"]}
    assert str(done.pk) in prepared and str(waiting.pk) not in prepared
    assert str(waiting.pk) in {x["visit_id"] for x in r.json()["awaiting_confirmation"]}
    assert api(care.client).post("/v1/care-payment-batches").status_code == 403


def test_release_confirmed_marks_the_visit_paid(care):
    """release.confirmed for a care visit: paid; a withdrawn instruction puts it back to confirmed."""
    from core.events import publish
    from escrow.services import withdraw_instruction

    v = care.confirm(care.checked_out())
    ins = services.prepare_payment(v, care.cm)
    withdraw_instruction(ins, care.cm, reason="Wrong week's batch")
    v.refresh_from_db()
    assert v.status == "confirmed" and v.instruction_id is None
    ins = services.prepare_payment(v, care.cm)
    publish("release.confirmed", ins.pk, {"instruction_id": ins.pk, "subject_type": "care_visit",
                                          "subject_id": v.pk})
    v.refresh_from_db()
    assert v.status == "paid" and v.paid_at


# --------------------------------------------------------------------------- access and flags

def test_visits_scoped_to_their_people(care, api, people):
    """02 7.4: CL own, FM own, staff, the assigned carer; others 404."""
    v = care.checked_out()
    assert api(care.client).get(f"/v1/care-visits/{v.pk}").status_code == 200
    assert api(care.carer_person).get(f"/v1/care-visits/{v.pk}").status_code == 200
    assert api(care.cm).get(f"/v1/care-visits/{v.pk}").status_code == 200
    for who in ("client2", "tenant", "agent", "institution"):
        assert api(people[who]).get(f"/v1/care-visits/{v.pk}").status_code == 404
    assert api(people["client2"]).get(f"/v1/care-plans/{v.plan_id}").status_code == 404


def test_line_closed_by_its_flag(care, api, settings):
    """06 2.6: everything behind lines.care."""
    settings.TENMINA_FLAG_OVERRIDES = {"lines.care": False}
    r = api(care.client).post("/v1/care-plans", {
        "family_member_id": str(care.mother.pk), "items": [{"key": "m", "kind": "medicine"}],
        "schedule": {"weekly": ["tue"], "window": "09:00-10:00"},
        "visit_fee": {"amount": "1.00", "currency": "GHS"}, "confirmers": [str(care.mother.pk)]}, format="json")
    assert r.status_code == 404 and r.json()["code"] == "feature-off"


def test_activation_needs_a_fresh_step_up(care):
    """RUL-28: agreeing the carer as payee of held funds needs a fresh MFA step-up."""
    from orders import legal

    plan = care.plan(activate=False)
    cur = legal.current(care.gh)
    with pytest.raises(MfaRequired):
        services.activate_plan(plan, care.client, terms_version=cur["terms_version"],
                               scope_version=cur["scope_version"], mfa_at=None)
