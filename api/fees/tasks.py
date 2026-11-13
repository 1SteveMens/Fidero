"""FEE background jobs (02 section 7.12). The beat schedule should add fees.schedule_due daily at 06:30 GMT,
fees.receipt_overdue daily and fees.institution_reverify monthly."""
from celery import shared_task

from . import services


@shared_task(name="fees.schedule_due")
def schedule_due():
    return services.schedule_due()


@shared_task(name="fees.receipt_overdue")
def receipt_overdue():
    return services.receipt_overdue()


@shared_task(name="fees.institution_reverify")
def institution_reverify():
    return services.institution_reverify()
