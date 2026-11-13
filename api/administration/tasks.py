"""Scheduled ADM jobs (02 section 7.12). Beat: administration.refresh_fx daily."""
from celery import shared_task


@shared_task(name="administration.refresh_fx")
def refresh_fx():
    from .services import refresh_fx as run

    return len(run())
