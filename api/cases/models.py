"""CASE Verification cases (FR-CASE-001 to FR-CASE-016; 02 sections 6.5, 6.7, 6.8, 6.15).

Every line that verifies something runs a case from a versioned template:
land, building, fresh search, and the checks other lines start through
`services.open_case` (institutions, properties, vendors, suppliers,
contractors, developers). Safety incidents live in the separate schema
`safety` and are read only by named people (FR-CASE-010, 02 10.9).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

from .templates import LINES

PRODUCT_LINES = list(LINES)
CASE_STATUSES = ["paid", "in_progress", "on_hold", "in_review", "released", "completed", "cancelled"]
OPEN_STATUSES = ["paid", "in_progress", "on_hold", "in_review"]


class Case(CountryScopedModel):
    reference = models.TextField(unique=True)
    order = models.OneToOneField("orders.Order", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="case")
    asset = models.ForeignKey("geo.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="cases")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="cases")
    product_line = models.TextField(choices=[(p, p) for p in PRODUCT_LINES])
    template_version = models.ForeignKey("administration.ConfigVersion", on_delete=models.PROTECT, related_name="+")
    title = models.TextField(blank=True, default="")
    # What the case is about when another module owns it (institution, managed property, vendor, ...).
    subject_type = models.TextField(blank=True, default="")
    subject_id = models.UUIDField(null=True, blank=True)
    parent_case = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    origin = models.TextField(blank=True, default="order")  # order | line | staff | reservation | escrow
    origin_ref = models.UUIDField(null=True, blank=True)
    status = models.TextField(default="paid", choices=[(s, s) for s in CASE_STATUSES])
    hold_reason = models.TextField(blank=True, default="")
    risk_flag = models.BooleanField(default=False)
    case_manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="managed_cases")
    accepted_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")
    refund_decision = models.TextField(blank=True, default="", choices=[("", ""), ("refund", "refund"),
                                                                        ("no_refund", "no_refund")])
    refund_id = models.UUIDField(null=True, blank=True)
    outcome = models.TextField(blank=True, default="", choices=[("", ""), ("verified", "verified"),
                                                                ("not_verified", "not_verified")])
    outcome_note = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    data_class = models.TextField(default="case_report")

    class Meta:
        db_table = "case_case"
        indexes = [models.Index(fields=["status", "country"]), models.Index(fields=["client", "-created_at"])]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=CASE_STATUSES), name="case_status_valid"),
            models.CheckConstraint(condition=~Q(status="on_hold") | ~Q(hold_reason=""), name="case_hold_has_reason"),
            models.CheckConstraint(condition=~Q(status="cancelled") | (~Q(cancel_reason="") & ~Q(refund_decision="")),
                                   name="case_cancel_has_reason_and_refund_decision"),
            models.CheckConstraint(condition=~Q(product_line__in=["land", "building"]) | Q(order__isnull=False),
                                   name="case_report_line_has_order"),
            models.CheckConstraint(condition=~Q(product_line__in=["land", "building", "fresh_search",
                                                                  "property_onboarding"]) | Q(asset__isnull=False),
                                   name="case_asset_line_has_asset"),
        ]

    def __str__(self):
        return self.reference

    @property
    def has_report(self) -> bool:
        return LINES.get(self.product_line, {}).get("report", False)


CASE = state.register("case", "case_case", {
    "paid": {"in_progress", "cancelled"},
    "in_progress": {"on_hold", "in_review", "completed", "cancelled"},
    "on_hold": {"in_progress", "cancelled"},
    "in_review": {"in_progress", "released", "cancelled"},
})

TASK_STATUSES = ["open", "in_progress", "done", "cancelled"]


class Task(CountryScopedModel):
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="tasks")
    step_key = models.TextField()
    title = models.TextField()
    position = models.PositiveSmallIntegerField(default=0)
    owner_role = models.CharField(max_length=4)
    assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="case_tasks")
    second_assignee = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="second_case_tasks")  # RUL-17
    assigned_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    due_at = models.DateTimeField()
    due_change_reason = models.TextField(blank=True, default="")
    required_evidence = models.JSONField(default=list)
    depends_on = models.JSONField(default=list)
    site_visit = models.BooleanField(default=False)
    search_kind = models.TextField(blank=True, default="")  # "", lodge, result
    review_step = models.BooleanField(default=False)
    client_message = models.TextField(blank=True, default="")
    status = models.TextField(default="open", choices=[(s, s) for s in TASK_STATUSES])
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    note = models.TextField(blank=True, default="")
    overdue_alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "case_task"
        ordering = ["position"]
        indexes = [models.Index(fields=["assignee", "status", "due_at"])]
        constraints = [
            models.UniqueConstraint(fields=["case", "step_key"], name="case_task_step_once"),
            models.CheckConstraint(condition=Q(second_assignee__isnull=True) | ~Q(second_assignee=models.F("assignee")),
                                   name="case_task_two_different_people"),
            models.CheckConstraint(condition=Q(status__in=TASK_STATUSES), name="case_task_status_valid"),
        ]

    def __str__(self):
        return f"{self.case.reference} {self.step_key}"


TASK = state.register("task", "case_task", {
    "open": {"in_progress", "done", "cancelled"},
    "in_progress": {"open", "done", "cancelled"},
})


class StatusMessage(CountryScopedModel):
    """FR-CASE-007: the plain-language status the client sees. Append-only."""

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="status_messages")
    task = models.ForeignKey(Task, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    template_key = models.TextField()
    text = models.TextField()
    message_date = models.DateField()
    next_expected_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "case_status_message"
        ordering = ["created_at"]


class DocumentRequest(CountryScopedModel):
    """FR-CASE-008: a document the case manager asks the client for."""

    STATUSES = ["open", "received", "cancelled"]
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="document_requests")
    title = models.TextField()
    description = models.TextField(blank=True, default="")
    due_on = models.DateField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="open", choices=[(s, s) for s in STATUSES])
    received_at = models.DateTimeField(null=True, blank=True)
    received_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    responded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    cancel_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "case_document_request"
        constraints = [models.CheckConstraint(condition=~Q(status="received") | Q(received_evidence__isnull=False),
                                              name="case_docreq_received_has_file")]


DOCUMENT_REQUEST = state.register("document_request", "case_document_request", {"open": {"received", "cancelled"}})


class RiskScreen(CountryScopedModel):
    """FR-CASE-009, RUL-17: recorded before any site visit. Append-only."""

    OUTCOMES = ["proceed", "proceed_with_two", "do_not_visit"]
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="risk_screens")
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="risk_screens")
    screened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    outcome = models.TextField(choices=[(o, o) for o in OUTCOMES])
    hazards = models.TextField(blank=True, default="")
    people_required = models.PositiveSmallIntegerField(default=1)
    disputed_at_screen = models.BooleanField(default=False)
    valid_until = models.DateTimeField()
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "case_risk_screen"
        constraints = [
            models.CheckConstraint(condition=Q(people_required__gte=1), name="case_risk_people_positive"),
            models.CheckConstraint(condition=~Q(disputed_at_screen=True) | Q(people_required__gte=2)
                                   | Q(outcome="do_not_visit"), name="case_risk_disputed_needs_two"),
        ]


class CostItem(CountryScopedModel):
    """FR-CASE-011, FR-PRO-010: cost of a case by item. PRO writes its accepted pay and expenses here."""

    ITEM_TYPES = ["lawyer", "surveyor", "runner", "inspector", "fees", "travel", "other"]
    SOURCES = ["manual", "pro_payable", "pro_expense"]
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="costs")
    item_type = models.TextField(choices=[(i, i) for i in ITEM_TYPES])
    amount = amount_field()
    currency = currency_field()
    incurred_on = models.DateField()
    description = models.TextField(blank=True, default="")
    source = models.TextField(default="manual", choices=[(s, s) for s in SOURCES])
    source_id = models.UUIDField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")

    class Meta:
        db_table = "case_cost_item"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gte=0), name="case_cost_not_negative"),
            models.UniqueConstraint(fields=["source", "source_id"], condition=Q(source_id__isnull=False),
                                    name="case_cost_once_per_source"),
        ]


class Message(CountryScopedModel):
    """FR-CASE-015: the case thread between the client and Tenmina. Append-only."""

    SIDES = ["client", "tenmina"]
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    side = models.TextField(choices=[(s, s) for s in SIDES])
    body = models.TextField()

    class Meta:
        db_table = "case_message"
        ordering = ["created_at"]


class Party(CountryScopedModel):
    """FR-ACC-013, RUL-31: who on a case must be checked against the national identity system."""

    ROLES = ["seller", "grantor", "consenting_party", "signatory"]
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="parties")
    role = models.TextField(choices=[(r, r) for r in ROLES])
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    for_organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    organisation_name = models.TextField(blank=True, default="")
    name = models.TextField()  # encrypt at field level in production (10.6)
    national_id_check = models.ForeignKey("accounts.NationalIdCheck", null=True, blank=True,
                                          on_delete=models.PROTECT, related_name="+")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="active", choices=[("active", "active"), ("removed", "removed")])
    removed_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "case_party"
        constraints = [
            models.CheckConstraint(condition=~Q(role="signatory") | Q(for_organisation__isnull=False)
                                   | ~Q(organisation_name=""), name="case_party_signatory_has_org"),
            models.CheckConstraint(condition=~Q(status="removed") | ~Q(removed_reason=""),
                                   name="case_party_removed_has_reason"),
        ]


class SearchRequest(CountryScopedModel):
    """FR-CASE-016, FR-CASE-014, RUL-30, ADR-25 (02 6.15)."""

    CHANNELS = ["online_portal", "registry_office"]
    STATUSES = ["submitted", "result_received", "confirmed", "rejected"]
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="search_requests")
    task = models.ForeignKey(Task, on_delete=models.PROTECT, related_name="search_requests")
    registry_partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    channel = models.TextField(choices=[(c, c) for c in CHANNELS])
    tenmina_account_ref = models.TextField()
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    submitted_at = models.DateTimeField()
    registry_reference = models.TextField(blank=True, default="")
    search_on = models.TextField(blank=True, default="")  # the plot, or the seller's name
    result_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    result_received_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    result_received_at = models.DateTimeField(null=True, blank=True)
    registry_result_date = models.DateField(null=True, blank=True)  # RUL-07 window counts from this date
    result_summary = models.TextField(blank=True, default="")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    confirmed_with = models.TextField(blank=True, default="")  # the registry officer's name and post
    confirmed_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="submitted", choices=[(s, s) for s in STATUSES])
    rejected_reason = models.TextField(blank=True, default="")
    overdue_alerted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "case_search_request"
        constraints = [
            models.CheckConstraint(condition=~Q(registry_reference=""), name="case_search_has_registry_reference"),
            models.CheckConstraint(
                condition=Q(status__in=["submitted", "rejected"]) | (
                    Q(result_evidence__isnull=False) & Q(result_received_by__isnull=False)
                    & Q(result_received_at__isnull=False) & Q(registry_result_date__isnull=False)),
                name="case_search_result_complete"),
            models.CheckConstraint(
                condition=~Q(status="confirmed") | (Q(confirmed_by__isnull=False) & ~Q(confirmed_with="")
                                                    & Q(confirmed_at__isnull=False)),
                name="case_search_confirmation_complete"),
            models.CheckConstraint(condition=~Q(status="rejected") | ~Q(rejected_reason=""),
                                   name="case_search_rejected_has_reason"),
        ]

    @property
    def usable(self) -> bool:
        """RUL-30: usable as the search task's evidence."""
        if self.channel == "online_portal":
            return self.status in ("result_received", "confirmed")
        return self.status == "confirmed"


SEARCH_REQUEST = state.register("search_request", "case_search_request", {
    "submitted": {"result_received", "confirmed", "rejected"},
    "result_received": {"confirmed", "rejected"},
})


class SearchCopyCheck(CountryScopedModel):
    """A copy handed in by a runner, seller, agent or client, compared with the official result (FR-CASE-016)."""

    search_request = models.ForeignKey(SearchRequest, on_delete=models.PROTECT, related_name="copy_checks")
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    matches = models.BooleanField()
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "case_search_copy_check"
        constraints = [models.UniqueConstraint(fields=["search_request", "evidence"], name="case_copy_check_once")]


class ReferenceCounter(models.Model):
    """Gap-free case references per country and year: TMC-GH-2026-00042."""

    country_code = models.CharField(max_length=2)
    year = models.PositiveIntegerField()
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "case_reference_counter"
        constraints = [models.UniqueConstraint(fields=["country_code", "year"], name="case_ref_counter_uq")]


class SafetyReader(BaseModel):
    """`safety.read` granted to a named person (02 10.4, 10.9). Every grant and removal is audited."""

    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")  # null = every country
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(blank=True, default="")
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "case_safety_reader"


class SafetyIncident(models.Model):
    """FR-CASE-010: the restricted incident log, in schema `safety` (02 6.7).

    No foreign keys across schemas by design; the application checks them.
    In production only the role `tenmina_safety` can read this schema and the
    narrative is encrypted with its own key (10.6, 10.9)."""

    SEVERITIES = ["low", "medium", "high", "critical"]
    id = models.UUIDField(primary_key=True)
    case_id = models.UUIDField(null=True, blank=True)  # null when logged from another line (care visit, errand)
    country_code = models.CharField(max_length=2)
    subject_type = models.TextField(blank=True, default="case")
    subject_id = models.UUIDField(null=True, blank=True)
    reported_by = models.UUIDField()
    occurred_at = models.DateTimeField()
    severity = models.TextField(choices=[(s, s) for s in SEVERITIES])
    narrative = models.TextField()  # encrypted with the safety key in production
    persons_named = models.TextField(blank=True, default="")
    location_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'safety"."incident'
        managed = True
