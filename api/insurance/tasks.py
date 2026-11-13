"""INS background jobs (02 section 7.12): insurance.renewal_reminders daily (notifications queue) and
insurance.premium_due daily."""
from celery import shared_task

from . import services


@shared_task(name="insurance.renewal_reminders")
def renewal_reminders():
    return services.renewal_reminders()


@shared_task(name="insurance.premium_due")
def premium_due():
    return services.premium_due()
