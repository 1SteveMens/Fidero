"""TSK background jobs (02 section 7.12)."""
from celery import shared_task


@shared_task(name="errands.target_watch")
def target_watch():
    """Daily: warn when an errand nears or passes its target time (FR-TSK-001)."""
    from .services import target_watch as run

    return run()
