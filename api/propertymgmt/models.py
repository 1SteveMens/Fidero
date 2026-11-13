"""PMG Property management (document 02: 4.2, 5.9, 6.13, 9.3; FR-PMG-001 to FR-PMG-006, RUL-22, RUL-24).

Tenmina never receives rent. Rent goes from the tenant to the owner's own
verified account at the partner bank (RUL-24); Tenmina only reads that
account's statement lines, under the owner's written mandate (FR-PMG-003),
and mirrors what they show. Repair money is held at the bank in a repair
escrow and released to the contractor's verified payee after an inspection
pass with photos (FR-PMG-005, RUL-22).
"""
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

PROPERTY_STATUSES = ["onboarding", "managed", "paused", "ended"]
MANDATE_STATUSES = ["signed", "active", "revoked", "expired"]
TENANCY_STATUSES = ["active", "ended", "terminated"]
RENT_PERIODS = {"monthly": 1, "quarterly": 3, "half_yearly": 6, "yearly": 12}
RENT_STATUSES = ["due", "received", "partial", "late", "written_off"]
REPAIR_STATUSES = ["reported", "quoting", "quotes_ready", "approved", "funded", "in_progress", "inspected",
                   "instructed", "paid", "rejected", "cancelled"]
REPAIR_APPROVED = ["approved", "funded", "in_progress", "inspected", "instructed", "paid"]
QUOTE_STATUSES = ["received", "approved", "declined", "withdrawn"]
INSPECTION_KINDS = ["onboarding", "periodic", "repair"]
INSPECTION_STATUSES = ["scheduled", "assigned", "submitted", "cancelled"]
OUTCOMES = ["pass", "pass_with_defects", "fail"]
CONDITIONS = ["good", "fair", "poor"]


class ManagedProperty(CountryScopedModel):
    """FR-PMG-001, FR-PMG-002. One managed property per geo asset (a building)."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    asset = models.OneToOneField("geo.Asset", on_delete=models.PROTECT, related_name="+")
    title = models.TextField()
    onboarding_case = models.ForeignKey("cases.Case", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    ownership_verified_at = models.DateTimeField(null=True, blank=True)
    ownership_outcome = models.TextField(blank=True, default="")  # verified | not_verified, from the case
    rent_account = models.ForeignKey("accounts.BankAccount", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")  # the OWNER'S own verified account (RUL-24)
    statement_mandate = models.ForeignKey("StatementMandate", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    inspection_interval_months = models.PositiveSmallIntegerField(default=6)  # assumption [TO VERIFY]
    next_inspection_due_on = models.DateField(null=True, blank=True)
    case_manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    fee_order_id = models.UUIDField(null=True, blank=True)  # ORD property_onboarding order, when one was drafted
    status = models.TextField(default="onboarding", choices=[(s, s) for s in PROPERTY_STATUSES])
    managed_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    data_class = models.TextField(default="tenancy")

    class Meta:
        db_table = "pmg_managed_property"
        indexes = [models.Index(fields=["owner", "status"]), models.Index(fields=["country", "status"])]
        constraints = [
            models.CheckConstraint(condition=~Q(status="managed") | (
                Q(rent_account__isnull=False) & Q(onboarding_case__isnull=False)), name="pmg_managed_needs_account"),
            models.CheckConstraint(condition=~Q(status="ended") | ~Q(end_reason=""), name="pmg_ended_has_reason"),
        ]

    def __str__(self):
        return self.title


PROPERTY = state.register("managed_property", "pmg_managed_property", {
    "onboarding": {"managed", "ended"},
    "managed": {"paused", "ended"},
    "paused": {"managed", "ended"},
})


class StatementMandate(CountryScopedModel):
    """FR-PMG-003, 9.3: the owner's written mandate allowing the bank to share
    the statement lines of the rent account, and only that account."""

    property = models.ForeignKey(ManagedProperty, on_delete=models.PROTECT, related_name="mandates")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    bank_account = models.ForeignKey("accounts.BankAccount", on_delete=models.PROTECT, related_name="+")
    mandate_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    bank_acknowledgement_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                      on_delete=models.PROTECT, related_name="+")
    statement_ref = models.TextField(unique=True)  # the reference the bank puts on lines it shares under this mandate
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    status = models.TextField(default="signed", choices=[(s, s) for s in MANDATE_STATUSES])
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pmg_statement_mandate"
        constraints = [
            models.CheckConstraint(condition=~Q(status="active") | (
                Q(bank_acknowledgement_evidence__isnull=False) & Q(acknowledged_by__isnull=False)),
                name="pmg_mandate_active_acknowledged"),
            models.UniqueConstraint(fields=["property"], condition=Q(status__in=["signed", "active"]),
                                    name="pmg_one_live_mandate"),
        ]


MANDATE = state.register("statement_mandate", "pmg_statement_mandate", {
    "signed": {"active", "revoked"},
    "active": {"revoked", "expired"},
})


class StatementImport(CountryScopedModel):
    """One statement for the rent account, read under a mandate. The lines
    live in esc_statement_line (account kind owner_rent); lines for any other
    account are refused at import and only counted (TC-PMG-003-03)."""

    SOURCES = ["file", "api", "manual"]
    property = models.ForeignKey(ManagedProperty, on_delete=models.PROTECT, related_name="statement_imports")
    mandate = models.ForeignKey(StatementMandate, on_delete=models.PROTECT, related_name="imports")
    statement_file = models.ForeignKey("escrow.StatementFile", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    source = models.TextField(choices=[(s, s) for s in SOURCES])
    original_name = models.TextField(blank=True, default="")
    accepted_count = models.PositiveIntegerField(default=0)
    refused_count = models.PositiveIntegerField(default=0)  # lines for another account: never stored
    matched_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")

    class Meta:
        db_table = "pmg_statement_import"


class Tenancy(CountryScopedModel):
    """FR-PMG-002: tenant, agreement, rent, due day and the reference the tenant writes on the transfer."""

    property = models.ForeignKey(ManagedProperty, on_delete=models.PROTECT, related_name="tenancies")
    tenant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    tenant_id_check = models.ForeignKey("accounts.NationalIdCheck", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    agreement_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    rent_amount = amount_field()
    rent_currency = currency_field()
    period = models.TextField(choices=[(p, p) for p in RENT_PERIODS])
    due_day = models.PositiveSmallIntegerField()
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    tenant_reference = models.TextField()
    status = models.TextField(default="active", choices=[(s, s) for s in TENANCY_STATUSES])
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.TextField(blank=True, default="")
    data_class = models.TextField(default="tenancy")

    class Meta:
        db_table = "pmg_tenancy"
        constraints = [
            models.UniqueConstraint(fields=["property"], condition=Q(status="active"), name="pmg_one_active_tenancy"),
            models.CheckConstraint(condition=Q(rent_amount__gt=0), name="pmg_rent_positive"),
            models.CheckConstraint(condition=Q(due_day__gte=1) & Q(due_day__lte=28), name="pmg_due_day_range"),
            models.CheckConstraint(condition=Q(ends_on__isnull=True) | Q(ends_on__gt=models.F("starts_on")),
                                   name="pmg_tenancy_dates"),
        ]


TENANCY = state.register("tenancy", "pmg_tenancy", {"active": {"ended", "terminated"}})


class RentPeriod(BaseModel):
    """FR-PMG-003: rent due and received. The received figure is a bank fact
    from a statement line of the owner's own account, never a Tenmina figure."""

    tenancy = models.ForeignKey(Tenancy, on_delete=models.PROTECT, related_name="periods")
    period_start = models.DateField()
    due_on = models.DateField()
    expected_amount = amount_field()
    expected_currency = currency_field()
    statement_line = models.ForeignKey("escrow.StatementLine", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    line_ids = ArrayField(models.UUIDField(), default=list, blank=True)  # every line counted for this period
    received_amount = amount_field(null=True, blank=True)
    received_on = models.DateField(null=True, blank=True)
    match_method = models.TextField(blank=True, default="")  # reference | amount_date | manual
    pending_line = models.ForeignKey("escrow.StatementLine", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")  # a manual match waiting for a second staff member
    pending_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    status = models.TextField(default="due", choices=[(s, s) for s in RENT_STATUSES])
    late_alert_sent_at = models.DateTimeField(null=True, blank=True)
    written_off_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pmg_rent_period"
        ordering = ["period_start"]
        constraints = [
            models.UniqueConstraint(fields=["tenancy", "period_start"], name="pmg_rent_period_uq"),
            models.CheckConstraint(condition=~Q(status__in=["received", "partial"]) | Q(statement_line__isnull=False),
                                   name="pmg_received_from_statement"),
            models.CheckConstraint(condition=Q(pending_by__isnull=True) | Q(checked_by__isnull=True)
                                   | ~Q(pending_by=models.F("checked_by")), name="pmg_manual_match_two_people"),
        ]


RENT = state.register("rent_period", "pmg_rent_period", {
    "due": {"received", "partial", "late", "written_off"},
    "late": {"received", "partial", "written_off"},
    "partial": {"received", "late", "written_off"},
})


class Inspection(CountryScopedModel):
    """FR-PMG-001 (onboarding), FR-PMG-005 (repair), FR-PMG-006 (periodic). Photos through evd_link
    on subject `property_inspection` (app capture only, RUL-08)."""

    property = models.ForeignKey(ManagedProperty, on_delete=models.PROTECT, related_name="inspections")
    repair = models.ForeignKey("Repair", null=True, blank=True, on_delete=models.PROTECT, related_name="inspections")
    kind = models.TextField(choices=[(k, k) for k in INSPECTION_KINDS])
    inspector = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    scheduled_for = models.DateField()
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    assigned_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="scheduled", choices=[(s, s) for s in INSPECTION_STATUSES])
    outcome = models.TextField(blank=True, default="", choices=[("", "")] + [(o, o) for o in OUTCOMES])
    condition_rating = models.TextField(blank=True, default="", choices=[("", "")] + [(c, c) for c in CONDITIONS])
    rooms = models.JSONField(default=list, blank=True)  # [{"room", "condition", "note", "evidence_ids"}]
    checklist = models.JSONField(default=list, blank=True)
    defects = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="")
    photo_ids = ArrayField(models.UUIDField(), default=list, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    submission_id = models.UUIDField(null=True, blank=True)  # mob_submission, when sent from Tenmina Field
    cancel_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pmg_inspection"
        indexes = [models.Index(fields=["inspector", "status"]), models.Index(fields=["property", "kind"])]
        constraints = [
            models.CheckConstraint(condition=Q(kind="repair", repair__isnull=False)
                                   | (~Q(kind="repair") & Q(repair__isnull=True)), name="pmg_inspection_repair_kind"),
            models.CheckConstraint(condition=~Q(status="assigned") | Q(inspector__isnull=False),
                                   name="pmg_inspection_assigned_has_inspector"),
            models.CheckConstraint(condition=~Q(status="submitted") | (~Q(outcome="") & Q(submitted_at__isnull=False)),
                                   name="pmg_inspection_submitted_has_outcome"),
            models.CheckConstraint(condition=~Q(status="cancelled") | ~Q(cancel_reason=""),
                                   name="pmg_inspection_cancel_reason"),
        ]


INSPECTION = state.register("pmg_inspection", "pmg_inspection", {
    "scheduled": {"assigned", "cancelled"},
    "assigned": {"submitted", "cancelled", "scheduled"},
})


class Repair(CountryScopedModel):
    """FR-PMG-004, FR-PMG-005."""

    REPORTER_ROLES = ["tenant", "owner", "inspector", "staff"]
    property = models.ForeignKey(ManagedProperty, on_delete=models.PROTECT, related_name="repairs")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reporter_role = models.TextField(choices=[(r, r) for r in REPORTER_ROLES])
    title = models.TextField()
    description = models.TextField()
    urgent = models.BooleanField(default=False)
    approved_quote = models.ForeignKey("RepairQuote", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    owner_approved_at = models.DateTimeField(null=True, blank=True)  # RUL-11
    single_quote_exception_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                                  on_delete=models.PROTECT, related_name="+")
    single_quote_exception_reason = models.TextField(blank=True, default="")
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    inspection = models.ForeignKey(Inspection, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")  # kind repair, outcome pass
    work_done_at = models.DateTimeField(null=True, blank=True)
    work_done_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    release_instruction = models.ForeignKey("escrow.ReleaseInstruction", null=True, blank=True,
                                            on_delete=models.PROTECT, related_name="+")
    paid_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.TextField(blank=True, default="")
    status = models.TextField(default="reported", choices=[(s, s) for s in REPAIR_STATUSES])

    class Meta:
        db_table = "pmg_repair"
        indexes = [models.Index(fields=["property", "status"])]
        constraints = [
            models.CheckConstraint(condition=~Q(status__in=REPAIR_APPROVED) | (
                Q(approved_quote__isnull=False) & Q(owner_approved_at__isnull=False)),
                name="pmg_repair_approved_has_quote"),
            models.CheckConstraint(condition=~Q(status__in=["instructed", "paid"]) | Q(inspection__isnull=False),
                                   name="pmg_repair_paid_after_inspection"),
            models.CheckConstraint(condition=~Q(status__in=["rejected", "cancelled"]) | ~Q(closed_reason=""),
                                   name="pmg_repair_closed_reason"),
            models.CheckConstraint(condition=Q(single_quote_exception_by__isnull=True)
                                   | ~Q(single_quote_exception_reason=""), name="pmg_single_quote_reason"),
        ]


REPAIR = state.register("repair", "pmg_repair", {
    "reported": {"quoting", "rejected", "cancelled"},
    "quoting": {"quotes_ready", "cancelled"},
    "quotes_ready": {"approved", "quoting", "cancelled"},
    "approved": {"funded", "cancelled"},
    "funded": {"in_progress"},
    "in_progress": {"inspected"},
    "inspected": {"instructed", "in_progress"},
    "instructed": {"paid", "inspected"},
})


class RepairQuote(CountryScopedModel):
    """A quote from a vetted panel contractor with a verified payee (FR-PMG-004)."""

    repair = models.ForeignKey(Repair, on_delete=models.PROTECT, related_name="quotes")
    contractor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    contractor_panel_member_id = models.UUIDField(null=True, blank=True)  # bld_panel_member when BLD has it
    payee = models.ForeignKey("escrow.Payee", on_delete=models.PROTECT, related_name="+")  # kind contractor
    quote_amount = amount_field()
    quote_currency = currency_field()
    description = models.TextField(blank=True, default="")
    quote_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    valid_until = models.DateField(null=True, blank=True)
    status = models.TextField(default="received", choices=[(s, s) for s in QUOTE_STATUSES])
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "pmg_repair_quote"
        constraints = [
            models.UniqueConstraint(fields=["repair", "contractor"], name="pmg_quote_one_per_contractor"),
            models.CheckConstraint(condition=Q(quote_amount__gt=0), name="pmg_quote_positive"),
        ]


QUOTE = state.register("repair_quote", "pmg_repair_quote", {
    "received": {"approved", "declined", "withdrawn"},
})
