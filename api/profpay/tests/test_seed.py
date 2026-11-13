"""PRO demo data loads and shows journeys in several states."""


def test_seed_states(seeded):
    """FR-PRO-001 to FR-PRO-009: the seed has agreements, payables, claims and runs in several states."""
    from profpay.models import Agreement, ExpenseClaim, Payable, PaymentRun

    assert Agreement.objects.filter(status="active").count() >= 3
    assert Agreement.objects.filter(status="draft").exists()
    statuses = set(Payable.objects.values_list("status", flat=True))
    assert {"paid", "in_run"} <= statuses
    assert set(PaymentRun.objects.values_list("status", flat=True)) & {"partly_confirmed", "confirmed"}
    assert PaymentRun.objects.filter(status="pending_approval").exists()
    assert ExpenseClaim.objects.filter(status="submitted", approved_by__isnull=False).exists()
