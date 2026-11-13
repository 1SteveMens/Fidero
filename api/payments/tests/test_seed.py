from orders.models import Order, ReferralReward
from payments.models import FeePayment, Invoice, Receipt, ReconIssue, Refund


def test_seed_covers_every_state_and_is_idempotent(seeded):
    """Demo data: orders and payments in several states; a second run adds nothing."""
    statuses = set(Order.objects.values_list("status", flat=True))
    assert {"draft", "awaiting_payment", "paid", "refunded"} <= statuses
    assert {"confirmed", "failed", "pending_approval", "refunded"} <= set(
        FeePayment.objects.values_list("status", flat=True))
    assert {"completed", "requested"} <= set(Refund.objects.values_list("status", flat=True))
    assert {"issued", "paid"} <= set(Invoice.objects.values_list("status", flat=True))
    assert ReconIssue.objects.filter(kind="unmatched_line").exists()
    assert ReferralReward.objects.filter(status="owed").exists()
    counts = [m.objects.count() for m in (Order, FeePayment, Refund, Invoice, Receipt, ReconIssue)]
    import importlib

    for name in ("orders", "payments"):
        importlib.import_module(f"{name}.seed").run(seeded)
    assert counts == [m.objects.count() for m in (Order, FeePayment, Refund, Invoice, Receipt, ReconIssue)]
