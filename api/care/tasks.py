"""CARE background jobs (02 section 7.12)."""
from celery import shared_task


@shared_task(name="care.visit_reminders")
def visit_reminders():
    """Daily 06:00 GMT and 2 hours before a window: create visits from plan schedules, remind the carer, tell the
    family who to expect."""
    from .services import visit_reminders as run

    return run()


@shared_task(name="care.missed_and_unconfirmed")
def missed_and_unconfirmed():
    """Every 15 minutes: missed, unconfirmed after 24 hours, to a reviewer at 72 hours (FR-CARE-004, -005)."""
    from .services import missed_and_unconfirmed as run

    return run()


@shared_task(name="care.weekly_payment_batch")
def weekly_payment_batch():
    """Weekly (assumption): instructions for confirmed, uninstructed visits (FR-CARE-004)."""
    from .services import payment_batch

    out = payment_batch()
    return {k: len(v) for k, v in out.items()}
