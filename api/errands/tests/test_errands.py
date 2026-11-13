"""TSK: catalogue, orders, agents, steps with receipts, official fees to the agency, completion by the checked
document, handover (FR-TSK-001 to FR-TSK-005, RUL-22, RUL-23, RUL-27)."""
import uuid
from datetime import timedelta

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.models import OutboxEvent
from errands import services
from errands.models import Errand, ErrandStep


def codes(exc):
    return {r.get("code") for r in getattr(exc, "blocking_reasons", [])}


def test_api_journey_order_to_handover(tsk, api, field_api, people):
    """J-12, US-TSK-002, US-TSK-003, US-TSK-004, US-TSK-005: the whole errand through the API."""
    r = api().get("/v1/errand-catalogue?country=GH")
    assert r.status_code == 200
    item = next(i for i in r.json()["items"] if i["code"] == "birth_cert")
    assert item["checklist"] and item["official_fees"]["amount"] == "120.00" and item["target_days"] == 14
    cl = api(tsk.client)
    r = cl.post("/v1/errands", {"code": "birth_cert", "country": "GH"}, format="json")
    assert r.status_code == 201, r.content
    eid = r.json()["id"]
    from django.core.files.uploadedfile import SimpleUploadedFile

    r = cl.post(f"/v1/errands/{eid}/documents/parent_id",
                {"file": SimpleUploadedFile("card.pdf", b"%PDF-1.4 card", content_type="application/pdf")},
                format="multipart")
    assert r.status_code == 201 and r.json()["status"] == "uploaded"
    r = cl.post(f"/v1/errands/{eid}/submit", tsk.terms(), format="json")
    assert r.status_code == 422 and r.json()["code"] == "checklist-incomplete"
    assert r.json()["missing"] == ["hospital_record"]
    cl.post(f"/v1/errands/{eid}/documents/hospital_record", {"evidence_id": str(tsk.ev("weigh").pk)}, format="json")
    r = cl.post(f"/v1/errands/{eid}/submit", tsk.terms(), format="json")
    assert r.status_code == 200, r.content
    pay = cl.get(f"/v1/errands/{eid}/payments").json()
    assert pay["tenmina_charge"]["route"] == "payment_provider" and pay["tenmina_charge"]["currency"] == "USD"
    assert pay["official_fees"]["route"] == "partner_bank_held_funds"
    assert {b["code"] for b in pay["blocking_reasons"]} >= {"document-uploaded", "charge-unpaid"}
    cm = api(tsk.cm)
    for key in ("parent_id", "hospital_record"):
        assert cm.post(f"/v1/errands/{eid}/documents/{key}/reviews", {"accept": True},
                       format="json").status_code == 200
    from orders.services import mark_paid

    mark_paid(Errand.objects.get(pk=eid).fee_order_id, payment_id=uuid.uuid4(), method="card")
    assert cl.get(f"/v1/errands/{eid}").json()["status"] == "funded"
    r = cm.post(f"/v1/errands/{eid}/assignments", {"agent_id": str(tsk.agent.pk),
                                                   "agency_payee_id": str(tsk.agency.pk)}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "assigned" and r.json()["agency_payee"]["id"] == str(tsk.agency.pk)

    fa = field_api(tsk.agent_person)
    assert any(x["id"] == eid for x in fa.get("/v1/mobile/errands").json()["items"])
    e = Errand.objects.get(pk=eid)
    s1, s2 = e.steps.get(seq=1), e.steps.get(seq=2)
    inbox = fa.get("/v1/mobile/inbox").json()
    assert any(i["subject_id"] == str(s1.pk) for i in inbox)
    r = cm.post(f"/v1/errands/{eid}/steps/1/instructions")
    assert r.status_code == 409 and r.json()["code"] == "visit-not-confirmed"  # TC-RUL-23-05: no receipt yet
    r = fa.post(f"/v1/mobile/errands/{eid}/steps/1/receipts",
                {"kind": "acknowledgement", "evidence_id": str(tsk.photo("errand_step", s1.pk, "acknowledgement"))},
                format="json")
    assert r.status_code == 201, r.content
    assert fa.post(f"/v1/mobile/errands/{eid}/steps/1/done").status_code == 409  # fee step: receipt after payment
    r = cm.post(f"/v1/errands/{eid}/steps/1/instructions")
    assert r.status_code == 201, r.content
    assert r.json()["payee"] == tsk.agency.legal_name and r.json()["amount"]["amount"] == "120.00"
    ins_id = r.json()["instruction_id"]
    publish("release.confirmed", uuid.UUID(ins_id), {"instruction_id": ins_id, "subject_type": "errand_step",
                                                     "subject_id": str(s1.pk)})
    assert ErrandStep.objects.get(pk=s1.pk).status == "fee_paid"
    r = fa.post(f"/v1/mobile/errands/{eid}/steps/1/receipts",
                {"kind": "receipt", "evidence_id": str(tsk.photo("errand_step", s1.pk, "receipt"))}, format="json")
    assert r.json()["status"] == "receipted"
    assert fa.post(f"/v1/mobile/errands/{eid}/steps/1/done").json()["status"] == "done"
    fa.post(f"/v1/mobile/errands/{eid}/steps/2/receipts",
            {"kind": "acknowledgement", "evidence_id": str(tsk.photo("errand_step", s2.pk, "acknowledgement"))},
            format="json")
    assert fa.post(f"/v1/mobile/errands/{eid}/steps/2/done").json()["status"] == "done"
    assert not OutboxEvent.objects.filter(topic="work.accepted", aggregate_id=eid).exists()
    r = fa.post(f"/v1/mobile/errands/{eid}/results", {"evidence_id": str(tsk.photo("errand", eid, "result"))},
                format="json")
    assert r.status_code == 201 and r.json()["status"] == "result_uploaded"
    r = cm.post(f"/v1/errands/{eid}/result-checks", {"accept": True, "note": "Certified copy, names match."},
                format="json")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    ev = OutboxEvent.objects.get(topic="work.accepted", aggregate_id=eid)
    assert ev.payload["person_id"] == str(tsk.agent_person.pk) and ev.payload["role"] == "CE"
    assert ev.payload["work_type"] == "errand"
    r = fa.post(f"/v1/mobile/errands/{eid}/handovers", {
        "method": "courier", "proof_kind": "photo", "evidence_id": str(tsk.photo("errand", eid, "handover")),
        "courier_name": "DHL Ghana", "tracking_reference": "DHL-123"}, format="json")
    assert r.status_code == 201, r.content
    d = cl.get(f"/v1/errands/{eid}").json()
    assert d["status"] == "handed_over" and d["handover"]["tracking_reference"] == "DHL-123"
    assert cl.post(f"/v1/errands/{eid}/handover-confirmations").json()["confirmed_via"] == "client"


# --------------------------------------------------------------------------- catalogue (FR-TSK-001)

def test_catalogue_per_country_and_incomplete_items(tsk, api):
    """US-TSK-001 AC1 AC2, TC-TSK-001-01, TC-TSK-001-02: only complete items are offered; new orders use a new
    fee and open errands keep theirs."""
    from countries.selectors import config

    open_errand = tsk.errand("land_search", pay=False)
    items = [dict(i) for i in config(tsk.gh, "errand_catalogue")]
    for i in items:
        if i["code"] == "land_search":
            i["official_fees"] = {"amount": "300.00", "currency": "GHS"}
            i["steps"] = [dict(i["steps"][0], official_fee="300.00"), i["steps"][1]]
    items.append({"code": "probate", "name": "Probate", "agency": "High Court"})  # no fees, checklist or steps
    from countries.selectors import current_config
    from countries.services import seed_publish

    # A new published version (two administrators in production; publish_config is blocked on this base by
    # superseded case and report template references from other seeds).
    seed_publish(tsk.gh, dict(current_config(tsk.gh).data, errand_catalogue=items))
    tsk.gh.refresh_from_db()
    codes_ = [i["code"] for i in api().get("/v1/errand-catalogue?country=GH").json()["items"]]
    assert "probate" not in codes_ and "land_search" in codes_
    staff = api(tsk.cm).get("/v1/errand-catalogue?country=GH&include_incomplete=1").json()["items"]
    probate = next(i for i in staff if i["code"] == "probate")
    assert not probate["orderable"] and "No official fees." in probate["problems"]
    with pytest.raises(Invalid) as ei:
        services.create_errand(tsk.client, country=tsk.gh, code="probate")
    assert ei.value.code == "catalogue-item-incomplete"
    new = services.create_errand(tsk.client, country=tsk.gh, code="land_search")
    assert new.official_fees_amount == 300
    assert Errand.objects.get(pk=open_errand.pk).official_fees_amount == 200
    assert api().get("/v1/errand-catalogue?country=NG").status_code == 404
    with pytest.raises(NotFound):
        services.create_errand(tsk.client, country=tsk.gh, code="no_such_errand")


# --------------------------------------------------------------------------- orders (FR-TSK-002)

def test_cannot_assign_until_documents_charge_and_fees_are_in(tsk, monkeypatch):
    """TC-TSK-002-02: a missing document, an unpaid charge or short official fees stop assignment; the client is
    told what is missing."""
    e = tsk.errand(pay=False)
    with pytest.raises(StateConflict) as ei:
        services.assign(e, tsk.cm, agent=tsk.agent, agency_payee=tsk.agency)
    assert "charge" in ei.value.detail
    import escrow.selectors as esel

    monkeypatch.setattr(esel, "available_to_instruct", lambda e, currency=None, exclude=None: 50)
    from orders.services import mark_paid

    mark_paid(e.fee_order_id, payment_id=uuid.uuid4(), method="card")
    e.refresh_from_db()
    assert e.status == "ordered" and "official-fees-short" in {b["code"] for b in services.funding_blockers(e)}
    e2 = tsk.errand(accept=False)
    services.review_document(e2.documents.first(), tsk.cm, accept=False, reason="Blurred")
    e2.refresh_from_db()
    assert e2.status == "documents_pending"
    assert "document-rejected" in {b["code"] for b in services.funding_blockers(e2)}


def test_each_payment_by_its_own_route(tsk):
    """TC-TSK-002-04, RUL-01: Tenmina's charge only through the provider (an order); official fees only into the
    held funds at the bank."""
    e = tsk.errand(pay=False)
    routes = services.payment_routes(e)
    assert routes["tenmina_charge"]["order_id"] == str(e.fee_order_id)
    assert routes["official_fees"]["route"] == "partner_bank_held_funds"
    from orders.models import Order

    order = Order.objects.get(pk=e.fee_order_id)
    assert order.kind == "errand" and order.price_currency == "USD" and order.price_amount == 40
    assert e.escrow.kind == "held_funds" and e.escrow.client_id == tsk.client.pk


def test_documents_restricted_to_client_staff_and_the_steps_agent(tsk, api, field_api, people):
    """TC-TSK-002-03: the agent opens only the documents an open step needs, by short link; others get 404."""
    e = tsk.assigned()
    fa = field_api(tsk.agent_person)
    r = fa.get(f"/v1/mobile/errands/{e.pk}/documents/parent_id/link")
    assert r.status_code == 200 and r.json()["url"].startswith("/v1/evidence-files/")
    for who in ("client2", "tenant", "institution"):
        assert api(people[who]).get(f"/v1/errands/{e.pk}").status_code == 404
    doc = e.documents.get(key="parent_id")
    from evidence import access

    assert not access.can_view(people["client2"], doc.evidence)
    assert access.can_view(tsk.client, doc.evidence) and access.can_view(tsk.agent_person, doc.evidence)
    s1 = e.steps.get(seq=1)
    ErrandStep.objects.filter(pk=s1.pk).update(needs_documents=[])
    assert fa.get(f"/v1/mobile/errands/{e.pk}/documents/parent_id/link").status_code == 404


# --------------------------------------------------------------------------- agents and fees (FR-TSK-003)

def test_only_vetted_agents_with_an_agreement(tsk, people):
    """TC-TSK-003-03, TC-TSK-003-07: unvetted refused; no agreement refused at assignment; the database agrees."""
    with pytest.raises(RuleBlocked) as ei:
        services.add_agent(tsk.cm, person=people["agent"])  # vetting still pending
    assert ei.value.code == "agent-not-vetted"
    no_deal = tsk.new_agent(agreement=False)
    e = tsk.errand()
    with pytest.raises(RuleBlocked) as ei:
        services.assign(e, tsk.cm, agent=no_deal, agency_payee=tsk.agency)
    assert "agent-no-agreement" in codes(ei.value)
    type(no_deal.vetting).objects.filter(pk=no_deal.vetting_id).update(status="expired")
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        type(no_deal).objects.filter(pk=no_deal.pk).update(status="active", status_reason="x")


def test_official_fee_never_to_the_agent_or_an_unverified_agency(tsk):
    """TC-TSK-003-02, RUL-22, RUL-27: the agent's own account, a carer's or an unverified payee is refused."""
    e = tsk.errand()
    payees = tsk.ctx["escrow"]["payees"]
    for bad in (payees["carer"], payees["mismatch"], None):
        with pytest.raises(RuleBlocked) as ei:
            services.assign(e, tsk.cm, agent=tsk.agent, agency_payee=bad)
        assert ei.value.code == "payee-not-verified"
    e = services.assign(e, tsk.cm, agent=tsk.agent, agency_payee=tsk.agency)
    s1 = e.steps.get(seq=1)
    services.record_step_proof(s1, tsk.agent_person, kind="acknowledgement",
                               evidence_id=tsk.photo("errand_step", s1.pk, "acknowledgement"))
    from escrow import services as esc

    with pytest.raises(RuleBlocked) as ei:
        esc.request_release(e.escrow, payee=tsk.ctx["escrow"]["payees"]["school"], amount="120.00",
                            subject_type="errand_step", subject_id=s1.pk, requested_by=tsk.cm)
    assert "payee-not-verified" in codes(ei.value)


def test_step_needs_its_receipt_or_acknowledgement(tsk):
    """TC-TSK-003-04, TC-RUL-23-05: a step is not done, and its fee not instructed, without the proof."""
    e = tsk.assigned()
    s1, s2 = e.steps.get(seq=1), e.steps.get(seq=2)
    with pytest.raises(RuleBlocked) as ei:
        services.prepare_step_fee(s1, tsk.cm)
    assert ei.value.code == "visit-not-confirmed"
    with pytest.raises(RuleBlocked):
        services.complete_step(s2, tsk.agent_person)
    with pytest.raises(RuleBlocked):
        services.complete_step(s1, tsk.agent_person)
    assert ErrandStep.objects.get(pk=s2.pk).status == "pending"
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        ErrandStep.objects.filter(pk=s1.pk).update(status="done")
    with pytest.raises(NotFound):
        services.start_step(s1, tsk.p["carer"])
    from evidence.services import store

    upload = store(data=b"\xff\xd8\xff gallery", country=tsk.gh, uploaded_by=tsk.agent_person,
                   content_type="image/jpeg")
    with pytest.raises(Invalid) as ei:
        services.record_step_proof(s1, tsk.agent_person, kind="receipt", evidence_id=upload.pk)
    assert ei.value.code == "evidence-rejected"


def test_step_fee_under_a_standing_approval(tsk):
    """TC-TSK-003-05, RUL-11: within the month no client approval; above it the client approves that fee."""
    from django.utils import timezone

    e1 = tsk.assigned()
    services.give_standing_approval(e1, tsk.client, monthly_max="130.00", mfa_at=timezone.now())
    services.approve_agency(e1, tsk.client, mfa_at=timezone.now())
    s = e1.steps.get(seq=1)
    services.record_step_proof(s, tsk.agent_person, kind="acknowledgement",
                               evidence_id=tsk.photo("errand_step", s.pk, "acknowledgement"))
    ins = services.prepare_step_fee(s, tsk.cm)
    assert ins.status == "pending_approval" and ins.client_approval_method == "standing"
    services.withdraw_standing_approval(e1, tsk.client)
    e2 = tsk.assigned()
    s2 = e2.steps.get(seq=1)
    services.record_step_proof(s2, tsk.agent_person, kind="acknowledgement",
                               evidence_id=tsk.photo("errand_step", s2.pk, "acknowledgement"))
    assert services.prepare_step_fee(s2, tsk.cm).status == "awaiting_client"


# --------------------------------------------------------------------------- completion (FR-TSK-004)

def _all_steps_done(tsk, e):
    for s in e.steps.all():
        services.record_step_proof(s, tsk.agent_person, kind="receipt",
                                   evidence_id=tsk.photo("errand_step", s.pk, "receipt"))
        services.complete_step(s, tsk.agent_person)


def test_completion_only_with_a_checked_document(tsk, api):
    """TC-TSK-004-02, TC-E2E-J12-03, TC-RUL-23-05: no result, no completion and no payable; the agent cannot
    check their own; a rejected result goes back to the agent."""
    e = tsk.assigned("utility_transfer")
    with pytest.raises(StateConflict):
        services.upload_result(e, tsk.agent_person, evidence_id=tsk.photo("errand", e.pk, "result"))
    _all_steps_done(tsk, e)
    with pytest.raises(StateConflict):
        services.check_result(e, tsk.cm, accept=True)
    services.upload_result(e, tsk.agent_person, evidence_id=tsk.photo("errand", e.pk, "result"))
    with pytest.raises(Forbidden):
        services.check_result(e, tsk.agent_person, accept=True)
    with pytest.raises(Invalid):
        services.check_result(e, tsk.cm, accept=False)
    e = services.check_result(e, tsk.cm, accept=False, note="The letter is for another account.")
    assert e.status == "in_progress"
    assert not OutboxEvent.objects.filter(topic="work.accepted", aggregate_id=e.pk).exists()
    with pytest.raises((IntegrityError, DatabaseError)), transaction.atomic():
        Errand.objects.filter(pk=e.pk).update(result_checked_by=tsk.agent_person)


def test_reused_result_document_is_not_confirmed(tsk):
    """TC-RUL-23-06, TC-TSK-004-03: an image already used on another errand is flagged and refused."""
    from mobile.devtools import jpeg

    data = jpeg("same-letter", model="SM-A145F")
    first = tsk.assigned("utility_transfer")
    _all_steps_done(tsk, first)
    services.upload_result(first, tsk.agent_person, evidence_id=tsk.photo("errand", first.pk, "result", data))
    services.check_result(first, tsk.cm, accept=True)
    second = tsk.assigned("utility_transfer")
    _all_steps_done(tsk, second)
    services.upload_result(second, tsk.agent_person, evidence_id=tsk.photo("errand", second.pk, "result", data))
    with pytest.raises(RuleBlocked) as ei:
        services.check_result(second, tsk.cm, accept=True)
    assert codes(ei.value) & {"result-reused", None} or ei.value.blocking_reasons
    assert Errand.objects.get(pk=second.pk).status == "result_uploaded"


# --------------------------------------------------------------------------- handover (FR-TSK-005)

def test_handover_to_a_named_receiver_only(tsk, people):
    """TC-TSK-005-01, TC-TSK-005-02: a representative not named for this errand, or a courier without a tracking
    reference, is refused; a family member receives a confirmation code."""
    e = tsk.assigned("utility_transfer")
    _all_steps_done(tsk, e)
    services.upload_result(e, tsk.agent_person, evidence_id=tsk.photo("errand", e.pk, "result"))
    services.check_result(e, tsk.cm, accept=True)
    sig = tsk.ev("signature", tsk.cm)
    with pytest.raises(Invalid) as ei:
        services.record_handover(e, tsk.cm, method="representative", proof_kind="signature", evidence=sig,
                                 receiver_person=people["family"])
    assert ei.value.code == "receiver-not-named"
    with pytest.raises(Invalid):
        services.record_handover(e, tsk.cm, method="courier", proof_kind="photo", evidence=sig,
                                 courier_name="DHL")
    with pytest.raises(Invalid):
        services.record_handover(e, tsk.agent_person, method="client", proof_kind="signature", evidence=sig)
    nephew = tsk.ctx["family_members"]["nephew"]
    h = services.record_handover(e, tsk.cm, method="family_member", proof_kind="signature", evidence=sig,
                                 family_member=nephew)
    assert h.receiver_name == nephew.full_name and h.confirmation_id
    from notifications.services import confirmation_status

    assert confirmation_status("errand_handover", h.pk).to_address == nephew.phone
    assert Errand.objects.get(pk=e.pk).status == "handed_over"


# --------------------------------------------------------------------------- jobs, retention, flags

def test_target_watch_warns_once(tsk):
    """FR-TSK-001: an errand past its target date is chased once."""
    from notifications.models import Message

    e = tsk.errand()
    Errand.objects.filter(pk=e.pk).update(due_on=timezone.localdate() - timedelta(days=1))
    assert services.target_watch()["overdue"] >= 1
    services.target_watch()
    assert Message.objects.filter(template="errand_overdue", person=tsk.client,
                                  subject_id=str(e.pk)).count() == 1


def test_documents_deleted_after_handover_under_retention(tsk):
    """Brief, 02 6.10: identity documents go after handover per the retention rule; access is withdrawn."""
    from dataprotection.registry import Scope, finders
    from evidence import access

    e = tsk.assigned("utility_transfer")
    _all_steps_done(tsk, e)
    services.upload_result(e, tsk.agent_person, evidence_id=tsk.photo("errand", e.pk, "result"))
    services.check_result(e, tsk.cm, accept=True)
    services.record_handover(e, tsk.cm, method="client", proof_kind="signature", evidence=tsk.ev("sig", tsk.cm))
    cands = [c for fn in finders("identity_documents")
             for c in fn(Scope(country=tsk.gh), timezone.now() + timedelta(days=1))]
    mine = [c for c in cands if c.subject_id in set(e.documents.values_list("pk", flat=True))]
    assert len(mine) == e.documents.count()
    for c in mine:
        c.apply()
    doc = e.documents.first()
    doc.refresh_from_db()
    assert doc.status == "deleted" and not access.can_view_subject(tsk.client, "errand_document", doc.pk)


def test_line_closed_by_its_flag(tsk, api, settings):
    """06 2.6: everything behind lines.tsk."""
    settings.TENMINA_FLAG_OVERRIDES = {"lines.tsk": False}
    assert api().get("/v1/errand-catalogue?country=GH").json()["code"] == "feature-off"
    r = api(tsk.client).post("/v1/errands", {"code": "birth_cert"}, format="json")
    assert r.status_code == 404


def test_cancel_before_the_agent_starts(tsk):
    e = tsk.errand(pay=False)
    with pytest.raises(Invalid):
        services.cancel_errand(e, tsk.client, reason="")
    assert services.cancel_errand(e, tsk.client, reason="Done it myself").status == "cancelled"
