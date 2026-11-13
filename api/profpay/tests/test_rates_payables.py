"""Rate cards, payables and holds (US-PRO-001, US-PRO-002, US-PRO-003, US-PRO-008)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, InternalError, connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from core.errors import DomainError, RuleBlocked, SameApprover, StateConflict


def _next_month():
    return (timezone.localdate().replace(day=1) + timedelta(days=32)).replace(day=1)


# ------------------------------------------------------------------ rate cards (US-PRO-001, US-PRO-003)

def test_rate_card_second_admin_and_versions(pro, api, mfa):
    """FR-PRO-001, US-PRO-001 AC2 and AC3, TC-PRO-001-01, TC-PRO-001-02: the drafter cannot approve; a second
    administrator approves with MFA; an approved card never changes."""
    from profpay.models import RateCard

    c = api(pro.admin)
    r = c.post("/v1/admin/pro/rate-cards", {"country": "GH", "role": "surveyor", "unit": "report_section",
                                           "rate": "1300.00", "valid_from": str(_next_month())}, format="json")
    assert r.status_code == 201, r.content
    cid = r.json()["id"]
    assert r.json()["state"] == "draft" and r.json()["version"] == 2
    mfa(c, pro.admin)
    r = c.post(f"/v1/admin/pro/rate-cards/{cid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    c2 = api(pro.admin2)
    r = c2.post(f"/v1/admin/pro/rate-cards/{cid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 401 and r.json()["code"] == "mfa-required"
    mfa(c2, pro.admin2)
    r = c2.post(f"/v1/admin/pro/rate-cards/{cid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["state"] == "approved", r.content
    old = RateCard.objects.get(country=pro.gh, role="surveyor", unit="report_section", version=1, agreement=None)
    assert old.valid_to == _next_month() - timedelta(days=1)
    r = c.patch(f"/v1/admin/pro/rate-cards/{cid}", {"rate": "1.00"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "rate-card-immutable"
    # The database refuses it too.
    with pytest.raises(DatabaseError), transaction.atomic():
        RateCard.objects.filter(pk=cid).update(rate=Decimal("1.00"))


def test_rate_applies_by_assignment_date(pro):
    """US-PRO-001 AC2: a new version applies to work assigned on or after its start; earlier work keeps its rate."""
    from profpay import services
    from profpay.models import RateCard

    card = services.draft_rate_card(pro.admin, country=pro.gh, role="lawyer", unit="recheck", rate="1000.00",
                                    valid_from=timezone.localdate() + timedelta(days=1))
    services.decide_rate_card(card, pro.admin2, mfa_at=timezone.now())
    card.refresh_from_db()
    assert card.state == "approved"
    early = pro.work(pro.lawyer, "LW", days_ago=0, assigned_days_ago=3)
    assert early.unit_rate == Decimal("900.00")
    later = services.card_in_force(pro.agr["lawyer"], "recheck", "standard",
                                   timezone.now() + timedelta(days=2))
    assert later.pk == card.pk and later.rate == Decimal("1000.00")
    assert RateCard.objects.filter(pk=card.pk, version=2).exists()


def test_rate_card_refuses_result_fields(pro, api):
    """RUL-26, US-PRO-003 AC1, TC-RUL-26-02, TC-PRO-003-02: there is no field for a verdict or outcome and the API
    rejects the unknown field; a result-named scope key cannot be added, even directly in the database."""
    from profpay.models import Scope

    c = api(pro.admin)
    for extra in ({"verdict": "red"}, {"outcome": "pass"}, {"rate_if_red": "10.00"}):
        r = c.post("/v1/admin/pro/rate-cards", {"country": "GH", "role": "lawyer", "unit": "report_section",
                                               "rate": "1500.00", "valid_from": str(_next_month()), **extra},
                   format="json")
        assert r.status_code == 400 and r.json()["code"] == "validation-error", r.content
    r = c.post("/v1/admin/pro/rate-cards", {"country": "GH", "role": "lawyer", "unit": "report_section",
                                           "rate": "1500.00", "valid_from": str(_next_month()),
                                           "scope_key": "verdict_red"}, format="json")
    assert r.status_code == 422
    with pytest.raises(DatabaseError), transaction.atomic():
        Scope.objects.create(key="red_report", description="Paid more when red")
    for s in Scope.objects.all():
        assert not any(w in s.key for w in ("verdict", "outcome", "pass", "fail", "green", "amber", "red", "risk"))


def test_only_admin_drafts_rate_card(pro, api):
    r = api(pro.cm).post("/v1/admin/pro/rate-cards", {"country": "GH", "role": "lawyer", "unit": "recheck",
                                                      "rate": "1.00", "valid_from": str(_next_month())},
                         format="json")
    assert r.status_code == 403


# ------------------------------------------------------------------ agreements (US-PRO-001 AC1, US-PRO-006)

def test_agreement_needs_verified_own_account(pro, api):
    """US-PRO-001 AC1, TC-PRO-001-03: no agreement or no verified payee account blocks assignment, with reasons."""
    from profpay import services

    blockers = services.assignment_blockers(pro.p["qs"], "QS", pro.gh)
    assert blockers and blockers[0]["code"] == "no-agreement"
    insp = pro.agr["inspector"]
    assert services.assignment_blockers(pro.p["inspector"], "IN", pro.gh)[0]["code"] == "no-agreement"
    r = api(pro.admin).post(f"/v1/admin/pro/agreements/{insp.pk}/activate")
    assert r.status_code == 409 and r.json()["code"] == "payee-not-verified"
    assert services.assignment_blockers(pro.lawyer, "LW", pro.gh) == []
    # Someone else's account (the runner's) is never the surveyor's destination.
    a = pro.agr["surveyor"]
    r = api(pro.admin).patch(f"/v1/admin/pro/agreements/{a.pk}",
                             {"bank_account_id": str(pro.ctx["pro"]["runner_account"].pk)}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "payee-not-verified"


def test_agreement_api_journey(pro, api):
    """FR-PRO-001: an administrator records a signed agreement for a carer; it stays a draft until it has a
    verified account."""
    ev = pro.ev("signed-carer")
    r = api(pro.admin).post("/v1/admin/pro/agreements", {
        "country": "GH", "professional_id": str(pro.p["carer"].pk), "role": "carer",
        "agreement_evidence_id": str(ev.pk)}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "draft" and r.json()["payable_now"][0]["code"] == "no-payee"
    r = api(pro.admin).post("/v1/admin/pro/agreements", {
        "country": "GH", "professional_id": str(pro.p["client"].pk), "role": "lawyer",
        "agreement_evidence_id": str(ev.pk)}, format="json")
    assert r.status_code == 422
    assert api(pro.lawyer).get("/v1/admin/pro/agreements").json()["items"] == []


# ------------------------------------------------------------------ payables (US-PRO-002, RUL-26)

def _case(n=0):
    from cases.models import Case

    return Case.objects.order_by("created_at")[n]


def test_payable_once_per_work_and_equal_whatever_the_verdict(pro):
    """FR-PRO-002, RUL-26, TC-RUL-26-01, TC-RUL-26-06, TC-PRO-002-03: one payable per piece of work; a
    replayed event and a re-delivery create nothing new; a red and a green report pay the same; a verdict in the
    payload is ignored and recorded."""
    from audit.models import AuditEvent
    from profpay.models import Payable

    ref = uuid.uuid4()
    p1 = pro.work(pro.lawyer, "LW", ref=ref)
    p2 = pro.work(pro.lawyer, "LW", ref=ref)
    assert p1.pk == p2.pk and Payable.objects.filter(work_ref=ref).count() == 1
    red = pro.work(pro.lawyer, "LW", kind="report_section", case=_case(0), verdict="red")
    green = pro.work(pro.lawyer, "LW", kind="report_section", case=_case(1), verdict="green")
    if red.case_id == green.case_id:
        pytest.skip("needs two cases")
    assert red.gross == green.gross and red.unit_rate == green.unit_rate
    assert AuditEvent.objects.filter(action="work_accepted.result_field_ignored").exists()
    # A corrected report version (a new section on the same case) is the same work: no second payable.
    again = pro.work(pro.lawyer, "LW", kind="report_section", case=_case(0))
    assert again.pk == red.pk
    assert not any(f.name in ("verdict", "outcome", "risk", "result") for f in Payable._meta.get_fields())


def test_payable_from_released_report(pro):
    """US-PRO-002 AC1, AC2, TC-PRO-002-01, TC-PRO-002-02: a payable exists for each signer of a released report and
    none for a report not released."""
    from profpay.models import Payable
    from reports.models import Report

    released = Report.objects.filter(status="released").first()
    if released is None:
        pytest.skip("no released report in the seed")
    signers = {s.signer_id for s in released.signatures.all()}
    assert Payable.objects.filter(case=released.case, work_kind="report_section",
                                  agreement__professional_id__in=signers).exists()
    for r in Report.objects.exclude(status__in=["released", "superseded"]):
        assert not Payable.objects.filter(work_kind="report_section",
                                          work_ref__in=r.sections.values("pk")).exists()


def test_payable_tax_and_due_date(pro):
    """FR-PRO-007 AC1, FR-PRO-008 AC1, TC-PRO-007-01, TC-PRO-008-01: withholding from the published configuration
    with its version stored; due date is acceptance plus 10 working days, skipping holidays."""
    from countries.selectors import add_working_days, current_config

    p = pro.work(pro.surveyor, "SV", days_ago=0)
    cfg = current_config(pro.gh)
    assert p.country_config_id == cfg.pk
    assert p.withholding_rate == Decimal(cfg.data["pro"]["withholding_rates"]["registered"])
    assert p.withholding == (p.gross * p.withholding_rate).quantize(Decimal("0.01"))
    assert p.due_by == add_working_days(pro.gh, timezone.localdate(), 10)


def test_tax_change_keeps_old_payables(pro):
    """TC-PRO-007-04: payables keep the configuration they were created under; new ones use the new rules."""
    from countries.selectors import current_config

    before = pro.work(pro.lawyer, "LW")
    cfg = current_config(pro.gh)
    data = dict(cfg.data)
    data["pro"] = dict(data["pro"], withholding_rates={"registered": "0.1", "not_registered": "0.1", "exempt": "0"})
    from countries.services import seed_publish

    seed_publish(pro.gh, data)
    after = pro.work(pro.lawyer, "LW")
    before.refresh_from_db()
    assert before.withholding_rate == Decimal("0.0750") and after.withholding_rate == Decimal("0.1000")
    assert before.country_config_id != after.country_config_id


def test_country_rules_not_hard_coded(pro):
    """FR-PRO-007 AC4, TC-PRO-007-02: a professional in a test country gets that country's rules and currency."""
    from countries.models import Country
    from countries.services import seed_publish
    from profpay import services
    from profpay.seed import approved_card

    tl = Country.objects.create(code="TL", name="Testland", currency="TLD", timezone="UTC", status="active")
    seed_publish(tl, {"currency": "TLD", "withholding_tax_rate": "0.2", "weekend_days": [5, 6],
                      "holiday_calendar": [], "pro": {"payment_period_working_days": 5}})
    approved_card(tl, role="lawyer", unit="recheck", rate="50.00", admin=pro.admin, admin2=pro.admin2,
                  valid_from=timezone.localdate() - timedelta(days=30))
    a = services.create_agreement(pro.admin, country=tl, professional=pro.lawyer, role="lawyer",
                                  agreement_evidence=pro.ev("tl"), contracting_party="organisation",
                                  organisation=pro.agr["lawyer"].organisation, payee=pro.agr["lawyer"].payee,
                                  valid_from=timezone.localdate() - timedelta(days=30))
    services.activate_agreement(a, pro.admin)
    p = pro.work(pro.lawyer, "LW", country="TL", days_ago=0)
    assert p.agreement_id == a.pk and p.currency == "TLD" and p.withholding_rate == Decimal("0.2000")
    from countries.selectors import add_working_days

    assert p.due_by == add_working_days(tl, timezone.localdate(), 5)


def test_runner_month_once_and_part_month(pro, api):
    """FR-PRO-002 AC4, TC-PRO-002-04: one payable per closed month; a second close is refused; a part month pays
    by calendar days."""
    from profpay import services
    from profpay.models import Payable

    a = pro.agr["runner"]
    month = ((timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1) - timedelta(days=1)).replace(
        day=1)
    r = api(pro.cm).post(f"/v1/pro/runner-months/{a.pk}/{month:%Y-%m}/close")
    assert r.status_code == 201, r.content
    assert r.json()["gross"]["amount"] == "3000.00"
    r = api(pro.cm).post(f"/v1/pro/runner-months/{a.pk}/{month:%Y-%m}/close")
    assert r.status_code == 409 and r.json()["code"] == "month-already-closed"
    assert api(pro.runner).post(f"/v1/pro/runner-months/{a.pk}/{month:%Y-%m}/close").status_code == 403
    # A runner who started on the 11th of a 31-day month is paid 21/31 of the fee.
    from profpay.models import Agreement

    import calendar

    m = timezone.localdate().replace(day=1)
    for _ in range(4):
        m = (m - timedelta(days=1)).replace(day=1)
    Agreement.objects.filter(pk=a.pk).update(valid_from=m.replace(day=11))
    a.refresh_from_db()
    rm = services.close_runner_month(a, m, pro.cm)
    p = Payable.objects.get(work_kind="runner_month", work_ref=a.pk, work_period=m)
    days_in = calendar.monthrange(m.year, m.month)[1]
    share = (Decimal(days_in - 10) / Decimal(days_in)).quantize(Decimal("0.0001"))
    assert rm.days_worked == days_in - 10 and p.quantity == share
    assert p.gross == (Decimal("3000.00") * share).quantize(Decimal("0.01"))


def test_runner_month_not_before_last_working_day(pro):
    from profpay import services

    with pytest.raises(StateConflict):
        services.close_runner_month(pro.agr["runner"], (timezone.localdate() + timedelta(days=40)).replace(day=1),
                                    pro.cm)


def test_hold_only_for_review_never_for_result(pro, api):
    """RUL-26, US-PRO-003 AC3, TC-RUL-26-04: a hold because the report was red is refused and audited; a reviewer
    may hold for a fraud review with a reason the professional sees; cancelling for a result is refused."""
    from audit.models import AuditEvent

    p = pro.work(pro.lawyer, "LW")
    r = api(pro.rv).post(f"/v1/pro/payables/{p.pk}/holds", {"reason": "red_verdict", "note": "Report was red"},
                         format="json")
    assert r.status_code == 409 and r.json()["code"] == "pay-independent-of-result"
    r = api(pro.rv).post(f"/v1/pro/payables/{p.pk}/holds", {"reason": "fraud_review", "note": "The report was red"},
                         format="json")
    assert r.status_code == 409
    assert AuditEvent.objects.filter(action="pro_payable.hold_refused", entity_id=str(p.pk)).count() == 2
    assert api(pro.cm).post(f"/v1/pro/payables/{p.pk}/holds", {"reason": "fraud_review", "note": "x"},
                            format="json").status_code == 403
    r = api(pro.rv).post(f"/v1/pro/payables/{p.pk}/holds",
                         {"reason": "fraud_review", "note": "Photos reused from another case"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "held"
    mine = api(pro.lawyer).get(f"/v1/me/pro/payables/{p.pk}").json()
    assert mine["hold_note"] == "Photos reused from another case"
    r = api(pro.rv).post(f"/v1/pro/payables/{p.pk}/cancellations", {"reason": "Inspection failed"}, format="json")
    assert r.status_code == 409
    r = api(pro.rv).post(f"/v1/pro/payables/{p.pk}/hold-releases", {"note": "Review closed"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "approved"


def test_payable_hold_reason_list_in_database(pro):
    """RUL-26: the database accepts no hold reason outside the review list."""
    from profpay.models import Payable

    p = pro.work(pro.lawyer, "LW")
    with pytest.raises(IntegrityError), transaction.atomic():
        Payable.objects.filter(pk=p.pk).update(status="held", hold_reason="red_verdict", held_by=pro.rv)


def test_overdue_alert(pro):
    """FR-PRO-008 AC2, TC-PRO-008-02: a payable past due and unpaid alerts operations once and shows overdue."""
    from core.models import OutboxEvent
    from profpay import services
    from profpay.models import Payable

    p = pro.work(pro.surveyor, "SV", days_ago=40, assigned_days_ago=45)
    Payable.objects.filter(pk=p.pk).update(overdue_alerted_at=None)
    n = services.check_overdue()
    assert n >= 1
    p.refresh_from_db()
    assert p.overdue_alerted_at is not None and services.is_overdue(p)
    assert OutboxEvent.objects.filter(topic="payable.overdue", aggregate_id=p.pk).exists()
    assert services.check_overdue() == 0


def test_case_cost_entries(pro, api):
    """FR-PRO-010, TC-PRO-010-01: an accepted payable on a case adds a cost entry with its amount and source;
    the cost-per-case report uses it."""
    from cases.models import CostItem

    case = _case(2) if _case(2) else _case(0)
    p = pro.work(pro.surveyor, "SV", kind="report_section", case=case)
    item = CostItem.objects.get(source="pro_payable", source_id=p.pk)
    assert item.amount == p.gross and item.case_id == case.pk
    rows = api(pro.cm).get("/v1/pro/cost-per-case?country=GH").json()
    row = next(r for r in rows if r["case_id"] == str(case.pk))
    assert Decimal(row["payables"]) >= p.gross
    assert api(pro.lawyer).get("/v1/pro/cost-per-case").status_code == 403


def test_my_pay_shows_own_only_and_no_verdict(pro, api):
    """US-PRO-002, RUL-26, issue 37: each professional sees only their own pay; no pay response carries a verdict."""
    import json

    lawyer = api(pro.lawyer)
    for path in ("/v1/me/pro/agreement", "/v1/me/pro/jobs", "/v1/me/pro/payables", "/v1/me/pro/statements",
                 "/v1/me/pro/expense-claims"):
        r = lawyer.get(path)
        assert r.status_code == 200, (path, r.content)
        body = json.dumps(r.json()).lower()
        assert "verdict" not in body and "outcome" not in body
    ids = {p["id"] for p in lawyer.get("/v1/me/pro/payables").json()["items"]}
    sv = {p["id"] for p in api(pro.surveyor).get("/v1/me/pro/payables").json()["items"]}
    assert ids and sv and not ids & sv
    assert api(pro.p["client"]).get("/v1/me/pro/payables").status_code == 403
    agr = lawyer.get("/v1/me/pro/agreement").json()[0]
    assert agr["destination"]["account_last4"] and agr["rate_cards"]
