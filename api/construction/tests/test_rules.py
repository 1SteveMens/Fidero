"""Each rule's refusal path (FR-BLD-001 to FR-BLD-011; RUL-09, RUL-10, RUL-19, RUL-20, RUL-22)."""
import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from construction import milestones, panel, projects
from construction.models import Milestone, PanelMember, Payment, Project
from core.errors import DomainError, Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.models import OutboxEvent


def test_unverified_plot_is_refused(b, codes):
    """TC-BLD-001-02, US-BLD-001 AC2: no released green or amber report, no project."""
    from geo.models import Asset

    plot = Asset.objects.filter(owner=b.client).exclude(pk=b.asset().pk).first()
    with pytest.raises(RuleBlocked) as ei:
        projects.create_project(b.client, type="construction", title="Unchecked plot", asset_id=plot.pk,
                                budget="50000.00")
    assert ei.value.code == "asset-not-verified"


def test_project_api_create(b, api):
    """TC-BLD-001-01: a project on a verified plot is created and linked to the report."""
    r = api(b.client).post("/v1/projects", {"type": "construction", "title": "My house",
                                            "asset_id": str(b.asset().pk),
                                            "budget": {"amount": "250000.00", "currency": "GHS"}}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["report_id"] == str(b.ctx["report"].pk)
    assert r.json()["payment_route"] == "client_direct"
    assert r.json()["status"] == "setup"


def test_split_must_total_100_and_only_qs(b, api):
    """TC-BLD-002-02: shares not totalling 100% are refused; a contractor cannot set the split."""
    p = b.project(start=False, inspector=None)
    Project.objects.filter(pk=p.pk).update(budget_approved_at=None)
    p.refresh_from_db()
    bad = [{"key": "a", "name": "A", "share_pct": "60"}, {"key": "b", "name": "B", "share_pct": "35"}]
    with pytest.raises(Invalid) as ei:
        projects.submit_boq(p, b.p["qs"], items=[{"description": "x", "amount": "100.00"}],
                            evidence_ids=[b.ev("boq", by=b.p["qs"]).pk], split=bad)
    assert ei.value.code == "split-not-100"
    r = api(p.contractor.person).post(f"/v1/projects/{p.pk}/boq", {
        "items": [{"description": "x", "amount": "100.00"}], "evidence_ids": [str(b.ev("x").pk)]}, format="json")
    assert r.status_code in (403, 404)


def test_split_locked_after_budget_approval(b):
    """US-BLD-002 AC3: once the client approves the budget the split is locked."""
    p = b.project(start=False)
    with pytest.raises(StateConflict):
        projects.submit_boq(p, b.p["qs"], items=[{"description": "x", "amount": "100.00"}],
                            evidence_ids=[b.ev("boq", by=b.p["qs"]).pk])


def test_inactive_contractor_not_offered(b, api):
    """TC-BLD-003-02: a pending or suspended contractor is not offered and cannot be chosen."""
    names = {m["name"] for m in api(b.client).get("/v1/panel-members?kind=contractor").json()["items"]}
    assert "Mensah Construction (demo)" in names and "Adom Builders (demo)" not in names
    p = b.project(start=False, inspector=None)
    Project.objects.filter(pk=p.pk).update(contractor=None)
    with pytest.raises(RuleBlocked) as ei:
        projects.choose_contractor(Project.objects.get(pk=p.pk), b.client, b.panel["adom"].pk)
    assert ei.value.code == "panel-not-active"


def test_panel_approval_needs_vetting(b, api):
    """TC-BLD-003-01: active only after the checks; RUL-20: an inspector without a verified licence stays out."""
    with pytest.raises(RuleBlocked) as ei:
        panel.approve(b.m("kwesi"), b.p["admin"])
    assert "RUL-20" in {r["rule"] for r in ei.value.blocking_reasons}
    r = api(b.p["admin"]).post(f"/v1/panel-members/{b.panel['adom'].pk}/approval", {}, format="json")
    assert r.status_code == 409


def test_conflicted_inspector_blocked(b, api, codes):
    """TC-RUL-10-01, TC-RUL-10-02: an inspector with a recorded link to the contractor is never assigned."""
    p = b.project("client_direct", contractor="kobby", inspector=None, start=False)
    with pytest.raises(RuleBlocked) as ei:
        projects.assign_inspector(p, b.cm, b.panel["asare"].pk)
    assert ei.value.code == "inspector-conflicted"
    r = api(b.cm).post(f"/v1/projects/{p.pk}/inspector-assignments", {"member_id": str(b.panel["esi"].pk)},
                       format="json")
    assert r.status_code == 200, r.content


def test_contractor_cannot_choose_inspector(b, api):
    """TC-RUL-10-03: a contractor has no way to choose or change the inspector."""
    p = b.project("client_direct", inspector=None, start=False)
    r = api(p.contractor.person).post(f"/v1/projects/{p.pk}/inspector-assignments",
                                      {"member_id": str(b.panel["esi"].pk)}, format="json")
    assert r.status_code == 403


def test_database_refuses_conflicted_inspector(b):
    """RUL-10 again in PostgreSQL (trigger bld_no_conflicted_inspector)."""
    p = b.project("client_direct", contractor="kobby", inspector=None, start=False)
    with pytest.raises(DatabaseError), transaction.atomic():
        Project.objects.filter(pk=p.pk).update(inspector=b.panel["asare"])


def test_mobilisation_shortcut_only_for_milestone_0(b):
    """TC-RUL-09-07, TC-STM-MIL-16: only milestone 0 jumps to client approved (the database checks it too)."""
    p = b.project("client_direct")
    found = b.ms(p, "foundation")
    with pytest.raises(DatabaseError), transaction.atomic():
        Milestone.objects.filter(pk=found.pk).update(status="client_approved")


def test_steps_cannot_be_skipped(b, api, mfa):
    """TC-BLD-005-02, TC-BLD-005-03, TC-STM-MIL-17, TC-STM-MIL-21."""
    p = b.project("client_direct")
    found = b.ms(p, "foundation")
    client = api(b.client)
    mfa(client, b.client)
    assert client.post(f"/v1/milestones/{found.pk}/client-approval", {}, format="json").status_code == 409
    cm = api(b.cm)
    r = cm.post(f"/v1/milestones/{found.pk}/inspections", {"inspector_id": str(b.panel["esi"].pk),
                                                          "scheduled_for": "2026-12-01"}, format="json")
    assert r.status_code == 409
    b.mobilise(p)
    found = b.submit(b.ms(p, "foundation"))
    Project.objects.filter(pk=p.pk).update(inspector=None)
    milestones.review_evidence(found, b.cm, decision="accept")
    r = cm.post(f"/v1/milestones/{found.pk}/inspections", {"inspector_id": str(b.panel["esi"].pk)}, format="json")
    assert r.status_code == 422  # no date
    r = cm.post(f"/v1/milestones/{found.pk}/inspections", {"inspector_id": str(b.panel["asare"].pk),
                                                          "scheduled_for": "2026-12-01"}, format="json")
    assert r.status_code == 200 or r.status_code == 201 or r.json()["code"] == "inspector-conflicted"


def test_inspection_recorded_only_by_assigned_inspector(b):
    """TC-STM-MIL-19: an unassigned inspector's result is refused."""
    p = b.project("client_direct")
    b.mobilise(p)
    found = b.submit(b.ms(p, "foundation"))
    milestones.review_evidence(found, b.cm, decision="accept")
    from construction.models import Inspection

    i = Inspection.objects.get(milestone=found, status="scheduled")
    with pytest.raises(Forbidden):
        milestones._require_recordable(i, b.panel["asare"].person_id)


def test_variation_agreed_by_both(b, api):
    """TC-RUL-19-01: a variation is recorded with both agreements, its cost and time; the budget follows."""
    p = b.project("client_direct")
    blocks = b.ms(p, "blocks")
    r = api(p.contractor.person).post(f"/v1/projects/{p.pk}/variations", {
        "milestone_id": str(blocks.pk), "description": "Extra window", "time_effect_days": 2,
        "cost_change": {"amount": "1500.00", "currency": "GHS"}}, format="json")
    assert r.status_code == 201, r.content
    vid = r.json()["id"]
    assert r.json()["status"] == "proposed" and r.json()["contractor_agreed_at"]
    r = api(b.client).post(f"/v1/variations/{vid}/agreements", {"decision": "agree"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "agreed" and r.json()["agreement_evidence_id"]
    assert Milestone.objects.get(pk=blocks.pk).amount == blocks.amount + 1500
    assert Project.objects.get(pk=p.pk).budget_amount == p.budget_amount + 1500


def test_unagreed_variation_flags_submission(b, codes):
    """TC-RUL-19-02: work submitted with an unagreed variation is flagged; only a reviewer accepts it."""
    p = b.project("client_direct")
    b.mobilise(p)
    found = b.ms(p, "foundation")
    projects.propose_variation(p, p.contractor.person, milestone_id=found.pk, description="Deeper footings",
                               cost_change="3000.00")
    found = b.submit(found)
    assert any(c["kind"] == "unagreed_variation" for c in found.concerns)
    with pytest.raises(Forbidden):
        milestones.review_evidence(found, b.cm, decision="accept")
    with pytest.raises(Invalid):
        milestones.review_evidence(found, b.rv, decision="accept")
    milestones.review_evidence(found, b.rv, decision="accept", note="Footings as drawn; extra depth not paid.")
    assert Milestone.objects.get(pk=found.pk).status == "inspection_scheduled"


def test_removal_needs_reviewer_and_freezes(b, api):
    """TC-BLD-010-01, TC-BLD-010-02: only a reviewer removes a contractor; their releases freeze."""
    p = b.project("client_direct")
    b.mobilise(p)
    found = b.to_inspected(p)
    pay = b.pay_for(found)
    r = api(b.cm).post(f"/v1/panel-members/{p.contractor_id}/removals", {"finding": "Photos of another site"},
                       format="json")
    assert r.status_code == 403
    r = api(b.rv).post(f"/v1/panel-members/{p.contractor_id}/removals", {"finding": "Photos of another site"},
                       format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "removed"
    assert Project.objects.get(pk=p.pk).status == "paused"
    assert Milestone.objects.get(pk=found.pk).status == "frozen"
    assert Payment.objects.get(pk=pay.pk).status == "withdrawn"
    assert OutboxEvent.objects.filter(topic="contractor.removed", aggregate_id=p.contractor_id).exists()


def test_offplan_needs_verified_developer(b, codes):
    """TC-BLD-011-02, US-BLD-011a: an off-plan escrow cannot open until the developer's check is verified."""
    p = b.ctx["construction"]["offplan"]
    p = Project.objects.get(pk=p.pk)
    assert p.offplan_case_id
    assert "developer-not-verified" in {r["code"] for r in projects.start_blockers(p)}
    Project.objects.filter(pk=p.pk).update(payment_route="escrow")
    with pytest.raises(DomainError):
        projects.open_escrow(Project.objects.get(pk=p.pk), b.cm)


def test_other_client_sees_nothing(b, api):
    """TC-BLD-009-02 and scoping: clients see only their own projects; field roles only their work."""
    p = b.project("client_direct")
    assert api(b.p["client2"]).get(f"/v1/projects/{p.pk}").status_code == 404
    assert api(b.p["runner"]).get(f"/v1/milestones?project_id={p.pk}").json()["items"] == []
    assert api(p.contractor.person).get(f"/v1/projects/{p.pk}").status_code == 200


def test_declared_link_moves_inspection(b, api):
    """RUL-10: an inspector who declares a link is taken off the work and the link is recorded."""
    from construction.models import ConflictLink, Inspection

    p = b.project("client_direct")
    b.mobilise(p)
    found = b.submit(b.ms(p, "foundation"))
    milestones.review_evidence(found, b.cm, decision="accept")
    i = Inspection.objects.get(milestone=found, status="scheduled")
    r = api(i.inspector.person).post(f"/v1/inspections/{i.pk}/declaration", {"has_link": True,
                                                                            "reason": "My cousin"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert ConflictLink.objects.filter(inspector=i.inspector, contractor=p.contractor).exists()
    assert Milestone.objects.get(pk=found.pk).status == "evidence_checked"


def test_mobilisation_without_handover_blocked(b, codes):
    """TC-RUL-09-06: no release of mobilisation without a staff member's site handover."""
    from construction import payments

    p = b.project("client_direct")
    mob = b.ms(p, "mobilisation")
    with pytest.raises(RuleBlocked) as ei:
        payments.prepare(p, part="main", subject_type="milestone", subject_id=mob.pk, payee=p.contractor.payee,
                         amount=mob.amount, by=b.cm, milestone=mob)
    assert "handover-unconfirmed" in codes(ei.value)
    _ = timezone, NotFound, PanelMember
