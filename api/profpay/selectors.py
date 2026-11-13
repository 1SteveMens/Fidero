"""PRO Professional payments: read-only queries other modules may use.

- assignment_blockers(person, role_code, country)   CASE, BLD, CARE and TSK call this before assigning work
  (US-PRO-001 AC1): no signed active agreement, or no verified payee account in the person's own name.
- has_active_agreement(person, role_code, country)
- my_jobs(person)                                    accepted and pending work with the rate that applies; never
                                                     a verdict or outcome (RUL-26)
- cost_per_case(country)                             FR-PRO-010
"""
from django.db.models import Q

from .models import CODE_FOR_ROLE, UNIT_FOR_WORK, Agreement, ExpenseClaim, Payable, PaymentRun


def assignment_blockers(person, role_code, country) -> list[dict]:
    from .services import assignment_blockers as _b

    return _b(person, role_code, country)


def has_active_agreement(person, role_code, country) -> bool:
    roles = [r for r, c in CODE_FOR_ROLE.items() if c == role_code]
    return Agreement.objects.filter(professional=person, role__in=roles, country=country, status="active").exists()


def agreements_of(person):
    return Agreement.objects.filter(professional=person).select_related("country", "payee", "bank_account")


def payables_of(person):
    return Payable.objects.filter(agreement__professional=person).select_related("agreement", "payment_line__run")


def claims_of(person):
    return ExpenseClaim.objects.filter(claimant=person)


def staff_runs(user):
    from accounts.selectors import scope_to_staff_countries

    return scope_to_staff_countries(PaymentRun.objects.all(), user, roles=("CM", "RV", "AD"))


def my_jobs(person) -> list[dict]:
    """GET /v1/me/pro/jobs: accepted work (with its payable) and assigned work still pending, with the rate
    that applies. Built from work keys, dates and units only; no verdict, outcome or risk is read (RUL-26)."""
    from cases.models import Task

    from .services import agreement_for_code, card_in_force

    out = []
    for p in payables_of(person).order_by("-accepted_at")[:200]:
        out.append({"state": "accepted", "work_kind": p.work_kind, "work_ref": str(p.work_ref),
                    "case_id": str(p.case_id) if p.case_id else None,
                    "case_reference": p.case.reference if p.case_id else None,
                    "assigned_at": p.assigned_at.isoformat(), "accepted_at": p.accepted_at.isoformat(),
                    "rate": {"amount": f"{p.unit_rate:.2f}", "currency": p.currency},
                    "unit": UNIT_FOR_WORK[p.work_kind], "payable_id": str(p.pk), "payable_status": p.status})
    tasks = Task.objects.filter(Q(assignee=person) | Q(second_assignee=person),
                                status__in=["open", "in_progress", "done"]).select_related("case", "case__country")
    paid_refs = {p["work_ref"] for p in out}
    for t in tasks.order_by("-assigned_at")[:200]:
        if str(t.pk) in paid_refs:
            continue
        a = agreement_for_code(person, t.owner_role, t.case.country)
        unit = "site_visit" if t.site_visit else "report_section" if t.owner_role in ("LW", "SV") else None
        card = card_in_force(a, unit, "standard", t.assigned_at or t.created_at) if (a and unit) else None
        if t.case.status in ("cancelled",):
            continue
        out.append({"state": "pending", "work_kind": unit or "task", "work_ref": str(t.pk),
                    "case_id": str(t.case_id), "case_reference": t.case.reference, "title": t.title,
                    "assigned_at": t.assigned_at.isoformat() if t.assigned_at else None, "accepted_at": None,
                    "rate": {"amount": f"{card.rate:.2f}", "currency": card.currency} if card else None,
                    "unit": unit, "payable_id": None, "payable_status": None})
    return out


def cost_per_case(country=None, case_ids=None):
    from .services import cost_per_case as _c

    return _c(country, case_ids=case_ids)
