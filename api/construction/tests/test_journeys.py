"""Full journeys on both routes (FR-BLD-001 to FR-BLD-009, FR-BLD-012; RUL-09, RUL-11, RUL-18)."""
from decimal import Decimal

import pytest
from django.utils import timezone

from construction import milestones, payments, projects
from construction.models import Defect, Inspection, Milestone, Payment, Project
from core.errors import DomainError, RuleBlocked, StateConflict
from core.models import OutboxEvent


def test_client_direct_journey_by_api(b, api, mfa):
    """FR-BLD-005, TC-BLD-005-01, decision 2026-11-12: the launch route. Tenmina checks the stage, the client
    approves, two staff confirm, the client pays the builder's verified account, the builder confirms."""
    p = b.project("client_direct")
    assert p.status == "active" and p.started_at
    assert OutboxEvent.objects.filter(topic="project.started", aggregate_id=p.pk).exists()
    ev = OutboxEvent.objects.filter(topic="project.started", aggregate_id=p.pk).first()
    assert ev.payload["asset_id"] == str(p.asset_id) and ev.payload["project_id"] == str(p.pk)
    cm = api(b.cm)
    r = cm.post(f"/v1/projects/{p.pk}/handover", {}, format="json")
    assert r.status_code == 200, r.content
    mob = b.ms(p, "mobilisation")
    pay = b.pay_for(mob)
    assert pay.status == "awaiting_client" and pay.route == "client_direct"
    client = api(b.client)
    mfa(client, b.client)
    r = client.post(f"/v1/milestones/{mob.pk}/client-approval", {}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "client_approved"
    for who in (b.rv, b.rv2):
        c = api(who)
        mfa(c, who)
        r = c.post(f"/v1/project-payments/{pay.pk}/approvals", {"decision": "approve"}, format="json")
        assert r.status_code == 200, r.content
    r = client.get(f"/v1/project-payments/{pay.pk}")
    assert r.json()["status"] == "release_approved"
    assert r.json()["pay_to"]["account_number"] == pay.payee.account_number
    r = client.post(f"/v1/project-payments/{pay.pk}/client-payments", {"reference": "NWB-1"}, format="json")
    assert r.status_code == 200, r.content
    builder = api(p.contractor.person)
    r = builder.post(f"/v1/project-payments/{pay.pk}/receipt", {}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "paid"
    assert Milestone.objects.get(pk=mob.pk).status == "paid"

    # Foundation from Tenmina Field: evidence checked, inspection with the project inspector, pass with a defect.
    found = b.submit(b.ms(p, "foundation"))
    assert found.status == "submitted"
    r = cm.post(f"/v1/milestones/{found.pk}/evidence-review", {"decision": "accept"}, format="json")
    assert r.status_code == 200, r.content
    found.refresh_from_db()
    assert found.status == "inspection_scheduled"
    found = b.inspect(found, outcome="pass_with_defects", defects=[("Honeycombing at the north footing", "500.00")])
    assert found.status == "inspected"
    pay = b.pay_for(found)
    assert pay.amount == found.amount - Decimal("500.00") and pay.holdback_amount == Decimal("500.00")
    b.settle(b.approve(pay))
    assert Milestone.objects.get(pk=found.pk).status == "paid"
    d = Defect.objects.get(milestone=found)
    r = builder.post(f"/v1/defects/{d.pk}/close", {"evidence_ids": []}, format="json")
    assert r.status_code == 400  # TC-BLD-006-02: never without evidence
    r = builder.post(f"/v1/defects/{d.pk}/close", {"evidence_ids": [str(b.ev("upload", by=p.contractor.person).pk)]},
                     format="json")
    assert r.status_code == 422 and r.json()["code"] == "evidence-rejected"  # RUL-08: app captures only
    proof = b.capture(p.contractor.person, "defect", d.pk)
    r = builder.post(f"/v1/defects/{d.pk}/close", {"evidence_ids": [str(proof.pk)]}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "fixed"
    assert b.pay_for(found, "defect_holdback") is None
    r = api(p.inspector.person).post(f"/v1/defects/{d.pk}/confirmation", {"confirm": True}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "closed"
    hold = b.pay_for(found, "defect_holdback")
    assert hold.amount == Decimal("500.00") and hold.status == "awaiting_client"
    b.settle(b.approve(hold))
    assert hold.status == "paid"

    dash = client.get(f"/v1/projects/{p.pk}/dashboard").json()
    assert Decimal(dash["paid"]["amount"]) == mob.amount + found.amount
    assert dash["defect_value_held"]["amount"] == "0.00"
    assert any(i["outcome"] == "pass_with_defects" for i in dash["inspections"])
    assert dash["photo_timeline"]
    assert api(b.p["client2"]).get(f"/v1/projects/{p.pk}/dashboard").status_code == 404  # TC-BLD-009-02


def test_escrow_journey(b):
    """FR-ESC-010, FR-BLD-005: the escrow route. The bank holds the money and pays the contractor per milestone."""
    p = b.project("escrow")
    assert p.status == "active" and p.escrow.kind == "construction"
    pay = b.mobilise(p)
    assert pay.status == "paid" and pay.instruction.status == "confirmed"
    assert b.ms(p, "mobilisation").status == "paid"
    found = b.to_inspected(p)
    pay = b.pay_for(found)
    assert pay.instruction.status == "awaiting_client"
    # TC-RUL-11-05: staff cannot approve before the client; reminders never approve.
    with pytest.raises(RuleBlocked):
        payments.staff_decide(pay, b.rv, mfa_at=timezone.now())
    pay.created_at = timezone.now() - timezone.timedelta(days=10)
    pay.save(update_fields=["created_at"])
    assert milestones.remind_clients() >= 1
    assert Milestone.objects.get(pk=found.pk).status == "inspected"
    milestones.client_approve(found, b.client, mfa_at=timezone.now())
    assert OutboxEvent.objects.filter(topic="milestone.client_approved", aggregate_id=found.pk).exists()
    pay = b.approve(pay, client=False)
    assert Milestone.objects.get(pk=found.pk).status == "release_approved"
    b.settle(pay)
    assert Milestone.objects.get(pk=found.pk).status == "paid"


def test_bank_release_needs_bld(b, codes):
    """RUL-09 via escrow.registry: a milestone instruction on a BLD escrow is prepared only from the project."""
    from escrow import services as esc

    p = b.project("escrow")
    with pytest.raises(RuleBlocked) as ei:
        esc.request_release(p.escrow, payee=p.contractor.payee, amount="5000.00", subject_type="milestone",
                            subject_id=b.ms(p, "foundation").pk, requested_by=b.cm)
    assert "milestone-unknown" in codes(ei.value)


def test_reprice_shown_and_reapproved(b, api, mfa):
    """RUL-18, TC-RUL-18-01, TC-RUL-18-03: a new guide rate re-prices the milestone; the client confirms the new
    amount; an approval given at the old rate is withdrawn."""
    from administration.services import set_fx_rate

    p = b.project("client_direct")
    b.mobilise(p)
    found = b.to_inspected(p)
    old = b.pay_for(found)
    set_fx_rate(country=b.gh, base="USD", quote="GHS", rate="16.72", by=b.p["admin"])
    old.refresh_from_db()
    assert old.status == "withdrawn"
    new = Payment.objects.get(milestone=found, part="main", status="awaiting_client")
    assert new.amount > old.amount and new.reprice.changed
    client = api(b.client)
    mfa(client, b.client)
    r = client.post(f"/v1/milestones/{found.pk}/client-approval", {}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "amount-changed"
    r = client.post(f"/v1/milestones/{found.pk}/client-approval",
                    {"confirm_amount": {"amount": f"{new.amount:.2f}", "currency": "GHS"}}, format="json")
    assert r.status_code == 200, r.content
    # The rate changes again before the staff approve: the client's approval is invalidated.
    set_fx_rate(country=b.gh, base="USD", quote="GHS", rate="16.10", by=b.p["admin"])
    new.refresh_from_db()
    assert new.status == "withdrawn"
    assert Milestone.objects.get(pk=found.pk).status == "inspected"


def test_reprice_stale_blocks(b, codes, monkeypatch):
    """TC-RUL-18-02: a re-price on a guide rate older than the configured age blocks the release."""
    p = b.project("client_direct")
    b.mobilise(p)
    found = b.to_inspected(p)
    pay = b.pay_for(found)
    import construction.pricing as pricing

    later = timezone.localdate() + timezone.timedelta(days=30)
    monkeypatch.setattr(pricing, "today", lambda country=None: later)
    reasons = payments.blockers(Payment.objects.get(pk=pay.pk), "client")
    assert "reprice-stale" in {r["code"] for r in reasons}


def test_fail_returns_and_defects_over_value(b):
    """TC-STM-MIL-08: a fail returns the milestone; TC-RUL-09-04: defects worth the milestone go to a reviewer."""
    p = b.project("client_direct")
    b.mobilise(p)
    m = b.to_inspected(p, outcome="fail")
    assert m.status == "returned" and m.return_reasons
    m = b.submit(m)
    assert m.status == "submitted" and m.submissions == 2
    milestones.review_evidence(m, b.cm, decision="accept")
    m = b.inspect(b.ms(p, "foundation"), outcome="pass_with_defects",
                  defects=[("Footing must be broken out", f"{b.ms(p, 'foundation').amount:.2f}")])
    assert m.status == "inspected"
    assert Inspection.objects.filter(milestone=m, needs_review=True).exists()
    assert b.pay_for(m) is None


def test_retention_waits_for_defects_period(b, monkeypatch):
    """FR-BLD-012, TC-BLD-012-02: the retention is held until the defects period ends with no open defect."""
    p = b.project("client_direct")
    monkeypatch.setattr(milestones, "_previous_passed", lambda m: True)
    ret = b.ms(p, "retention")
    ok, why = milestones.submission_state(ret)
    assert not ok
    Project.objects.filter(pk=p.pk).update(defects_period_ends_on=timezone.localdate() + timezone.timedelta(days=5))
    assert "defects period" in milestones.submission_state(Milestone.objects.get(pk=ret.pk))[1]


def test_extra_inspection_on_order_paid(b):
    """FR-ORD-007: an extra inspection ordered by the client is created and given to the project's inspector."""
    from core.events import publish

    p = b.project("client_direct")
    publish("order.paid", None, {"order_id": "0192f3c1-0000-7000-8000-00000000e001", "kind": "extra_inspection",
                                 "subject_type": "project", "subject_id": str(p.pk),
                                 "details": {"concern": "Cracks after the rains"}})
    i = Inspection.objects.get(project=p, kind="extra")
    assert i.inspector_id == p.inspector_id and i.concern == "Cracks after the rains" and i.scheduled_for


def test_dispute_freezes_and_lifts(b):
    """TC-STM-MIL-13, TC-STM-MIL-14: a dispute freezes every unpaid milestone; resolution restores them."""
    from core.events import publish

    p = b.project("client_direct")
    publish("dispute.opened", None, {"dispute_id": "0192f3c1-0000-7000-8000-00000000d001", "project_id": str(p.pk)})
    assert set(p.milestones.values_list("status", flat=True)) == {"frozen"}
    publish("dispute.resolved", None, {"dispute_id": "0192f3c1-0000-7000-8000-00000000d001",
                                       "project_id": str(p.pk)})
    assert set(p.milestones.values_list("status", flat=True)) == {"not_started"}


def test_inbox_for_field_roles(b, api):
    """FR-MOB-001: the contractor sees the next milestone; the inspector sees the inspection and the
    independence statement."""
    from mobile import inbox

    p = b.project("client_direct")
    b.mobilise(p)
    keys = {i.subject_id for i in inbox.items_for(p.contractor.person)}
    assert str(b.ms(p, "foundation").pk) in keys and str(b.ms(p, "blocks").pk) not in keys
    m = b.submit(b.ms(p, "foundation"))
    milestones.review_evidence(m, b.cm, decision="accept")
    items = [i for i in inbox.items_for(p.inspector.person) if i.subject_type == "milestone_inspection"]
    assert items and items[0].details["independence"] == "You have no link to this contractor."


def test_materials_order(b):
    """FR-BLD-013 (R3): the supplier is paid after the client and two staff approve; delivery needs app photos."""
    from construction import materials
    from escrow.models import Payee

    p = b.project("client_direct")
    supplier = Payee.objects.filter(country=b.gh, kind="supplier", verification_status="verified").first()
    if supplier is None:
        pytest.skip("No verified supplier payee in the seed")
    o = materials.request_materials(p, b.cm, milestone_id=b.ms(p, "blocks").pk, supplier_payee_id=supplier.pk,
                                    description="4,000 sandcrete blocks", amount="18000.00",
                                    quote_evidence_ids=[b.ev("quote").pk])
    pay = Payment.objects.get(subject_id=o.pk)
    b.settle(b.approve(pay))
    o.refresh_from_db()
    assert o.status == "paid"
    with pytest.raises(DomainError):
        materials.record_delivery(o, b.cm, evidence_ids=[b.ev("delivery", kind="image/jpeg").pk])


def test_mobilisation_rules(b, api, codes):
    """RUL-09 exception, TC-RUL-09-06: mobilisation needs the signed contract and a staff member's site
    handover; the contractor cannot confirm it."""
    p = b.project("client_direct")
    r = api(p.contractor.person).post(f"/v1/projects/{p.pk}/handover", {}, format="json")
    assert r.status_code in (403, 404)
    with pytest.raises(StateConflict):
        milestones.prepare_main(b.ms(p, "foundation"), b.cm)  # not inspected
    q = b.project("client_direct", start=False)
    with pytest.raises(DomainError):
        projects.confirm_handover(q, b.cm)
