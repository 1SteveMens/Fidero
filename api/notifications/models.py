"""Notifications (NTF, FR-NTF-001 to 005, FR-APP-002, ADR-20).

Templates per language and channel, preferences, the message log with
delivery events, push devices per app install, family confirmation codes and
the reminder log.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel


class Template(BaseModel):
    """FR-NTF-002: an editable template per code, channel and language. Saving
    makes a new version, used for the next message; old versions are kept."""

    CHANNELS = ["in_app", "email", "sms", "whatsapp", "push"]
    STATUSES = ["active", "retired"]

    code = models.TextField()
    channel = models.TextField(choices=[(c, c) for c in CHANNELS])
    language = models.CharField(max_length=8, default="en")
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")  # null = every country
    version = models.PositiveIntegerField()
    subject = models.TextField(blank=True, default="")
    body = models.TextField()
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    whatsapp_template_name = models.TextField(blank=True, default="")  # the provider-approved template (US-NTF-001b)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "ntf_template"
        ordering = ["code", "channel", "language", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["code", "channel", "language", "country", "version"],
                                    name="ntf_template_version_uq"),
            models.UniqueConstraint(fields=["code", "channel", "language", "version"], condition=Q(country__isnull=True),
                                    name="ntf_template_version_global_uq"),
        ]


class Preference(BaseModel):
    """Per person and channel: on or off, quiet hours, muted categories.
    Money and safety messages always go in-app (catalogue.MANDATORY_IN_APP)."""

    CHANNELS = ["in_app", "email", "sms", "whatsapp", "push"]

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ntf_preferences")
    channel = models.TextField(choices=[(c, c) for c in CHANNELS])
    enabled = models.BooleanField(default=True)
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)
    timezone = models.TextField(blank=True, default="")
    muted_categories = models.JSONField(default=list, blank=True)
    address = models.TextField(blank=True, default="")  # a different phone or email for this channel

    class Meta:
        db_table = "ntf_preference"
        constraints = [models.UniqueConstraint(fields=["person", "channel"], name="ntf_preference_uq")]


class Message(BaseModel):
    """FR-NTF-005: every notification with its channel and delivery status."""

    CHANNELS = ["in_app", "email", "sms", "whatsapp", "push"]
    STATUSES = ["queued", "deferred", "sent", "delivered", "failed", "read", "suppressed"]

    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="messages")
    to_address = models.TextField(blank=True, default="")  # phone or email for people without an account
    channel = models.TextField(choices=[(c, c) for c in CHANNELS], default="in_app")
    template = models.TextField()
    template_version = models.ForeignKey(Template, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    category = models.TextField(default="status")
    language = models.CharField(max_length=8, default="en")
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    subject = models.TextField(blank=True, default="")
    body = models.TextField()
    link = models.TextField(blank=True, default="")
    subject_type = models.TextField(blank=True, default="")
    subject_id = models.TextField(blank=True, default="")
    status = models.TextField(default="queued")  # see STATUSES
    read_at = models.DateTimeField(null=True, blank=True)
    needs_action = models.BooleanField(default=False)  # orange in the apps: needs the client
    action_done_at = models.DateTimeField(null=True, blank=True)
    provider = models.TextField(blank=True, default="")
    provider_ref = models.TextField(blank=True, default="", db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True, default="")
    scheduled_for = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    fallback_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="fallbacks")
    group_id = models.UUIDField(null=True, blank=True, db_index=True)  # the messages of one notify() call

    class Meta:
        db_table = "ntf_message"
        indexes = [models.Index(fields=["person", "status"]), models.Index(fields=["subject_type", "subject_id"]),
                   models.Index(fields=["person", "channel", "read_at"])]


class DeliveryEvent(BaseModel):
    """A provider's delivery report, deduplicated on its event id (7.3)."""

    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="delivery_events")
    provider = models.TextField()
    provider_event_id = models.TextField()
    provider_ref = models.TextField(blank=True, default="")
    status = models.TextField()
    occurred_at = models.DateTimeField(null=True, blank=True)
    raw_sha256 = models.CharField(max_length=64)
    payload = models.JSONField(default=dict)

    class Meta:
        db_table = "ntf_delivery_event"
        constraints = [models.UniqueConstraint(fields=["provider", "provider_event_id"], name="ntf_delivery_uq")]


class PushDevice(BaseModel):
    """FR-APP-002: one row per app install. Revoked at sign-out, account
    deletion or when the provider reports the token invalid."""

    APPS = ["client", "field"]
    PLATFORMS = ["ios", "android"]

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="push_devices")
    app = models.TextField(choices=[(a, a) for a in APPS])
    platform = models.TextField(choices=[(p, p) for p in PLATFORMS])
    provider = models.TextField(default="fcm")  # apns | fcm
    token = models.TextField()  # encrypt at field level in production (10.6)
    token_sha256 = models.CharField(max_length=64)
    install_id = models.TextField(blank=True, default="")
    app_version = models.TextField(blank=True, default="")
    os_version = models.TextField(blank=True, default="")
    last_seen_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "ntf_push_device"
        constraints = [models.UniqueConstraint(fields=["token_sha256"], condition=Q(revoked_at__isnull=True),
                                               name="ntf_push_token_live_uq")]


class ConfirmationCode(BaseModel):
    """ADR-20: a one-time code sent out of band to a person who confirms
    (a family member for a care visit, a client's confirmer for an event
    delivery). The code is stored hashed and never shown to the carer or agent.
    6 digits, 24 hours, 5 tries (assumptions)."""

    STATUSES = ["pending", "pending_check", "confirmed", "disputed", "locked", "expired", "superseded", "cancelled"]

    country = models.ForeignKey("countries.Country", on_delete=models.PROTECT, related_name="+")
    subject_type = models.TextField()
    subject_id = models.TextField()
    purpose = models.TextField(default="care_visit")
    recipient_person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    recipient_name = models.TextField(blank=True, default="")
    to_address = models.TextField(blank=True, default="")
    channel = models.TextField(default="sms")
    summary = models.TextField(blank=True, default="")
    code_hash = models.CharField(max_length=64)
    link_token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_via = models.TextField(blank=True, default="")  # code | link | reply | staff_call
    message = models.ForeignKey(Message, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    call_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    call_outcome = models.TextField(blank=True, default="")
    call_note = models.TextField(blank=True, default="")
    call_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")

    class Meta:
        db_table = "ntf_confirmation_code"
        indexes = [models.Index(fields=["subject_type", "subject_id"]), models.Index(fields=["to_address", "status"])]
        constraints = [models.CheckConstraint(
            condition=Q(call_checked_by__isnull=True) | ~Q(call_checked_by=models.F("call_recorded_by")),
            name="ntf_call_check_other_person")]


CONFIRMATION = state.register("confirmation_code", "ntf_confirmation_code", {
    "pending": {"pending_check", "confirmed", "disputed", "locked", "expired", "superseded", "cancelled"},
    "pending_check": {"confirmed", "disputed", "pending", "cancelled"},
    "locked": {"superseded", "cancelled"},
    "expired": {"superseded", "cancelled"},
})


class Reminder(BaseModel):
    """FR-NTF-003: one row per reminder or overdue alert, so a job run twice
    sends each only once (TC-NTF-003-02)."""

    subject_type = models.TextField()
    subject_id = models.TextField()
    kind = models.TextField()  # due_soon | overdue
    due_on = models.DateField()
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "ntf_reminder"
        constraints = [models.UniqueConstraint(fields=["subject_type", "subject_id", "kind", "due_on"],
                                               name="ntf_reminder_once")]
