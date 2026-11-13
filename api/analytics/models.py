"""ANL Analytics (FR-ANL-001 to FR-ANL-003; 02 sections 4.2 and 7.4).

Metrics are computed on request from every module's tables with read-only
queries (metrics.py); there are no copies of the data here. The one table is
the export log: every CSV that leaves the platform, and every request for an
export of personal data, which goes through the two-person bulk export in
DPR (FR-DPR-005, issue I-11).
"""
from django.conf import settings
from django.db import models

from core.models import BaseModel


class ExportLog(BaseModel):
    """One row per export. Append-only (dbsql.py). `country` is set when the
    export covers one country; `countries` lists them all (empty: every country)."""

    FORMATS = ["csv"]
    STATUSES = ["produced", "sent_for_approval"]
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    countries = models.JSONField(default=list, blank=True)
    metric = models.TextField()
    filters = models.JSONField(default=dict, blank=True)
    format = models.TextField(default="csv", choices=[(f, f) for f in FORMATS])
    status = models.TextField(default="produced", choices=[(s, s) for s in STATUSES])
    row_count = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    suppressed_cells = models.PositiveIntegerField(default=0)
    personal_data = models.BooleanField(default=False)
    bulk_export = models.ForeignKey("dataprotection.BulkExport", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    purpose = models.TextField(blank=True, default="")

    class Meta:
        db_table = "anl_export_log"
        indexes = [models.Index(fields=["requested_by", "-created_at"]), models.Index(fields=["metric"])]
        constraints = [
            # Personal data never leaves as a plain metric CSV: it waits for two approvals in DPR.
            models.CheckConstraint(condition=models.Q(personal_data=False) | models.Q(bulk_export__isnull=False),
                                   name="anl_export_personal_via_dpr"),
            models.CheckConstraint(condition=models.Q(status__in=["produced", "sent_for_approval"]),
                                   name="anl_export_status_valid"),
        ]
