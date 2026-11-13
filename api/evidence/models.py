"""Evidence store (EVD): FR-EVD-001 to FR-EVD-006, ADR-04, document 02 sections 6.6 and 10.7.

Every file is stored write-once with its SHA-256 hash, who and what captured
it, when and where, and the subject it belongs to. Rows are never deleted;
only the retention sweep may set `deleted_at`, and only after `retain_until`.
Database triggers in dbsql.py enforce this a second time.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core import state
from core.models import BaseModel, CountryScopedModel


class Evidence(CountryScopedModel):
    SOURCES = ["upload", "field_app", "official_channel", "provider", "generated"]
    PROVENANCE = ["app_captured", "uploaded", "system_generated"]
    SCAN = ["pending", "clean", "rejected"]

    sha256 = models.CharField(max_length=64, db_index=True)
    size_bytes = models.BigIntegerField()
    content_type = models.TextField()
    original_name = models.TextField(blank=True, default="")
    storage_key = models.TextField(unique=True)
    object_version = models.TextField(blank=True, default="")  # S3 version ID in production
    source = models.TextField(choices=[(s, s) for s in SOURCES], default="upload")
    # FR-EVD-006: app_captured only with a verified device signature (set by MOB, never by a client field).
    provenance = models.TextField(choices=[(p, p) for p in PROVENANCE], default="uploaded")
    device_id = models.UUIDField(null=True, blank=True)  # mob_device
    signature_valid = models.BooleanField(null=True, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    captured_at = models.DateTimeField(null=True, blank=True)  # device time
    received_at = models.DateTimeField(default=timezone.now)  # server time
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    position_accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    capture_device = models.TextField(blank=True, default="")  # make and model reported at capture
    device_signature = models.TextField(blank=True, default="")
    scan_status = models.TextField(choices=[(s, s) for s in SCAN], default="pending")
    description = models.TextField(blank=True, default="")
    # The case, project or listing the file belongs to (FR-EVD-001).
    owner_type = models.TextField(blank=True, default="")
    owner_id = models.UUIDField(null=True, blank=True)
    data_class = models.TextField(default="case")
    retain_until = models.DateField(null=True, blank=True)  # mirrors the Object Lock date
    deleted_at = models.DateTimeField(null=True, blank=True)  # set only by the retention sweep
    metadata = models.JSONField(default=dict, blank=True)  # EXIF make, model, time; image size
    phash = models.CharField(max_length=16, blank=True, default="", db_index=True)  # average hash of images

    class Meta:
        db_table = "evd_evidence"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(provenance="app_captured")
                | (models.Q(device_id__isnull=False) & models.Q(signature_valid__isnull=False)),
                name="evd_app_captured_has_device",
            ),
            models.CheckConstraint(condition=models.Q(size_bytes__gte=0), name="evd_size_not_negative"),
        ]

    def __str__(self):
        return f"{self.original_name or self.storage_key} ({self.sha256[:12]})"

    @property
    def is_release_grade(self) -> bool:
        """RUL-08: only app-captured items with a verified signature can back a release."""
        return self.provenance == "app_captured" and bool(self.signature_valid) and self.scan_status == "clean" \
            and self.deleted_at is None


EVIDENCE_SCAN = state.register("evidence_scan", "evd_evidence", {
    "pending": {"clean", "rejected"},
}, field="scan_status")


class EvidenceLink(CountryScopedModel):
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name="links")
    subject_type = models.TextField()  # e.g. 'case', 'report', 'milestone', 'fee_invoice'
    subject_id = models.UUIDField()
    role = models.TextField(default="supporting")  # evidence kind, e.g. 'site_photo', 'official_search_result'
    linked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "evd_link"
        indexes = [models.Index(fields=["subject_type", "subject_id"])]
        constraints = [models.UniqueConstraint(fields=["evidence", "subject_type", "subject_id"],
                                               name="evd_link_once_per_subject")]


class Preview(BaseModel):
    """FR-EVD-004: resized image or compressed video preview, shown by default."""

    KINDS = ["image", "video"]
    STATUS = ["ready", "placeholder", "failed"]
    evidence = models.OneToOneField(Evidence, on_delete=models.PROTECT, related_name="preview")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    status = models.TextField(choices=[(s, s) for s in STATUS])
    storage_key = models.TextField(blank=True, default="")
    content_type = models.TextField(blank=True, default="")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    detail = models.TextField(blank=True, default="")

    class Meta:
        db_table = "evd_preview"


class ScanResult(BaseModel):
    """FR-EVD-005: every scan verdict, including files rejected before storage."""

    evidence = models.ForeignKey(Evidence, null=True, blank=True, on_delete=models.PROTECT, related_name="scans")
    country = models.ForeignKey("countries.Country", on_delete=models.PROTECT, related_name="+")
    sha256 = models.CharField(max_length=64)
    size_bytes = models.BigIntegerField(default=0)
    content_type = models.TextField(blank=True, default="")
    original_name = models.TextField(blank=True, default="")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    scanner = models.TextField()
    verdict = models.TextField(choices=[(v, v) for v in ("clean", "rejected", "pending")])
    detail = models.TextField(blank=True, default="")

    class Meta:
        db_table = "evd_scan_result"


class UploadSlot(CountryScopedModel):
    """POST /v1/uploads: the client declares the file and its SHA-256, then sends the bytes."""

    STATUS = ["open", "completed", "rejected", "expired"]
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    subject_type = models.TextField()
    subject_id = models.UUIDField()
    role = models.TextField(default="supporting")
    expected_sha256 = models.CharField(max_length=64)
    content_type = models.TextField()
    size_bytes = models.BigIntegerField()
    original_name = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    captured_at = models.DateTimeField(null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    position_accuracy_m = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    status = models.TextField(choices=[(s, s) for s in STATUS], default="open")
    expires_at = models.DateTimeField()
    evidence = models.ForeignKey(Evidence, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    rejection_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "evd_upload_slot"


UPLOAD_SLOT = state.register("upload_slot", "evd_upload_slot", {
    "open": {"completed", "rejected", "expired"},
})


class AccessLog(CountryScopedModel):
    """Who opened which evidence, when and how (FR-EVD-003; the released report folder log)."""

    ACTIONS = ["link_issued", "downloaded", "refused", "delete_refused"]
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name="access_log")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    action = models.TextField(choices=[(a, a) for a in ACTIONS])
    variant = models.TextField(blank=True, default="")
    link_expires_at = models.DateTimeField(null=True, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")
    detail = models.TextField(blank=True, default="")

    class Meta:
        db_table = "evd_access_log"
        indexes = [models.Index(fields=["evidence", "created_at"])]


class IssuedDocument(CountryScopedModel):
    """A document Tenmina issued (a released report PDF, a statement), so anyone holding
    it can confirm its fingerprint (FR-RPT-008 by hash only)."""

    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name="issued_as")
    sha256 = models.CharField(max_length=64, db_index=True)
    subject_type = models.TextField()
    subject_id = models.UUIDField()
    kind = models.TextField(default="report_pdf")
    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")

    class Meta:
        db_table = "evd_issued_document"
        constraints = [models.UniqueConstraint(fields=["evidence", "subject_type", "subject_id"],
                                               name="evd_issued_once")]


class FingerprintCheck(BaseModel):
    """Log of public fingerprint checks: only the hash asked and the answer."""

    sha256 = models.CharField(max_length=64)
    matched = models.BooleanField()
    ip_hash = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        db_table = "evd_fingerprint_check"


class IntegrityRun(BaseModel):
    """Daily integrity sampling (10.7 step 7, job evidence.integrity_sample)."""

    seed = models.TextField()
    population = models.PositiveIntegerField(default=0)
    sample_size = models.PositiveIntegerField(default=0)
    checked = models.PositiveIntegerField(default=0)
    mismatches = models.PositiveIntegerField(default=0)
    finished_at = models.DateTimeField(null=True, blank=True)
    triggered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")

    class Meta:
        db_table = "evd_integrity_run"


class IntegrityIncident(CountryScopedModel):
    """A stored object whose bytes no longer match its hash: a security incident."""

    run = models.ForeignKey(IntegrityRun, null=True, blank=True, on_delete=models.PROTECT, related_name="incidents")
    evidence = models.ForeignKey(Evidence, on_delete=models.PROTECT, related_name="incidents")
    expected_sha256 = models.CharField(max_length=64)
    actual_sha256 = models.CharField(max_length=64, blank=True, default="")  # empty when the object is missing
    status = models.TextField(choices=[(s, s) for s in ("open", "resolved")], default="open")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "evd_integrity_incident"


INTEGRITY_INCIDENT = state.register("integrity_incident", "evd_integrity_incident", {"open": {"resolved"}})


class RetentionDeletion(CountryScopedModel):
    """FR-EVD-002: every retention deletion with the rule applied."""

    evidence = models.OneToOneField(Evidence, on_delete=models.PROTECT, related_name="retention_deletion")
    rule = models.TextField()
    retain_until = models.DateField()
    run_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")

    class Meta:
        db_table = "evd_retention_deletion"
