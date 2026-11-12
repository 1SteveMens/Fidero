"""Append-only, hash-chained audit log (ADR-05, FR-AUD-001 to 004)."""
from django.db import models


class AuditEvent(models.Model):
    seq = models.BigAutoField(primary_key=True)
    occurred_at = models.DateTimeField()
    actor_id = models.UUIDField(null=True, blank=True)
    actor_label = models.TextField(blank=True, default="")
    action = models.TextField(db_index=True)
    entity = models.TextField(db_index=True)
    entity_id = models.TextField(db_index=True)
    country_code = models.CharField(max_length=2, blank=True, default="")
    data = models.JSONField(default=dict)
    prev_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        db_table = "aud_event"
        ordering = ["seq"]


class AuditAnchor(models.Model):
    """Daily anchor of the chain head, copied to a store Tenmina cannot edit."""

    seq = models.BigIntegerField()
    hash = models.CharField(max_length=64)
    anchored_at = models.DateTimeField(auto_now_add=True)
    location = models.TextField(default="local")

    class Meta:
        db_table = "aud_anchor"
