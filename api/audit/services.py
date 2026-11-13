"""AUD services: the audit chain (FR-AUD-001 to 004) and security events (02 10.10).

Other modules call `record(...)` for every write that matters and
`security_event(...)` for the events listed in 02 section 10.10.
"""
import hashlib
import json
import logging
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from . import context
from .models import AuditAnchor, AuditEvent, ChainCheck, SecurityAlert

GENESIS = "0" * 64
log = logging.getLogger("tenmina.security")


def _canonical(e: dict) -> str:
    return json.dumps(e, sort_keys=True, separators=(",", ":"), default=str)


def _digest(prev_hash, fields):
    return hashlib.sha256((prev_hash + _canonical(fields)).encode()).hexdigest()


def _fields(*, occurred_at, actor_id, action, entity, entity_id, country_code, data, actor_kind="system",
            origin_ip="", user_agent="", trace_id="") -> dict:
    """The hashed content of an entry. Optional parts join the hash only when
    set, so entries written before they existed still verify."""
    f = {
        "occurred_at": occurred_at, "actor_id": actor_id, "action": action, "entity": entity,
        "entity_id": entity_id, "country_code": country_code, "data": data,
    }
    if actor_kind and actor_kind != "system":
        f["actor_kind"] = actor_kind
    for k, v in (("origin_ip", origin_ip), ("user_agent", user_agent), ("trace_id", trace_id)):
        if v:
            f[k] = v
    return f


def _fields_of(e: AuditEvent) -> dict:
    return _fields(occurred_at=e.occurred_at.isoformat(), actor_id=str(e.actor_id) if e.actor_id else None,
                   action=e.action, entity=e.entity, entity_id=e.entity_id, country_code=e.country_code,
                   data=e.data, actor_kind=e.actor_kind, origin_ip=e.origin_ip, user_agent=e.user_agent,
                   trace_id=e.trace_id)


def record(*, actor=None, action: str, entity: str, entity_id, data=None, country=None, actor_kind=None,
           origin=None) -> AuditEvent:
    """Append one entry in the caller's transaction. Serialised by an advisory
    lock so the chain is linear. If this fails, the caller's change fails too
    (TC-AUD-001-02).

    `origin` is {"ip", "user_agent", "trace_id"}; by default it comes from the
    current request (audit.context)."""
    from core.events import _jsonable

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(7311)")
        last = AuditEvent.objects.order_by("-seq").only("hash").first()
        prev = last.hash if last else GENESIS
        now = timezone.now()
        org = origin or context.current()
        kind = actor_kind or ("person" if actor is not None and getattr(actor, "pk", None) else "system")
        country_code = getattr(country, "code", country) or ""
        fields = _fields(
            occurred_at=now.isoformat(),
            actor_id=str(actor.pk) if actor is not None and getattr(actor, "pk", None) else None,
            action=action, entity=entity, entity_id=str(entity_id), country_code=str(country_code).upper(),
            data=_jsonable(data or {}), actor_kind=kind, origin_ip=org.get("ip", ""),
            user_agent=org.get("user_agent", ""), trace_id=org.get("trace_id", ""),
        )
        return AuditEvent.objects.create(
            occurred_at=now, actor_id=fields["actor_id"], actor_kind=kind,
            actor_label=(getattr(actor, "full_name", "") or getattr(actor, "email", "")) if actor else "system",
            action=action, entity=entity, entity_id=fields["entity_id"], country_code=fields["country_code"],
            data=fields["data"], origin_ip=org.get("ip", ""), user_agent=org.get("user_agent", ""),
            trace_id=org.get("trace_id", ""), prev_hash=prev, hash=_digest(prev, fields),
        )


def entry_ok(e: AuditEvent) -> bool:
    """The entry's own hash matches its content and its stated predecessor."""
    return _digest(e.prev_hash, _fields_of(e)) == e.hash


def verify_chain() -> dict:
    """FR-AUD-004: recompute every hash. Returns {"ok": bool, "checked": n, "broken_at": seq|None}."""
    prev = GENESIS
    n = 0
    for e in AuditEvent.objects.order_by("seq").iterator():
        if e.prev_hash != prev or _digest(prev, _fields_of(e)) != e.hash:
            return {"ok": False, "checked": n, "broken_at": e.seq}
        prev = e.hash
        n += 1
    return {"ok": True, "checked": n, "broken_at": None}


def verify_anchors() -> tuple[bool, str]:
    """Each anchor must still match the entry at its sequence number, so a
    removed or rewritten tail is found even if the chain recomputes."""
    from core.adapters import get_adapter

    store = get_adapter("audit_anchor_store", default="audit.adapters.LocalAnchorStore")
    for a in AuditAnchor.objects.order_by("seq"):
        e = AuditEvent.objects.filter(seq=a.seq).first()
        if e is None or e.hash != a.hash:
            return False, f"Anchor at entry {a.seq} no longer matches the log."
        if not store.check(a.location, a.seq, a.hash):
            return False, f"Anchor copy for entry {a.seq} is missing or changed."
    return True, ""


def run_chain_check(by=None) -> ChainCheck:
    """The daily verification job (07.12 audit.verify_chain). A failure raises
    a critical security alert."""
    res = verify_chain()
    anchors_ok, problem = verify_anchors()
    chk = ChainCheck.objects.create(ok=res["ok"] and anchors_ok, checked=res["checked"], broken_at=res["broken_at"],
                                    anchors_ok=anchors_ok, anchor_problem=problem, triggered_by=by)
    if not chk.ok:
        security_event("audit.chain_broken", actor=by, entity="aud_chain_check", entity_id=chk.pk,
                       data={"broken_at": res["broken_at"], "anchor_problem": problem},
                       summary="The audit chain failed verification.")
    else:
        record(actor=by, action="audit.chain_verified", entity="aud_chain_check", entity_id=chk.pk,
               data={"checked": res["checked"]})
    return chk


def anchor() -> AuditAnchor | None:
    """Write the chain head to the write-once anchor store (07.12 audit.anchor_head)."""
    from core.adapters import get_adapter

    last = AuditEvent.objects.order_by("-seq").first()
    if not last:
        return None
    existing = AuditAnchor.objects.filter(seq=last.seq).first()
    if existing:
        return existing
    store = get_adapter("audit_anchor_store", default="audit.adapters.LocalAnchorStore")
    location = store.put(last.seq, last.hash)
    return AuditAnchor.objects.create(seq=last.seq, hash=last.hash, location=location)


def trail(entity: str, entity_id) -> list[AuditEvent]:
    return list(AuditEvent.objects.filter(entity=entity, entity_id=str(entity_id)).order_by("seq"))


def export_trail(entity: str, entity_id, *, by=None) -> dict:
    """An entity's full trail as a signed-off extract. The export itself is
    logged (FR-AUD-001, US-AUD-001 criterion 2)."""
    from .serializers import AuditEventSerializer

    rows = trail(entity, entity_id)
    items = AuditEventSerializer(rows, many=True).data
    body = json.loads(json.dumps(items, default=str))
    digest = hashlib.sha256(_canonical(body).encode()).hexdigest()
    intact = all(entry_ok(e) for e in rows)
    record(actor=by, action="audit.exported", entity=entity, entity_id=entity_id,
           data={"entries": len(rows), "sha256": digest})
    return {"entity": entity, "entity_id": str(entity_id), "exported_at": timezone.now(), "entries": len(rows),
            "entries_intact": intact, "sha256": digest, "items": body}


# --- Security events (02 section 10.10) -------------------------------------

ALWAYS = "always"
# kind -> (mode, severity, channel, threshold, window_minutes, group_by_entity)
SECURITY_RULES = {
    "signin.failed": (None, "info", "on_call", 0, 0, False),
    "signin.succeeded": (None, "info", "on_call", 0, 0, False),
    "account.locked": ("threshold", "warning", "on_call", 3, 10, False),
    "mfa.enrolled": (None, "info", "on_call", 0, 0, False),
    "mfa.removed": (ALWAYS, "high", "on_call", 0, 0, False),
    "role.granted": (ALWAYS, "high", "on_call", 0, 0, False),
    "role.revoked": (ALWAYS, "high", "on_call", 0, 0, False),
    "payee.created": (ALWAYS, "high", "reviewer", 0, 0, False),
    "payee.verified": (ALWAYS, "high", "reviewer", 0, 0, False),
    "payee.changed": (ALWAYS, "high", "reviewer", 0, 0, False),
    "payee.suspended": (ALWAYS, "high", "reviewer", 0, 0, False),
    "payee_change.requested": (ALWAYS, "high", "reviewer", 0, 0, False),
    "payee_change.applied": (ALWAYS, "high", "reviewer", 0, 0, False),
    "payee_change.stopped": (ALWAYS, "high", "reviewer", 0, 0, False),
    "national_id.no_match": (ALWAYS, "high", "reviewer", 0, 0, False),
    "recheck.failed": (ALWAYS, "critical", "founder", 0, 0, False),
    "incident.opened": (ALWAYS, "critical", "founder", 0, 0, False),
    "confirmation_code.failed": ("threshold", "warning", "reviewer", 3, 24 * 60, True),
    "confirmation_code.locked": (ALWAYS, "high", "reviewer", 0, 0, False),
    "country_config.published": (ALWAYS, "high", "on_call", 0, 0, False),
    "country.activated": (ALWAYS, "high", "on_call", 0, 0, False),
    "approval.out_of_hours": (ALWAYS, "warning", "on_call", 0, 0, False),
    "evidence.rejected": (ALWAYS, "high", "on_call", 0, 0, False),
    "audit.chain_broken": (ALWAYS, "critical", "on_call", 0, 0, False),
    "partner_bank.changed": (ALWAYS, "high", "founder", 0, 0, False),
    "feature_flag.changed": (ALWAYS, "warning", "on_call", 0, 0, False),
    "min_app_version.changed": (ALWAYS, "warning", "on_call", 0, 0, False),
    "access.cross_country_refused": ("threshold", "warning", "on_call", 5, 60, False),
    "partner.consent_failed": ("threshold", "warning", "on_call", 5, 60, False),
}


# Bursts across entities: kind -> (count, window_minutes), alerted once per window.
SECURITY_BURSTS = {"confirmation_code.failed": (10, 60), "signin.failed": (50, 10)}


def security_event(kind: str, *, actor=None, entity="security", entity_id="", data=None, country=None,
                   summary="", defer=False) -> AuditEvent | None:
    """Log a security event to the audit log and the security logger, and raise
    an alert when the rule for `kind` says so. Unknown kinds are logged and
    alerted, which errs on the safe side.

    `defer=True` for a refusal: the entry is written after the request ends,
    so it survives the rollback of the refused request (audit.context.defer)."""
    if defer:
        context.defer(lambda: security_event(kind, actor=actor, entity=entity, entity_id=entity_id, data=data,
                                             country=country, summary=summary))
        log.warning("security event %s entity=%s:%s (deferred)", kind, entity, entity_id)
        return None
    entry = record(actor=actor, action=f"security.{kind}", entity=entity, entity_id=entity_id, data=data,
                   country=country)
    log.warning("security event %s entity=%s:%s data=%s", kind, entity, entity_id, data)
    mode, severity, channel, threshold, window, by_entity = SECURITY_RULES.get(
        kind, (ALWAYS, "high", "on_call", 0, 0, False))
    if kind in SECURITY_BURSTS:
        n, minutes = SECURITY_BURSTS[kind]
        since = timezone.now() - timedelta(minutes=minutes)
        if AuditEvent.objects.filter(action=f"security.{kind}", occurred_at__gte=since).count() == n:
            raise_alert(f"{kind}_burst", severity="high", channel=channel,
                        summary=f"{n} or more {kind.replace('.', ' ').replace('_', ' ')} events within {minutes} minutes",
                        entity=entity, entity_id=entity_id, country=country, audit_seq=entry.seq)
    if mode is None:
        return entry
    if mode == "threshold":
        since = timezone.now() - timedelta(minutes=window)
        qs = AuditEvent.objects.filter(action=f"security.{kind}", occurred_at__gte=since)
        if by_entity:
            qs = qs.filter(entity=entity, entity_id=str(entity_id))
        if qs.count() != threshold:  # alert once, when the threshold is reached
            return entry
    raise_alert(kind, severity=severity, channel=channel, summary=summary or kind.replace(".", " ").replace("_", " "),
                entity=entity, entity_id=entity_id, country=country, audit_seq=entry.seq)
    return entry


def raise_alert(kind, *, severity="high", channel="on_call", summary="", entity="", entity_id="", country=None,
                audit_seq=None) -> SecurityAlert:
    from core.events import publish

    alert = SecurityAlert.objects.create(kind=kind, severity=severity, channel=channel, summary=summary,
                                         entity=entity, entity_id=str(entity_id or ""),
                                         country_code=(getattr(country, "code", country) or ""),
                                         audit_seq=audit_seq)
    publish("security.alert_raised", alert.pk, {"alert_id": alert.pk, "kind": kind, "severity": severity,
                                                "channel": channel})
    _notify_alert(alert)
    return alert


def _notify_alert(alert: SecurityAlert):
    """In-app alert to administrators, plus reviewers for the reviewer channel."""
    try:
        from accounts.models import Person
        from notifications.services import notify
    except ImportError:  # pragma: no cover
        return
    roles = ["AD"] + (["RV"] if alert.channel in ("reviewer", "founder") else [])
    people = Person.objects.filter(role_grants__role__in=roles, role_grants__revoked_at__isnull=True,
                                   is_active=True).distinct()
    for p in people:
        notify(p, "security_alert", body=f"Security alert: {alert.summary}.", subject="Security alert",
               link=f"/back-office/security-alerts/{alert.pk}", channels=("in_app",), category="safety",
               needs_action=False)


def acknowledge_alert(alert: SecurityAlert, by, note="") -> SecurityAlert:
    if alert.acknowledged_at:
        return alert
    alert.acknowledged_by, alert.acknowledged_at, alert.note = by, timezone.now(), note
    alert.save(update_fields=["acknowledged_by", "acknowledged_at", "note"])
    record(actor=by, action="security_alert.acknowledged", entity="aud_security_alert", entity_id=alert.pk,
           data={"kind": alert.kind})
    return alert
