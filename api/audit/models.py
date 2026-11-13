"""Append-only, hash-chained audit log (ADR-05, FR-AUD-001 to 004) and
security event alerts (02 section 10.10)."""
from django.conf import settings
from django.db import models

from core.ids import uuid7


class AuditEvent(models.Model):
    """One entry per create, change, approval, release, export and sign-in.

    Rows are never updated or deleted: a trigger rejects both (dbsql.py) and
    no function in the code base does either (FR-AUD-002).
    """

    ACTOR_KINDS = ["person", "partner", "system"]

    seq = models.BigAutoField(primary_key=True)
    occurred_at = models.DateTimeField()
    actor_id = models.UUIDField(null=True, blank=True)
    actor_label = models.TextField(blank=True, default="")
    actor_kind = models.TextField(default="system", choices=[(k, k) for k in ACTOR_KINDS])
    action = models.TextField(db_index=True)
    entity = models.TextField(db_index=True)
    entity_id = models.TextField(db_index=True)
    country_code = models.CharField(max_length=2, blank=True, default="")
    data = models.JSONField(default=dict)
    # Where from (FR-AUD-001): filled from the request context when there is one.
    origin_ip = models.TextField(blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    trace_id = models.TextField(blank=True, default="")
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = "aud_event"
        ordering = ["seq"]
        indexes = [models.Index(fields=["occurred_at"]), models.Index(fields=["actor_id"])]


class AuditAnchor(models.Model):
    """Anchor of the chain head, copied to a store Tenmina cannot edit
    (Object Lock in production, a write-once local file in development)."""

    seq = models.BigIntegerField()
    hash = models.CharField(max_length=64)
    anchored_at = models.DateTimeField(auto_now_add=True)
    location = models.TextField(default="local")

    class Meta:
        db_table = "aud_anchor"


class ChainCheck(models.Model):
    """One run of the chain verification job (FR-AUD-004)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    ran_at = models.DateTimeField(auto_now_add=True)
    ok = models.BooleanField()
    checked = models.BigIntegerField(default=0)
    broken_at = models.BigIntegerField(null=True, blank=True)
    anchors_ok = models.BooleanField(default=True)
    anchor_problem = models.TextField(blank=True, default="")
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")

    class Meta:
        db_table = "aud_chain_check"
        ordering = ["-ran_at"]


class SecurityAlert(models.Model):
    """An alert raised by a security event (02 section 10.10)."""

    SEVERITIES = ["info", "warning", "high", "critical"]

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    kind = models.TextField(db_index=True)
    severity = models.TextField(choices=[(s, s) for s in SEVERITIES], default="high")
    channel = models.TextField(default="on_call")  # on_call | reviewer | founder
    summary = models.TextField()
    entity = models.TextField(blank=True, default="")
    entity_id = models.TextField(blank=True, default="")
    country_code = models.CharField(max_length=2, blank=True, default="")
    audit_seq = models.BigIntegerField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "aud_security_alert"
        ordering = ["-created_at"]
