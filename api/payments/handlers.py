"""PAY event subscribers. Every handler is idempotent."""
from core.events import subscribe

from . import services
from .models import FeePayment


@subscribe("approval.approved")
def on_approved(ev):
    p = ev.payload
    if p.get("subject_type") == "refund":
        services.on_refund_approved(p["subject_id"])
    elif p.get("subject_type") == "offline_fee_payment":
        pay = FeePayment.objects.filter(pk=p["subject_id"], status="pending_approval").first()
        if pay is not None:
            services.confirm_payment(pay)


@subscribe("approval.rejected")
def on_rejected(ev):
    p = ev.payload
    if p.get("subject_type") == "refund":
        services.on_refund_rejected(p["subject_id"])
    elif p.get("subject_type") == "offline_fee_payment":
        pay = FeePayment.objects.filter(pk=p["subject_id"], status="pending_approval").first()
        if pay is not None:
            services.fail_payment(pay, "rejected_by_staff")


@subscribe("order.created")
def on_order_created(ev):
    """Checked plots: a seller-paid check is billed to the seller's organisation (FR-PAY-007)."""
    if ev.payload.get("bill_to") == "organisation":
        services.invoice_for_order(ev.payload["order_id"])


@subscribe("listing.submitted")
def on_listing_submitted(ev):
    services.invoice_for_listing(ev.payload, "listing_fee")


@subscribe("listing.sold")
def on_listing_sold(ev):
    services.invoice_for_listing(ev.payload, "success_fee")
