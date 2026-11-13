"""CARE Care visits: read-only queries other modules may use.

Scoping (02 7.4, 10.4): clients see their own plans, visits and concerns; a family member with an account sees
the visits they may confirm or that are to them; a carer sees only their assigned visits; staff see their
countries. Everyone else gets 404.
"""
from django.db.models import Q

from accounts.selectors import scope_to_staff_countries
from core.permissions import STAFF_ROLES, has_role

from .models import CarePlan, Carer, Concern, Visit


def _is_staff(person):
    return has_role(person, *STAFF_ROLES)


def _family_ids(person):
    from accounts.models import FamilyMember

    return list(FamilyMember.objects.filter(person=person, status="active").values_list("pk", flat=True))


def visible_plans(person):
    qs = CarePlan.objects.select_related("country", "client", "family_member", "carer__person")
    if not person.is_authenticated:
        return qs.none()
    if _is_staff(person):
        return scope_to_staff_countries(qs, person)
    fams = _family_ids(person)
    cond = Q(client=person) | Q(carer__person=person)
    if fams:
        cond |= Q(family_member_id__in=fams) | Q(confirmers__overlap=fams)
    return qs.filter(cond).distinct()


def visible_visits(person):
    qs = Visit.objects.select_related("country", "plan__family_member", "plan__client", "carer__person", "checkin",
                                      "checkout")
    if not person.is_authenticated:
        return qs.none()
    if _is_staff(person):
        return scope_to_staff_countries(qs, person)
    fams = _family_ids(person)
    cond = Q(plan__client=person) | Q(carer__person=person)
    if fams:
        cond |= Q(plan__family_member_id__in=fams) | Q(plan__confirmers__overlap=fams)
    return qs.filter(cond).distinct()


def visible_concerns(person):
    qs = Concern.objects.select_related("country", "plan__family_member", "plan__client", "raised_by")
    if not person.is_authenticated:
        return qs.none()
    if has_role(person, "RV", "CM", "AD"):
        return scope_to_staff_countries(qs, person)
    return qs.filter(Q(plan__client=person) | Q(raised_by=person))


def panel(person, country=None):
    qs = Carer.objects.select_related("person", "vetting", "payee", "agency_org", "country")
    if _is_staff(person):
        qs = scope_to_staff_countries(qs, person)
        return qs.filter(country=country) if country else qs
    # a client reads the carers assigned to their own plans
    return qs.filter(plans__client=person).distinct()


def plan_for_client(client, plan_id):
    return CarePlan.objects.filter(pk=plan_id, client=client).first()


def visits_for_carer(person, *, since=None, until=None):
    qs = Visit.objects.filter(carer__person=person, carer__status="active").select_related("plan__family_member")
    if since:
        qs = qs.filter(window_end__gte=since)
    if until:
        qs = qs.filter(window_start__lte=until)
    return qs


def statement(plan: CarePlan) -> dict:
    """Per family member: visits by status and what was paid (for the client's statement)."""
    from django.db.models import Count, Sum

    rows = plan.visits.values("status").annotate(n=Count("id"), total=Sum("fee_amount"))
    return {r["status"]: {"count": r["n"], "amount": f"{r['total'] or 0:.2f}"} for r in rows}
