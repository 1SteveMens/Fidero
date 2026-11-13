"""Background jobs (02 section 7.12). Signature and fraud checks (mobile.verify_evidence) run inline at
`complete`; the beat schedule runs mobile.missing_checkouts at the end of each day."""
from celery import shared_task


@shared_task(name="mobile.missing_checkouts")
def missing_checkouts():
    from .services import missing_checkouts as run

    return {"reported": len(run())}
