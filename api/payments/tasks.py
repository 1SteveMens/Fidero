"""PAY background jobs (02 section 7.12; IF-02 fallback). Beat schedule: tenmina/celery_schedule.py.
`python manage.py pay_jobs pending|settlement` runs the same work by hand."""
from celery import shared_task


@shared_task(name="payments.reconcile_pending")
def reconcile_pending():
    """Every 15 minutes: verify open payment attempts with the provider, time out the rest."""
    from .services import reconcile_pending as run

    return str(run())


@shared_task(name="payments.reconcile")
def reconcile(settlement_date=None):
    """Daily 02:00 GMT: reconcile the provider's settlement against orders (FR-PAY-006)."""
    from datetime import date

    from .services import daily_reconcile

    d = date.fromisoformat(settlement_date) if settlement_date else None
    return [{"country": r.country.code, "date": str(r.settlement_date), "lines": r.line_count, "issues": r.issues}
            for r in daily_reconcile(d)]
