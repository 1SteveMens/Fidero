"""Country registry and versioned country configuration (FR-CTY-001 to 004, ADR-16).

Country is configuration: nothing about Ghana is hard-coded. Rules that
differ by country (currency, ID system, search fees, tax deductions,
errand catalogue, cooling-off, retention) are read from the published
CountryConfig.data.
"""
from django.conf import settings
from django.db import models

from core import state
from core.models import BaseModel


class Country(BaseModel):
    code = models.CharField(max_length=2, unique=True)  # ISO 3166-1 alpha-2, upper case
    name = models.TextField()
    currency = models.CharField(max_length=3)
    timezone = models.TextField(default="Africa/Accra")
    status = models.TextField(default="draft")  # draft -> manual_phase -> active -> paused
    activated_at = models.DateTimeField(null=True, blank=True)
    cell = models.TextField(default="af-south-1")
    data_location_ruling = models.TextField(blank=True, default="")

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
    "manual_phase": {"active", "draft"},
    "active": {"paused"},
    "paused": {"active"},
})


class CountryConfig(BaseModel):
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="configs")
    version = models.PositiveIntegerField()
    status = models.TextField(default="draft")  # draft -> pending_approval -> published -> superseded
    data = models.JSONField(default=dict)
    copied_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "cty_country_config"
        constraints = [models.UniqueConstraint(fields=["country", "version"], name="cty_config_version_uq")]


COUNTRY_CONFIG = state.register("country_config", "cty_country_config", {
    "draft": {"pending_approval"},
    "pending_approval": {"published", "draft"},
    "published": {"superseded"},
})
