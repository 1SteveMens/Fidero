"""PAY Tenmina fee payments: read-only queries other modules may use."""
from django.db.models import Q

from core.permissions import has_role
from orders.access import organisation_ids, staff_country_ids

from .models import FeePayment, Invoice, Receipt, ReconIssue, Refund, SettlementRun


def _staff_scope(qs, user, field="country"):
    ids = staff_country_ids(user)
    if ids is None:
        return qs
    return qs.filter(**{f"{field}_id__in": ids})


def visible_payments(user):
    qs = FeePayment.objects.select_related("order", "invoice", "country", "payer")
    if not user or not user.is_authenticated:
        return qs.none()
    ids = staff_country_ids(user)
    if ids is None:
        return qs
    cond = Q(payer=user) | Q(order__client=user)
    orgs = organisation_ids(user)
    if orgs:
        cond |= Q(invoice__organisation_id__in=orgs)
    if ids:
        cond |= Q(country_id__in=ids)
    return qs.filter(cond)


def visible_receipts(user):
    return Receipt.objects.filter(payment__in=visible_payments(user)).select_related("payment")


def visible_invoices(user):
    qs = Invoice.objects.select_related("organisation", "country")
    if not user or not user.is_authenticated:
        return qs.none()
    ids = staff_country_ids(user)
    if ids is None:
        return qs
    cond = Q(bill_to_person=user) | Q(organisation_id__in=organisation_ids(user))
    if ids:
        cond |= Q(country_id__in=ids)
    return qs.filter(cond)


def staff_refunds(user):
    if not has_role(user, "CM", "RV", "AD"):
        return Refund.objects.none()
    return _staff_scope(Refund.objects.select_related("payment", "approval_request"), user)


def staff_issues(user):
    if not has_role(user, "CM", "RV", "AD"):
        return ReconIssue.objects.none()
    return _staff_scope(ReconIssue.objects.all(), user)


def staff_runs(user):
    if not has_role(user, "CM", "RV", "AD"):
        return SettlementRun.objects.none()
    return _staff_scope(SettlementRun.objects.all(), user)


def confirmed_payment_for_order(order_id) -> FeePayment | None:
    return FeePayment.objects.filter(order_id=order_id, status__in=["confirmed", "partially_refunded"]).first()


def fee_income(*, country=None, since=None):
    """For ANL: confirmed fee payments less completed refunds, per purpose and currency."""
    from django.db.models import Sum

    qs = FeePayment.objects.filter(status__in=["confirmed", "partially_refunded", "refunded"])
    if country is not None:
        qs = qs.filter(country=country)
    if since is not None:
        qs = qs.filter(confirmed_at__gte=since)
    return list(qs.values("purpose", "currency").annotate(gross=Sum("amount"), refunded=Sum("refunded_amount"))
                .order_by("purpose", "currency"))
