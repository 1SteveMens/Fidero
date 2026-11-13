"""DSP background jobs (02 section 7.12): disputes.deadline_tick, hourly."""
from celery import shared_task

from . import services


@shared_task(name="disputes.deadline_tick")
def deadline_tick():
    return services.deadline_tick()
