"""Shared kernel tables (document 02, 6.3) and base classes for every module."""
from django.conf import settings
from django.db import models

from .ids import uuid7


class BaseModel(models.Model):
    """uuid7 key, timestamps and optimistic locking (6.1)."""

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    row_version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            self.row_version = (self.row_version or 0) + 1
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = list(set(kwargs["update_fields"]) | {"row_version", "updated_at"})
        super().save(*args, **kwargs)


class CountryScopedModel(BaseModel):
    """Every tenant-scoped row carries country_id (FR-CTY-001)."""

    country = models.ForeignKey("countries.Country", on_delete=models.PROTECT, db_column="country_id", related_name="+")

    class Meta:
        abstract = True


class AllowedTransition(models.Model):
    entity = models.TextField()
    from_status = models.TextField()
    to_status = models.TextField()

    class Meta:
        db_table = "core_allowed_transition"
        constraints = [models.UniqueConstraint(fields=["entity", "from_status", "to_status"], name="core_transition_uq")]


class ApprovalRequest(BaseModel):
    """One approval component for every two-person rule (ADR-12)."""

    SUBJECT_TYPES = [
        "report_release", "escrow_release", "escrow_cancel", "refund", "locked_text_change", "bulk_export",
        "payee_verification", "bank_account_verification", "release_setting_change", "release_rights_grant",
        "country_config_publish", "payment_rights_grant", "pro_rate_card_change", "pro_payment_run",
        "pro_expense_exception", "payee_change", "fee_payment", "care_payment", "errand_payment",
        "repair_release", "event_payment", "insurance_premium", "milestone_release", "project_release",
        "country_activation", "role_grant", "dispute_decision", "legal_hold", "recheck_incident",
        "feature_flag_change", "setting_change", "partner_bank_change",
    ]
    ONE_APPROVER_TYPES = {"pro_rate_card_change", "pro_payment_run", "pro_expense_exception",
                          # "a second administrator" (FR-ADM-003 to 005, 06 2.6, ADR-16): preparer plus one
                          "locked_text_change", "release_setting_change", "country_config_publish",
                          "country_activation", "feature_flag_change", "setting_change", "partner_bank_change"}

    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    required = models.PositiveSmallIntegerField(default=2)
    status = models.TextField(default="open", choices=[(s, s) for s in ("open", "approved", "rejected", "withdrawn")])
    summary = models.TextField(blank=True, default="")
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_approval_request"
        indexes = [models.Index(fields=["subject_type", "subject_id"])]


class Approval(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    request = models.ForeignKey(ApprovalRequest, on_delete=models.PROTECT, related_name="approvals")
    slot = models.TextField()
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decision = models.TextField(choices=[("approve", "approve"), ("reject", "reject")])
    mfa_method = models.TextField(default="totp")
    mfa_at = models.DateTimeField()
    approved_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "core_approval"
        constraints = [
            models.UniqueConstraint(fields=["request", "approver"], name="core_approval_one_person"),
            models.UniqueConstraint(fields=["request", "slot"], name="core_approval_one_slot"),
        ]


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    topic = models.TextField(db_index=True)
    aggregate_id = models.UUIDField(null=True)
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_outbox_event"


class ConsumedEvent(models.Model):
    event_id = models.UUIDField()
    consumer = models.TextField()
    consumed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_consumed_event"
        constraints = [models.UniqueConstraint(fields=["event_id", "consumer"], name="core_consumed_uq")]


class IdempotencyKey(models.Model):
    principal = models.TextField()
    key = models.TextField()
    request_hash = models.TextField()
    response_code = models.PositiveSmallIntegerField(null=True)
    response_body = models.JSONField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "core_idempotency_key"
        constraints = [models.UniqueConstraint(fields=["principal", "key"], name="core_idem_uq")]
