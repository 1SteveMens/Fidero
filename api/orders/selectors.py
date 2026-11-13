"""ORD Orders: read-only queries other modules may use."""
from django.db.models import Count, Q

from core.permissions import has_role

from .access import scope
from .models import Order, ReferralCode, ReferralReward


def get(order_id) -> Order | None:
    return Order.objects.select_related("country", "client").filter(pk=order_id).first()


def visible_orders(user):
    return scope(Order.objects.select_related("country", "client", "referral_code"), user)


def for_client(person):
    return Order.objects.filter(client=person)


def is_paid(order_id) -> bool:
    return Order.objects.filter(pk=order_id, status="paid").exists()


def lead_source_summary(*, country=None, since=None):
    """FR-ORD-005, BR-16: orders and paid orders per lead source, for the founder's dashboard (ANL)."""
    qs = Order.objects.exclude(status="draft")
    if country is not None:
        qs = qs.filter(country=country)
    if since is not None:
        qs = qs.filter(submitted_at__gte=since)
    rows = (qs.values("lead_source")
            .annotate(orders=Count("id"), paid=Count("id", filter=Q(status__in=["paid", "refunded"])))
            .order_by("lead_source"))
    return [{"lead_source": r["lead_source"] or "unknown", "orders": r["orders"], "paid": r["paid"]} for r in rows]


def visible_rewards(user):
    qs = ReferralReward.objects.select_related("referral_code", "order")
    if not user or not user.is_authenticated:
        return qs.none()
    if has_role(user, "CM", "AD"):
        return scope(qs, user, client_field="referrer", org_field=None)
    return qs.filter(referrer=user)


def visible_codes(user):
    if not user or not user.is_authenticated:
        return ReferralCode.objects.none()
    if has_role(user, "CM", "AD"):
        return scope(ReferralCode.objects.all(), user, client_field="owner", org_field=None)
    return ReferralCode.objects.filter(owner=user)
