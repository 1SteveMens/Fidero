"""CASE Verification cases: read-only queries other modules may use.

- visible_cases(user), visible_tasks(user)   object-level scoping (02 10.4)
- case_for_order(order_id), case(pk)
- latest_fresh_search(asset_id)               ESC's RUL-07 check: registry result date and site check date
- cost_summary(case), cost_per_report(...)    FR-CASE-011, BO-02
- work_queue(user, ...)                       FR-CASE-005, FR-CASE-006
"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from core.permissions import has_role

from .models import OPEN_STATUSES, Case, CostItem, SearchRequest, Task

STAFF = ("CM", "RV")


def _staff_country_ids(user):
    """None means every country; [] means not staff."""
    grants = user.role_grants.filter(revoked_at__isnull=True, role__in=STAFF)
    if grants.filter(country__isnull=True).exists():
        return None
    return list(grants.values_list("country_id", flat=True))


def visible_cases(user):
    """Clients see their own; representatives the case they were named for; staff their countries;
    professionals the cases they are assigned to. Administrators get no case access by default."""
    if not user or not user.is_authenticated:
        return Case.objects.none()
    from accounts.selectors import representative_subject_ids

    q = Q(client=user) | Q(pk__in=representative_subject_ids(user, "case"))
    if has_role(user, *STAFF):
        ids = _staff_country_ids(user)
        if ids is None:
            return Case.objects.all()
        q |= Q(country_id__in=ids)
    q |= Q(pk__in=Task.objects.filter(Q(assignee=user) | Q(second_assignee=user)).values("case_id"))
    return Case.objects.filter(q)


def visible_tasks(user):
    if not user or not user.is_authenticated:
        return Task.objects.none()
    q = Q(assignee=user) | Q(second_assignee=user)
    if has_role(user, *STAFF):
        ids = _staff_country_ids(user)
        if ids is None:
            return Task.objects.all()
        q |= Q(country_id__in=ids)
    return Task.objects.filter(q)


def work_queue(user, *, owner=None, step=None, status=None, include_closed=False):
    """Tasks sorted by due date, overdue first (FR-CASE-005). Professionals see only their own."""
    qs = visible_tasks(user).select_related("case", "assignee", "second_assignee", "case__country")
    if not has_role(user, *STAFF):
        qs = qs.filter(Q(assignee=user) | Q(second_assignee=user))
    if not include_closed:
        qs = qs.filter(status__in=["open", "in_progress"], case__status__in=["in_progress", "on_hold", "in_review"])
    if owner:
        qs = qs.filter(Q(assignee_id=owner) | Q(second_assignee_id=owner)) if owner != "unassigned" \
            else qs.filter(assignee__isnull=True)
    if step:
        qs = qs.filter(step_key=step)
    if status:
        qs = qs.filter(status=status)
    return qs.order_by("due_at", "position")


def case(pk) -> Case | None:
    return Case.objects.filter(pk=pk).first()


def case_for_order(order_id) -> Case | None:
    return Case.objects.filter(order_id=order_id).first()


def cases_for_subject(subject_type, subject_id):
    return Case.objects.filter(subject_type=subject_type, subject_id=subject_id).order_by("-created_at")


def open_cases_for_client(person):
    return Case.objects.filter(client=person, status__in=OPEN_STATUSES)


def latest_fresh_search(asset_id) -> dict | None:
    """RUL-07: the latest completed fresh search on the asset with the registry's result date (from which
    the window is counted) and the date of the site check. None when there is none."""
    c = Case.objects.filter(asset_id=asset_id, product_line="fresh_search", status="completed") \
        .order_by("-closed_at").first()
    if c is None:
        return None
    sr = SearchRequest.objects.filter(case=c, status__in=["result_received", "confirmed"]) \
        .order_by("-registry_result_date").first()
    site = c.tasks.filter(step_key="site_check", status="done").first()
    if sr is None or not sr.usable or site is None:
        return None
    return {"case_id": c.pk, "search_request_id": sr.pk, "registry_result_date": sr.registry_result_date,
            "site_check_date": timezone.localtime(site.completed_at).date(), "completed_at": c.closed_at}


def usable_search(case_obj) -> SearchRequest | None:
    for sr in case_obj.search_requests.exclude(status="rejected").order_by("-registry_result_date"):
        if sr.usable:
            return sr
    return None


def search_blockers(case_obj) -> list[dict]:
    """FR-CASE-016: every search task needs a usable result from the registry's channel."""
    out = []
    for t in case_obj.tasks.filter(search_kind="result").exclude(status="cancelled"):
        if not any(sr.usable for sr in case_obj.search_requests.exclude(status="rejected")):
            out.append({"rule": "RUL-30", "message": f"'{t.title}': no result received from the registry's own "
                                                     "channel."})
    return out


def waiting_fresh_search_orders(asset_id):
    from orders.models import Order

    return Order.objects.filter(kind="fresh_search", status="paid", case_id__isnull=True).filter(
        Q(asset_id=asset_id) | Q(parent_order__asset_id=asset_id))


def cost_summary(case_obj) -> dict:
    by_item = defaultdict(lambda: defaultdict(Decimal))
    totals = defaultdict(Decimal)
    for c in CostItem.objects.filter(case=case_obj):
        by_item[c.item_type][c.currency] += c.amount
        totals[c.currency] += c.amount
    return {"by_item": {k: {cur: f"{v:.2f}" for cur, v in d.items()} for k, d in by_item.items()},
            "totals": {cur: f"{v:.2f}" for cur, v in totals.items()}}


def cost_per_report(country=None, *, since=None, until=None) -> dict:
    """BO-02: total cost of closed report cases divided by their number, per currency."""
    qs = Case.objects.filter(product_line__in=["land", "building"], status="released")
    if country is not None:
        qs = qs.filter(country=country)
    if since:
        qs = qs.filter(closed_at__gte=since)
    if until:
        qs = qs.filter(closed_at__lt=until)
    n = qs.count()
    totals = defaultdict(Decimal)
    for c in CostItem.objects.filter(case__in=qs):
        totals[c.currency] += c.amount
    return {"reports": n, "totals": {k: f"{v:.2f}" for k, v in totals.items()},
            "per_report": {k: f"{(v / n):.2f}" for k, v in totals.items()} if n else {}}


def people_linked_to_case(case_obj) -> set:
    """Everyone who worked on the case or is party to it (RUL-32 re-checks need someone with no link)."""
    ids = set()
    for a, b in case_obj.tasks.values_list("assignee_id", "second_assignee_id"):
        ids |= {a, b}
    ids |= {case_obj.client_id, case_obj.case_manager_id, case_obj.decided_by_id}
    ids |= set(case_obj.parties.values_list("person_id", flat=True))
    ids |= set(case_obj.search_requests.values_list("submitted_by_id", flat=True))
    ids |= set(case_obj.search_requests.values_list("result_received_by_id", flat=True))
    from accounts.models import RepresentativeGrant

    ids |= set(RepresentativeGrant.objects.filter(subject_type="case", subject_id=case_obj.pk)
               .values_list("representative_id", flat=True))
    if case_obj.client_id:
        ids |= set(RepresentativeGrant.objects.filter(client_id=case_obj.client_id)
                   .values_list("representative_id", flat=True))
    ids.discard(None)
    return ids
