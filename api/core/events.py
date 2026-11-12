"""Transactional outbox and in-process event bus (ADR-08, document 02 4.1 rule 5).

Producers call publish() inside their transaction. Consumers register with
@subscribe("topic") in their module's `handlers.py`, which each AppConfig
imports in ready(). Delivery mode is settings.TENMINA["EVENT_DISPATCH"].
"""
import logging
from collections import defaultdict

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import ConsumedEvent, OutboxEvent

log = logging.getLogger(__name__)
_handlers = defaultdict(list)


def subscribe(*topics):
    def deco(fn):
        for t in topics:
            if fn not in _handlers[t]:
                _handlers[t].append(fn)
        return fn

    return deco


def _jsonable(value):
    import uuid
    from datetime import date, datetime
    from decimal import Decimal

    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def publish(topic: str, aggregate_id=None, payload=None) -> OutboxEvent:
    ev = OutboxEvent.objects.create(topic=topic, aggregate_id=aggregate_id, payload=_jsonable(payload or {}))
    mode = settings.TENMINA.get("EVENT_DISPATCH", "immediate")
    if mode == "immediate":
        dispatch(ev)
    elif mode == "on_commit":
        transaction.on_commit(lambda: dispatch(OutboxEvent.objects.get(pk=ev.pk)))
    return ev


def dispatch(ev: OutboxEvent):
    for fn in list(_handlers.get(ev.topic, [])) + list(_handlers.get("*", [])):
        consumer = f"{fn.__module__}.{fn.__qualname__}"
        try:
            with transaction.atomic():
                ConsumedEvent.objects.create(event_id=ev.id, consumer=consumer)
                fn(ev)
        except IntegrityError:
            log.debug("event %s already consumed by %s", ev.id, consumer)
    OutboxEvent.objects.filter(pk=ev.pk).update(published_at=timezone.now())


def relay_pending(limit=500):
    """Called by the Celery beat relay in production."""
    for ev in OutboxEvent.objects.filter(published_at__isnull=True).order_by("created_at")[:limit]:
        dispatch(ev)
