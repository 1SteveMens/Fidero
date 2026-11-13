"""PAY Tenmina fee payments (FR-PAY-001 to FR-PAY-008; ADR-03, ADR-24; 02 sections 6.4, 6.8).

Only Tenmina's own fees. There is no balance, wallet or ledger, and no purpose
for purchase, construction, project or premium money (RUL-01, RUL-25). Every
payment links to a fee order or a seller invoice. A refund has no destination
column: it goes back through the provider to the original payment method, or
for an offline payment to the account it came from (RUL-29, FR-PAY-008).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

PURPOSES = ["report_fee", "escrow_fee", "inspection_fee", "listing_fee", "success_fee", "construction_mgmt_fee",
            "api_fee", "conveyancing_fee", "institution_service_fee", "care_service_fee", "property_mgmt_fee",
            "errand_fee", "event_service_fee"]
METHODS = ["card", "mobile_money", "bank_transfer_offline"]
PAYMENT_STATUSES = ["initiated", "pending_approval", "confirmed", "failed", "refunded", "partially_refunded"]


class FeePayment(CountryScopedModel):
    purpose = models.TextField(choices=[(p, p) for p in PURPOSES])
    payer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="fee_payments")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT,
                              related_name="payments")
    invoice = models.ForeignKey("payments.Invoice", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="payments")
    amount = amount_field()
    currency = currency_field()
    method = models.TextField(choices=[(m, m) for m in METHODS])
    provider = models.TextField()                       # adapter name, or "offline"
    provider_ref = models.TextField(null=True, blank=True, unique=True)
    checkout_url = models.TextField(blank=True, default="")
    return_url = models.TextField(blank=True, default="")
    card_brand = models.TextField(blank=True, default="")
    card_last4 = models.CharField(max_length=4, blank=True, default="")      # never the full number (FR-PAY-002)
    wallet_last4 = models.CharField(max_length=4, blank=True, default="")    # mobile money number, last 4 only
    wallet_network = models.TextField(blank=True, default="")
    status = models.TextField(default="initiated", choices=[(s, s) for s in PAYMENT_STATUSES])
    failure_code = models.TextField(blank=True, default="")
    failure_message = models.TextField(blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    refunded_amount = amount_field(default=0)         # sum of completed refunds, a recorded fact
    last_checked_at = models.DateTimeField(null=True, blank=True)
    # Offline payment (FR-ORD-004): proof, who recorded it, and the account it came from (refund to source, I-40)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    proof_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    offline_reference = models.TextField(blank=True, default="")   # the bank's or wallet's transaction reference
    received_on = models.DateField(null=True, blank=True)
    source_bank_name = models.TextField(blank=True, default="")
    source_account_name = models.TextField(blank=True, default="")
    source_account_number = models.TextField(blank=True, default="")  # encrypt at field level in production
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")

    class Meta:
        db_table = "pay_fee_payment"
        indexes = [models.Index(fields=["order", "status"]), models.Index(fields=["status", "created_at"])]
        constraints = [
            models.CheckConstraint(condition=Q(purpose__in=PURPOSES), name="pay_purpose_fee_only"),
            models.CheckConstraint(condition=Q(method__in=METHODS), name="pay_method_valid"),
            models.CheckConstraint(condition=Q(status__in=PAYMENT_STATUSES), name="pay_status_valid"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="pay_amount_positive"),
            models.CheckConstraint(condition=Q(order__isnull=False) | Q(invoice__isnull=False),
                                   name="pay_linked_to_fee_order_or_invoice"),
            models.CheckConstraint(condition=Q(card_last4="") | Q(card_last4__regex=r"^[0-9]{4}$"),
                                   name="pay_card_last4_only"),
            models.CheckConstraint(
                condition=~Q(method="bank_transfer_offline") | (
                    Q(proof_evidence__isnull=False) & Q(recorded_by__isnull=False) & ~Q(source_account_name="")),
                name="pay_offline_needs_proof_and_source"),
            models.CheckConstraint(condition=Q(refunded_amount__gte=0) & Q(refunded_amount__lte=models.F("amount")),
                                   name="pay_refunded_not_above_amount"),
        ]


PAYMENT = state.register("pay_payment", "pay_fee_payment", {
    "initiated": {"confirmed", "failed"},
    "pending_approval": {"confirmed", "failed"},
    # A late confirmation from the provider after a timeout wins: the provider is authoritative (7.3).
    "failed": {"confirmed"},
    "confirmed": {"partially_refunded", "refunded"},
    "partially_refunded": {"refunded"},
})


class Receipt(CountryScopedModel):
    """A numbered receipt per confirmed payment, and a credit note per refund (FR-PAY-003). Append-only."""

    KINDS = ["receipt", "credit_note"]
    number = models.TextField(unique=True)
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    payment = models.ForeignKey(FeePayment, on_delete=models.PROTECT, related_name="receipts")
    refund = models.OneToOneField("payments.Refund", null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="credit_note")
    issued_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    issued_to_name = models.TextField()
    amount = amount_field()
    currency = currency_field()
    description = models.TextField()
    order_reference = models.TextField(blank=True, default="")
    invoice_number = models.TextField(blank=True, default="")
    method = models.TextField()
    method_detail = models.TextField(blank=True, default="")   # "Visa ending 4242", "MTN MoMo ending 1234"
    issued_at = models.DateTimeField()
    sha256 = models.CharField(max_length=64)                    # canonical content hash (tamper-evident)

    class Meta:
        db_table = "pay_receipt"
        constraints = [
            models.UniqueConstraint(fields=["payment"], condition=Q(kind="receipt"), name="pay_one_receipt_per_payment"),
            models.CheckConstraint(condition=Q(kind="receipt", refund__isnull=True) |
                                   Q(kind="credit_note", refund__isnull=False), name="pay_credit_note_has_refund"),
        ]


class Refund(CountryScopedModel):
    """FR-PAY-004, FR-PAY-008, RUL-29. No destination column: the money goes back the way it came."""

    STATUSES = ["requested", "approved", "processing", "completed", "failed", "rejected", "withdrawn"]
    payment = models.ForeignKey(FeePayment, on_delete=models.PROTECT, related_name="refunds")
    amount = amount_field()
    currency = currency_field()
    reason = models.TextField()
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    status = models.TextField(default="requested", choices=[(s, s) for s in STATUSES])
    provider_refund_ref = models.TextField(blank=True, default="")
    attempts = models.PositiveSmallIntegerField(default=0)
    failure_message = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # Offline payments are paid back by staff to the source account, with the bank's proof.
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    proof_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")

    class Meta:
        db_table = "pay_refund"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="pay_refund_amount_positive"),
            models.CheckConstraint(condition=Q(reason__regex=r"\S"), name="pay_refund_reason_required"),
            models.CheckConstraint(condition=~Q(status="completed") | ~Q(provider_refund_ref=""),
                                   name="pay_refund_completed_has_reference"),
        ]


REFUND = state.register("pay_refund", "pay_refund", {
    "requested": {"approved", "rejected", "withdrawn"},
    "approved": {"processing", "completed", "failed"},
    "processing": {"completed", "failed"},
    "failed": {"processing", "completed"},   # retried through the provider only (FR-PAY-008, I-41)
})


class Invoice(CountryScopedModel):
    """A Tenmina invoice to a seller or developer organisation (FR-PAY-007, checked plots)."""

    KINDS = ["checked_plot_fee", "listing_fee", "success_fee", "api_fee", "other_fee"]
    STATUSES = ["draft", "issued", "paid", "void"]
    number = models.TextField(unique=True)
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    purpose = models.TextField(choices=[(p, p) for p in PURPOSES])
    organisation = models.ForeignKey("accounts.Organisation", on_delete=models.PROTECT, related_name="+")
    bill_to_person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    subject_type = models.TextField(blank=True, default="")    # e.g. listing
    subject_id = models.UUIDField(null=True, blank=True)
    description = models.TextField()
    amount = amount_field()
    currency = currency_field()
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    issued_at = models.DateTimeField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "pay_invoice"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="pay_invoice_amount_positive"),
            models.CheckConstraint(condition=Q(purpose__in=PURPOSES), name="pay_invoice_fee_only"),
            models.UniqueConstraint(fields=["kind", "subject_type", "subject_id"],
                                    condition=Q(subject_id__isnull=False) & ~Q(status="void"),
                                    name="pay_invoice_one_per_subject"),
            models.UniqueConstraint(fields=["order"], condition=Q(order__isnull=False) & ~Q(status="void"),
                                    name="pay_invoice_one_per_order"),
        ]


INVOICE = state.register("pay_invoice", "pay_invoice", {
    "draft": {"issued", "void"},
    "issued": {"paid", "void"},
})


class SettlementRun(CountryScopedModel):
    """One import of a provider's settlement report (FR-PAY-006)."""

    provider = models.TextField()
    settlement_date = models.DateField()
    source = models.TextField(default="provider")     # provider (fetched through the adapter) or upload
    file_sha256 = models.CharField(max_length=64)
    line_count = models.PositiveIntegerField(default=0)
    matched = models.PositiveIntegerField(default=0)
    issues = models.PositiveIntegerField(default=0)
    run_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")

    class Meta:
        db_table = "pay_settlement_run"
        constraints = [models.UniqueConstraint(fields=["provider", "file_sha256"], name="pay_settlement_file_once")]


class SettlementLine(CountryScopedModel):
    MATCH = ["matched", "unmatched", "amount_mismatch", "duplicate"]
    run = models.ForeignKey(SettlementRun, on_delete=models.PROTECT, related_name="lines")
    provider_ref = models.TextField()
    amount = amount_field()
    currency = currency_field()
    fee_amount = amount_field(default=0)
    net_amount = amount_field(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)
    payment = models.ForeignKey(FeePayment, null=True, blank=True, on_delete=models.PROTECT,
                                related_name="settlement_lines")
    match_status = models.TextField(choices=[(m, m) for m in MATCH])

    class Meta:
        db_table = "pay_settlement_line"
        indexes = [models.Index(fields=["provider_ref"])]


class ReconIssue(CountryScopedModel):
    """A mismatch or exception for a case manager (FR-PAY-006, FR-PAY-008, TC-RUL-01-04)."""

    KINDS = ["unmatched_line", "missing_settlement", "amount_mismatch", "duplicate_line", "unlinked_payment",
             "duplicate_payment", "payment_on_closed_order", "refund_failed", "stale_payment"]
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    payment = models.ForeignKey(FeePayment, null=True, blank=True, on_delete=models.PROTECT, related_name="issues")
    refund = models.ForeignKey(Refund, null=True, blank=True, on_delete=models.PROTECT, related_name="issues")
    line = models.ForeignKey(SettlementLine, null=True, blank=True, on_delete=models.PROTECT, related_name="issues")
    run = models.ForeignKey(SettlementRun, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    provider_ref = models.TextField(blank=True, default="")
    detail = models.TextField()
    status = models.TextField(default="open", choices=[("open", "open"), ("resolved", "resolved")])
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pay_recon_issue"
        indexes = [models.Index(fields=["status", "kind"])]


RECON_ISSUE = state.register("pay_recon_issue", "pay_recon_issue", {"open": {"resolved"}})


class WebhookEvent(BaseModel):
    """Inbound provider webhooks (7.3): signature checked, body hash kept, deduplicated on the vendor's event ID.
    The raw body is not stored, so no card data can land here."""

    provider = models.TextField()
    vendor_event_id = models.TextField()
    event_type = models.TextField(blank=True, default="")
    provider_ref = models.TextField(blank=True, default="")
    body_sha256 = models.CharField(max_length=64)
    signature_ok = models.BooleanField()
    processed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.TextField(blank=True, default="")

    class Meta:
        db_table = "pay_webhook_event"
        constraints = [models.UniqueConstraint(fields=["provider", "vendor_event_id"], name="pay_webhook_once")]


class NumberCounter(models.Model):
    """Gap-free receipt, credit note and invoice numbers per country and year."""

    series = models.CharField(max_length=8)   # RCT, CRN, INV
    country_code = models.CharField(max_length=2)
    year = models.PositiveIntegerField()
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "pay_number_counter"
        constraints = [models.UniqueConstraint(fields=["series", "country_code", "year"], name="pay_counter_uq")]


class FakeProviderTransaction(BaseModel):
    """The fake payment provider's own side (ADR-10), so the hosted checkout, webhooks, verification,
    refunds and settlement all work offline. Not used by a real adapter."""

    reference = models.TextField(unique=True)
    amount = amount_field()
    currency = currency_field()
    method = models.TextField()
    status = models.TextField(default="pending")   # pending | success | failed
    failure_code = models.TextField(blank=True, default="")
    card_brand = models.TextField(blank=True, default="")
    card_last4 = models.CharField(max_length=4, blank=True, default="")
    wallet_last4 = models.CharField(max_length=4, blank=True, default="")
    refundable = models.BooleanField(default=True)  # False simulates a closed card or wallet (TC-PAY-008-03)
    refunded = amount_field(default=0)
    paid_at = models.DateTimeField(null=True, blank=True)
    session_token = models.TextField()

    class Meta:
        db_table = "pay_fake_provider_txn"
