import hashlib
import json

from django.db import connection, transaction
from django.utils import timezone

from .models import AuditAnchor, AuditEvent

GENESIS = "0" * 64


def _canonical(e: dict) -> str:
    return json.dumps(e, sort_keys=True, separators=(",", ":"), default=str)


def _digest(prev_hash, fields):
    return hashlib.sha256((prev_hash + _canonical(fields)).encode()).hexdigest()


def record(*, actor=None, action: str, entity: str, entity_id, data=None, country=None) -> AuditEvent:
    """Append one entry. Serialised by an advisory lock so the chain is linear."""
    from core.events import _jsonable

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7311)")
        last = AuditEvent.objects.order_by("-seq").only("hash").first()
        prev = last.hash if last else GENESIS
        now = timezone.now()
        fields = {
            "occurred_at": now.isoformat(),
            "actor_id": str(actor.pk) if actor is not None and getattr(actor, "pk", None) else None,
            "action": action,
            "entity": entity,
            "entity_id": str(entity_id),
            "country_code": getattr(country, "code", "") or "",
            "data": _jsonable(data or {}),
        }
        return AuditEvent.objects.create(
            occurred_at=now, actor_id=fields["actor_id"],
            actor_label=(getattr(actor, "full_name", "") or getattr(actor, "email", "")) if actor else "system",
            action=action, entity=entity, entity_id=fields["entity_id"], country_code=fields["country_code"],
            data=fields["data"], prev_hash=prev, hash=_digest(prev, fields),
        )


def verify_chain() -> dict:
    """FR-AUD-003: recompute every hash. Returns {"ok": bool, "checked": n, "broken_at": seq|None}."""
    prev = GENESIS
    n = 0
    for e in AuditEvent.objects.order_by("seq").iterator():
        fields = {
            "occurred_at": e.occurred_at.isoformat(), "actor_id": str(e.actor_id) if e.actor_id else None,
            "action": e.action, "entity": e.entity, "entity_id": e.entity_id,
            "country_code": e.country_code, "data": e.data,
        }
        if e.prev_hash != prev or _digest(prev, fields) != e.hash:
            return {"ok": False, "checked": n, "broken_at": e.seq}
        prev = e.hash
        n += 1
    return {"ok": True, "checked": n, "broken_at": None}


def anchor() -> AuditAnchor | None:
    last = AuditEvent.objects.order_by("-seq").first()
    if not last:
        return None
    return AuditAnchor.objects.create(seq=last.seq, hash=last.hash)


def trail(entity: str, entity_id) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(entity=entity, entity_id=str(entity_id)).order_by("seq"))
