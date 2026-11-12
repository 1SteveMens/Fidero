"""Administration (ADM). Foundation part: feature flags (document 06, 2.6).
Versioned configuration, prices, FX guides, partner registry, locked texts
and settings are added by the ADM build."""
from django.conf import settings
from django.db import models

from core.models import BaseModel

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
