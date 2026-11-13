"""PTR background jobs. Beat schedule: partners.deliver_webhooks every minute."""
from celery import shared_task

from . import services


@shared_task(name="partners.deliver_webhooks")
def deliver_webhooks():
    return services.deliver_due()
