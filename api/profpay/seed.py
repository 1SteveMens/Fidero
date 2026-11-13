"""PRO demo data: the pay configuration, agreements for the seeded lawyer,
surveyor and runner, approved and draft rate cards, payables from the
released reports, a runner's month, expense claims, a confirmed payment run
with remittance advices, a run waiting for approval, a review hold and an
overdue payable. Every rate, limit and period is a working assumption
[TO VERIFY], not verified data.

Payee accounts: the lawyer is paid through the law firm's verified payee
(`esc_payee`); the surveyor and the runner through their own verified
accounts (`acc_bank_account`). ACC lets only clients add accounts today, so the
seed writes those two rows the way the ACC seed does (see "Needs" in the
module report)."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

NS = uuid.UUID("2b0f5b8e-4c1d-4a6e-9a77-0e1c5a7d3f10")

PRO_CONFIG = {
    # Working assumptions [TO VERIFY with the accountant, Q-25, and operations, 06 6.7].
    "payment_period_working_days": 10,
    "bulk_file_format": "generic_csv_v1",
    "tax_year_start_month": 1,
    "withholding_on_expenses": False,
    "withholding_rates": {"registered": "0.075", "not_registered": "0.075", "exempt": "0"},
    "other_deductions": [],
    "expense_limits": {
        "default": {"official_search_fee": "500.00", "travel": "150.00", "approved_cost": "300.00"},
        "runner": {"official_search_fee": "500.00", "travel": "250.00", "approved_cost": "300.00"},
        "surveyor": {"official_search_fee": "500.00", "travel": "400.00", "approved_cost": "500.00"},
    },
}
# GHS per unit [TO VERIFY]: flat, whatever the verdict or outcome (RUL-26).
STANDARD_RATES = [
    ("lawyer", "report_section", "1500.00"), ("lawyer", "recheck", "900.00"),
    ("surveyor", "report_section", "1200.00"), ("surveyor", "site_visit", "300.00"), ("surveyor", "recheck", "700.00"),
    ("runner", "month", "3000.00"), ("runner", "site_visit", "150.00"),
    ("inspector", "inspection", "600.00"), ("quantity_surveyor", "bill_of_quantities", "900.00"),
    ("errand_agent", "errand", "120.00"), ("carer", "care_visit", "80.00"),
]


def did(name):
    return uuid.uuid5(NS, name)


def _ev(gh, by, name, text=None):
    from evidence.models import Evidence
    from evidence.services import store

    ev = Evidence.objects.filter(original_name=name, country=gh).first()
    return ev or store(data=(text or f"Demo document: {name}").encode(), country=gh, uploaded_by=by,
                       content_type="text/plain", original_name=name, data_class="payables")


def _config(gh, admin):
    from countries.services import seed_publish

    cur = gh.configs.filter(status="published").order_by("-version").first()
    if cur is not None and "pro" not in (cur.data or {}):
        seed_publish(gh, dict(cur.data, pro=PRO_CONFIG), by=admin)
        gh.refresh_from_db()


def own_account(gh, person, number, approvers, preparer, *, bank="Demo Savings Bank [TO VERIFY]"):
    """Seed only: a professional's own verified account, written as the ACC seed writes client accounts."""
    from accounts.models import BankAccount
    from accounts.normalise import normalise_name
    from accounts.seed import _approved_request

    acct = BankAccount.objects.filter(holder=person, account_number=number).first()
    if acct:
        return acct
    letter = _ev(gh, preparer, f"bank-letter-{person.email}.txt", f"Bank letter: account name {person.full_name}")
    acct = BankAccount.objects.create(country=gh, holder=person, bank_name=bank, account_number=number,
                                      account_name=person.full_name.upper(),
                                      account_name_norm=normalise_name(person.full_name), name_match="matched",
                                      evidence=letter, name_source="bank_letter", verification_status="pending",
                                      prepared_by=preparer, purpose="professional_pay")
    acct.approval_request = _approved_request("bank_account_verification", acct.pk, preparer, approvers, country=gh)
    acct.verification_status, acct.verified_at = "verified", timezone.now()
    acct.save(update_fields=["approval_request", "verification_status", "verified_at"])
    return acct


def firm_payee(gh, people, *, org_name, signer, number, nid_number):
    """The law firm's verified payee: national identity check of the signer, the bank's name check and two
    staff approvals, through the ESC services."""
    from accounts.models import Organisation
    from accounts.services import request_national_id_check
    from core import approvals
    from escrow import services as esc
    from escrow.models import Payee

    cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
    org, _ = Organisation.objects.get_or_create(name=org_name, kind="law_firm", country=gh)
    p = Payee.objects.filter(subject_type="organisation", subject_id=org.pk, kind="contracted_professional").first()
    if p is None:
        chk = request_national_id_check(by=cm, country=gh, subject_role="professional", subject_name=signer.full_name,
                                        id_number=nid_number, person=signer)
        p = esc.create_payee(cm, country=gh, kind="contracted_professional", subject_type="organisation", subject_id=org.pk,
                             legal_name=org_name, legal_name_evidence=_ev(gh, cm, f"registration-{org_name}.txt"),
                             bank_name="Demo Commercial Bank [TO VERIFY]", account_number=number,
                             account_name_source="bank_name_check", organisation=org, national_id_check=chk)
    if p.verification_status == "pending" and p.name_match == "matched":
        esc.prepare_verification(p, cm)
        p.refresh_from_db()
        for a in (rv, rv2):
            approvals.decide(p.approval_request, a, mfa_at=timezone.now())
        p.refresh_from_db()
    return org, p


def approved_card(gh, *, role, unit, rate, admin, admin2, valid_from, agreement=None, scope="standard"):
    """Seed only: an approved card that started before today (the service accepts start dates from today)."""
    from accounts.seed import _approved_request

    from .models import RateCard

    card = RateCard.objects.filter(country=gh, role=role, unit=unit, agreement=agreement, scope_key_id=scope,
                                   version=1).first()
    if card:
        return card
    cid = did(f"card:{gh.code}:{role}:{unit}:{scope}:{agreement.pk if agreement else 'std'}")
    req = _approved_request("pro_rate_card_change", cid, admin, [admin2], country=gh,
                            summary=f"{role} per {unit} v1 (seed)")
    return RateCard.objects.create(id=cid, country=gh, role=role, unit=unit, scope_key_id=scope,
                                   rate=Decimal(rate), currency=gh.currency, version=1, valid_from=valid_from,
                                   state="approved", created_by=admin, approval_request=req, approved_by=admin2,
                                   approved_at=timezone.now())


def run(ctx):
    from core import approvals
    from core.models import OutboxEvent

    from . import services
    from .models import Agreement, ExpenseClaim, Payable, PaymentRun

    gh, people = ctx["gh"], ctx["people"]
    admin, admin2, cm, rv, rv2 = (people[k] for k in ("admin", "admin2", "cm", "reviewer", "reviewer2"))
    lawyer, surveyor, runner, inspector = (people[k] for k in ("lawyer", "surveyor", "runner", "inspector"))
    out = ctx.setdefault("pro", {})
    _config(gh, admin)
    start = timezone.localdate() - timedelta(days=400)
    for role, unit, rate in STANDARD_RATES:
        approved_card(gh, role=role, unit=unit, rate=rate, admin=admin, admin2=admin2, valid_from=start)

    # A new lawyer rate drafted by one administrator, waiting for a second (US-PRO-001 AC2).
    from .models import RateCard

    if not RateCard.objects.filter(country=gh, role="lawyer", unit="report_section", state="draft").exists():
        nxt = (timezone.localdate().replace(day=1) + timedelta(days=32)).replace(day=1)
        services.draft_rate_card(admin, country=gh, role="lawyer", unit="report_section", rate="1650.00",
                                 valid_from=nxt)

    # ---- agreements
    org, firm = firm_payee(gh, people, org_name="Nana & Co Chambers (demo)", signer=lawyer, number="3300112233",
                           nid_number="GHA-711111111-1")
    sv_acct = own_account(gh, surveyor, "4400556677", [rv, rv2], cm)
    rn_acct = own_account(gh, runner, "5500667788", [rv, rv2], cm)

    def agreement(person, role, **kw):
        a = Agreement.objects.filter(professional=person, role=role, country=gh).first()
        if a is None:
            a = services.create_agreement(admin, country=gh, professional=person, role=role,
                                          agreement_evidence=_ev(gh, admin, f"signed-agreement-{person.email}-{role}.txt"),
                                          valid_from=start, **kw)
        if kw.get("payee") or kw.get("bank_account"):
            if a.status == "draft":
                services.activate_agreement(a, admin)
        return a

    out["lawyer"] = agreement(lawyer, "lawyer", contracting_party="organisation", organisation=org, payee=firm,
                              tax_status="registered", tax_id="C0001234567 [demo]")
    out["surveyor"] = agreement(surveyor, "surveyor", bank_account=sv_acct, tax_status="registered")
    out["runner"] = agreement(runner, "runner", bank_account=rn_acct)
    out["inspector"] = agreement(inspector, "inspector")  # draft: no verified account yet
    out["firm_payee"], out["surveyor_account"], out["runner_account"] = firm, sv_acct, rn_acct

    # ---- payables from released reports (replays the work.accepted events RPT already sent)
    for ev in OutboxEvent.objects.filter(topic="work.accepted").order_by("created_at"):
        services.record_work_accepted(dict(ev.payload), event_id=ev.id)

    # ---- synthetic accepted work so every screen has data
    now = timezone.now()

    def accepted(key, person, role, kind, days_ago, assigned_days_ago=None):
        ref = did(f"work:{key}")
        if Payable.objects.filter(work_ref=ref).exists():
            return Payable.objects.get(work_ref=ref)
        return services.record_work_accepted(
            {"work_kind": kind, "work_ref": str(ref), "person_id": str(person.pk), "role": role, "country": "GH",
             "assigned_at": (now - timedelta(days=assigned_days_ago or days_ago + 5)).isoformat(),
             "accepted_at": (now - timedelta(days=days_ago)).isoformat(), "quantity": 1}, event_id=did(f"ev:{key}"))

    p_recheck = accepted("recheck-1", lawyer, "LW", "recheck", 9)
    p_hold = accepted("recheck-3", lawyer, "LW", "recheck", 3)
    p_new = accepted("recheck-4", surveyor, "SV", "recheck", 1)
    out["payables"] = {"recheck": p_recheck, "hold": p_hold, "new": p_new}

    # Runner's previous month (FR-PRO-002 AC4).
    last_month = (timezone.localdate().replace(day=1) - timedelta(days=1)).replace(day=1)
    if not out["runner"].months.filter(month=last_month).exists():
        services.close_runner_month(out["runner"], last_month, cm)

    # ---- expense claims (US-PRO-004)
    if not ExpenseClaim.objects.filter(claimant=runner).exists():
        receipt = _ev(gh, runner, "receipt-trotro-demo.txt", "Receipt: trotro fares Accra to Kasoa, GHS 85.00")
        c1 = services.submit_claim(runner, kind="approved_cost", description="Fares to the Kasoa site visit",
                                   amount="85.00", incurred_on=timezone.localdate() - timedelta(days=4),
                                   receipt_evidence=receipt)
        services.decide_claim(c1, cm, decision="approve")
        c2 = services.submit_claim(runner, kind="approved_cost", description="Photocopies at the Lands Commission",
                                   amount="40.00", incurred_on=timezone.localdate() - timedelta(days=2))
        services.decide_claim(c2, cm, decision="approve", note="Receipt lost; vendor confirmed by phone")
        receipt3 = _ev(gh, runner, "receipt-search-fee-demo.txt", "Receipt: official search fee GHS 650.00")
        services.submit_claim(runner, kind="approved_cost", description="Official search fee paid at the counter",
                              amount="290.00", incurred_on=timezone.localdate() - timedelta(days=1),
                              receipt_evidence=receipt3)

    # ---- a confirmed run with remittance advices, then a run waiting for approval
    if not PaymentRun.objects.filter(country=gh).exists():
        p_hold.refresh_from_db()
        if p_hold.status == "approved":
            services.hold_payable(p_hold, rv, reason="fraud_review",
                                  note="Same site photos appear on another case; review opened (demo)")
        p_new.refresh_from_db()
        if p_new.status == "approved":
            services.hold_payable(p_new, rv, reason="misconduct_review", note="Late filing complaint (demo)")
        run1 = services.prepare_run(cm, country=gh, cut_off_at=now)
        services.submit_run(run1, cm)
        run1.refresh_from_db()
        approvals.decide(run1.approval_request, rv, mfa_at=timezone.now())
        run1.refresh_from_db()
        services.mark_uploaded(run1, rv)
        lines = list(run1.lines.order_by("position"))
        rows = ["payment_reference,status,bank_reference,reason,amount"]
        for i, ln in enumerate(lines):
            if i == len(lines) - 1 and len(lines) > 1:
                rows.append(f"{ln.reference},failed,,Account closed (demo),{ln.net}")
            else:
                rows.append(f"{ln.reference},paid,OPB{ln.position:06d},,{ln.net}")
        services.import_confirmation(run1, cm, data=("\n".join(rows) + "\n").encode(), name="bank-confirmation.csv")
        out["run_confirmed"] = PaymentRun.objects.get(pk=run1.pk)
        # Accepted 30 days ago and still unpaid: overdue (FR-PRO-008).
        out["payables"]["overdue"] = accepted("recheck-2", surveyor, "SV", "recheck", 30)
        # The review on p_new closes: its pay joins the next run.
        p_new.refresh_from_db()
        if p_new.status == "held":
            services.release_hold(p_new, rv, note="Complaint not upheld (demo)")
        run2 = services.prepare_run(cm, country=gh, cut_off_at=timezone.now())
        if run2.line_count:
            services.submit_run(run2, cm)
        out["run_pending"] = PaymentRun.objects.get(pk=run2.pk)
    # Overdue alert (FR-PRO-008).
    services.check_overdue()
