"""Evidence store (EVD). Foundation part: tamper-evident evidence records and
links to any subject. Previews, signed links, scanning and integrity
sampling are added by the EVD build."""
from django.conf import settings
from django.db import models

from core.models import CountryScopedModel


class Evidence(CountryScopedModel):
    SOURCES = ["upload", "field_app", "official_channel", "provider", "generated"]
    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.BigIntegerField()
    content_type = models.TextField()
    original_name = models.TextField(blank=True, default="")
    storage_key = models.TextField(unique=True)
    source = models.TextField(choices=[(s, s) for s in SOURCES], default="upload")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    captured_at = models.DateTimeField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    device_signature = models.TextField(blank=True, default="")
    scan_status = models.TextField(default="pending")  # pending | clean | rejected
    description = models.TextField(blank=True, default="")

    class Meta:
        db_table = "evd_evidence"


class EvidenceLink(CountryScopedModel):
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name="links")
    subject_type = models.TextField()  # e.g. 'case', 'report', 'milestone', 'fee_invoice'
    subject_id = models.UUIDField()
    role = models.TextField(default="supporting")  # e.g. 'site_photo', 'receipt', 'official_search'
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "evd_link"
        indexes = [models.Index(fields=["subject_type", "subject_id"])]
