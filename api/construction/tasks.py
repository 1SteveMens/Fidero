"""BLD background jobs (02 section 7.12). Beat schedule: tenmina/celery_schedule.py."""
from celery import shared_task


@shared_task(name="construction.remind_clients")
def remind_clients():
    """Daily: remind clients to approve inspected milestones. Silence is never approval (RUL-11, Q-13)."""
    from .milestones import remind_clients as run

    return run()
