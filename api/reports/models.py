"""RPT Reports (FR-RPT-001 to FR-RPT-012; 02 sections 5.2, 6.5, 6.8, 6.15; ADR-15, ADR-25).

A report is built from the versioned report template with sections 1 to 14
in order (building reports add their extra checks after section 10). A
released report never changes: a correction is a new version that
supersedes it. Rules are enforced again in PostgreSQL (dbsql.py).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel

VERDICTS = ["red", "amber", "green"]
REPORT_STATUSES = ["draft", "in_review", "approved", "released", "superseded"]


class Report(CountryScopedModel):
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="reports")
    version = models.PositiveIntegerField()
    reference = models.TextField(unique=True)
    template_version = models.ForeignKey("administration.ConfigVersion", on_delete=models.PROTECT, related_name="+")
    scope_text_version = models.ForeignKey("administration.LockedTextVersion", on_delete=models.PROTECT,
                                           related_name="+")  # RUL-04
    overall_verdict = models.TextField(null=True, blank=True, choices=[(v, v) for v in VERDICTS])
    verdict_set_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    status = models.TextField(default="draft", choices=[(s, s) for s in REPORT_STATUSES])
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    pdf_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    pdf_sha256 = models.CharField(max_length=64, blank=True, default="")
    released_at = models.DateTimeField(null=True, blank=True)
    supersedes = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    correction_reason = models.TextField(blank=True, default="")
    incident = models.ForeignKey("reports.Incident", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")  # the re-check incident a correction answers
    release_error = models.TextField(blank=True, default="")
    client_notified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rpt_report"
        ordering = ["case", "version"]
        constraints = [
            models.UniqueConstraint(fields=["case", "version"], name="rpt_report_case_version_uq"),
            models.CheckConstraint(condition=Q(status__in=REPORT_STATUSES), name="rpt_report_status_valid"),
            models.CheckConstraint(
                condition=~Q(status__in=["released", "superseded"]) | (~Q(pdf_sha256="") & Q(released_at__isnull=False)
                                                                       & Q(pdf_evidence__isnull=False)),
                name="rpt_released_has_pdf_and_hash"),
            models.CheckConstraint(condition=Q(supersedes__isnull=True) | ~Q(correction_reason=""),
                                   name="rpt_correction_has_reason"),
        ]

    def __str__(self):
        return self.reference


REPORT = state.register("report", "rpt_report", {
    "draft": {"in_review"},
    "in_review": {"draft", "approved"},
    "approved": {"released"},
    "released": {"superseded"},
})


class Section(BaseModel):
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="sections")
    number = models.PositiveSmallIntegerField()
    position = models.PositiveSmallIntegerField()
    label = models.TextField()  # "4", or "10A" for a building check
    key = models.TextField()
    title = models.TextField()
    owner_role = models.TextField()  # CM, LW, SV, IN, system
    locked = models.BooleanField(default=False)  # section 12, the scope statement (RUL-04)
    in_verdict_rule = models.BooleanField(default=False)  # sections 4 to 10 and building checks (RUL-02)
    needs_signature = models.BooleanField(default=False)
    findings = models.JSONField(default=dict, blank=True)
    verdict = models.TextField(null=True, blank=True, choices=[(v, v) for v in VERDICTS])
    proposed_verdict = models.TextField(null=True, blank=True, choices=[(v, v) for v in VERDICTS])  # GEO, section 7
    proposed_reasons = models.JSONField(default=list, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    edited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rpt_section"
        ordering = ["report", "position"]
        constraints = [
            models.UniqueConstraint(fields=["report", "number"], name="rpt_section_number_uq"),
            models.CheckConstraint(condition=Q(number__gte=1) & Q(number__lte=30), name="rpt_section_number_range"),
        ]


class Signature(BaseModel):
    """FR-RPT-005, RUL-20: name, licence and time at signing, with a hash of the section content."""

    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="signatures")
    section = models.ForeignKey(Section, on_delete=models.PROTECT, related_name="signatures")
    signer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=4)
    licence = models.ForeignKey("accounts.ProfessionalLicence", on_delete=models.PROTECT, related_name="+")
    signer_name = models.TextField()
    licence_number = models.TextField()
    licence_body = models.TextField()
    signed_at = models.DateTimeField()
    content_sha256 = models.CharField(max_length=64)
    invalidated_at = models.DateTimeField(null=True, blank=True)  # the section changed after signing
    invalidated_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "rpt_signature"


class Condition(BaseModel):
    """FR-RPT-009: section 11 release conditions as structured items escrow can copy."""

    RESPONSIBLE = ["buyer", "seller", "lawyer", "surveyor", "tenmina", "authority", "developer", "other"]
    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="conditions")
    position = models.PositiveSmallIntegerField(default=0)
    key = models.TextField(blank=True, default="")
    text = models.TextField()
    responsible = models.TextField(choices=[(r, r) for r in RESPONSIBLE])
    closing_evidence = models.TextField()  # the evidence that closes it
    release_part = models.TextField(default="main", choices=[("main", "main"), ("held_back", "held_back")])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "rpt_condition"
        ordering = ["report", "position"]


class HashCheck(models.Model):
    """FR-RPT-008: every public check, with only what was asked and the answer."""

    id = models.BigAutoField(primary_key=True)
    reference = models.TextField(blank=True, default="")
    sha256 = models.CharField(max_length=64)
    report = models.ForeignKey(Report, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    matched = models.BooleanField()
    ip_hash = models.CharField(max_length=64, blank=True, default="")
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rpt_hash_check"


class AnonymisedCopy(CountryScopedModel):
    """FR-RPT-011: a case-study copy, made only with the client's consent on file."""

    report = models.ForeignKey(Report, on_delete=models.PROTECT, related_name="anonymised_copies")
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    consent_id = models.UUIDField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    removed = models.JSONField(default=list)  # kinds of data removed

    class Meta:
        db_table = "rpt_anonymised_copy"


class RecheckCandidate(CountryScopedModel):
    """The month's population (02 6.15): reports released and escrow conditions closed, kept from
    report.released and condition.closed."""

    SUBJECT_TYPES = ["report", "escrow_condition"]
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="+")
    report = models.ForeignKey(Report, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    occurred_at = models.DateTimeField()
    sample_month = models.DateField()
    linked_person_ids = models.JSONField(default=list)  # e.g. who closed the condition

    class Meta:
        db_table = "rpt_recheck_candidate"
        constraints = [models.UniqueConstraint(fields=["subject_type", "subject_id"], name="rpt_candidate_once")]


class RecheckDraw(CountryScopedModel):
    """One random draw per country and month (RUL-32). Insert-only."""

    sample_month = models.DateField()
    sample_pct = models.DecimalField(max_digits=5, decimal_places=2)
    population_count = models.PositiveIntegerField()
    population_sha256 = models.CharField(max_length=64)
    seed = models.CharField(max_length=64)  # hex of 32 bytes from a cryptographic random source
    selected_count = models.PositiveIntegerField(default=0)
    method = models.TextField(default="rank by sha256(seed || subject_type:subject_id), take the first n; "
                                      "n = ceil(population x share), at least 1 when the population is not empty")
    drawn_at = models.DateTimeField(auto_now_add=True)
    drawn_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")

    class Meta:
        db_table = "rpt_recheck_draw"
        constraints = [
            models.UniqueConstraint(fields=["country", "sample_month"], name="rpt_draw_once_per_month"),
            models.CheckConstraint(condition=Q(sample_pct__gt=0) & Q(sample_pct__lte=100), name="rpt_draw_pct_range"),
        ]


class Recheck(CountryScopedModel):
    STATUSES = ["selected", "assigned", "done", "skipped"]
    RESULTS = ["confirmed", "correction_needed", "failed"]
    draw = models.ForeignKey(RecheckDraw, on_delete=models.PROTECT, related_name="rechecks")
    subject_type = models.TextField(choices=[(s, s) for s in RecheckCandidate.SUBJECT_TYPES])
    subject_id = models.UUIDField()
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="+")
    report = models.ForeignKey(Report, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    assignee_role = models.CharField(max_length=4, blank=True, default="")
    licence = models.ForeignKey("accounts.ProfessionalLicence", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    assigned_at = models.DateTimeField(null=True, blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    result = models.TextField(null=True, blank=True, choices=[(r, r) for r in RESULTS])
    findings = models.TextField(blank=True, default="")  # encrypt at field level in production
    result_at = models.DateTimeField(null=True, blank=True)
    incident = models.ForeignKey("reports.Incident", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    status = models.TextField(default="selected", choices=[(s, s) for s in STATUSES])
    skipped_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    skip_reason = models.TextField(blank=True, default="")
    carried_from = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    due_alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rpt_recheck"
        constraints = [
            models.UniqueConstraint(fields=["draw", "subject_type", "subject_id"], name="rpt_recheck_once_per_draw"),
            models.CheckConstraint(condition=Q(status__in=["selected", "skipped"]) | (
                Q(assignee__isnull=False) & Q(licence__isnull=False)), name="rpt_recheck_assigned_licensed"),
            models.CheckConstraint(condition=~Q(status="done") | (Q(result__isnull=False) & Q(result_at__isnull=False)),
                                   name="rpt_recheck_done_has_result"),
            models.CheckConstraint(condition=Q(result__isnull=True) | Q(result="confirmed") | Q(incident__isnull=False),
                                   name="rpt_recheck_failure_has_incident"),
            models.CheckConstraint(condition=~Q(status="skipped") | (Q(skipped_by__isnull=False) & ~Q(skip_reason="")),
                                   name="rpt_recheck_skip_has_reason"),
        ]


RECHECK = state.register("recheck", "rpt_recheck", {
    "selected": {"assigned", "skipped"},
    "assigned": {"done", "skipped"},
})


class Incident(CountryScopedModel):
    """FR-RPT-012: a failed or correcting re-check. ESC freezes releases on affected escrows while open."""

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="+")
    recheck = models.OneToOneField(Recheck, on_delete=models.PROTECT, related_name="+")
    report = models.ForeignKey(Report, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    condition_id = models.UUIDField(null=True, blank=True)  # esc_condition, when that was re-checked
    kind = models.TextField(choices=[("correction_needed", "correction_needed"), ("failed", "failed")])
    summary = models.TextField(blank=True, default="")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    correction_report = models.ForeignKey(Report, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    client_notified_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="open", choices=[("open", "open"), ("closed", "closed")])
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    closure_note = models.TextField(blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rpt_incident"
        constraints = [
            models.CheckConstraint(condition=~Q(status="closed") | (Q(closed_by__isnull=False) & ~Q(closure_note="")),
                                   name="rpt_incident_closed_has_note"),
            models.CheckConstraint(condition=~Q(status="closed") | Q(correction_report__isnull=True)
                                   | Q(client_notified_at__isnull=False), name="rpt_incident_correction_told"),
        ]


INCIDENT = state.register("rpt_incident", "rpt_incident", {"open": {"closed"}})
