"""ORD event subscribers. Every handler is idempotent."""
from core.events import subscribe

from . import services


@subscribe("payment.confirmed", "payment.offline_recorded")
def on_payment_confirmed(ev):
    """FR-ORD-004: the order is paid only when PAY confirms (provider or offline with proof)."""
    p = ev.payload
    if p.get("order_id"):
        services.mark_paid(p["order_id"], payment_id=p.get("payment_id"), method=p.get("method", ""))


@subscribe("payment.failed")
def on_payment_failed(ev):
    p = ev.payload
    if p.get("order_id"):
        services.note_payment(p["order_id"], "failed", p.get("message", ""))


@subscribe("refund.completed")
def on_refund_completed(ev):
    p = ev.payload
    if p.get("order_id") and p.get("payment_fully_refunded"):
        services.mark_refunded(p["order_id"])


@subscribe("case.created")
def on_case_created(ev):
    p = ev.payload
    if p.get("order_id") and (p.get("case_id") or p.get("id")):
        services.attach_case(p["order_id"], p.get("case_id") or p.get("id"))
