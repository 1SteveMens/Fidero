"""PRO Professional payments (document 02: 4.2, 5.11, 6.14; ADR-23; RUL-26, RUL-27).

Tenmina pays the professionals it contracts (lawyers, surveyors, runners,
inspectors, quantity surveyors, carers and errand agents) from its own
operating account, out of fee income. No table here references an escrow,
held-funds, release-instruction, bank-event, standing-approval or statement
table (RUL-27). The only money record shared with ESC is the verified payee
registry (`esc_payee`); a professional's own account verified through ACC
(`acc_bank_account`) is the other accepted destination.

RUL-26: no column records a verdict, inspection outcome, risk flag or report
state. A rate is one flat amount per unit, varied only by a scope key known
at assignment (`pro_scope`, seeded by migration only).
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

ROLES = ["lawyer", "surveyor", "runner", "inspector", "quantity_surveyor", "carer", "errand_agent"]
# Role codes (core.permissions) to agreement roles. CE is a carer or an errand agent (the agreement says which).
ROLE_FROM_CODE = {"LW": "lawyer", "SV": "surveyor", "RN": "runner", "IN": "inspector", "QS": "quantity_surveyor",
                  "CE": "errand_agent"}
CODE_FOR_ROLE = {"lawyer": "LW", "surveyor": "SV", "runner": "RN", "inspector": "IN", "quantity_surveyor": "QS",
                 "carer": "CE", "errand_agent": "CE"}
UNITS = ["report_section", "site_visit", "inspection", "bill_of_quantities", "errand", "care_visit", "month",
         "recheck"]
WORK_KINDS = ["report_section", "site_visit", "inspection", "bill_of_quantities", "errand", "care_visit",
              "runner_month", "recheck"]
UNIT_FOR_WORK = {"report_section": "report_section", "site_visit": "site_visit", "inspection": "inspection",
                 "bill_of_quantities": "bill_of_quantities", "errand": "errand", "care_visit": "care_visit",
                 "runner_month": "month", "recheck": "recheck"}
# Words no scope key or description may contain (RUL-26, TC-RUL-26-02).
RESULT_WORDS = ["verdict", "outcome", "pass", "fail", "green", "amber", "red", "risk", "finding", "defect",
                "result", "approved_report", "rejected"]
HOLD_REASONS = ["fraud_review", "misconduct_review", "payee_not_verified", "agreement_suspended"]
REVIEW_HOLDS = ["fraud_review", "misconduct_review"]
EXPENSE_KINDS = ["official_search_fee", "travel", "approved_cost"]


class Agreement(CountryScopedModel):
    """FR-PRO-001: a signed agreement per professional, country and role. Active
    only with a verified payee account in the professional's (or their firm's) own name."""

    STATUSES = ["draft", "active", "suspended", "ended"]
    PARTIES = ["person", "organisation"]
    TAX_STATUSES = ["registered", "not_registered", "exempt"]

    reference = models.TextField(unique=True)
    professional = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                     related_name="pro_agreements")
    role = models.TextField(choices=[(r, r) for r in ROLES])
    contracting_party = models.TextField(default="person", choices=[(p, p) for p in PARTIES])
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")  # the law or survey firm that signs (I-35)
    agreement_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    tax_status = models.TextField(default="not_registered", choices=[(t, t) for t in TAX_STATUSES])
    tax_id = models.TextField(blank=True, default="")  # taxpayer number; field-level encryption in production (10.6)
    # Exactly one verified destination in the professional's own name (FR-PRO-006).
    payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    bank_account = models.ForeignKey("accounts.BankAccount", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    monthly_fee_currency = currency_field(blank=True, default="")  # informational; the rate card is the source
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    status_reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    data_class = models.TextField(default="payables")

    class Meta:
        db_table = "pro_agreement"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(contracting_party="organisation", organisation__isnull=False)
                                   | Q(contracting_party="person", organisation__isnull=True),
                                   name="pro_agreement_party_org"),
            models.CheckConstraint(condition=~Q(status="active") | Q(payee__isnull=False)
                                   | Q(bank_account__isnull=False), name="pro_agreement_active_has_payee"),
            models.CheckConstraint(condition=Q(payee__isnull=True) | Q(bank_account__isnull=True),
                                   name="pro_agreement_one_destination"),
            models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                                   name="pro_agreement_dates"),
            models.UniqueConstraint(fields=["country", "professional", "role"], condition=Q(status="active"),
                                    name="pro_one_active_agreement"),
            models.CheckConstraint(condition=Q(role__in=ROLES), name="pro_agreement_role"),
        ]

    def __str__(self):
        return f"{self.reference} {self.role}"


AGREEMENT = state.register("pro_agreement", "pro_agreement", {
    "draft": {"active", "ended"},
    "active": {"suspended", "ended"},
    "suspended": {"active", "ended"},
})


class Scope(models.Model):
    """FR-PRO-003, RUL-26: the only thing a rate may vary by. Seeded by
    migration only; a trigger refuses any other write and any result word."""

    key = models.TextField(primary_key=True)
    description = models.TextField()
    known_at = models.TextField(default="assignment")

    class Meta:
        db_table = "pro_scope"
        constraints = [
            models.CheckConstraint(condition=Q(known_at="assignment"), name="pro_scope_known_at_assignment"),
            models.CheckConstraint(condition=Q(key__regex=r"^[a-z0-9_]+$"), name="pro_scope_key_format"),
        ]


class RateCard(CountryScopedModel):
    """FR-PRO-001, FR-PRO-003: one flat rate per unit, versioned, immutable once
    approved by a second administrator (`pro_rate_card_change`)."""

    STATES = ["draft", "approved", "retired"]

    role = models.TextField(choices=[(r, r) for r in ROLES])
    agreement = models.ForeignKey(Agreement, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="rate_cards")  # NULL: the country's standard card for the role
    unit = models.TextField(choices=[(u, u) for u in UNITS])
    scope_key = models.ForeignKey(Scope, db_column="scope_key", to_field="key", default="standard",
                                  on_delete=models.PROTECT, related_name="+")
    rate = amount_field()
    currency = currency_field()
    version = models.PositiveIntegerField()
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    state = models.TextField(default="draft", choices=[(s, s) for s in STATES])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pro_rate_card"
        ordering = ["role", "unit", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["country", "role", "agreement", "unit", "scope_key", "version"],
                                    nulls_distinct=False, name="pro_rate_card_version_uq"),
            models.CheckConstraint(condition=Q(rate__gt=0), name="pro_rate_positive"),
            models.CheckConstraint(condition=Q(version__gte=1), name="pro_rate_version_positive"),
            models.CheckConstraint(condition=Q(state="draft") | (Q(approval_request__isnull=False)
                                                                 & Q(approved_at__isnull=False)),
                                   name="pro_rate_card_approved_needs_approval"),
            models.CheckConstraint(condition=Q(approved_by__isnull=True) | ~Q(approved_by=F("created_by")),
                                   name="pro_rate_card_second_admin"),
            models.CheckConstraint(condition=Q(valid_to__isnull=True) | Q(valid_to__gte=F("valid_from")),
                                   name="pro_rate_card_dates"),
            # RUL-26: a rate varies by unit and scope only; both are fixed lists.
            models.CheckConstraint(condition=Q(role__in=ROLES) & Q(unit__in=UNITS), name="pro_rate_card_unit"),
        ]


RATE_CARD = state.register("pro_rate_card", "pro_rate_card", {
    "draft": {"approved", "retired"},
    "approved": {"retired"},
}, field="state")


class PaymentRun(CountryScopedModel):
    """FR-PRO-005, FR-PRO-006, FR-PRO-009: one run debits Tenmina's operating
    account only. Prepared by one person, approved by a different one with
    payment rights (`pro_payment_run`, MFA)."""

    STATUSES = ["draft", "pending_approval", "approved", "file_issued", "partly_confirmed", "confirmed", "closed",
                "withdrawn"]

    reference = models.TextField(unique=True)
    operating_account = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    file_format = models.TextField()
    cut_off_at = models.DateTimeField()
    currency = currency_field()
    total_gross = amount_field(default=0)
    total_net = amount_field(default=0)
    line_count = models.PositiveIntegerField(default=0)
    excluded = models.JSONField(default=list, blank=True)  # items left out, with reasons (FR-PRO-005 AC1)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    file_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    file_sha256 = models.CharField(max_length=64, blank=True, default="")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    uploaded_at = models.DateTimeField(null=True, blank=True)
    confirmation_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="+")
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    status_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pro_payment_run"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(approved_by__isnull=True) | ~Q(approved_by=F("prepared_by")),
                                   name="pro_run_preparer_never_approves"),
            models.CheckConstraint(condition=Q(status__in=["draft", "pending_approval", "withdrawn"])
                                   | (Q(approval_request__isnull=False) & Q(approved_by__isnull=False)
                                      & Q(approved_at__isnull=False)), name="pro_run_approved_fields"),
            models.CheckConstraint(condition=~Q(status__in=["file_issued", "partly_confirmed", "confirmed", "closed"])
                                   | (Q(file_evidence__isnull=False) & ~Q(file_sha256="")),
                                   name="pro_run_file_fields"),
            models.CheckConstraint(condition=Q(total_net__gte=0), name="pro_run_total_net"),
        ]


PAYMENT_RUN = state.register("pro_payment_run", "pro_payment_run", {
    "draft": {"pending_approval", "withdrawn"},
    "pending_approval": {"approved", "draft", "withdrawn"},
    "approved": {"file_issued", "draft"},
    "file_issued": {"partly_confirmed", "confirmed", "draft"},
    "partly_confirmed": {"confirmed", "closed"},
    "confirmed": {"closed"},
})


class PaymentLine(BaseModel):
    """One credit to one professional's verified account in one run."""

    OUTCOMES = ["pending", "confirmed", "failed", "unconfirmed"]
    RESOLUTIONS = ["next_run", "cancelled", "confirmed_by_bank_letter"]

    run = models.ForeignKey(PaymentRun, on_delete=models.PROTECT, related_name="lines")
    position = models.PositiveIntegerField()
    reference = models.TextField(unique=True)  # what the bank echoes back in its confirmation
    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, related_name="lines")
    payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    bank_account = models.ForeignKey("accounts.BankAccount", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    account_name = models.TextField()  # as verified, copied when the line is built
    account_last4 = models.CharField(max_length=4)
    gross = amount_field()
    withholding = amount_field()
    other_deductions = amount_field(default=0)
    reimbursed_expenses = amount_field(default=0)
    net = models.GeneratedField(
        expression=F("gross") - F("withholding") - F("other_deductions") + F("reimbursed_expenses"),
        output_field=models.DecimalField(max_digits=18, decimal_places=2), db_persist=True)
    currency = currency_field()
    bank_reference = models.TextField(blank=True, default="")
    outcome = models.TextField(default="pending", choices=[(o, o) for o in OUTCOMES])
    failure_reason = models.TextField(blank=True, default="")
    resolution = models.TextField(blank=True, default="", choices=[("", "")] + [(r, r) for r in RESOLUTIONS])
    resolution_note = models.TextField(blank=True, default="")
    letter_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    letter_recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "pro_payment_line"
        ordering = ["run", "position"]
        constraints = [
            models.UniqueConstraint(fields=["run", "agreement"], name="pro_line_one_per_agreement"),
            models.UniqueConstraint(fields=["run", "payee"], condition=Q(payee__isnull=False),
                                    name="pro_line_one_per_payee"),
            models.UniqueConstraint(fields=["run", "bank_account"], condition=Q(bank_account__isnull=False),
                                    name="pro_line_one_per_account"),
            models.CheckConstraint(condition=Q(payee__isnull=False) ^ Q(bank_account__isnull=False),
                                   name="pro_line_one_destination"),
            models.CheckConstraint(condition=Q(gross__gte=0) & Q(withholding__gte=0) & Q(other_deductions__gte=0)
                                   & Q(reimbursed_expenses__gte=0), name="pro_line_amounts"),
            models.CheckConstraint(condition=Q(gross__gte=F("withholding") + F("other_deductions")
                                               - F("reimbursed_expenses")), name="pro_line_net_not_negative"),
            models.CheckConstraint(condition=~Q(outcome="failed") | ~Q(failure_reason=""),
                                   name="pro_line_failed_has_reason"),
            models.CheckConstraint(condition=~Q(resolution="confirmed_by_bank_letter")
                                   | (Q(letter_evidence__isnull=False) & Q(resolved_by__isnull=False)
                                      & ~Q(resolved_by=F("letter_recorded_by"))),
                                   name="pro_line_letter_second_person"),
        ]


def _gross():
    return Round(F("unit_rate") * F("quantity"), 2)


class Payable(CountryScopedModel):
    """FR-PRO-002, FR-PRO-003, FR-PRO-007, FR-PRO-008: one payable per piece of
    accepted work, at the card in force when the work was assigned."""

    STATUSES = ["approved", "held", "in_run", "paid", "cancelled"]

    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, related_name="payables")
    work_kind = models.TextField(choices=[(w, w) for w in WORK_KINDS])
    work_ref = models.UUIDField()
    work_period = models.DateField(null=True, blank=True)  # first day of the month, runner_month only
    source_event_id = models.UUIDField()
    case = models.ForeignKey("cases.Case", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    subject_type = models.TextField(blank=True, default="")  # project, errand, visit, property (R2 sources)
    subject_id = models.UUIDField(null=True, blank=True)
    assigned_at = models.DateTimeField()
    accepted_at = models.DateTimeField()
    rate_card = models.ForeignKey(RateCard, on_delete=models.PROTECT, related_name="payables")
    unit_rate = amount_field()
    quantity = models.DecimalField(max_digits=9, decimal_places=4, default=1)
    gross = models.GeneratedField(expression=_gross(), output_field=models.DecimalField(max_digits=18,
                                                                                         decimal_places=2),
                                  db_persist=True)
    currency = currency_field()
    country_config = models.ForeignKey("countries.CountryConfig", on_delete=models.PROTECT, related_name="+")
    withholding_rate = models.DecimalField(max_digits=5, decimal_places=4)
    withholding = models.GeneratedField(expression=Round(_gross() * F("withholding_rate"), 2),
                                        output_field=models.DecimalField(max_digits=18, decimal_places=2),
                                        db_persist=True)
    other_deductions_rate = models.DecimalField(max_digits=5, decimal_places=4, default=0)
    other_deductions = models.GeneratedField(expression=Round(_gross() * F("other_deductions_rate"), 2),
                                             output_field=models.DecimalField(max_digits=18, decimal_places=2),
                                             db_persist=True)
    due_by = models.DateField()
    overdue_alerted_at = models.DateTimeField(null=True, blank=True)
    payment_line = models.ForeignKey(PaymentLine, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="payables")
    status = models.TextField(default="approved", choices=[(s, s) for s in STATUSES])
    hold_reason = models.TextField(null=True, blank=True, choices=[(h, h) for h in HOLD_REASONS])
    hold_note = models.TextField(blank=True, default="")
    held_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    cancel_reason = models.TextField(blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)
    data_class = models.TextField(default="payables")

    class Meta:
        db_table = "pro_payable"
        ordering = ["due_by", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["work_kind", "work_ref", "work_period"], nulls_distinct=False,
                                    name="pro_one_payable_per_work"),
            models.CheckConstraint(condition=Q(work_kind="runner_month", work_period__isnull=False)
                                   | (~Q(work_kind="runner_month") & Q(work_period__isnull=True)),
                                   name="pro_payable_month_period"),
            models.CheckConstraint(condition=Q(status="held", hold_reason__isnull=False)
                                   | (~Q(status="held") & Q(hold_reason__isnull=True)),
                                   name="pro_payable_held_reason"),
            models.CheckConstraint(condition=~Q(hold_reason__in=REVIEW_HOLDS) | Q(held_by__isnull=False),
                                   name="pro_payable_review_hold_by"),
            models.CheckConstraint(condition=~Q(status__in=["in_run", "paid"]) | Q(payment_line__isnull=False),
                                   name="pro_payable_run_line"),
            models.CheckConstraint(condition=Q(accepted_at__gte=F("assigned_at")), name="pro_payable_dates"),
            models.CheckConstraint(condition=Q(unit_rate__gt=0) & Q(quantity__gt=0), name="pro_payable_rate"),
            models.CheckConstraint(condition=Q(withholding_rate__gte=0) & Q(withholding_rate__lt=1)
                                   & Q(other_deductions_rate__gte=0) & Q(other_deductions_rate__lt=1),
                                   name="pro_payable_tax_rates"),
            models.CheckConstraint(condition=Q(work_kind__in=WORK_KINDS), name="pro_payable_work_kind"),
            # RUL-26: only a fraud or misconduct review (or an unverified payee) holds pay, never a result.
            models.CheckConstraint(condition=Q(hold_reason__isnull=True) | Q(hold_reason__in=HOLD_REASONS),
                                   name="pro_payable_hold_reason_list"),
        ]


PAYABLE = state.register("pro_payable", "pro_payable", {
    "approved": {"held", "in_run", "cancelled"},
    "held": {"approved", "cancelled"},
    "in_run": {"approved", "paid", "cancelled"},
})


class ExpenseClaim(CountryScopedModel):
    """FR-PRO-004: an expense with a receipt photo, within the limit for the
    role and kind. Over the limit or without a receipt needs a second, different
    staff approval (`pro_expense_exception`)."""

    STATUSES = ["submitted", "approved", "rejected", "in_run", "paid", "cancelled"]

    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, related_name="expense_claims")
    claimant = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    case = models.ForeignKey("cases.Case", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    project_id = models.UUIDField(null=True, blank=True)  # bld_project when BLD has it
    errand_id = models.UUIDField(null=True, blank=True)  # tsk_errand when TSK has it
    kind = models.TextField(choices=[(k, k) for k in EXPENSE_KINDS])
    description = models.TextField()
    amount = amount_field()
    currency = currency_field()
    incurred_on = models.DateField()
    receipt_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    receipt_sha256 = models.CharField(max_length=64, null=True, blank=True, unique=True)  # one receipt, one claim
    limit_amount = amount_field()
    country_config = models.ForeignKey("countries.CountryConfig", on_delete=models.PROTECT, related_name="+")
    needs_second_approval = models.GeneratedField(
        expression=models.Case(models.When(Q(receipt_evidence__isnull=True) | Q(amount__gt=F("limit_amount")),
                                           then=models.Value(True)), default=models.Value(False)),
        output_field=models.BooleanField(), db_persist=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    decision_note = models.TextField(blank=True, default="")
    payment_line = models.ForeignKey(PaymentLine, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="expenses")
    status = models.TextField(default="submitted", choices=[(s, s) for s in STATUSES])
    data_class = models.TextField(default="payables")

    class Meta:
        db_table = "pro_expense_claim"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="pro_expense_amount"),
            models.CheckConstraint(condition=Q(case__isnull=True, project_id__isnull=True)
                                   | Q(case__isnull=True, errand_id__isnull=True)
                                   | Q(project_id__isnull=True, errand_id__isnull=True),
                                   name="pro_expense_one_subject"),
            models.CheckConstraint(condition=~Q(status__in=["approved", "in_run", "paid"])
                                   | Q(approved_by__isnull=False), name="pro_expense_approved_by"),
            models.CheckConstraint(condition=~Q(status__in=["approved", "in_run", "paid"])
                                   | Q(needs_second_approval=False) | Q(approval_request__isnull=False),
                                   name="pro_expense_exception_approved"),
            models.CheckConstraint(condition=Q(approved_by__isnull=True) | ~Q(approved_by=F("claimant")),
                                   name="pro_expense_not_self_approved"),
            models.CheckConstraint(condition=~Q(status__in=["in_run", "paid"]) | Q(payment_line__isnull=False),
                                   name="pro_expense_run_line"),
            models.CheckConstraint(condition=Q(kind__in=EXPENSE_KINDS), name="pro_expense_kind"),
        ]


EXPENSE = state.register("pro_expense_claim", "pro_expense_claim", {
    "submitted": {"approved", "rejected", "cancelled"},
    "approved": {"in_run", "cancelled"},
    "in_run": {"approved", "paid", "cancelled"},
})


class RunnerMonth(CountryScopedModel):
    """A runner's month closed by a case manager (FR-PRO-002 AC4): one per agreement and month."""

    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, related_name="months")
    month = models.DateField()  # first day of the month
    days_worked = models.PositiveSmallIntegerField()
    days_in_month = models.PositiveSmallIntegerField()
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    closed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pro_runner_month"
        constraints = [models.UniqueConstraint(fields=["agreement", "month"], name="pro_runner_month_once")]


class Document(CountryScopedModel):
    """FR-PRO-007: remittance advices and yearly statements, as hashed PDFs."""

    KINDS = ["remittance_advice", "yearly_statement"]

    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, related_name="documents")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    payment_line = models.ForeignKey(PaymentLine, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="documents")
    tax_year = models.PositiveSmallIntegerField(null=True, blank=True)
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    gross = amount_field(default=0)
    withholding = amount_field(default=0)
    other_deductions = amount_field(default=0)
    reimbursed_expenses = amount_field(default=0)
    net = amount_field(default=0)
    currency = currency_field()
    issued_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "pro_document"
        ordering = ["-issued_at"]
        constraints = [
            models.CheckConstraint(condition=Q(kind="remittance_advice", payment_line__isnull=False)
                                   | Q(kind="yearly_statement", payment_line__isnull=True),
                                   name="pro_document_line"),
            models.CheckConstraint(condition=Q(kind="yearly_statement", tax_year__isnull=False)
                                   | Q(kind="remittance_advice", tax_year__isnull=True),
                                   name="pro_document_year"),
            models.UniqueConstraint(fields=["agreement", "tax_year"], condition=Q(kind="yearly_statement"),
                                    name="pro_one_statement_per_year"),
            models.UniqueConstraint(fields=["payment_line"], condition=Q(kind="remittance_advice"),
                                    name="pro_one_advice_per_line"),
        ]
