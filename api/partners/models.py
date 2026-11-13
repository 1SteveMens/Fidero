"""PTR Partner API (document 02: 4.2, 5.6, 6.8, 7.3, 7.8; FR-PTR-001 to FR-PTR-004; RUL-16).

Banks checking collateral and other partners call the API with OAuth 2.0
client credentials. A verdict and date are returned only with the client's
consent for that partner (`dpr_consent` purpose `partner_status`), checked at
read time; the full report only with a specific consent for that report
(`partner_full_report`). Every call is metered (`ptr_usage_event`)."""
import hashlib

from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel

SCOPES = ["plot_status.read", "report.read", "orders.write", "usage.read", "webhooks.manage"]
WEBHOOK_EVENTS = ["verification.status_changed", "order.completed", "consent.withdrawn"]


def secret_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ApiClient(CountryScopedModel):
    """A partner's API credentials: client ID, hashed secret, scopes and rate limits (FR-PTR-004)."""

    STATUSES = ["active", "suspended", "revoked"]

    partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    name = models.TextField()
    client_id = models.CharField(max_length=64, unique=True)
    secret_sha256 = models.CharField(max_length=64)
    secret_rotated_at = models.DateTimeField(null=True, blank=True)
    scopes = models.JSONField(default=list)
    rate_limit_per_minute = models.PositiveIntegerField(default=60)  # [TO VERIFY] per partner contract
    monthly_quota = models.PositiveIntegerField(null=True, blank=True)
    contact_person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")  # the partner's PT user, told when a webhook fails
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "ptr_api_client"
        ordering = ["name"]

    def __str__(self):
        return self.name


API_CLIENT = state.register("ptr_api_client", "ptr_api_client", {
    "active": {"suspended", "revoked"},
    "suspended": {"active", "revoked"},
})


class AccessToken(BaseModel):
    """15-minute bearer token from the client credentials grant (5.6). Only the hash is stored."""

    client = models.ForeignKey(ApiClient, on_delete=models.PROTECT, related_name="tokens")
    token_sha256 = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ptr_access_token"


class UsageEvent(models.Model):
    """One metered call (FR-PTR-004). Append-only."""

    RESULTS = ["ok", "no_report", "in_progress", "report_exists", "verified", "ambiguous", "full_report",
               "consent_missing", "order_created", "refused", "rate_limited", "quota_exceeded", "not_found",
               "invalid"]

    id = models.BigAutoField(primary_key=True)
    client = models.ForeignKey(ApiClient, on_delete=models.PROTECT, related_name="usage")
    country = models.ForeignKey("countries.Country", on_delete=models.PROTECT, related_name="+")
    endpoint = models.TextField()
    method = models.CharField(max_length=8)
    result_class = models.TextField(choices=[(r, r) for r in RESULTS])
    status_code = models.PositiveSmallIntegerField()
    billable = models.BooleanField(default=True)
    billed = models.BooleanField(default=False)  # set only through the month's statement row, never here
    asset_id = models.UUIDField(null=True, blank=True)
    report_id = models.UUIDField(null=True, blank=True)
    consent_id = models.UUIDField(null=True, blank=True)
    order_id = models.UUIDField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "ptr_usage_event"
        indexes = [models.Index(fields=["client", "occurred_at"])]


class UsageStatement(CountryScopedModel):
    """A partner's month, closed for invoicing (US-PTR-004 AC1)."""

    client = models.ForeignKey(ApiClient, on_delete=models.PROTECT, related_name="statements")
    month = models.DateField()  # first day
    call_count = models.PositiveIntegerField()
    billable_count = models.PositiveIntegerField()
    order_count = models.PositiveIntegerField()
    by_result = models.JSONField(default=dict)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "ptr_usage_statement"
        constraints = [models.UniqueConstraint(fields=["client", "month"], name="ptr_one_statement_per_month")]


class PartnerOrder(CountryScopedModel):
    """FR-PTR-003: a partner orders a verification for a consenting client; the client confirms in the portal."""

    STATUSES = ["awaiting_client", "confirmed", "declined", "completed", "cancelled"]

    reference = models.TextField(unique=True)
    client = models.ForeignKey(ApiClient, on_delete=models.PROTECT, related_name="orders")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="partner_orders")
    consent_id = models.UUIDField()
    partner_reference = models.TextField(blank=True, default="")  # the bank's own loan or file number
    asset_type = models.TextField(default="plot")
    locality = models.TextField()
    plot_number = models.TextField(blank=True, default="")
    site_plan_ref = models.TextField(blank=True, default="")
    seller_name = models.TextField(blank=True, default="")
    seller_phone = models.TextField(blank=True, default="")
    tier = models.TextField(blank=True, default="standard")
    order_id = models.UUIDField(null=True, blank=True)  # ord_order once the client confirms
    case_id = models.UUIDField(null=True, blank=True)
    status = models.TextField(default="awaiting_client", choices=[(s, s) for s in STATUSES])
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ptr_partner_order"
        ordering = ["-created_at"]


PARTNER_ORDER = state.register("ptr_partner_order", "ptr_partner_order", {
    "awaiting_client": {"confirmed", "declined", "cancelled"},
    "confirmed": {"completed", "cancelled"},
})


class WebhookSubscription(CountryScopedModel):
    """7.3 outbound webhooks: signed with HMAC-SHA256 over `timestamp.body` with a per-subscription secret."""

    STATUSES = ["active", "failing", "deleted"]

    client = models.ForeignKey(ApiClient, on_delete=models.PROTECT, related_name="webhooks")
    url = models.URLField(max_length=500)
    events = models.JSONField(default=list)
    secret = models.TextField()  # needed to sign; encrypt at field level in production (10.6)
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    failing_since = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ptr_webhook_subscription"


class WebhookDelivery(BaseModel):
    """At least once, exponential back-off for 24 hours (assumption), then failed."""

    STATUSES = ["pending", "delivered", "failed"]

    subscription = models.ForeignKey(WebhookSubscription, on_delete=models.PROTECT, related_name="deliveries")
    event_id = models.UUIDField()
    event_type = models.TextField()
    body = models.TextField()  # minimal envelope with ids only; the partner reads details through the API
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    last_status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    delivered_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])

    class Meta:
        db_table = "ptr_webhook_delivery"
        constraints = [models.UniqueConstraint(fields=["subscription", "event_id"], name="ptr_delivery_once"),
                       models.CheckConstraint(condition=~Q(status="delivered") | Q(delivered_at__isnull=False),
                                              name="ptr_delivered_at")]
