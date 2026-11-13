"""Country registry, cells, the routing directory and versioned country
configuration (FR-CTY-001 to 004, ADR-16, 02 section 6.9).

Country is configuration: nothing about Ghana is hard-coded. Rules that
differ by country (currency, ID system, search fees, tax deductions,
errand catalogue, cooling-off, retention, holiday calendar) are read from the
published CountryConfig.data. References to other configuration rows sit
under data["refs"]: {"config_versions": {kind: id}, "locked_texts": {kind: id},
"partners": {port: id}}.
"""
from django.conf import settings
from django.db import models

from core import state
from core.models import BaseModel


class Cell(BaseModel):
    """One complete deployment in one region and account (ADR-16). Global table."""

    name = models.TextField(unique=True)
    aws_region = models.TextField()
    aws_account = models.TextField(blank=True, default="")
    api_host = models.TextField(blank=True, default="")
    portal_host = models.TextField(blank=True, default="")
    data_location_notes = models.TextField(blank=True, default="")
    status = models.TextField(default="active", choices=[(s, s) for s in ("planned", "active", "retired")])

    class Meta:
        db_table = "cty_cell"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Country(BaseModel):
    STATUSES = ["draft", "manual_phase", "validating", "active", "paused"]

    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2, upper case
    name = models.TextField()
    currency = models.CharField(max_length=3)
    timezone = models.TextField(default="UTC")
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    activated_at = models.DateTimeField(null=True, blank=True)
    cell = models.ForeignKey(Cell, null=True, blank=True, on_delete=models.PROTECT, related_name="countries")
    # Data location (FR-CTY-002): where this country's records, evidence and backups live.
    data_location_ruling = models.TextField(blank=True, default="")
    data_location = models.TextField(blank=True, default="")
    evidence_prefix = models.TextField(blank=True, default="")
    backup_location = models.TextField(blank=True, default="")
    kms_key_alias = models.TextField(blank=True, default="")
    current_config = models.ForeignKey("CountryConfig", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    activation_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    # Gate before activation (C-13, AS-13): manual phase and 90-day validation passed.
    manual_phase_started_at = models.DateTimeField(null=True, blank=True)
    validation_started_at = models.DateTimeField(null=True, blank=True)
    gate_passed = models.BooleanField(default=False)
    gate_decided_at = models.DateTimeField(null=True, blank=True)
    gate_decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    gate_note = models.TextField(blank=True, default="")
    gate_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")

    class Meta:
        db_table = "cty_country"
        ordering = ["code"]

    def __str__(self):
        return self.code

    def config(self) -> dict:
        c = self.configs.filter(status="published").order_by("-version").first()
        return c.data if c else {}


COUNTRY = state.register("country", "cty_country", {
    "draft": {"manual_phase"},
    "manual_phase": {"validating", "active", "draft"},
    "validating": {"active", "manual_phase"},
    "active": {"paused"},
    "paused": {"active"},
})


class CountryConfig(BaseModel):
    """A versioned, immutable once published, country configuration pack."""

    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="configs")
    version = models.PositiveIntegerField()
    status = models.TextField(default="draft")  # draft -> pending_approval -> published -> superseded; draft -> retired
    schema_version = models.TextField(default="1")
    data = models.JSONField(default=dict)
    content_sha256 = models.CharField(max_length=64, blank=True, default="")
    copied_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cty_country_config"
        constraints = [models.UniqueConstraint(fields=["country", "version"], name="cty_config_version_uq")]
        ordering = ["country", "-version"]


COUNTRY_CONFIG = state.register("country_config", "cty_country_config", {
    "draft": {"pending_approval", "retired"},
    "pending_approval": {"published", "draft"},
    "published": {"superseded"},
})


class DirectoryEntry(BaseModel):
    """Routes a sign-in or a reference prefix to its cell (ADR-16). Holds a
    blind index, never the email or phone itself. Global table."""

    KINDS = ["signin", "reference_prefix"]
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    key = models.TextField()
    cell = models.ForeignKey(Cell, on_delete=models.PROTECT, related_name="+")
    country = models.ForeignKey(Country, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "cty_directory"
        constraints = [models.UniqueConstraint(fields=["kind", "key"], name="cty_directory_key_uq")]
