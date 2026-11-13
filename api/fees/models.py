"""FEE Payments to institutions (document 02 section 6.12, FR-FEE-001 to FR-FEE-007).

Two routes pay an institution invoice (decision 2026-11-12, two front doors):

- `client_direct` ("verify and confirm"): Tenmina verifies the institution, its
  account in its own name and a named contact who confirms the invoice. The
  client pays that verified account from their own bank or transfer service;
  the institution confirms receipt; Tenmina returns the official receipt.
  Tenmina never touches the money.
- `held_funds`: the partner bank pays the institution's verified payee record
  from the client's held funds, through `escrow.services.request_release`,
  after the client and then two staff approve (RUL-05, RUL-11, RUL-22).

The route is chosen per country (`fees.payment_route` in the country
configuration, default `client_direct`) and a case manager can override it
per invoice before the client approves. There is no cash route anywhere
(FR-FEE-006): a runner task carries paper, never money.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

# Default institution types; a country may publish its own list as `fees.institution_types` (02 6.12).
INSTITUTION_TYPES = ["school", "university", "hospital", "clinic", "pharmacy", "utility", "government_agency",
                     "landlord_company", "church", "mosque", "funeral_home"]
ROUTES = ["client_direct", "held_funds"]


class Institution(CountryScopedModel):
    """FR-FEE-001. `eligible_for_direct_payment` is computed by the database:
    only a verified institution with a payee record can be paid (FR-FEE-006)."""

    STATUSES = ["pending", "verified", "not_verified", "not_eligible", "suspended"]
    CHANNELS = ["manual_upload", "institution_portal", "file"]

    type = models.TextField()
    legal_name = models.TextField()
    legal_name_norm = models.TextField()
    legal_name_bidx = models.CharField(max_length=64)
    registration_number = models.TextField(blank=True, default="")
    registration_number_norm = models.TextField(blank=True, default="")
    registration_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="+")
    address = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    verification_case = models.ForeignKey("cases.Case", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    payee = models.OneToOneField("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    invoice_channel = models.TextField(default="manual_upload", choices=[(c, c) for c in CHANNELS])
    returns_confirmation = models.BooleanField(default=False)  # enrolment or treatment confirmation, FR-FEE-004
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    eligible_for_direct_payment = models.GeneratedField(
        expression=models.Case(models.When(Q(status="verified") & Q(payee__isnull=False), then=models.Value(True)),
                               default=models.Value(False)),
        output_field=models.BooleanField(), db_persist=True)
    status_reason = models.TextField(blank=True, default="")  # shown to the client in plain words
    not_eligible_reason = models.TextField(blank=True, default="")
    eligibility_proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                                on_delete=models.PROTECT, related_name="+")
    eligibility_proposed_at = models.DateTimeField(null=True, blank=True)
    eligibility_proposed_reason = models.TextField(blank=True, default="")
    eligibility_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                               on_delete=models.PROTECT, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    look_alike_of = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    look_alike_status = models.TextField(blank=True, default="", choices=[
        ("", ""), ("open", "open"), ("cleared", "cleared"), ("confirmed", "confirmed")])
    look_alike_reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                               on_delete=models.PROTECT, related_name="+")
    # What the client typed. Never used for a payment: only the verified payee record is (RUL-22).
    proposed_bank_name = models.TextField(blank=True, default="")
    proposed_account_number = models.TextField(blank=True, default="")
    proposed_account_name = models.TextField(blank=True, default="")
    added_by_client = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    data_class = models.TextField(default="institution")

    class Meta:
        db_table = "fee_institution"
        indexes = [models.Index(fields=["country", "status"]), models.Index(fields=["registration_number_norm"])]
        constraints = [
            models.UniqueConstraint(fields=["country", "legal_name_bidx"], name="fee_institution_name_uq"),
            models.UniqueConstraint(fields=["country", "registration_number_norm"],
                                    condition=~Q(registration_number_norm=""), name="fee_institution_reg_uq"),
            models.CheckConstraint(condition=~Q(status="verified") | Q(payee__isnull=False),
                                   name="fee_institution_verified_has_payee"),
            models.CheckConstraint(condition=~Q(status="not_eligible") | (~Q(not_eligible_reason="")
                                                                          & Q(eligibility_checked_by__isnull=False)),
                                   name="fee_institution_not_eligible_reason"),
        ]

    def __str__(self):
        return self.legal_name


INSTITUTION = state.register("fee_institution", "fee_institution", {
    "pending": {"verified", "not_verified", "not_eligible", "suspended"},
    "verified": {"suspended", "pending", "not_eligible"},
    "not_verified": {"pending"},
    "not_eligible": {"pending"},
    "suspended": {"pending", "verified", "not_eligible"},
})


class ClientInstitution(BaseModel):
    """Which institutions a client has added or uses. A duplicate registration
    links the client to the existing record (TC-FEE-001-04)."""

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="client_links")

    class Meta:
        db_table = "fee_client_institution"
        constraints = [models.UniqueConstraint(fields=["client", "institution"], name="fee_client_institution_uq")]


class Beneficiary(CountryScopedModel):
    """A family member who is a pupil, student or patient at an institution.
    `tenmina_reference` is what the institution quotes when it sends an invoice
    to Tenmina (US-FEE-002); it names no one."""

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="beneficiaries")
    institution_account_ref = models.TextField(blank=True, default="")  # student or patient number
    tenmina_reference = models.CharField(max_length=32, unique=True)
    status = models.TextField(default="active", choices=[("active", "active"), ("ended", "ended")])

    class Meta:
        db_table = "fee_beneficiary"
        constraints = [models.UniqueConstraint(fields=["family_member", "institution"], condition=Q(status="active"),
                                               name="fee_beneficiary_uq")]


class InstitutionContact(BaseModel):
    """FR-FEE-001: the named contact who confirms invoices and sends receipts.
    `person` is set when the contact has a Tenmina account (role IC)."""

    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="contacts")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    full_name = models.TextField()
    role_title = models.TextField(blank=True, default="")
    phone = models.CharField(max_length=32, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    may_confirm_invoices = models.BooleanField(default=True)
    may_send_receipts = models.BooleanField(default=True)
    confirmation_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="+")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="active", choices=[("active", "active"), ("removed", "removed")])
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fee_institution_contact"
        constraints = [
            models.UniqueConstraint(fields=["institution", "person"], condition=Q(status="active", person__isnull=False),
                                    name="fee_contact_person_uq"),
        ]


class Schedule(CountryScopedModel):
    """FR-FEE-005: termly or monthly fees. The job creates a draft invoice, asks
    the institution for the bill and reminds the client. Nothing is paid
    without the client's approval of that invoice (RUL-11)."""

    PERIODS = ["term", "month", "quarter"]
    STATUSES = ["active", "paused", "ended"]
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="schedules")
    label = models.TextField(blank=True, default="")
    period = models.TextField(choices=[(p, p) for p in PERIODS])
    expected_amount = amount_field()
    expected_currency = currency_field()
    next_due_on = models.DateField()
    reminder_lead_days = models.PositiveSmallIntegerField(default=14)
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    last_generated_due_on = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "fee_schedule"
        constraints = [models.CheckConstraint(condition=Q(expected_amount__gt=0), name="fee_schedule_amount_positive")]


SCHEDULE = state.register("fee_schedule", "fee_schedule", {
    "active": {"paused", "ended"},
    "paused": {"active", "ended"},
})


class Invoice(CountryScopedModel):
    """FR-FEE-002, FR-FEE-003. The family member is never the payee."""

    SUBMITTERS = ["client", "institution_contact", "schedule", "case_manager", "runner"]
    CHECK_STATUSES = ["pending", "flagged", "checked", "rejected"]
    STATUSES = ["draft", "submitted", "checked", "client_approved", "instructed", "paid", "receipted", "rejected",
                "cancelled"]
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="invoices")
    schedule = models.ForeignKey(Schedule, null=True, blank=True, on_delete=models.PROTECT, related_name="invoices")
    institution_reference = models.TextField()  # invoice, student or patient reference
    description = models.TextField(blank=True, default="")
    amount = amount_field()
    currency = currency_field()
    due_on = models.DateField(null=True, blank=True)
    # What the document itself says, checked against the records (TC-FEE-002-03, TC-SEC-34).
    name_on_invoice = models.TextField(blank=True, default="")  # the pupil or patient
    institution_name_on_invoice = models.TextField(blank=True, default="")
    account_number_on_invoice = models.TextField(blank=True, default="")
    submitted_by = models.TextField(choices=[(s, s) for s in SUBMITTERS])
    submitted_by_person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="+")
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    evidence_sha256 = models.CharField(max_length=64, blank=True, default="")
    check_status = models.TextField(default="pending", choices=[(s, s) for s in CHECK_STATUSES])
    check_flags = models.JSONField(default=list, blank=True)  # [{"code", "message", "resolvable"}]
    contact_confirmed_by = models.ForeignKey(InstitutionContact, null=True, blank=True, on_delete=models.PROTECT,
                                             related_name="+")
    contact_confirmed_at = models.DateTimeField(null=True, blank=True)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    checked_at = models.DateTimeField(null=True, blank=True)
    check_note = models.TextField(blank=True, default="")
    route = models.TextField(choices=[(r, r) for r in ROUTES])
    route_overridden_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="+")
    client_approved_at = models.DateTimeField(null=True, blank=True)  # RUL-11; required before any payment
    client_approval_method = models.TextField(blank=True, default="")
    client_declined_at = models.DateTimeField(null=True, blank=True)
    service_order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")  # Tenmina's fee, through PAY
    status = models.TextField(default="submitted", choices=[(s, s) for s in STATUSES])
    status_reason = models.TextField(blank=True, default="")
    client_reminded_at = models.DateTimeField(null=True, blank=True)
    data_class = models.TextField(default="family_payment")

    class Meta:
        db_table = "fee_invoice"
        indexes = [models.Index(fields=["client", "family_member", "created_at"]),
                   models.Index(fields=["status", "due_on"])]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="fee_invoice_amount_positive"),
            models.CheckConstraint(condition=~Q(status__in=["client_approved", "instructed", "paid", "receipted"])
                                   | Q(client_approved_at__isnull=False), name="fee_invoice_approved_has_time"),
            models.CheckConstraint(condition=~Q(status__in=["checked", "client_approved", "instructed", "paid",
                                                            "receipted"]) | Q(check_status="checked"),
                                   name="fee_invoice_checked_before_pay"),
            models.CheckConstraint(condition=Q(status__in=["draft", "cancelled"]) | Q(evidence__isnull=False),
                                   name="fee_invoice_has_document"),
            models.CheckConstraint(condition=~Q(status="draft") | Q(submitted_by="schedule"),
                                   name="fee_invoice_draft_from_schedule"),
            models.UniqueConstraint(fields=["institution", "institution_reference"],
                                    condition=~Q(status__in=["rejected", "cancelled"]),
                                    name="fee_invoice_reference_uq"),
        ]


INVOICE = state.register("fee_invoice", "fee_invoice", {
    "draft": {"submitted", "cancelled"},
    "submitted": {"checked", "rejected", "cancelled"},
    "checked": {"client_approved", "submitted", "rejected", "cancelled"},
    "client_approved": {"instructed", "submitted", "cancelled", "paid"},
    "instructed": {"paid", "client_approved", "cancelled"},
    "paid": {"receipted"},
})


class Payment(CountryScopedModel):
    """FR-FEE-003, FR-FEE-004. One live payment per invoice. A held-funds
    payment names its escrow release instruction; a client-direct payment never
    does (Tenmina sends no instruction: the client pays the institution)."""

    STATUSES = ["awaiting_client_payment", "client_reported", "instructed", "paid", "receipted", "receipt_overdue",
                "withdrawn"]
    CONFIRMATION_METHODS = ["contact_portal", "contact_call", "bank_confirmation", "receipt"]
    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    route = models.TextField(choices=[(r, r) for r in ROUTES])
    amount = amount_field()
    currency = currency_field()
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    release_instruction = models.ForeignKey("escrow.ReleaseInstruction", null=True, blank=True,
                                            on_delete=models.PROTECT, related_name="+")
    # client_direct: what the client tells us about their own transfer
    client_paid_on = models.DateField(null=True, blank=True)
    client_transfer_reference = models.TextField(blank=True, default="")
    client_transfer_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    client_reported_at = models.DateTimeField(null=True, blank=True)
    # the institution confirms it received the money
    institution_confirmed_at = models.DateTimeField(null=True, blank=True)
    institution_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    institution_confirmed_contact = models.ForeignKey(InstitutionContact, null=True, blank=True,
                                                      on_delete=models.PROTECT, related_name="+")
    confirmation_method = models.TextField(blank=True, default="",
                                           choices=[("", "")] + [(m, m) for m in CONFIRMATION_METHODS])
    confirmation_note = models.TextField(blank=True, default="")
    bank_reference = models.TextField(blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)
    receipt_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    confirmation_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="+")  # enrolment, treatment, service
    receipt_received_at = models.DateTimeField(null=True, blank=True)
    receipt_due_at = models.DateTimeField(null=True, blank=True)  # paid_at + receipt_target_days
    receipt_chased_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(choices=[(s, s) for s in STATUSES])
    withdrawn_reason = models.TextField(blank=True, default="")
    data_class = models.TextField(default="family_payment")

    class Meta:
        db_table = "fee_payment"
        indexes = [models.Index(fields=["status", "receipt_due_at"])]
        constraints = [
            models.UniqueConstraint(fields=["invoice"], condition=~Q(status="withdrawn"), name="fee_payment_one_live"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="fee_payment_amount_positive"),
            models.CheckConstraint(condition=~Q(route="held_funds") | (Q(escrow__isnull=False)
                                                                       & Q(release_instruction__isnull=False)),
                                   name="fee_payment_held_funds_names_instruction"),
            models.CheckConstraint(condition=~Q(route="client_direct") | Q(release_instruction__isnull=True),
                                   name="fee_payment_client_direct_no_instruction"),
            models.CheckConstraint(condition=~Q(status__in=["paid", "receipted", "receipt_overdue"])
                                   | Q(paid_at__isnull=False, receipt_due_at__isnull=False),
                                   name="fee_payment_paid_has_time"),
            models.CheckConstraint(condition=~Q(status="receipted") | Q(receipt_evidence__isnull=False),
                                   name="fee_payment_receipted_has_receipt"),
        ]


PAYMENT = state.register("fee_payment", "fee_payment", {
    "awaiting_client_payment": {"client_reported", "paid", "withdrawn"},
    "client_reported": {"paid", "awaiting_client_payment", "withdrawn"},
    "instructed": {"paid", "withdrawn"},
    "paid": {"receipted", "receipt_overdue"},
    "receipt_overdue": {"receipted"},
})


class RunnerTask(CountryScopedModel):
    """FR-FEE-006: a runner collects an invoice or delivers a receipt in person.
    No amount column and no link to a release instruction: a runner task cannot
    carry or move money, and a runner is never a payee (RUL-22)."""

    KINDS = ["collect_invoice", "deliver_receipt"]
    STATUSES = ["open", "done", "cancelled"]
    institution = models.ForeignKey(Institution, on_delete=models.PROTECT, related_name="runner_tasks")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")
    invoice = models.ForeignKey(Invoice, null=True, blank=True, on_delete=models.PROTECT, related_name="runner_tasks")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    runner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    deliver_to_family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    instructions = models.TextField(blank=True, default="")
    due_at = models.DateTimeField()
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    note = models.TextField(blank=True, default="")
    done_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="open", choices=[(s, s) for s in STATUSES])
    cancel_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fee_runner_task"
        constraints = [
            models.CheckConstraint(condition=~Q(kind="deliver_receipt") | Q(invoice__isnull=False),
                                   name="fee_runner_deliver_has_invoice"),
            models.CheckConstraint(condition=~Q(status="done") | Q(evidence__isnull=False),
                                   name="fee_runner_done_has_evidence"),
            models.CheckConstraint(condition=~Q(kind="collect_invoice") | Q(family_member__isnull=False),
                                   name="fee_runner_collect_names_member"),
        ]


RUNNER_TASK = state.register("fee_runner_task", "fee_runner_task", {
    "open": {"done", "cancelled"},
})


class Statement(CountryScopedModel):
    """US-FEE-007 AC2: a downloaded statement PDF with its hash stored."""

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    sha256 = models.CharField(max_length=64)
    period_from = models.DateField(null=True, blank=True)
    period_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "fee_statement"
