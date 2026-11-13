"""Shared-kernel background jobs (02 section 7.12). Beat schedule: tenmina/celery_schedule.py."""
from datetime import timedelta

from celery import shared_task

IDEMPOTENCY_KEY_HOURS = 24  # 02 section 7.1, assumption


@shared_task(name="core.relay_outbox")
def relay_outbox(limit=500):
    """Publish outbox events not yet dispatched (ADR-08). In development and tests events dispatch at once, so
    this usually finds nothing to do. Returns the number published."""
    from .events import relay_pending
    from .models import OutboxEvent

    before = OutboxEvent.objects.filter(published_at__isnull=True).count()
    relay_pending(limit=limit)
    return before - OutboxEvent.objects.filter(published_at__isnull=True).count()


@shared_task(name="core.purge_idempotency")
def purge_idempotency(hours=IDEMPOTENCY_KEY_HOURS):
    """Remove Idempotency-Key records older than the keep time (02 section 7.1)."""
    from django.utils import timezone

    from .models import IdempotencyKey

    deleted, _ = IdempotencyKey.objects.filter(created_at__lt=timezone.now() - timedelta(hours=hours)).delete()
    return deleted
