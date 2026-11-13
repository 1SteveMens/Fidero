"""Background jobs (02 section 7.12). Beat schedule: evidence.integrity_sample daily at 01:00 GMT;
evidence.retention_sweep nightly (6.10)."""
from celery import shared_task


@shared_task(name="evidence.integrity_sample")
def integrity_sample(size=None):
    from .services import integrity_sample as run

    r = run(size=size)
    return {"run": str(r.pk), "checked": r.checked, "mismatches": r.mismatches}


@shared_task(name="evidence.retention_sweep")
def retention_sweep():
    from .services import retention_sweep as run

    return {"deleted": len(run())}
