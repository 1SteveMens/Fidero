"""Expenses, payment runs, reconciliation and statements (US-PRO-004 to US-PRO-007, US-PRO-009, US-PRO-010)."""
import hashlib
import os
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from core.errors import Forbidden, SameApprover, StateConflict


# ------------------------------------------------------------------ expenses (US-PRO-004)

def test_expense_within_limit_one_approval(pro, api):
    """US-PRO-004 AC1, TC-PRO-004-01: a claim with a receipt within the limit joins the next run on one approval."""
    receipt = pro.ev("receipt", by=pro.runner)
    r = api(pro.runner).post("/v1/me/pro/expense-claims", {
        "kind": "approved_cost", "description": "Fares to site", "amount": "60.00",
        "incurred_on": str(timezone.localdate()), "receipt_evidence_id": str(receipt.pk)}, format="json")
    assert r.status_code == 201, r.content
    cid = r.json()["id"]
    assert r.json()["needs_second_approval"] is False and r.json()["limit"]["amount"] == "300.00"
    r = api(pro.cm).post(f"/v1/pro/expense-claims/{cid}/decisions", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_expense_exception_needs_second_staff(pro, api, mfa):
    """US-PRO-004 AC2, TC-RUL-27-06, TC-PRO-004-02: no receipt (or over the limit) needs a second, different staff
    approval; the first approver cannot give it; until then it stays out of a run."""
    from profpay import services

    c = services.submit_claim(pro.runner, kind="approved_cost", description="Search fee, no receipt",
                              amount="250.00", incurred_on=timezone.localdate())
    over = services.submit_claim(pro.runner, kind="approved_cost", description="Big cost", amount="900.00",
                                 incurred_on=timezone.localdate(), receipt_evidence=pro.ev("big", by=pro.runner))
    assert c.needs_second_approval and over.needs_second_approval
    cm = api(pro.cm)
    assert cm.post(f"/v1/pro/expense-claims/{c.pk}/decisions", {"decision": "approve"},
                   format="json").json()["status"] == "submitted"
    mfa(cm, pro.cm)
    r = cm.post(f"/v1/pro/expense-claims/{c.pk}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    pro.clear_pending_runs()
    run = services.prepare_run(pro.cm, country=pro.gh)
    assert any(x["id"] == str(c.pk) and x["kind"] == "expense" for x in run.excluded)
    rv = api(pro.rv)
    mfa(rv, pro.rv)
    r = rv.post(f"/v1/pro/expense-claims/{c.pk}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved", r.content


def test_expense_reused_receipt_and_self_approval(pro):
    """US-PRO-004 AC3, AC4, TC-PRO-004-03: a receipt already on a claim is refused; a claimant never approves their
    own claim."""
    from profpay import services

    receipt = pro.ev("dup", by=pro.runner)
    c = services.submit_claim(pro.runner, kind="approved_cost", description="Taxi", amount="20.00",
                              incurred_on=timezone.localdate(), receipt_evidence=receipt)
    with pytest.raises(StateConflict) as e:
        services.submit_claim(pro.runner, kind="approved_cost", description="Taxi again", amount="20.00",
                              incurred_on=timezone.localdate(), receipt_evidence=receipt)
    assert e.value.code == "receipt-reused"
    with pytest.raises(SameApprover):
        services.decide_claim(c, pro.runner, decision="approve")
    with pytest.raises(Forbidden):
        services.submit_claim(pro.p["client"], kind="travel", description="x", amount="1.00",
                              incurred_on=timezone.localdate())


def test_expense_must_name_assigned_work(pro):
    from cases.models import Case, Task
    from core.errors import Invalid
    from profpay import services

    with pytest.raises(Invalid):
        services.submit_claim(pro.runner, kind="travel", description="Travel", amount="10.00",
                              incurred_on=timezone.localdate())
    other = Case.objects.exclude(pk__in=Task.objects.filter(assignee=pro.runner).values("case_id")).first()
    with pytest.raises(Forbidden):
        services.submit_claim(pro.runner, kind="travel", description="Travel", amount="10.00",
                              incurred_on=timezone.localdate(), case=other)


# ------------------------------------------------------------------ runs (US-PRO-005, US-PRO-006)

def _fresh_run(pro, *extra):
    from profpay import services

    pro.clear_pending_runs()
    for person, role in extra:
        pro.work(person, role)
    return services.prepare_run(pro.cm, country=pro.gh)


def test_run_journey_api(pro, api, mfa):
    """US-PRO-005 AC1, AC2, TC-PRO-005-01, TC-RUL-27-01, TC-PRO-006-01: lines per professional with gross, tax,
    expenses and net; the preparer cannot approve; a person without payment rights cannot; a different person with
    payment rights approves with MFA; the bulk file is built from the operating account to verified professional
    accounts only and its SHA-256 is stored and shown."""
    pro.clear_pending_runs()
    pro.work(pro.lawyer, "LW")
    pro.work(pro.surveyor, "SV")
    cm = api(pro.cm)
    r = cm.post("/v1/pro/payment-runs", {"country": "GH"}, format="json")
    assert r.status_code == 201, r.content
    run = r.json()
    assert run["line_count"] >= 2 and run["operating_account"]["kind"] in ("operating_bank",
                                                                          "operating_mobile_money")
    for ln in run["lines"]:
        net = Decimal(ln["gross"]["amount"]) - Decimal(ln["withholding"]["amount"]) - Decimal(
            ln["other_deductions"]["amount"]) + Decimal(ln["reimbursed_expenses"]["amount"])
        assert Decimal(ln["net"]["amount"]) == net
    rid = run["id"]
    assert cm.post(f"/v1/pro/payment-runs/{rid}/submit").status_code == 200
    mfa(cm, pro.cm)
    r = cm.post(f"/v1/pro/payment-runs/{rid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    assert cm.get(f"/v1/pro/payment-runs/{rid}/file").status_code in (403, 409)
    rv = api(pro.rv)
    r = rv.post(f"/v1/pro/payment-runs/{rid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 401
    mfa(rv, pro.rv)
    r = rv.post(f"/v1/pro/payment-runs/{rid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "file_issued", r.content
    sha = r.json()["file_sha256"]
    f = rv.get(f"/v1/pro/payment-runs/{rid}/file")
    assert f.status_code == 200 and hashlib.sha256(f.content).hexdigest() == sha
    text = f.content.decode()
    from administration.models import Partner

    op = Partner.objects.get(pk=r.json()["operating_account"]["id"])
    for line in text.strip().splitlines()[1:]:
        assert op.account_number in line
    assert api(pro.lawyer).get(f"/v1/pro/payment-runs/{rid}/file").status_code in (403, 404)
    assert cm.get(f"/v1/pro/payment-runs/{rid}/file").status_code == 200  # the preparer
    assert cm.post(f"/v1/pro/payment-runs/{rid}/uploads").status_code == 200


def test_run_approver_needs_payment_rights(pro):
    """US-PRO-005 AC4, TC-PRO-005-02: a staff member without payment rights cannot approve."""
    from core import approvals
    from profpay import services

    run = _fresh_run(pro, (pro.lawyer, "LW"))
    run = services.submit_run(run, pro.rv)
    with pytest.raises(Forbidden):
        services.decide_run(run, pro.cm, mfa_at=timezone.now())
    with pytest.raises(SameApprover):
        services.decide_run(run, pro.rv, mfa_at=timezone.now())
    with pytest.raises(Forbidden):
        approvals.decide(run.approval_request, pro.cm, mfa_at=timezone.now(), allowed=services.run_allowed(run))


def test_change_after_approval_returns_to_draft(pro, api):
    """US-PRO-005 AC3, TC-PRO-005-03: removing a line after approval withdraws it; the run goes back to draft and
    the file cannot be downloaded."""
    from profpay import services

    run = _fresh_run(pro, (pro.lawyer, "LW"), (pro.surveyor, "SV"))
    services.submit_run(run, pro.cm)
    pro.approve_run(run)
    assert run.status == "file_issued"
    line = run.lines.first()
    r = api(pro.cm).post(f"/v1/pro/payment-lines/{line.pk}/removals", {"reason": "Wrong amount"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["file_downloadable"] is False
    run.refresh_from_db()
    assert run.approved_by is None and run.file_sha256 == ""
    assert api(pro.rv).get(f"/v1/pro/payment-runs/{run.pk}/file").status_code == 409


def test_altered_file_fails_hash(pro, settings):
    """TC-PRO-005-04: an altered stored file fails its hash check and cannot be downloaded."""
    from core.errors import DomainError
    from profpay import services

    run = _fresh_run(pro, (pro.lawyer, "LW"))
    services.submit_run(run, pro.cm)
    pro.approve_run(run)
    path = os.path.join(settings.MEDIA_ROOT, "evidence", run.file_evidence.storage_key)
    os.chmod(path, 0o640)
    with open(path, "ab") as fh:
        fh.write(b"CR,extra,line\n")
    with pytest.raises(DomainError) as e:
        services.download_file(run, pro.rv)
    assert e.value.code == "file-integrity"


def test_unverified_payee_left_out(pro):
    """US-PRO-006 AC2, TC-PRO-006-02: a professional whose account is not verified is left out with the reason,
    and an approved payable is held until the account is verified again."""
    from accounts.models import BankAccount
    from core import state
    from profpay import services

    pro.clear_pending_runs()
    p = pro.work(pro.surveyor, "SV")
    acct = BankAccount.objects.get(pk=pro.agr["surveyor"].bank_account_id)
    state.transition(acct, "bank_account", "suspended", actor=pro.rv, reason="Bank letter withdrawn")
    p.refresh_from_db()
    assert p.status == "held" and p.hold_reason == "payee_not_verified"
    run = services.prepare_run(pro.cm, country=pro.gh)
    assert any(x["id"] == str(p.pk) for x in run.excluded)
    assert not run.lines.filter(agreement=pro.agr["surveyor"]).exists()


def test_operating_account_only(pro):
    """RUL-27, TC-RUL-27-03: a run never debits the escrow bank account, in the service or in the database."""
    from administration.models import Partner
    from core.errors import RuleBlocked
    from profpay import services
    from profpay.models import PaymentRun

    bank = Partner.objects.filter(country=pro.gh, kind="escrow_bank").first()
    with pytest.raises(RuleBlocked):
        services.prepare_run(pro.cm, country=pro.gh, operating_account_id=bank.pk)
    run = _fresh_run(pro, (pro.lawyer, "LW"))
    with pytest.raises(DatabaseError), transaction.atomic():
        PaymentRun.objects.filter(pk=run.pk).update(operating_account=bank)


def test_line_never_pays_another_kind_of_payee(pro):
    """RUL-27, TC-RUL-27-03: a payment line refuses an institution, contractor or carer payee (database check)."""
    from escrow.models import Payee
    from profpay.models import PaymentLine

    run = _fresh_run(pro, (pro.lawyer, "LW"))
    line = run.lines.first()
    other = Payee.objects.exclude(kind__in=["professional", "contracted_professional"]).filter(
        verification_status="verified").first()
    if other is None:
        pytest.skip("no other verified payee in the seed")
    with pytest.raises(DatabaseError), transaction.atomic():
        PaymentLine.objects.filter(pk=line.pk).update(payee=other, bank_account=None)


def test_no_release_from_client_money_to_a_professional(pro):
    """RUL-27, US-PRO-006 AC3, TC-RUL-27-02, TC-PRO-006-03: every escrow release subject refuses a payee linked to
    a professional's agreement."""
    from escrow import registry
    from escrow.models import SUBJECT_TYPES

    firm = pro.agr["lawyer"].payee
    for st in SUBJECT_TYPES:
        reasons = registry.run_checks(SimpleNamespace(subject_type=st, payee_id=firm.pk, subject_id=uuid.uuid4()))
        assert any(r["rule"] == "RUL-27" for r in reasons), st


def test_no_import_of_escrow_money_tables():
    """TC-RUL-27-04: profpay imports from escrow only the payee registry and the release-subject hook."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1]
    banned = re.compile(r"(Escrow\b|ReleaseInstruction|BankEvent|StandingApproval|StatementFile|StatementLine|"
                        r"request_release|held_funds_for|open_held_funds)")
    for f in root.glob("*.py"):
        text = f.read_text()
        for m in re.finditer(r"from escrow[\w.]* import ([^\n]+)", text):
            assert not banned.search(m.group(1)), (f.name, m.group(0))
    from profpay import models

    for model in [m for m in models.__dict__.values() if hasattr(m, "_meta") and hasattr(m._meta, "db_table")]:
        for fld in model._meta.get_fields():
            target = getattr(getattr(fld, "related_model", None), "_meta", None)
            if target is not None and target.db_table.startswith("esc_"):
                assert target.db_table == "esc_payee", (model, fld.name)


def test_payment_runs_paused(pro, settings):
    """06 2.6 pro.payment_runs_paused: nothing is prepared, approved or issued while it is on."""
    from core.errors import DomainError
    from profpay import services

    run = _fresh_run(pro, (pro.lawyer, "LW"))
    run = services.submit_run(run, pro.cm)
    settings.TENMINA_FLAG_OVERRIDES = {"pro.payment_runs_paused": True}
    with pytest.raises(DomainError) as e:
        services.prepare_run(pro.cm, country=pro.gh)
    assert e.value.code == "payment-runs-paused"
    with pytest.raises(DomainError):
        services.decide_run(run, pro.rv, mfa_at=timezone.now())


# ------------------------------------------------------------------ reconciliation (US-PRO-009, US-PRO-007)

def _issued(pro, *extra):
    from profpay import services

    run = _fresh_run(pro, *extra)
    services.submit_run(run, pro.cm)
    return pro.approve_run(run)


def test_reconciliation_failed_line_paid_once(pro, api):
    """US-PRO-009 AC1, AC2, TC-PRO-009-01, TC-PRO-009-02, TC-PRO-010-02: lines are confirmed, failed or unconfirmed
    from the bank's file; a failed line goes to the next run, its payables return to approved and are paid once;
    remittance advices show gross, deductions and net; the case cost is not counted twice."""
    from profpay import services
    from profpay.models import Document, Payable

    run = _issued(pro, (pro.lawyer, "LW"), (pro.surveyor, "SV"))
    lines = list(run.lines.order_by("position"))
    assert len(lines) >= 2
    ok, bad = lines[0], lines[1]
    body = (f"payment_reference,status,bank_reference,reason,amount\n{ok.reference},paid,B1,,{ok.net}\n"
            f"{bad.reference},failed,,Account closed,{bad.net}\n")
    r = api(pro.cm).post(f"/v1/pro/payment-runs/{run.pk}/confirmations", {"content": body}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "partly_confirmed"
    outcomes = {ln["reference"]: ln["outcome"] for ln in r.json()["lines"]}
    assert outcomes[ok.reference] == "confirmed" and outcomes[bad.reference] == "failed"
    assert all(o == "unconfirmed" for ref, o in outcomes.items() if ref not in (ok.reference, bad.reference))
    adv = Document.objects.get(payment_line=ok, kind="remittance_advice")
    assert adv.net == ok.net and adv.gross == ok.gross and adv.evidence.content_type == "application/pdf"
    assert not Payable.objects.filter(payment_line=ok).exclude(status="paid").exists()
    bad_payables = list(Payable.objects.filter(payment_line=bad).values_list("pk", flat=True))
    r = api(pro.cm).post(f"/v1/pro/payment-lines/{bad.pk}/resolutions", {"resolution": "next_run"}, format="json")
    assert r.status_code == 200, r.content
    assert set(Payable.objects.filter(pk__in=bad_payables).values_list("status", flat=True)) == {"approved"}
    # Importing the same confirmation again pays nothing twice.
    services.import_confirmation(run, pro.cm, data=body.encode())
    assert set(Payable.objects.filter(pk__in=bad_payables).values_list("status", flat=True)) == {"approved"}
    run2 = services.prepare_run(pro.cm, country=pro.gh)
    assert Payable.objects.filter(pk__in=bad_payables, payment_line__run=run2).count() == len(bad_payables)
    services.submit_run(run2, pro.cm)
    run2 = pro.approve_run(run2)
    rows = "\n".join(f"{ln.reference},paid,B{ln.position},,{ln.net}" for ln in run2.lines.all())
    services.import_confirmation(run2, pro.cm, data=f"payment_reference,status,bank_reference,reason,amount\n{rows}\n"
                                 .encode())
    assert set(Payable.objects.filter(pk__in=bad_payables).values_list("status", flat=True)) == {"paid"}
    from cases.models import CostItem

    for pid in bad_payables:
        assert CostItem.objects.filter(source_id=pid).count() <= 1


def test_unconfirmed_line_bank_letter_second_person(pro, api):
    """US-PRO-009 AC3, TC-PRO-009-03: a line resolved by a bank letter is confirmed only after a second staff
    member checks it."""
    from profpay import services
    from profpay.models import PaymentLine

    run = _issued(pro, (pro.lawyer, "LW"))
    services.import_confirmation(run, pro.cm, data=b"payment_reference,status\n")
    line = run.lines.first()
    line.refresh_from_db()
    assert line.outcome == "unconfirmed"
    letter = pro.ev("bank-letter")
    r = api(pro.cm).post(f"/v1/pro/payment-lines/{line.pk}/resolutions",
                         {"resolution": "confirmed_by_bank_letter", "letter_evidence_id": str(letter.pk)},
                         format="json")
    assert r.status_code == 200 and r.json()["outcome"] == "unconfirmed"
    r = api(pro.cm).post(f"/v1/pro/payment-lines/{line.pk}/letter-checks", {"accept": True}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    r = api(pro.rv).post(f"/v1/pro/payment-lines/{line.pk}/letter-checks", {"accept": True}, format="json")
    assert r.status_code == 200 and r.json()["outcome"] == "confirmed"
    assert PaymentLine.objects.get(pk=line.pk).documents.filter(kind="remittance_advice").exists()


def test_paid_line_never_changes(pro):
    """06 6.7 Never: an edit to a paid line (database check)."""
    from profpay import services
    from profpay.models import PaymentLine

    run = _issued(pro, (pro.lawyer, "LW"))
    line = run.lines.first()
    services.import_confirmation(run, pro.cm, data=f"payment_reference,status\n{line.reference},paid\n".encode())
    with pytest.raises(DatabaseError), transaction.atomic():
        PaymentLine.objects.filter(pk=line.pk).update(gross=Decimal("1.00"), withholding=0)


def test_yearly_statement_adds_up(pro, api):
    """US-PRO-007 AC2, AC3, TC-PRO-007-03: the yearly statement adds up to the remittance advices; both are
    hashed PDFs the professional downloads from My pay."""
    from profpay import services
    from profpay.models import Document

    year = services.tax_year_of(pro.gh, timezone.localdate())
    docs = services.generate_statements(pro.gh, year, by=pro.cm)
    st = next(d for d in docs if d.agreement.professional_id == pro.lawyer.pk) if any(
        d.agreement.professional_id == pro.lawyer.pk for d in docs) else None
    if st is None:
        pytest.skip("no paid lines for the lawyer in the seed")
    advices = Document.objects.filter(agreement=st.agreement, kind="remittance_advice")
    assert st.net == sum(a.net for a in advices) and st.gross == sum(a.gross for a in advices)
    assert services.generate_statements(pro.gh, year) == []
    r = api(pro.lawyer).get(f"/v1/me/pro/statements/{st.pk}/pdf")
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
    assert hashlib.sha256(r.content).hexdigest() == st.evidence.sha256
    assert api(pro.surveyor).get(f"/v1/me/pro/statements/{st.pk}/pdf").status_code == 404


def test_expense_cost_entry_and_run(pro):
    """FR-PRO-010 AC1: an approved expense on a case adds a cost entry; it is reimbursed in the run without
    withholding (Q-25)."""
    from cases.models import CostItem, Task
    from profpay import services

    task = Task.objects.filter(assignee=pro.runner).select_related("case").first()
    if task is None:
        pytest.skip("the runner has no assigned task in the seed")
    c = services.submit_claim(pro.runner, kind="travel", description="Bus to site", amount="30.00",
                              incurred_on=timezone.localdate(), receipt_evidence=pro.ev("bus", by=pro.runner),
                              case=task.case)
    services.decide_claim(c, pro.cm, decision="approve")
    assert CostItem.objects.filter(source="pro_expense", source_id=c.pk, amount=Decimal("30.00")).exists()
    pro.clear_pending_runs()
    run = services.prepare_run(pro.cm, country=pro.gh)
    line = run.lines.get(agreement=pro.agr["runner"])
    assert line.reimbursed_expenses >= Decimal("30.00")
