"""ESC Escrow and held funds (document 02: 4.2, 6.5, 6.11, 6.15, 6.16, 6.17).

Tenmina never holds client money (ADR-03). Every table here is a mirror of
what the licensed bank reports, plus the instructions Tenmina sends it. No
column stores a balance: what is "held at the bank" is derived at read time
from bank-confirmed events (ADR-18, ADR-26, view `esc_confirmed_funds`).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

ESCROW_KINDS = ["purchase", "construction", "offplan", "project_fund", "held_funds", "repair", "event"]
# Kinds that pay out in several instructions; the instruction carries the release state (FR-ESC-010, 014).
STAGED_KINDS = {"construction", "offplan", "project_fund", "held_funds", "repair", "event"}
# RUL-07: a fresh search and site check before any release on a land, building or off-plan purchase.
FRESH_SEARCH_KINDS = {"purchase", "offplan"}
ESCROW_STATUSES = ["proposed", "agreed", "funded", "ready_to_release", "client_approved", "release_approved",
                   "partly_released", "released", "frozen", "cancelled"]
OPEN_STATUSES = [s for s in ESCROW_STATUSES if s not in ("released", "cancelled")]

PAYEE_KINDS = ["institution", "supplier", "vendor", "professional", "contractor", "agency", "insurer", "carer",
               "seller", "developer", "client_own_account"]
SUBJECT_TYPES = ["milestone", "offplan_stage", "project_invoice", "fee_invoice", "care_visit", "errand_step",
                 "repair", "event_vendor_payment", "premium"]
# 02 6.11 esc.payee_kind_for_subject(): which payee kinds each subject may pay. A purchase release
# (no subject) pays the seller or developer. No subject pays a runner or a contracted professional (RUL-27).
PAYEE_KIND_FOR_SUBJECT = {
    None: {"seller", "developer"},
    "milestone": {"contractor", "developer", "supplier"},
    "offplan_stage": {"developer"},
    "project_invoice": {"supplier", "contractor", "vendor", "professional"},
    "fee_invoice": {"institution"},
    "care_visit": {"carer", "agency"},
    "errand_step": {"agency", "institution"},
    "repair": {"contractor", "supplier"},
    "event_vendor_payment": {"vendor"},
    "premium": {"insurer"},
}
LIVE_INSTRUCTION = ["awaiting_client", "pending_approval", "approved", "sent"]


# ----------------------------------------------------------------- accounts at the bank (RUL-34)

class ProgrammeAccount(CountryScopedModel):
    """The partner bank's escrow account for the programme, one per currency
    and country, held by the bank as escrow agent. Never a Tenmina account."""

    KINDS = ["programme", "single_escrow"]
    STATUSES = ["pending", "active", "closed"]
    bank_partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    currency = currency_field()
    kind = models.TextField(default="programme", choices=[(k, k) for k in KINDS])
    holder = models.TextField(default="bank_as_escrow_agent")
    account_number = models.TextField()  # encrypt at field level in production (10.6)
    account_number_bidx = models.CharField(max_length=64)
    account_name = models.TextField()  # as the bank states it
    agreement_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    opened_on = models.DateField(null=True, blank=True)
    closed_on = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "esc_programme_account"
        constraints = [
            models.UniqueConstraint(fields=["country", "currency"], condition=Q(kind="programme", status="active"),
                                    name="esc_one_programme_account_per_currency"),
            models.CheckConstraint(condition=Q(holder="bank_as_escrow_agent"), name="esc_programme_holder_bank"),
            models.CheckConstraint(condition=~Q(status="closed") | Q(closed_on__isnull=False),
                                   name="esc_programme_closed_on"),
        ]

    @property
    def last4(self):
        return self.account_number[-4:]


PROGRAMME_ACCOUNT = state.register("programme_account", "esc_programme_account", {
    "pending": {"active", "closed"},
    "active": {"closed"},
})


# ----------------------------------------------------------------- verified payees (ADR-17, RUL-22)

class Payee(CountryScopedModel):
    """One registry of everyone who can receive money from an escrow or held
    amount. `name_match` is computed by the database; nobody can override it."""

    STATUSES = ["pending", "verified", "suspended", "revoked"]
    SUBJECT_TYPES = ["institution", "supplier", "panel_member", "organisation", "person", "partner"]
    NAME_SOURCES = ["bank_name_check", "bank_letter"]

    kind = models.TextField(choices=[(k, k) for k in PAYEE_KINDS])
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")  # an individual payee, or the person who signs for an organisation
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    legal_name = models.TextField()
    legal_name_norm = models.TextField()
    legal_name_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    bank_partner_id = models.UUIDField(null=True, blank=True)
    bank_name = models.TextField()
    account_number = models.TextField()  # encrypt at field level in production (10.6)
    account_number_bidx = models.CharField(max_length=64)
    account_name = models.TextField()  # as the BANK states it
    account_name_norm = models.TextField()
    account_name_source = models.TextField(choices=[(s, s) for s in NAME_SOURCES])
    account_name_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    account_name_raw_sha256 = models.CharField(max_length=64, blank=True, default="")
    name_match = models.GeneratedField(
        expression=models.Case(models.When(legal_name_norm=models.F("account_name_norm"), then=models.Value("matched")),
                               default=models.Value("mismatch")),
        output_field=models.TextField(), db_persist=True)
    verification_status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    second_check_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    suspend_reason = models.TextField(blank=True, default="")
    national_id_check = models.ForeignKey("accounts.NationalIdCheck", null=True, blank=True,
                                          on_delete=models.PROTECT, related_name="+")
    account_version = models.PositiveIntegerField(default=1)  # RUL-28: raised only by apply_payee_change()
    cooling_off_until = models.DateTimeField(null=True, blank=True)  # RUL-28: no release before this time
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    data_class = models.TextField(default="payee")

    class Meta:
        db_table = "esc_payee"
        indexes = [models.Index(fields=["country", "kind", "verification_status"])]
        constraints = [
            models.UniqueConstraint(fields=["subject_type", "subject_id", "kind"], name="esc_payee_subject_kind_uq"),
            models.CheckConstraint(condition=~Q(verification_status="verified") | (
                Q(name_match="matched") & Q(verified_by__isnull=False) & Q(second_check_by__isnull=False)
                & ~Q(second_check_by=models.F("verified_by")) & Q(approval_request__isnull=False)),
                name="esc_payee_verified_needs_two_and_match"),
            models.CheckConstraint(condition=~Q(verification_status="verified") | ~Q(subject_type="person")
                                   | Q(national_id_check__isnull=False), name="esc_payee_person_has_nid"),
        ]

    def __str__(self):
        return f"{self.legal_name} ({self.kind})"

    @property
    def last4(self):
        return self.account_number[-4:]


PAYEE = state.register("payee", "esc_payee", {
    "pending": {"verified", "revoked"},
    "verified": {"suspended", "pending", "revoked"},
    "suspended": {"pending", "verified", "revoked"},
}, field="verification_status")


# ----------------------------------------------------------------- escrows (FR-ESC-001)

class Escrow(CountryScopedModel):
    reference = models.TextField(unique=True)
    kind = models.TextField(choices=[(k, k) for k in ESCROW_KINDS])
    title = models.TextField(blank=True, default="")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="escrows")
    asset_id = models.UUIDField(null=True, blank=True)  # geo asset (plot or building)
    report_id = models.UUIDField(null=True, blank=True)  # rpt_report: verdict and section 11 conditions
    project_id = models.UUIDField(null=True, blank=True)  # bld_project or prj_project
    case_id = models.UUIDField(null=True, blank=True)
    bank_partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    bank_reference = models.TextField(blank=True, default="")
    programme_account = models.ForeignKey(ProgrammeAccount, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="escrows")
    virtual_account_ref = models.TextField(null=True, blank=True)  # issued by the bank (RUL-34)
    agreed_amount = amount_field()  # recorded fact from the terms, not a balance
    held_back_amount = amount_field(default=0)  # FR-ESC-020: set only by the escrow terms
    held_back_condition = models.TextField(blank=True, default="")
    currency = currency_field()  # the price currency: the country's own (RUL-35, Q-32)
    conversion_choice = models.TextField(default="on_deposit",
                                         choices=[("on_deposit", "on_deposit"), ("at_release", "at_release")])
    fx_buffer_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    conversion_chosen_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="+")
    conversion_chosen_at = models.DateTimeField(null=True, blank=True)
    terms_version = models.ForeignKey("administration.LockedTextVersion", on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="proposed", choices=[(s, s) for s in ESCROW_STATUSES])
    prior_status = models.TextField(blank=True, default="")  # restored when a freeze lifts
    fresh_search_case_id = models.UUIDField(null=True, blank=True)
    fresh_search_result_date = models.DateField(null=True, blank=True)  # date on the registry's result (RUL-07)
    site_check_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    agreed_at = models.DateTimeField(null=True, blank=True)
    funded_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    cancel_requested_at = models.DateTimeField(null=True, blank=True)
    cancel_requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                            on_delete=models.PROTECT, related_name="+")
    cancel_reason = models.TextField(blank=True, default="")
    cancel_approval = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    data_class = models.TextField(default="escrow_payment")

    class Meta:
        db_table = "esc_escrow"
        indexes = [models.Index(fields=["client", "kind", "status"])]
        constraints = [
            models.CheckConstraint(condition=~Q(kind="purchase") | Q(report_id__isnull=False),
                                   name="esc_purchase_has_report"),
            models.CheckConstraint(condition=~Q(kind__in=["construction", "offplan", "project_fund"])
                                   | Q(project_id__isnull=False), name="esc_project_kinds_have_project"),
            models.CheckConstraint(condition=Q(kind__in=["held_funds", "event", "project_fund"])
                                   | Q(asset_id__isnull=False), name="esc_asset_required"),
            models.CheckConstraint(condition=Q(agreed_amount__gt=0) | (Q(kind="held_funds") & Q(agreed_amount__gte=0)),
                                   name="esc_agreed_amount_positive"),
            models.CheckConstraint(condition=Q(status="proposed") | Q(status="cancelled", agreed_at__isnull=True) | (
                Q(programme_account__isnull=False) & Q(virtual_account_ref__isnull=False)),
                name="esc_agreed_needs_virtual_account"),
            models.CheckConstraint(condition=Q(held_back_amount=0) | (
                ~Q(kind="held_funds") & Q(held_back_amount__lt=models.F("agreed_amount"))),
                name="esc_held_back_share"),
            models.CheckConstraint(condition=Q(conversion_choice="on_deposit") | Q(fx_buffer_pct__isnull=False),
                                   name="esc_at_release_has_buffer"),
            models.UniqueConstraint(fields=["programme_account", "virtual_account_ref"],
                                    condition=Q(virtual_account_ref__isnull=False),
                                    name="esc_one_escrow_per_virtual_account"),
            models.UniqueConstraint(fields=["client", "country", "currency"],
                                    condition=Q(kind="held_funds") & ~Q(status__in=["released", "cancelled"]),
                                    name="esc_one_held_funds_per_client_currency"),
        ]

    def __str__(self):
        return self.reference

    @property
    def agreed_currency(self):
        return self.currency

    @property
    def is_staged(self):
        return self.kind in STAGED_KINDS

    @property
    def needs_fresh_search(self):
        return self.kind in FRESH_SEARCH_KINDS


ESCROW = state.register("escrow", "esc_escrow", {
    "proposed": {"agreed", "cancelled"},
    "agreed": {"funded", "cancelled"},
    "funded": {"ready_to_release", "partly_released", "released", "frozen", "cancelled"},
    "ready_to_release": {"client_approved", "funded", "frozen", "cancelled"},
    "client_approved": {"release_approved", "ready_to_release", "funded", "frozen"},
    "release_approved": {"released", "partly_released", "ready_to_release", "funded", "frozen"},
    "partly_released": {"ready_to_release", "released", "frozen", "cancelled"},
    "frozen": {"funded", "ready_to_release", "client_approved", "release_approved", "partly_released", "cancelled"},
})


class Party(BaseModel):
    ROLES = ["buyer", "seller", "developer", "contractor", "supplier", "vendor", "tenmina"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="parties")
    role = models.TextField(choices=[(r, r) for r in ROLES])
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    name = models.TextField()
    payee = models.ForeignKey(Payee, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    national_id_check = models.ForeignKey("accounts.NationalIdCheck", null=True, blank=True,
                                          on_delete=models.PROTECT, related_name="+")
    must_accept = models.BooleanField(default=True)

    class Meta:
        db_table = "esc_party"


class Acceptance(BaseModel):
    """FR-ESC-002: append-only. A new terms version needs new acceptances;
    earlier ones stay on the old version."""

    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="acceptances")
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="acceptances")
    terms_version = models.ForeignKey("administration.LockedTextVersion", on_delete=models.PROTECT, related_name="+")
    terms_sha256 = models.CharField(max_length=64)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    on_behalf = models.BooleanField(default=False)  # staff record a signed paper acceptance
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    accepted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "esc_acceptance"
        constraints = [
            models.UniqueConstraint(fields=["party", "terms_version"], name="esc_one_acceptance_per_version"),
            models.CheckConstraint(condition=Q(on_behalf=False) | Q(evidence__isnull=False),
                                   name="esc_acceptance_on_behalf_has_evidence"),
        ]


class Condition(BaseModel):
    """FR-ESC-005: release conditions, copied from the report's section 11 or added by staff."""

    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="conditions")
    source_condition_id = models.UUIDField(null=True, blank=True)  # rpt_condition
    key = models.TextField(blank=True, default="")
    text = models.TextField()
    status = models.TextField(default="open", choices=[("open", "open"), ("closed", "closed")])
    release_part = models.TextField(default="main", choices=[("main", "main"), ("held_back", "held_back")])
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_note = models.TextField(blank=True, default="")
    reopened_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopen_reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "esc_condition"
        constraints = [models.CheckConstraint(condition=Q(status="open") | (
            Q(closed_by__isnull=False) & Q(closed_at__isnull=False)), name="esc_condition_closed_by")]


CONDITION = state.register("esc_condition", "esc_condition", {"open": {"closed"}, "closed": {"open"}})


class StandingApproval(CountryScopedModel):
    """RUL-11: for care visits and errand steps the client may approve once, up
    to a monthly amount. Each payment still needs evidence and two staff."""

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="standing_approvals")
    subject_kind = models.TextField(choices=[("care_plan", "care_plan"), ("errand", "errand")])
    subject_id = models.UUIDField()
    monthly_max = amount_field()
    currency = currency_field()
    approved_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="active", choices=[("active", "active"), ("withdrawn", "withdrawn")])

    class Meta:
        db_table = "esc_standing_approval"
        constraints = [
            models.UniqueConstraint(fields=["subject_kind", "subject_id"], condition=Q(status="active"),
                                    name="esc_one_active_standing_approval"),
            models.CheckConstraint(condition=Q(monthly_max__gt=0), name="esc_standing_max_positive"),
            models.CheckConstraint(condition=~Q(status="withdrawn") | Q(withdrawn_at__isnull=False),
                                   name="esc_standing_withdrawn_at"),
        ]


class EscrowPayee(BaseModel):
    """RUL-28: whom an escrow may pay, and to which account version."""

    SOURCES = ["terms_agreed", "client_approved_payment", "payee_change"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="locked_payees")
    payee = models.ForeignKey(Payee, on_delete=models.PROTECT, related_name="locks")
    account_version = models.PositiveIntegerField()
    source = models.TextField(choices=[(s, s) for s in SOURCES])
    change = models.ForeignKey("PayeeChange", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    client_approved_at = models.DateTimeField()
    locked_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "esc_escrow_payee"
        constraints = [
            models.UniqueConstraint(fields=["escrow", "payee", "account_version"], name="esc_escrow_payee_uq"),
            models.CheckConstraint(condition=Q(source="payee_change", change__isnull=False)
                                   | (~Q(source="payee_change") & Q(change__isnull=True)),
                                   name="esc_escrow_payee_change_source"),
        ]


class PayeeChange(CountryScopedModel):
    """FR-ESC-016, FR-ESC-017, RUL-28, RUL-29, sequence 5.12."""

    KINDS = ["new_account", "new_payee", "refund_destination"]
    SOURCES = ["payee_signed_in", "staff_in_person", "client_signed_in"]
    STATUSES = ["requested", "checks_passed", "client_approved", "pending_approval", "applied", "stopped",
                "rejected", "withdrawn"]
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    payee = models.ForeignKey(Payee, null=True, blank=True, on_delete=models.PROTECT, related_name="changes")
    replaces_payee = models.ForeignKey(Payee, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    escrow = models.ForeignKey(Escrow, null=True, blank=True, on_delete=models.PROTECT, related_name="payee_changes")
    deposit_event = models.ForeignKey("BankEvent", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField()
    request_source = models.TextField(choices=[(s, s) for s in SOURCES])
    bank_name = models.TextField(blank=True, default="")
    account_number = models.TextField(blank=True, default="")
    account_name = models.TextField(blank=True, default="")
    account_name_norm = models.TextField(blank=True, default="")
    account_name_source = models.TextField(blank=True, default="", choices=[("", "")] + [
        (s, s) for s in Payee.NAME_SOURCES])
    account_name_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="+")
    account_name_raw_sha256 = models.CharField(max_length=64, blank=True, default="")
    account_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    previous_bank_name = models.TextField(blank=True, default="")
    previous_account_number = models.TextField(blank=True, default="")
    previous_account_name = models.TextField(blank=True, default="")
    national_id_check = models.ForeignKey("accounts.NationalIdCheck", null=True, blank=True,
                                          on_delete=models.PROTECT, related_name="+")
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    second_channel_message_id = models.UUIDField(null=True, blank=True)  # ntf_message
    applied_at = models.DateTimeField(null=True, blank=True)
    cooling_off_until = models.DateTimeField(null=True, blank=True)
    stopped_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    stopped_at = models.DateTimeField(null=True, blank=True)
    stop_reason = models.TextField(blank=True, default="")
    stop_token_hash = models.CharField(max_length=64, blank=True, default="")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(auto_now_add=True)
    client_reminded_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="requested", choices=[(s, s) for s in STATUSES])
    data_class = models.TextField(default="payee")

    class Meta:
        db_table = "esc_payee_change"
        constraints = [
            models.CheckConstraint(condition=~Q(kind="new_account") | (
                Q(payee__isnull=False) & ~Q(account_number="")), name="esc_change_new_account"),
            models.CheckConstraint(condition=~Q(kind="new_payee") | (
                Q(payee__isnull=False) & Q(replaces_payee__isnull=False) & Q(escrow__isnull=False)),
                name="esc_change_new_payee"),
            models.CheckConstraint(condition=~Q(kind="refund_destination") | (
                Q(payee__isnull=True) & Q(escrow__isnull=False) & Q(deposit_event__isnull=False)
                & ~Q(account_number="")), name="esc_change_refund_destination"),
            models.CheckConstraint(condition=~Q(account_name_source="bank_letter") | Q(account_checked_by__isnull=False)
                                   | ~Q(status__in=["checks_passed", "client_approved", "pending_approval", "applied",
                                                     "stopped"]), name="esc_change_letter_checked"),
            models.CheckConstraint(condition=~Q(status__in=["applied", "stopped"]) | (
                Q(national_id_check__isnull=False) & Q(approval_request__isnull=False)
                & Q(second_channel_message_id__isnull=False) & Q(applied_at__isnull=False)
                & Q(cooling_off_until__gt=models.F("applied_at"))
                & (Q(escrow__isnull=True) | Q(client_approved_at__isnull=False))), name="esc_change_applied_complete"),
            models.CheckConstraint(condition=~Q(status="stopped") | (
                Q(stopped_by__isnull=False) & Q(stopped_at__isnull=False)
                & Q(stopped_at__lt=models.F("cooling_off_until"))), name="esc_change_stopped_in_cooling_off"),
            models.UniqueConstraint(fields=["payee"], condition=Q(status__in=[
                "requested", "checks_passed", "client_approved", "pending_approval"]) & Q(payee__isnull=False),
                name="esc_one_open_change_per_payee"),
        ]


PAYEE_CHANGE = state.register("payee_change", "esc_payee_change", {
    "requested": {"checks_passed", "rejected", "withdrawn"},
    "checks_passed": {"client_approved", "pending_approval", "rejected", "withdrawn"},
    "client_approved": {"pending_approval", "rejected", "withdrawn"},
    "pending_approval": {"applied", "rejected", "withdrawn"},
    "applied": {"stopped"},
})


# ----------------------------------------------------------------- bank events (FR-ESC-004, 009, 017, 019)

class StatementFile(CountryScopedModel):
    """FR-ESC-011: the bank's statement file. The same file is never applied twice."""

    ACCOUNT_KINDS = ["escrow", "held_funds", "owner_rent"]
    programme_account = models.ForeignKey(ProgrammeAccount, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    account_kind = models.TextField(default="escrow", choices=[(k, k) for k in ACCOUNT_KINDS])
    sha256 = models.CharField(max_length=64, unique=True)
    original_name = models.TextField(blank=True, default="")
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    line_count = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "esc_statement_file"


class BankEvent(CountryScopedModel):
    """What the bank reports: deposits, release and refund confirmations,
    and the two legs of a conversion. Only `confirmed` rows count."""

    KINDS = ["deposit", "release_confirmed", "refund_confirmed", "conversion_debit", "conversion_credit",
             "correction_debit"]  # correction_debit: the bank's correcting entry for a misdirected deposit (I-43)
    SOURCES = ["api", "statement", "manual"]
    STATUSES = ["pending_check", "confirmed", "rejected"]
    ROUTES = ["", "bank_transfer", "transfer_partner", "bank_correction"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="bank_events")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    amount = amount_field()
    currency = currency_field()
    occurred_at = models.DateTimeField()
    bank_reference = models.TextField()
    programme_account = models.ForeignKey(ProgrammeAccount, on_delete=models.PROTECT, related_name="+")
    virtual_account_ref = models.TextField()  # as the bank's confirmation gives it
    source = models.TextField(choices=[(s, s) for s in SOURCES])
    status = models.TextField(default="pending_check", choices=[(s, s) for s in STATUSES])
    proof_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    checked_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True, default="")
    # Deposits: the source account exactly as the bank's confirmation gives it (FR-ESC-017, RUL-29).
    source_bank_name = models.TextField(blank=True, default="")
    source_account_number = models.TextField(blank=True, default="")
    source_account_name = models.TextField(blank=True, default="")
    source_account_bidx = models.CharField(max_length=64, blank=True, default="")
    source_account_known = models.BooleanField(default=True)
    source_cannot_receive = models.BooleanField(default=False)  # set when the bank returns a refund
    deposit_route = models.TextField(blank=True, default="", choices=[(r, r) for r in ROUTES])
    transfer_partner = models.ForeignKey("administration.Partner", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    partner_reference = models.TextField(blank=True, default="")
    instruction = models.ForeignKey("ReleaseInstruction", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="bank_events")
    applied_rate = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
    applied_fees = amount_field(null=True, blank=True)
    statement_line = models.ForeignKey("StatementLine", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    misdirected = models.BooleanField(default=False)  # RUL-34: credited here by the bank's mistake; never released
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "esc_bank_event"
        indexes = [models.Index(fields=["escrow", "currency", "status"])]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="esc_bank_event_amount_positive"),
            models.UniqueConstraint(fields=["escrow", "kind", "bank_reference"], condition=~Q(status="rejected"),
                                    name="esc_bank_event_counts_once"),
            models.CheckConstraint(condition=~Q(source="manual") | Q(status="pending_check") | Q(status="rejected") | (
                Q(proof_evidence__isnull=False) & Q(entered_by__isnull=False) & Q(checked_by__isnull=False)
                & ~Q(checked_by=models.F("entered_by"))), name="esc_bank_event_manual_second_person"),
            models.CheckConstraint(condition=~Q(source="manual") | Q(proof_evidence__isnull=False),
                                   name="esc_bank_event_manual_has_proof"),
            models.CheckConstraint(condition=~Q(kind="deposit") | Q(source_account_known=False) | (
                ~Q(source_account_number="") & ~Q(source_account_name="")), name="esc_deposit_source_account"),
            models.CheckConstraint(condition=~Q(kind__in=["release_confirmed", "refund_confirmed", "conversion_debit"])
                                   | Q(instruction__isnull=False), name="esc_outgoing_event_names_instruction"),
        ]


class StatementLine(BaseModel):
    KINDS = ["credit", "debit", "position"]
    MATCH = ["matched", "unmatched", "duplicate", "ignored"]
    file = models.ForeignKey(StatementFile, on_delete=models.PROTECT, related_name="lines")
    line_no = models.PositiveIntegerField()
    booked_on = models.DateField()
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    amount = amount_field()
    currency = currency_field()
    virtual_account_ref = models.TextField(blank=True, default="")
    bank_reference = models.TextField(blank=True, default="")
    counterparty_bank = models.TextField(blank=True, default="")
    counterparty_account = models.TextField(blank=True, default="")
    counterparty_name = models.TextField(blank=True, default="")
    narrative = models.TextField(blank=True, default="")
    match_status = models.TextField(default="unmatched", choices=[(m, m) for m in MATCH])
    escrow = models.ForeignKey(Escrow, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    bank_event = models.ForeignKey(BankEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    bank_position = models.ForeignKey("BankPosition", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "esc_statement_line"
        constraints = [models.UniqueConstraint(fields=["file", "line_no"], name="esc_statement_line_uq")]


class BankPosition(CountryScopedModel):
    """FR-ESC-019: the bank's own daily figure per escrow and currency,
    compared with the derived figure. A mismatch blocks releases."""

    STATUSES = ["pending_check", "matched", "mismatch", "resolved"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="bank_positions")
    virtual_account_ref = models.TextField()
    as_of = models.DateField()
    reported_held_amount = amount_field()  # the bank's figure; never used to pay
    currency = currency_field()
    source = models.TextField(choices=[(s, s) for s in ("api", "statement", "manual")])
    statement_file = models.ForeignKey(StatementFile, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    proof_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    derived_held_at_bank = amount_field(null=True, blank=True)
    status = models.TextField(default="pending_check", choices=[(s, s) for s in STATUSES])
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolution_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                              on_delete=models.PROTECT, related_name="+")
    resolution_note = models.TextField(blank=True, default="")
    resolution_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "esc_bank_position"
        constraints = [
            models.UniqueConstraint(fields=["escrow", "currency", "as_of"], name="esc_one_position_per_day"),
            models.CheckConstraint(condition=~Q(source="manual") | Q(status="pending_check") | (
                Q(proof_evidence__isnull=False) & Q(entered_by__isnull=False) & Q(checked_by__isnull=False)
                & ~Q(checked_by=models.F("entered_by"))), name="esc_position_manual_second_person"),
            models.CheckConstraint(condition=~Q(status="resolved") | (
                Q(resolved_by__isnull=False) & Q(resolution_checked_by__isnull=False)
                & ~Q(resolution_checked_by=models.F("resolved_by")) & ~Q(resolution_note="")
                & Q(resolution_evidence__isnull=False)), name="esc_position_resolved_by_two"),
            models.CheckConstraint(condition=~Q(status="matched") | Q(
                reported_held_amount=models.F("derived_held_at_bank")), name="esc_position_matched_equal"),
        ]


POSITION = state.register("bank_position", "esc_bank_position", {
    "pending_check": {"matched", "mismatch"},
    "mismatch": {"resolved"},
})


# ----------------------------------------------------------------- instructions (5.3, FR-ESC-006 to 010, 013)

class ReleaseInstruction(CountryScopedModel):
    KINDS = ["release", "partial_release", "cancel_refund", "conversion"]
    STATUSES = ["draft", "awaiting_client", "pending_approval", "approved", "sent", "confirmed", "rejected_by_bank",
                "rejected", "withdrawn"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="instructions")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    subject_type = models.TextField(null=True, blank=True, choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField(null=True, blank=True)
    subject_label = models.TextField(blank=True, default="")
    family_member_id = models.UUIDField(null=True, blank=True)  # for the statement per family member (FR-FEE-007)
    payee = models.ForeignKey(Payee, null=True, blank=True, on_delete=models.PROTECT, related_name="instructions")
    payee_account_version = models.PositiveIntegerField(null=True, blank=True)
    standing_approval = models.ForeignKey(StandingApproval, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    amount = amount_field()
    holdback_amount = amount_field(default=0)
    currency = currency_field()
    to_currency = currency_field(null=True, blank=True)
    fx_quote = models.ForeignKey("FxQuote", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.TextField(blank=True, default="")
    approval_request = models.ForeignKey("core.ApprovalRequest", on_delete=models.PROTECT, related_name="+")
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    client_approval_method = models.TextField(blank=True, default="")  # mfa_step_up | totp_code | standing
    client_approved_amount = amount_field(null=True, blank=True)
    client_declined_at = models.DateTimeField(null=True, blank=True)
    client_reminded_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="awaiting_client", choices=[(s, s) for s in STATUSES])
    document_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    document_sha256 = models.CharField(max_length=64, blank=True, default="")
    kms_signature = models.TextField(blank=True, default="")
    signature_key_id = models.TextField(blank=True, default="")
    sent_at = models.DateTimeField(null=True, blank=True)
    sent_channel = models.TextField(blank=True, default="")
    sent_recipient = models.TextField(blank=True, default="")
    sent_reference = models.TextField(blank=True, default="")
    send_attempts = models.PositiveSmallIntegerField(default=0)
    last_send_error = models.TextField(blank=True, default="")
    bank_confirmation_event = models.ForeignKey(BankEvent, null=True, blank=True, on_delete=models.PROTECT,
                                                related_name="+")
    refund_source_event = models.ForeignKey(BankEvent, null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="refunds")
    refund_change = models.ForeignKey(PayeeChange, null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    release_part = models.TextField(default="main", choices=[("main", "main"), ("held_back", "held_back")])
    clock_started_at = models.DateTimeField(null=True, blank=True)
    staff_approval_due_on = models.DateField(null=True, blank=True)
    last_approval_at = models.DateTimeField(null=True, blank=True)
    send_due_on = models.DateField(null=True, blank=True)
    bank_pay_due_on = models.DateField(null=True, blank=True)
    shortfall_since = models.DateTimeField(null=True, blank=True)
    shortfall_amount = amount_field(null=True, blank=True)
    send_overdue_alerted_at = models.DateTimeField(null=True, blank=True)
    bank_overdue_alerted_at = models.DateTimeField(null=True, blank=True)
    approval_overdue_alerted_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.TextField(blank=True, default="")
    data_class = models.TextField(default="escrow_payment")

    class Meta:
        db_table = "esc_release_instruction"
        indexes = [models.Index(fields=["escrow", "status"]), models.Index(fields=["status", "send_due_on"])]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="esc_instruction_amount_positive"),
            models.CheckConstraint(condition=Q(holdback_amount__gte=0), name="esc_instruction_holdback"),
            models.CheckConstraint(condition=~Q(kind="partial_release") | Q(subject_id__isnull=False),
                                   name="esc_partial_has_subject"),
            models.CheckConstraint(condition=Q(subject_type__isnull=True, subject_id__isnull=True)
                                   | Q(subject_type__isnull=False, subject_id__isnull=False),
                                   name="esc_subject_pair"),
            models.CheckConstraint(condition=Q(kind__in=["cancel_refund", "conversion"]) | Q(payee__isnull=False),
                                   name="esc_release_names_payee"),
            models.CheckConstraint(condition=Q(kind="conversion", to_currency__isnull=False)
                                   | (~Q(kind="conversion") & Q(to_currency__isnull=True)),
                                   name="esc_conversion_to_currency"),
            models.CheckConstraint(condition=~Q(kind="conversion") | (
                Q(payee__isnull=True) & Q(fx_quote__isnull=False) & ~Q(to_currency=models.F("currency"))
                & Q(subject_id__isnull=True)), name="esc_conversion_shape"),
            models.CheckConstraint(condition=Q(kind="cancel_refund", refund_source_event__isnull=False)
                                   | (~Q(kind="cancel_refund") & Q(refund_source_event__isnull=True)),
                                   name="esc_refund_names_deposit"),
            models.CheckConstraint(condition=Q(refund_change__isnull=True) | Q(kind="cancel_refund"),
                                   name="esc_refund_change_only_refund"),
            models.CheckConstraint(condition=Q(payee__isnull=True, payee_account_version__isnull=True)
                                   | Q(payee__isnull=False, payee_account_version__isnull=False),
                                   name="esc_payee_version_pair"),
            models.CheckConstraint(condition=Q(standing_approval__isnull=True)
                                   | Q(subject_type__in=["care_visit", "errand_step"]), name="esc_standing_subjects"),
            models.CheckConstraint(condition=~Q(status__in=["sent", "confirmed"]) | (
                ~Q(document_sha256="") & ~Q(kms_signature="")), name="esc_sent_is_signed"),
            models.CheckConstraint(condition=~Q(status__in=["approved", "sent", "confirmed"]) | (
                Q(last_approval_at__isnull=False) & Q(send_due_on__isnull=False)), name="esc_approved_has_clock"),
            models.CheckConstraint(condition=Q(release_part="main") | Q(kind="release"), name="esc_held_back_release"),
            models.UniqueConstraint(fields=["subject_type", "subject_id"], condition=Q(
                status__in=["awaiting_client", "pending_approval", "approved", "sent", "confirmed"])
                & Q(subject_id__isnull=False), name="esc_one_live_instruction_per_subject"),
            models.UniqueConstraint(fields=["refund_source_event"], condition=Q(
                status__in=["awaiting_client", "pending_approval", "approved", "sent"])
                & Q(refund_source_event__isnull=False), name="esc_one_live_refund_per_deposit"),
        ]


INSTRUCTION = state.register("release_instruction", "esc_release_instruction", {
    "draft": {"awaiting_client", "pending_approval", "withdrawn"},
    "awaiting_client": {"pending_approval", "rejected", "withdrawn"},
    "pending_approval": {"approved", "rejected", "withdrawn", "awaiting_client"},
    "approved": {"sent", "withdrawn"},
    "sent": {"confirmed", "rejected_by_bank"},
})


class Freeze(BaseModel):
    """RUL-15, RUL-32: a dispute, a failed re-check incident or a reviewer's
    hold freezes releases. 02 6.15 `esc_incident_freeze`."""

    KINDS = ["incident", "dispute", "reviewer_hold"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="freezes")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    source_id = models.UUIDField()  # rpt_incident, dsp_dispute, or this row for a hold
    prior_status = models.TextField()
    reason = models.TextField(blank=True, default="")
    frozen_at = models.DateTimeField(auto_now_add=True)
    frozen_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    lift_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "esc_incident_freeze"
        constraints = [models.UniqueConstraint(fields=["escrow", "kind", "source_id"], name="esc_freeze_uq")]


class ReportSnapshot(BaseModel):
    """What ESC learnt from `report.released` (RPT is a separate module): the
    verdict and the section 11 conditions an escrow is created from."""

    report_id = models.UUIDField(unique=True)
    country = models.ForeignKey("countries.Country", on_delete=models.PROTECT, related_name="+")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    case_id = models.UUIDField(null=True, blank=True)
    asset_id = models.UUIDField(null=True, blank=True)
    verdict = models.TextField()  # green | amber | red
    conditions = models.JSONField(default=list, blank=True)  # [{"id", "key", "text"}]
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "esc_report_snapshot"


# ----------------------------------------------------------------- exchange (6.17, RUL-35, RUL-36)

class FxAccount(CountryScopedModel):
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="fx_accounts")
    programme_account = models.ForeignKey(ProgrammeAccount, on_delete=models.PROTECT, related_name="+")
    currency = currency_field()
    virtual_account_ref = models.TextField()
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "esc_fx_account"
        constraints = [
            models.UniqueConstraint(fields=["escrow", "currency"], name="esc_fx_account_one_per_currency"),
            models.UniqueConstraint(fields=["programme_account", "virtual_account_ref"],
                                    name="esc_fx_account_unique_ref"),
        ]


class ProgrammeRate(CountryScopedModel):
    """Q-33: the bank's written programme margin over the reference rate."""

    bank_partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    from_currency = currency_field()
    to_currency = currency_field()
    band_from = amount_field(default=0)
    band_to = amount_field(null=True, blank=True)
    margin_pct = models.DecimalField(max_digits=7, decimal_places=4)
    tolerance_pct = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    fee_schedule = models.JSONField(default=list)  # [{"name", "amount", "currency"}]
    reference_source = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    valid_from = models.DateField()
    valid_to = models.DateField(null=True, blank=True)
    agreement_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="pending", choices=[(s, s) for s in ("pending", "active", "rejected")])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "esc_programme_rate"
        constraints = [
            models.CheckConstraint(condition=~Q(from_currency=models.F("to_currency")), name="esc_prate_pair"),
            models.CheckConstraint(condition=Q(band_to__isnull=True) | Q(band_to__gt=models.F("band_from")),
                                   name="esc_prate_band"),
            models.CheckConstraint(condition=Q(margin_pct__gte=0) & Q(tolerance_pct__gte=0), name="esc_prate_margin"),
        ]


class FxRateObservation(CountryScopedModel):
    KINDS = ["reference", "programme", "provider"]
    source_partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    from_currency = currency_field()
    to_currency = currency_field()
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    send_amount = amount_field(null=True, blank=True)
    fees_total = amount_field(null=True, blank=True)
    delivered_amount = amount_field(null=True, blank=True)
    source_published_at = models.DateTimeField(null=True, blank=True)
    collected_at = models.DateTimeField(auto_now_add=True)
    method = models.TextField(choices=[(m, m) for m in ("api", "file", "manual")])
    raw_sha256 = models.CharField(max_length=64)
    proof_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "esc_fx_rate_observation"
        constraints = [
            models.CheckConstraint(condition=Q(rate__gt=0), name="esc_obs_rate_positive"),
            models.CheckConstraint(condition=Q(kind="reference") | (
                Q(send_amount__isnull=False) & Q(fees_total__isnull=False) & Q(delivered_amount__isnull=False)),
                name="esc_obs_provider_figures"),
            models.CheckConstraint(condition=~Q(method="manual") | (
                Q(proof_evidence__isnull=False) & Q(entered_by__isnull=False)), name="esc_obs_manual_proof"),
            models.CheckConstraint(condition=Q(checked_by__isnull=True) | ~Q(checked_by=models.F("entered_by")),
                                   name="esc_obs_checker_differs"),
        ]

    @property
    def usable(self):
        return self.method != "manual" or self.checked_by_id is not None


class FxComparisonRun(CountryScopedModel):
    run_date = models.DateField()
    from_currency = currency_field()
    to_currency = currency_field()
    send_amount = amount_field()
    reference_observation = models.ForeignKey(FxRateObservation, null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="+")
    providers_expected = models.PositiveIntegerField()
    providers_fresh = models.PositiveIntegerField()
    status = models.TextField(choices=[(s, s) for s in ("complete", "partial", "failed")])
    best_observation = models.ForeignKey(FxRateObservation, null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    programme_rank = models.PositiveIntegerField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "esc_fx_comparison_run"
        constraints = [
            models.UniqueConstraint(fields=["country", "run_date", "from_currency", "to_currency", "send_amount"],
                                    name="esc_fx_run_uq"),
            models.CheckConstraint(condition=~Q(status="complete") | (
                Q(providers_fresh=models.F("providers_expected")) & Q(providers_expected__gte=1)
                & Q(reference_observation__isnull=False) & Q(best_observation__isnull=False)),
                name="esc_fx_run_complete"),
        ]


class FxComparisonItem(BaseModel):
    run = models.ForeignKey(FxComparisonRun, on_delete=models.PROTECT, related_name="items")
    observation = models.ForeignKey(FxRateObservation, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    provider = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    stale = models.BooleanField()
    rank = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "esc_fx_comparison_item"
        constraints = [models.UniqueConstraint(fields=["run", "provider"], name="esc_fx_item_uq")]


class FxQuote(CountryScopedModel):
    """RUL-35: what the client saw and accepted. Insert-only, except acceptance."""

    PURPOSES = ["deposit", "release_conversion", "refund_conversion"]
    ROUTES = ["escrow_fx_account", "escrow_local_account", "transfer_partner"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="fx_quotes")
    purpose = models.TextField(choices=[(p, p) for p in PURPOSES])
    route = models.TextField(choices=[(r, r) for r in ROUTES])
    provider_partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    from_currency = currency_field()
    from_amount = amount_field()
    to_currency = currency_field()
    reference_observation = models.ForeignKey(FxRateObservation, on_delete=models.PROTECT, related_name="+")
    reference_rate = models.DecimalField(max_digits=18, decimal_places=8)
    offered_rate = models.DecimalField(max_digits=18, decimal_places=8)
    margin_pct = models.DecimalField(max_digits=9, decimal_places=4)
    programme_rate = models.ForeignKey(ProgrammeRate, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    fees = models.JSONField(default=list)
    fees_total_to = amount_field()
    expected_to_amount = amount_field()
    limits_text = models.TextField(blank=True, default="")
    tenmina_margin = amount_field(default=0)
    partner_payment_to_tenmina = amount_field(default=0)
    partner_payment_currency = currency_field(null=True, blank=True)
    is_estimate = models.BooleanField(default=False)  # the client's own bank: not checked by Tenmina
    best_rate_claim = models.BooleanField(default=False)
    comparison_run = models.ForeignKey(FxComparisonRun, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    shown_text = models.TextField()
    shown_sha256 = models.CharField(max_length=64)
    quoted_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "esc_fx_quote"
        constraints = [
            models.CheckConstraint(condition=~Q(from_currency=models.F("to_currency")), name="esc_quote_pair"),
            models.CheckConstraint(condition=Q(from_amount__gt=0) & Q(reference_rate__gt=0) & Q(offered_rate__gt=0)
                                   & Q(expected_to_amount__gt=0) & Q(fees_total_to__gte=0),
                                   name="esc_quote_positive"),
            models.CheckConstraint(condition=Q(tenmina_margin=0), name="esc_quote_no_tenmina_margin"),
            models.CheckConstraint(condition=Q(accepted_by__isnull=True, accepted_at__isnull=True)
                                   | Q(accepted_by__isnull=False, accepted_at__isnull=False),
                                   name="esc_quote_accept_pair"),
            models.CheckConstraint(condition=Q(accepted_at__isnull=True) | Q(accepted_at__lte=models.F("expires_at")),
                                   name="esc_quote_accept_in_time"),
            models.CheckConstraint(condition=~Q(route="escrow_fx_account") | Q(programme_rate__isnull=False),
                                   name="esc_quote_bank_route_programme_rate"),
            models.CheckConstraint(condition=Q(partner_payment_to_tenmina=0)
                                   | Q(partner_payment_currency__isnull=False), name="esc_quote_partner_payment"),
            models.CheckConstraint(condition=Q(best_rate_claim=False) | Q(comparison_run__isnull=False),
                                   name="esc_quote_best_rate_needs_run"),
        ]


class FxConversion(CountryScopedModel):
    ROUTES = ["bank_conversion", "transfer_partner", "client_bank"]
    STATUSES = ["within", "outside", "not_checked", "resolved"]
    escrow = models.ForeignKey(Escrow, on_delete=models.PROTECT, related_name="fx_conversions")
    quote = models.ForeignKey(FxQuote, on_delete=models.PROTECT, related_name="conversions")
    route = models.TextField(choices=[(r, r) for r in ROUTES])
    instruction = models.ForeignKey(ReleaseInstruction, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    debit_event = models.ForeignKey(BankEvent, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    credit_event = models.OneToOneField(BankEvent, on_delete=models.PROTECT, related_name="fx_conversion")
    from_amount = amount_field()
    to_amount = amount_field()
    applied_rate = models.DecimalField(max_digits=18, decimal_places=8)
    applied_fees = amount_field()
    reference_observation = models.ForeignKey(FxRateObservation, on_delete=models.PROTECT, related_name="+")
    reference_rate = models.DecimalField(max_digits=18, decimal_places=8)
    margin_pct = models.DecimalField(max_digits=9, decimal_places=4)
    programme_rate = models.ForeignKey(ProgrammeRate, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    short_of_quote = amount_field()
    status = models.TextField(choices=[(s, s) for s in STATUSES])
    findings = models.JSONField(default=list, blank=True)
    claim_amount = amount_field(null=True, blank=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claim_reference = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolution_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                              on_delete=models.PROTECT, related_name="+")
    resolution_note = models.TextField(blank=True, default="")
    resolution_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="+")

    class Meta:
        db_table = "esc_fx_conversion"
        constraints = [
            models.CheckConstraint(condition=~Q(route="bank_conversion") | (
                Q(debit_event__isnull=False) & Q(programme_rate__isnull=False)), name="esc_conv_bank_legs"),
            models.CheckConstraint(condition=~Q(status="resolved") | (
                Q(resolved_by__isnull=False) & Q(resolution_checked_by__isnull=False)
                & ~Q(resolution_checked_by=models.F("resolved_by")) & ~Q(resolution_note="")
                & Q(resolution_evidence__isnull=False)), name="esc_conv_resolved_by_two"),
        ]
