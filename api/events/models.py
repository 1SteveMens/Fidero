"""EVT Events and ceremonies (document 02: 4.2, 6.13; FR-EVT-001 to FR-EVT-003, BR-22, RUL-22).

Funerals, weddings, naming ceremonies and anniversaries funded through an
event escrow at the partner bank. Vendors are verified (registration and an
account in their own name, two staff) and paid only to their verified payee:
deposits against a signed quote, balances against an invoice, delivery
evidence and a family confirmation (ADR-20). Never cash to a relative.
"""
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from core import state
from core.models import CountryScopedModel
from core.money import amount_field, currency_field

EVENT_KINDS = ["funeral", "wedding", "naming", "anniversary", "other"]
EVENT_STATUSES = ["planning", "funded", "in_progress", "closed", "cancelled"]
VENDOR_KINDS = ["caterer", "tent_and_chairs", "funeral_home", "printer", "decorator", "sound", "transport", "venue",
                "other"]
VENDOR_STATUSES = ["unverified", "verifying", "verified", "rejected", "removed"]
PAYMENT_KINDS = ["deposit", "balance", "full"]
PAYMENT_STATUSES = ["proposed", "evidenced", "client_approved", "instructed", "paid", "rejected"]
COMMITTED = ["proposed", "evidenced", "client_approved", "instructed", "paid"]


class Event(CountryScopedModel):
    """FR-EVT-001, FR-EVT-003."""

    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    kind = models.TextField(choices=[(k, k) for k in EVENT_KINDS])
    name = models.TextField()
    event_date = models.DateField()
    locality = models.TextField(blank=True, default="")
    budget_amount = amount_field()
    budget_currency = currency_field()
    budget_history = models.JSONField(default=list, blank=True)  # [{"from", "to", "at", "by", "reason"}]
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    confirmer_family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True,
                                                on_delete=models.PROTECT, related_name="+")  # ADR-20
    case_manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    fee_order_id = models.UUIDField(null=True, blank=True)
    status = models.TextField(default="planning", choices=[(s, s) for s in EVENT_STATUSES])
    closed_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "evt_event"
        indexes = [models.Index(fields=["client", "status"]), models.Index(fields=["country", "status"])]
        constraints = [
            models.CheckConstraint(condition=Q(budget_amount__gt=0), name="evt_budget_positive"),
            models.CheckConstraint(condition=~Q(status="cancelled") | ~Q(cancel_reason=""),
                                   name="evt_cancel_reason"),
        ]

    def __str__(self):
        return self.name


EVENT = state.register("evt_event", "evt_event", {
    "planning": {"funded", "cancelled"},
    "funded": {"in_progress", "closed", "cancelled"},
    "in_progress": {"closed"},
})


class Vendor(CountryScopedModel):
    """FR-EVT-001: a caterer, tent hire, funeral home or printer, with its
    verification case and verified payee. Unverified until two staff check
    the registration and the account name (US-EVT-001 AC1)."""

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="vendors")
    kind = models.TextField(choices=[(k, k) for k in VENDOR_KINDS])
    name = models.TextField()
    is_organisation = models.BooleanField(default=True)
    registration_number = models.TextField(blank=True, default="")
    registration_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                              related_name="+")
    contact_name = models.TextField(blank=True, default="")
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    quote_amount = amount_field(null=True, blank=True)  # from the signed quote
    quote_currency = currency_field(blank=True, default="")
    quote_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    verification_case = models.ForeignKey("cases.Case", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    status = models.TextField(default="unverified", choices=[(s, s) for s in VENDOR_STATUSES])
    verified_at = models.DateTimeField(null=True, blank=True)
    removed_reason = models.TextField(blank=True, default="")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "evt_vendor"
        constraints = [
            models.CheckConstraint(condition=~Q(status="verified") | (
                Q(payee__isnull=False) & Q(verified_at__isnull=False)), name="evt_vendor_verified_has_payee"),
            models.CheckConstraint(condition=Q(quote_amount__isnull=True) | Q(quote_amount__gt=0),
                                   name="evt_vendor_quote_positive"),
        ]

    def __str__(self):
        return self.name


VENDOR = state.register("evt_vendor", "evt_vendor", {
    "unverified": {"verifying", "verified", "rejected", "removed"},
    "verifying": {"verified", "rejected", "removed", "unverified"},
    "verified": {"removed", "unverified"},
    "rejected": {"verifying", "removed"},
})


class VendorPayment(CountryScopedModel):
    """FR-EVT-002: a deposit against a signed quote, or a balance or full
    payment against an invoice, delivery evidence and a family confirmation."""

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="payments")
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="payments")
    kind = models.TextField(choices=[(k, k) for k in PAYMENT_KINDS])
    amount = amount_field()
    currency = currency_field()
    description = models.TextField(blank=True, default="")
    quote_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")  # signed quote, required for a deposit
    invoice_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    delivery_evidence_ids = ArrayField(models.UUIDField(), default=list, blank=True)  # photos, delivery notes
    family_confirmation = models.ForeignKey("notifications.ConfirmationCode", null=True, blank=True,
                                            on_delete=models.PROTECT, related_name="+")  # ADR-20
    family_confirmed_at = models.DateTimeField(null=True, blank=True)
    evidenced_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)
    budget_warning_acknowledged = models.BooleanField(default=False)
    release_instruction = models.ForeignKey("escrow.ReleaseInstruction", null=True, blank=True,
                                            on_delete=models.PROTECT, related_name="+")  # payee = vendor
    paid_at = models.DateTimeField(null=True, blank=True)
    bank_reference = models.TextField(blank=True, default="")
    status = models.TextField(default="proposed", choices=[(s, s) for s in PAYMENT_STATUSES])
    reject_reason = models.TextField(blank=True, default="")
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "evt_vendor_payment"
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="evt_payment_positive"),
            models.CheckConstraint(condition=~Q(kind="deposit") | Q(quote_evidence__isnull=False),
                                   name="evt_deposit_needs_signed_quote"),
            models.CheckConstraint(condition=Q(kind="deposit") | ~Q(status__in=["evidenced", "client_approved",
                                                                              "instructed", "paid"])
                                   | (Q(invoice_evidence__isnull=False) & Q(delivery_evidence_ids__len__gte=1)
                                      & Q(family_confirmed_at__isnull=False)),
                                   name="evt_payment_needs_delivery_evidence"),
            models.CheckConstraint(condition=~Q(status__in=["client_approved", "instructed", "paid"])
                                   | Q(client_approved_at__isnull=False), name="evt_payment_client_approved"),
            models.CheckConstraint(condition=~Q(status="rejected") | ~Q(reject_reason=""),
                                   name="evt_payment_reject_reason"),
        ]


VENDOR_PAYMENT = state.register("vendor_payment", "evt_vendor_payment", {
    "proposed": {"evidenced", "rejected"},
    "evidenced": {"client_approved", "rejected", "proposed"},
    "client_approved": {"instructed", "rejected"},
    "instructed": {"paid", "client_approved"},
})
