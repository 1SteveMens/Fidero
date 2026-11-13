"""DPR Data protection (FR-DPR-001 to 005, FR-APP-004; 02 sections 6.7,
6.8, 6.10 and 10.9). Privacy notice versions and acceptances, consents
(video, partner sharing, case studies, marketing), access, correction,
erasure and in-app deletion requests, retention rules and runs, legal
holds, bulk exports, the data catalogue and data locations."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core import state
from core.models import BaseModel, CountryScopedModel

DATA_CLASSES = ["case", "consent_recordings", "escrow_payment", "professional_payables", "account", "safety",
                "health_care", "tenancy", "identity_documents", "insurance", "audit", "marketing", "family",
                "payee"]


class PrivacyNotice(BaseModel):
    """Versioned plain-language privacy notice (FR-DPR-001). A country row
    overrides the platform row (country null)."""

    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    version = models.TextField()
    title = models.TextField(default="How Tenmina uses your data")
    summary = models.TextField(blank=True, default="")
    text = models.TextField()
    status = models.TextField(default="draft", choices=[(s, s) for s in ("draft", "published", "retired")])
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")

    class Meta:
        db_table = "dpr_privacy_notice"
        constraints = [models.UniqueConstraint(fields=["country", "version"], name="dpr_notice_version_uq")]


PRIVACY_NOTICE = state.register("privacy_notice", "dpr_privacy_notice", {
    "draft": {"published"},
    "published": {"retired"},
})


class PrivacyAcceptance(BaseModel):
    """Acceptance of one notice version (append-only)."""

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    notice = models.ForeignKey(PrivacyNotice, on_delete=models.PROTECT, related_name="acceptances")
    version = models.TextField()
    accepted_at = models.DateTimeField(default=timezone.now)
    ip = models.TextField(blank=True, default="")
    source = models.TextField(default="portal")  # signup | invitation | portal | app

    class Meta:
        db_table = "dpr_privacy_acceptance"
        constraints = [models.UniqueConstraint(fields=["person", "notice"], name="dpr_acceptance_once")]


class Consent(CountryScopedModel):
    """02 section 6.7. Video consent must name its recording; partner
    consents name the partner; a full report consent names the report."""

    PURPOSES = ["privacy_notice", "video_recording", "partner_status", "partner_full_report", "case_study",
                "marketing"]
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    subject_name = models.TextField(blank=True, default="")  # people without accounts, e.g. family heads
    subject_phone = models.CharField(max_length=32, blank=True, default="")
    purpose = models.TextField(choices=[(p, p) for p in PURPOSES])
    text_version = models.TextField()
    partner_client_id = models.UUIDField(null=True, blank=True)  # ptr_api_client when PTR has it
    report_id = models.UUIDField(null=True, blank=True)  # rpt_report when RPT has it
    case_id = models.UUIDField(null=True, blank=True)
    recording_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="+")
    role_in_recording = models.TextField(blank=True, default="")  # seller, family head, witness, ...
    given_at = models.DateTimeField(default=timezone.now)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    withdrawn_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")

    class Meta:
        db_table = "dpr_consent"
        indexes = [models.Index(fields=["partner_client_id", "person"]),
                   models.Index(fields=["recording_evidence"])]
        constraints = [
            models.CheckConstraint(condition=~models.Q(purpose="video_recording") | models.Q(
                recording_evidence__isnull=False), name="dpr_consent_video_has_recording"),
            models.CheckConstraint(condition=~models.Q(purpose__in=["partner_status", "partner_full_report"])
                                   | models.Q(
                partner_client_id__isnull=False), name="dpr_consent_partner_named"),
            models.CheckConstraint(condition=~models.Q(purpose="partner_full_report") | models.Q(
                report_id__isnull=False), name="dpr_consent_report_named"),
            models.CheckConstraint(condition=models.Q(person__isnull=False) | ~models.Q(subject_name=""),
                                   name="dpr_consent_has_subject"),
        ]


class DataRequest(CountryScopedModel):
    """Access, correction, erasure and in-app deletion requests (FR-DPR-003,
    FR-APP-004) with a deadline."""

    TYPES = ["access", "correction", "erasure", "deletion"]
    SOURCES = ["portal", "app", "staff"]
    STATUSES = ["open", "in_progress", "waiting", "completed", "rejected"]
    subject = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    type = models.TextField(choices=[(t, t) for t in TYPES])
    source = models.TextField(choices=[(s, s) for s in SOURCES], default="portal")
    details = models.TextField(blank=True, default="")
    due_on = models.DateField()
    status = models.TextField(default="open", choices=[(s, s) for s in STATUSES])
    export_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    export_sha256 = models.CharField(max_length=64, blank=True, default="")
    corrections = models.JSONField(default=list, blank=True)  # field names and when; old values stay in audit
    kept_statement = models.JSONField(default=list, blank=True)  # classes kept, why, until when
    open_matters = models.JSONField(default=list, blank=True)  # money matters or holds that delay deletion
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    rejection_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "dpr_request"
        indexes = [models.Index(fields=["subject", "type", "status"])]


DATA_REQUEST = state.register("data_request", "dpr_request", {
    "open": {"in_progress", "waiting", "completed", "rejected"},
    "in_progress": {"waiting", "completed", "rejected"},
    "waiting": {"completed", "in_progress"},
})


class RetentionRule(BaseModel):
    """Retention per data class (FR-DPR-004, 01 C5.2). period_days null means
    the period is still [TO VERIFY] (Q-08): nothing in that class is
    deleted."""

    ANCHORS = ["case_release", "escrow_close", "account_closure", "last_contact", "removal", "tax_year_end",
               "handover", "policy_end", "tenancy_end", "creation"]
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    data_class = models.TextField(choices=[(c, c) for c in DATA_CLASSES])
    description = models.TextField(blank=True, default="")
    period_days = models.PositiveIntegerField(null=True, blank=True)
    anchor = models.TextField(choices=[(a, a) for a in ANCHORS], default="creation")
    action = models.TextField(choices=[("delete", "delete"), ("anonymise", "anonymise")], default="anonymise")
    kept_on_deletion = models.BooleanField(default=False)  # kept when a person deletes their account
    reason = models.TextField(blank=True, default="")  # plain reason shown to the person
    status = models.TextField(default="active", choices=[("active", "active"), ("retired", "retired")])
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "dpr_retention_rule"
        constraints = [models.UniqueConstraint(fields=["country", "data_class"], condition=models.Q(status="active"),
                                               name="dpr_one_active_rule")]


class RetentionRun(BaseModel):
    """Log of each retention sweep (US-DPR-004a AC1: the job is logged)."""

    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    finished_at = models.DateTimeField(null=True, blank=True)
    results = models.JSONField(default=dict)

    class Meta:
        db_table = "dpr_retention_run"


class LegalHold(CountryScopedModel):
    """Data needed for a claim is never deleted (FR-DPR-004). A hold takes
    effect at once; lifting it needs two people (legal_hold)."""

    subject_type = models.TextField()  # person, case, escrow, evidence, family_member, ...
    subject_id = models.UUIDField()
    reason = models.TextField()
    placed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    placed_at = models.DateTimeField(default=timezone.now)
    status = models.TextField(default="active", choices=[(s, s) for s in ("active", "lift_pending", "lifted")])
    lift_requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    lift_reason = models.TextField(blank=True, default="")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    lifted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dpr_legal_hold"
        indexes = [models.Index(fields=["subject_type", "subject_id", "status"])]


LEGAL_HOLD = state.register("legal_hold", "dpr_legal_hold", {
    "active": {"lift_pending"},
    "lift_pending": {"lifted", "active"},
})


class BulkExport(CountryScopedModel):
    """Two-person bulk export of personal data (FR-DPR-005)."""

    STATUSES = ["pending_approval", "produced", "rejected", "withdrawn", "expired"]
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    purpose = models.TextField()
    scope = models.JSONField(default=dict)  # {"roles": [...], "fields": [...]}
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    status = models.TextField(default="pending_approval", choices=[(s, s) for s in STATUSES])
    file_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    file_sha256 = models.CharField(max_length=64, blank=True, default="")
    row_count = models.PositiveIntegerField(default=0)
    produced_at = models.DateTimeField(null=True, blank=True)
    link_expires_at = models.DateTimeField(null=True, blank=True)
    download_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "dpr_bulk_export"
        constraints = [models.CheckConstraint(condition=~models.Q(status="produced") | models.Q(
            approval_request__isnull=False), name="dpr_export_needs_approval")]


BULK_EXPORT = state.register("bulk_export", "dpr_bulk_export", {
    "pending_approval": {"produced", "rejected", "withdrawn"},
    "produced": {"expired"},
})


class DataCatalogueEntry(BaseModel):
    """Every table and field with purpose and data class (NFR-PRIV-02)."""

    table_name = models.TextField()
    field_name = models.TextField()
    purpose = models.TextField(blank=True, default="")
    data_class = models.TextField(choices=[(c, c) for c in DATA_CLASSES] + [("none", "none")], default="none")
    personal = models.BooleanField(default=False)
    special_category = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "dpr_data_catalogue"
        constraints = [models.UniqueConstraint(fields=["table_name", "field_name"], name="dpr_catalogue_uq")]


class DataLocation(BaseModel):
    """Where each country's data lives, per service and vendor (NFR-PRIV-01)."""

    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    cell = models.TextField(blank=True, default="")
    service = models.TextField()
    vendor = models.TextField()
    region = models.TextField()
    data_classes = models.JSONField(default=list)
    transfer_basis = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "dpr_data_location"
