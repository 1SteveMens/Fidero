"""NTF jobs (02 section 7.12). Beat: notifications.due_reminders daily 07:00
GMT; notifications.send_deferred every 5 minutes (quiet hours)."""
from celery import shared_task


@shared_task(name="notifications.due_reminders")
def due_reminders():
    from .reminders import run

    return run()


@shared_task(name="notifications.send_deferred")
def send_deferred():
    from .services import send_due

    return send_due()
