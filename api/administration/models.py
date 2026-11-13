"""Administration (ADM, FR-ADM-001 to 005, ADR-11, 02 sections 6.8 and 6.9).

Versioned configuration, prices, exchange-rate guides, the partner registry,
locked texts, configurable settings, app versions, feature flags and the
change requests that carry the two-person rules.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

SAFETY_FLAGS_PREFIXES = ("escrow.enabled", "escrow.bank", "escrow.partial", "listings.", "partner_api.", "mobile.",
                         "projects.", "building.", "lines.", "country.", "payments.", "identity.", "geo.")
KILL_SWITCHES = ("maintenance.read_only", "escrow.instructions_paused", "pro.payment_runs_paused")


class FeatureFlag(BaseModel):
    name = models.TextField()
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")  # null = platform value
    enabled = models.BooleanField(default=False)
    value = models.TextField(blank=True, default="")  # for setting-like flags such as app.fee_payment_mode
    owner = models.TextField(blank=True, default="")
    reason = models.TextField(blank=True, default="")
    removal_date = models.DateField(null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "adm_feature_flag"
        constraints = [
            models.UniqueConstraint(fields=["name", "country"], name="adm_flag_country_uq"),
            models.UniqueConstraint(fields=["name"], condition=models.Q(country__isnull=True),
                                    name="adm_flag_platform_uq"),
        ]


class ConfigVersion(BaseModel):
    """ADR-11: each configuration item as JSON with a content hash and a state.
    A published version never changes; new work uses the latest published
    version and existing work keeps the id it started with."""

    KINDS = ["case_template", "report_template", "condition_set", "milestone_schedule", "tier_catalogue",
             "checklist", "status_message_set", "notification_set", "errand_catalogue", "care_plan_template",
             "vetting_checklist", "institution_types", "holiday_calendar"]
    STATES = ["draft", "published", "retired"]

    kind = models.TextField(choices=[(k, k) for k in KINDS])
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")  # null = shareable across countries
    product_line = models.TextField(blank=True, default="")
    version = models.PositiveIntegerField()
    name = models.TextField(blank=True, default="")
    content = models.JSONField(default=dict)
    content_sha256 = models.CharField(max_length=64)
    schema_version = models.TextField(default="1")
    state = models.TextField(default="draft", choices=[(s, s) for s in STATES])
    copied_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "adm_config_version"
        ordering = ["kind", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["kind", "country", "product_line", "version"], name="adm_cfg_version_uq"),
            models.UniqueConstraint(fields=["kind", "product_line", "version"], condition=Q(country__isnull=True),
                                    name="adm_cfg_version_global_uq"),
        ]


CONFIG_VERSION = state.register("config_version", "adm_config_version", {
    "draft": {"published", "retired"},
    "published": {"retired"},
}, field="state")


class Price(CountryScopedModel):
    """FR-ADM-002: Tenmina's fee per country, product line, tier and audience.
    A change closes the old row and opens a new one, so an order keeps the
    price it was quoted (orders copy the amount and this row's id)."""

    product_line = models.TextField(default="land")
    tier = models.TextField()
    audience = models.TextField(default="standard")  # standard | diaspora | local, as the catalogue sets
    price_amount = amount_field()
    price_currency = currency_field()
    valid_from = models.DateTimeField()
    valid_to = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "adm_price"
        ordering = ["product_line", "tier", "-valid_from"]
        constraints = [
            models.CheckConstraint(condition=Q(price_amount__gte=0), name="adm_price_not_negative"),
            models.UniqueConstraint(fields=["country", "product_line", "tier", "audience"],
                                    condition=Q(valid_to__isnull=True), name="adm_price_one_current"),
        ]


class FxRate(CountryScopedModel):
    """FR-ADM-002, RUL-18: exchange-rate guides for display of prices and
    milestone costs. Never used for a quote (FR-ESC-023)."""

    base_currency = currency_field()
    quote_currency = currency_field()
    rate = models.DecimalField(max_digits=18, decimal_places=6)
    rate_date = models.DateField()
    source = models.TextField(default="manual")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "adm_fx_rate"
        ordering = ["base_currency", "quote_currency", "-rate_date", "-created_at"]
        constraints = [models.CheckConstraint(condition=Q(rate__gt=0), name="adm_fx_rate_positive")]


class Partner(CountryScopedModel):
    """FR-ADM-003: the partner registry. Bank details change only through an
    approved change request (a second administrator); a database trigger
    checks this again."""

    KINDS = ["escrow_bank", "payment_provider", "identity", "messaging", "insurer", "institution_portal",
             "developer", "bank_api", "operating_bank", "operating_mobile_money", "registry", "rate_source",
             "transfer_partner", "professional", "contractor", "inspector", "supplier", "api_partner"]
    STATUSES = ["active", "inactive"]

    kind = models.TextField(choices=[(k, k) for k in KINDS])
    name = models.TextField()
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")  # a professional, contractor or inspector
    adapter_port = models.TextField(blank=True, default="")
    adapter_path = models.TextField(blank=True, default="")
    contact_name = models.TextField(blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    licence_number = models.TextField(blank=True, default="")
    licence_body = models.TextField(blank=True, default="")
    is_national_id_system = models.BooleanField(default=False)  # identity partners (RUL-31, IF-03)
    details = models.JSONField(default=dict, blank=True)  # corridors, limits, rate kind, channels, terms
    # Bank details (FR-ADM-003): changed only by an approved change request.
    bank_name = models.TextField(blank=True, default="")
    bank_branch = models.TextField(blank=True, default="")
    account_name = models.TextField(blank=True, default="")
    account_number = models.TextField(blank=True, default="")  # encrypt at field level in production (10.6)
    account_number_bidx = models.CharField(max_length=64, blank=True, default="")
    bank_change_request = models.ForeignKey("ChangeRequest", null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="+")
    deactivated_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "adm_partner"
        ordering = ["kind", "name"]


PARTNER = state.register("partner", "adm_partner", {"active": {"inactive"}, "inactive": {"active"}})


class LockedTextVersion(CountryScopedModel):
    """FR-ADM-004, RUL-04: locked texts. A version is published only after a
    second administrator approves (locked_text_change) and, where the kind
    needs them, the lawyer's and insurer's approvals are recorded."""

    KINDS = ["scope_statement", "terms", "privacy_notice", "escrow_terms"]
    STATUSES = ["draft", "pending_approval", "published", "superseded", "retired"]

    kind = models.TextField(choices=[(k, k) for k in KINDS])
    version = models.PositiveIntegerField()
    title = models.TextField(blank=True, default="")
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    lawyer_approval_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    lawyer_approved_by = models.TextField(blank=True, default="")  # name of the lawyer who approved
    lawyer_approved_at = models.DateTimeField(null=True, blank=True)
    insurer_approval_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                  on_delete=models.PROTECT, related_name="+")
    insurer_approved_by = models.TextField(blank=True, default="")
    insurer_approved_at = models.DateTimeField(null=True, blank=True)
    copied_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "adm_locked_text_version"
        ordering = ["kind", "-version"]
        constraints = [models.UniqueConstraint(fields=["country", "kind", "version"], name="adm_locked_text_uq")]


LOCKED_TEXT = state.register("locked_text", "adm_locked_text_version", {
    "draft": {"pending_approval", "retired"},
    "pending_approval": {"published", "draft"},
    "published": {"superseded"},
})


class ChangeRequest(BaseModel):
    """A change that waits for a second administrator: a release-affecting or
    second-admin setting, a safety flag switched on, a raised minimum app
    version, or a partner's bank details. Nothing changes until it is approved."""

    KINDS = ["setting", "feature_flag", "app_version", "partner_bank"]
    STATUSES = ["pending", "applied", "rejected", "withdrawn"]

    kind = models.TextField(choices=[(k, k) for k in KINDS])
    target = models.TextField()  # setting key, flag name, app/platform, or partner id
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "adm_change_request"
        ordering = ["-created_at"]


CHANGE_REQUEST = state.register("adm_change", "adm_change_request", {
    "pending": {"applied", "rejected", "withdrawn"},
})


class Setting(BaseModel):
    """FR-ADM-005: one configurable value per key and country (null = platform).
    Keys and their ranges are in administration.registry."""

    key = models.TextField()
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    value = models.JSONField()
    affects_release = models.BooleanField(default=False)
    confirmed = models.BooleanField(default=False)  # set by an administrator, not a [TO VERIFY] default
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    change_request = models.ForeignKey(ChangeRequest, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")

    class Meta:
        db_table = "adm_setting"
        ordering = ["key"]
        constraints = [
            models.UniqueConstraint(fields=["key", "country"], name="adm_setting_country_uq"),
            models.UniqueConstraint(fields=["key"], condition=Q(country__isnull=True), name="adm_setting_platform_uq"),
        ]


class AppVersion(BaseModel):
    """FR-APP-006: minimum and latest version per app and platform (8.10)."""

    APPS = ["client", "field"]
    PLATFORMS = ["ios", "android"]

    app = models.TextField(choices=[(a, a) for a in APPS])
    platform = models.TextField(choices=[(p, p) for p in PLATFORMS])
    min_version = models.TextField(default="0.0.0")
    latest_version = models.TextField(default="0.0.0")
    store_url = models.TextField(blank=True, default="")
    previous_min_version = models.TextField(blank=True, default="")
    min_raised_at = models.DateTimeField(null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    change_request = models.ForeignKey(ChangeRequest, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")

    class Meta:
        db_table = "adm_app_version"
        constraints = [models.UniqueConstraint(fields=["app", "platform"], name="adm_app_version_uq")]
