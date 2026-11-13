"""Project funds (FR-PRJ-001 to FR-PRJ-005; RUL-21, RUL-22)."""
import uuid

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from construction import milestones
from construction.models import Payment, Project
from construction.tests.helpers import Builder
from core.errors import DomainError, RuleBlocked, SameApprover, StateConflict
from core.models import OutboxEvent
from projectfunds import services
from projectfunds.models import NO_ADVICE_STATEMENT, Agreement, AmlReview, BackgroundCheck, Invoice, Supplier
from projectfunds.seed import _supplier_payee, complete_case


@pytest.fixture
def b(seeded):
    return Builder(seeded)


def _new(b, budget="40000.00", stages=None, suppliers=None, route="client_direct"):
    return services.create_fund_project(b.cm, {
        "country": b.gh, "client": b.p["client2"], "title": f"Fund {uuid.uuid4().hex[:6]}", "budget": budget,
        "payment_route": route, "runner": {"name": "Yaw Runner", "phone": "+233244999001"},
        "stages": stages or [{"name": "Stage one", "amount": "25000.00", "visit_required": False},
                             {"name": "Stage two", "amount": f"{float(budget) - 25000:.2f}"}],
        "suppliers": suppliers if suppliers is not None else [
            {"name": f"Supplier {uuid.uuid4().hex[:6]} Ltd", "contact_name": "Ama Supplier",
             "contact_phone": "+233244999002", "bank_name": "Demo Bank", "account_number": "1100" +
             str(uuid.uuid4().int)[:9]}]})


def _ready(b, p):
    """Every check passed, the agreement accepted: the project starts on the launch route."""
    services.accept_agreement(p, p.client)
    for chk in services.start_checks(p, b.cm, runner_id_number="GHA-700000051-6"):
        chk.refresh_from_db()
        if chk.subject_kind == "supplier":
            complete_case(chk.case_id, b.gh, b.p)
    runner = BackgroundCheck.objects.get(project=p, subject_kind="runner")
    services.record_runner_check(runner, b.rv if runner.level == "enhanced" else b.cm, outcome="passed",
                                 evidence=b.ev("background"))
    for s in Supplier.objects.filter(project=p, status="passed"):
        _supplier_payee(s, b.gh, b.p, "GHA-700000052-7")
    p.refresh_from_db()
    return p


def test_create_by_api_and_stage_total(b, api):
    """TC-PRJ-001-01, US-PRJ-001 AC1 and AC2: stages must total the budget; a supplier without bank details is
    flagged incomplete."""
    c = api(b.p["client2"])
    body = {"type": "funds", "title": "Family shop", "country": "GH",
            "budget": {"amount": "20000.00", "currency": "GHS"},
            "stages": [{"name": "Shelves", "amount": "5000.00"}, {"name": "Stock", "amount": "10000.00"}],
            "runner": {"name": "Kwesi Boateng"}, "suppliers": [{"name": "Adum Wholesale"}]}
    r = c.post("/v1/projects", body, format="json")
    assert r.status_code == 422 and r.json()["code"] == "stages-not-budget"
    body["stages"][1]["amount"] = "15000.00"
    r = c.post("/v1/projects", body, format="json")
    assert r.status_code == 201, r.content
    pid = r.json()["id"]
    assert len(r.json()["milestones"]) == 2
    sups = c.get(f"/v1/projects/{pid}/suppliers").json()
    assert sups[0]["status"] == "incomplete" and sups[0]["missing"]
    r = c.patch(f"/v1/project-suppliers/{sups[0]['id']}", {"contact_phone": "+233244100100", "bank_name": "B",
                                                           "account_number": "11002233445"}, format="json")
    assert r.json()["status"] == "pending_check"


def test_no_advice_statement(b, api):
    """TC-PRJ-005-01, TC-PRJ-005-02: every agreement carries the statement; the database refuses one without it
    and refuses a changed text."""
    p = _new(b)
    r = api(p.client).get(f"/v1/projects/{p.pk}/agreement")
    assert NO_ADVICE_STATEMENT in r.json()["text"]
    with pytest.raises(DatabaseError), transaction.atomic():
        Agreement.objects.create(country=b.gh, project=p, version=9, text="An agreement with no statement.",
                                 text_sha256="0" * 64)
    with pytest.raises(DatabaseError), transaction.atomic():
        Agreement.objects.filter(project=p).update(text=f"{NO_ADVICE_STATEMENT} edited")


def test_funding_blocked_until_checked(b, api):
    """TC-PRJ-002-01, US-PRJ-002 AC1: unchecked suppliers or runner: no funding."""
    p = _new(b)
    r = api(b.cm).post(f"/v1/projects/{p.pk}/funding", {}, format="json")
    assert r.status_code == 409
    codes = {x["code"] for x in r.json()["blocking_reasons"]}
    assert {"supplier-unchecked", "runner-unchecked", "agreement-not-accepted"} <= codes
    p = _ready(b, p)
    assert p.status == "active"  # US-PRJ-002 AC2


def test_failed_supplier(b):
    """TC-PRJ-002-02: a failed supplier is blocked and the client told to replace it."""
    p = _new(b)
    services.start_checks(p, b.cm)
    s = Supplier.objects.get(project=p)
    complete_case(s.check_case_id, b.gh, b.p, outcome="not_verified", note="Not registered")
    s.refresh_from_db()
    assert s.status == "failed"
    assert OutboxEvent.objects.filter(topic="supplier.checked", aggregate_id=s.pk).exists()
    assert "supplier-unchecked" in {r["code"] for r in services.funding_blockers(p)}


def test_runner_is_never_a_supplier(b):
    """TC-RUL-21-02: the person running the project cannot be named as a supplier."""
    p = _new(b)
    with pytest.raises(RuleBlocked) as ei:
        services.add_supplier(p, p.client, {"name": "Yaw Runner", "contact_phone": "+233200000000"})
    assert "runner-not-payee" in {r["code"] for r in ei.value.blocking_reasons}
    with pytest.raises(RuleBlocked):
        services.add_supplier(p, p.client, {"name": "Other Name", "contact_phone": "+233244999001"})


def test_invoice_journey_and_duplicates(b, api, mfa):
    """TC-PRJ-003-01, TC-RUL-21-01, TC-RUL-21-04: a checked supplier is paid against an accepted invoice once
    the stage is confirmed; the same invoice is never paid twice."""
    p = _ready(b, _new(b))
    stage = p.milestones.get(seq=0)
    s = Supplier.objects.get(project=p)
    cm = api(b.cm)
    r = cm.post(f"/v1/projects/{p.pk}/invoices", {
        "supplier_id": str(s.pk), "milestone_id": str(stage.pk), "number": "INV-1",
        "amount": {"amount": "25000.00", "currency": "GHS"}, "evidence_ids": [str(b.ev("inv").pk)]}, format="json")
    assert r.status_code == 201, r.content
    inv_id = r.json()["id"]
    r = cm.post(f"/v1/projects/{p.pk}/invoices", {
        "supplier_id": str(s.pk), "milestone_id": str(stage.pk), "number": "INV-1",
        "amount": {"amount": "25000.00", "currency": "GHS"}, "evidence_ids": [str(b.ev("inv").pk)]}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "invoice-duplicate"
    r = cm.post(f"/v1/project-invoices/{inv_id}/decision", {"decision": "accept"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "accepted"
    assert OutboxEvent.objects.filter(topic="invoice.accepted", aggregate_id=inv_id).exists()
    assert not Payment.objects.filter(subject_id=inv_id).exists()  # the stage is not confirmed yet
    milestones.submit_stage_evidence(stage, p.client, evidence_ids=[b.ev("receipts", by=p.client).pk])
    milestones.review_evidence(stage, b.cm, decision="accept")
    milestones.confirm_stage(stage, b.cm)
    pay = Payment.objects.get(subject_id=inv_id)
    assert pay.status == "awaiting_client" and pay.payee_id == s.payee_id
    client = api(p.client)
    mfa(client, p.client)
    r = client.post(f"/v1/project-payments/{pay.pk}/client-approval", {}, format="json")
    assert r.status_code == 200, r.content
    b.settle(b.approve(Payment.objects.get(pk=pay.pk), client=False))
    inv = Invoice.objects.get(pk=inv_id)
    assert inv.status == "paid"
    assert p.milestones.get(seq=0).status == "paid"  # every invoice on the stage paid


def test_invoice_blockers(b, codes):
    """TC-RUL-21-03, US-PRJ-003 AC3: an unchecked supplier or an unconfirmed stage blocks the payment."""
    p = _new(b)
    stage = p.milestones.get(seq=1)
    s = Supplier.objects.get(project=p)
    inv = services.submit_invoice(p, b.cm, supplier_id=s.pk, milestone_id=stage.pk, number="X-1", amount="100.00",
                                  evidence_ids=[b.ev("inv").pk])
    with pytest.raises(RuleBlocked) as ei:
        services.decide_invoice(inv, b.cm, decision="accept")
    assert "supplier-unchecked" in codes(ei.value)
    # A stage with a visit configured is not confirmed at the desk.
    with pytest.raises(DomainError):
        milestones.confirm_stage(stage, b.cm)


def test_aml_threshold(b):
    """TC-PRJ-004-01: above the threshold the enhanced check is required and approved by a different person;
    below it is not."""
    small = _new(b, budget="40000.00")
    assert not AmlReview.objects.filter(project=small).exists()
    big = _new(b, budget="400000.00", stages=[{"name": "Build", "amount": "400000.00"}])
    r = AmlReview.objects.get(project=big)
    assert r.status == "required"
    assert "aml-review-open" in {x["code"] for x in services.funding_blockers(big)}
    services.prepare_aml(big, b.cm, source_of_funds="Salary savings in the UK", purpose="Church building",
                         evidence_ids=[b.ev("payslips").pk])
    r.refresh_from_db()
    with pytest.raises(SameApprover):
        services.decide_aml(r, b.cm, decision="approve")
    services.decide_aml(r, b.rv, decision="approve")
    assert AmlReview.objects.get(pk=r.pk).status == "approved"


def test_scoping(b, api):
    """Clients see only their own projects; background checks are staff only."""
    p = _new(b)
    assert api(b.client).get(f"/v1/projects/{p.pk}/suppliers").status_code == 404
    assert api(p.client).get(f"/v1/projects/{p.pk}/background-checks").status_code == 404
    assert api(b.cm).get(f"/v1/projects/{p.pk}/background-checks").status_code == 200
    _ = timezone, StateConflict, Project


def test_client_uploads_an_invoice_file_and_submits_it(b, api):
    """FR-PRJ-003, RUL-21: the client stores the invoice file against a named supplier, then submits the
    invoice with it; another client cannot attach files to that supplier."""
    import hashlib

    p = _ready(b, _new(b))
    s = Supplier.objects.get(project=p)
    stage = p.milestones.get(seq=0)
    data = b"%PDF-1.4 invoice"
    slot = {"subject_type": "prj_supplier", "subject_id": str(s.pk), "role": "invoice", "content_type": "application/pdf",
            "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "original_name": "inv.pdf"}
    assert api(b.client).post("/v1/uploads", slot, format="json").status_code == 404
    c = api(p.client)
    r = c.post("/v1/uploads", slot, format="json")
    assert r.status_code == 201, r.content
    ev = c.put(f"/v1/uploads/{r.json()['id']}/content", data=data, content_type="application/pdf")
    assert ev.status_code == 201, ev.content
    r = c.post(f"/v1/projects/{p.pk}/invoices", {
        "supplier_id": str(s.pk), "milestone_id": str(stage.pk), "number": "INV-C1",
        "amount": {"amount": "1000.00", "currency": "GHS"}, "evidence_ids": [ev.json()["id"]]}, format="json")
    assert r.status_code == 201, r.content
