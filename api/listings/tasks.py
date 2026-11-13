"""LST background jobs (02 section 7.12): listings.expire_badges and listings.lapse_reservations, hourly."""
from celery import shared_task

from . import services


@shared_task(name="listings.expire_badges")
def expire_badges():
    return services.expire_badges()


@shared_task(name="listings.lapse_reservations")
def lapse_reservations():
    return services.lapse_reservations()
