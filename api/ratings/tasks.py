"""RAT background jobs (02 section 7.12): ratings.recompute, nightly."""
from celery import shared_task

from . import services


@shared_task(name="ratings.recompute")
def recompute():
    return services.recompute_all()
