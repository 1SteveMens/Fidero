"""ORD Orders (FR-ORD-001 to FR-ORD-007; 02 sections 4.2, 5.1, 6.4, 6.8).

An order is what a client buys from Tenmina's fee side. No case, inspection
or line object exists until the order is paid (FR-ORD-004): the owning
module creates it on `order.paid`.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import CountryScopedModel
from core.money import amount_field, currency_field

from .catalogue import KINDS, LEAD_SOURCES

STATUSES = ["draft", "awaiting_payment", "paid", "cancelled", "refunded"]
ASSET_TYPES = ["plot", "building", "offplan_unit"]


class Order(CountryScopedModel):
    reference = models.TextField(unique=True)
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    placed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    bill_to = models.TextField(default="client", choices=[("client", "client"), ("organisation", "organisation")])
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    product_code = models.TextField(blank=True, default="")
    # The asset (FR-ORD-001). GEO owns geo_asset and fills asset_id on order.paid.
    asset_type = models.TextField(blank=True, default="", choices=[(a, a) for a in ASSET_TYPES])
    asset_id = models.UUIDField(null=True, blank=True)
    locality = models.TextField(blank=True, default="")
    plot_number = models.TextField(blank=True, default="")
    site_plan_ref = models.TextField(blank=True, default="")
    ghana_post_gps = models.TextField(blank=True, default="")  # optional (US-ORD-001 AC1)
    seller_name = models.TextField(blank=True, default="")
    seller_phone = models.CharField(max_length=32, blank=True, default="")
    seller_email = models.EmailField(blank=True, default="")
    # What the order is about when another module owns it (project, institution, care plan, ...).
    subject_type = models.TextField(blank=True, default="")
    subject_id = models.UUIDField(null=True, blank=True)
    parent_order = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    details = models.JSONField(default=dict, blank=True)  # kind-specific fields (building permit no., month, ...)
    notes = models.TextField(blank=True, default="")
    # Quote, fixed when the order leaves draft (FR-ORD-002; amount charged equals amount shown).
    tier = models.TextField(blank=True, default="")
    tier_name = models.TextField(blank=True, default="")
    list_price_amount = amount_field(null=True, blank=True)
    list_price_currency = currency_field(blank=True, default="")
    discount_amount = amount_field(default=0)
    price_amount = amount_field(null=True, blank=True)      # card, in the price currency (USD)
    price_currency = currency_field(blank=True, default="")
    local_price_amount = amount_field(null=True, blank=True)  # mobile money, in the country currency (GHS)
    local_price_currency = currency_field(blank=True, default="")
    guides = models.JSONField(default=dict, blank=True)     # GBP, EUR, CAD as guides only
    price_source = models.TextField(blank=True, default="")
    config_version = models.PositiveIntegerField(null=True, blank=True)
    quoted_at = models.DateTimeField(null=True, blank=True)
    turnaround_days = models.PositiveSmallIntegerField(null=True, blank=True)
    # Lead source and referral (FR-ORD-005, FR-ORD-006)
    lead_source = models.TextField(blank=True, default="")
    lead_source_detail = models.TextField(blank=True, default="")
    referral_code = models.ForeignKey("orders.ReferralCode", null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="orders")
    # Terms acceptance, the latest one (FR-ORD-003; history in ord_terms_acceptance)
    terms_version = models.TextField(blank=True, default="")
    scope_version = models.TextField(blank=True, default="")
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    submitted_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_payment_id = models.UUIDField(null=True, blank=True)   # pay_fee_payment
    paid_method = models.TextField(blank=True, default="")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")
    refunded_at = models.DateTimeField(null=True, blank=True)
    case_id = models.UUIDField(null=True, blank=True)            # case_case, set by CASE on case.created
    last_payment_status = models.TextField(blank=True, default="")
    last_payment_message = models.TextField(blank=True, default="")

    class Meta:
        db_table = "ord_order"
        indexes = [models.Index(fields=["client", "-created_at"]), models.Index(fields=["country", "status"])]
        constraints = [
            models.CheckConstraint(condition=Q(price_amount__isnull=True) | Q(price_amount__gte=0),
                                   name="ord_order_price_not_negative"),
            models.CheckConstraint(condition=Q(status__in=STATUSES), name="ord_order_status_valid"),
            models.CheckConstraint(condition=Q(lead_source="") | Q(lead_source__in=LEAD_SOURCES),
                                   name="ord_order_lead_source_valid"),
            # Nothing leaves draft without a price and a recorded terms acceptance (FR-ORD-002, FR-ORD-003).
            models.CheckConstraint(
                condition=Q(status="draft") | (Q(price_amount__isnull=False) & Q(terms_accepted_at__isnull=False)),
                name="ord_order_priced_and_accepted"),
            models.CheckConstraint(condition=Q(bill_to="client") | Q(organisation__isnull=False),
                                   name="ord_order_org_bill_has_org"),
        ]

    def __str__(self):
        return self.reference


ORDER = state.register("order", "ord_order", {
    "draft": {"awaiting_payment", "cancelled"},
    "awaiting_payment": {"paid", "cancelled", "draft"},
    "paid": {"refunded"},
})


class TermsAcceptance(CountryScopedModel):
    """Every acceptance of the scope statement and terms (FR-ORD-003). Append-only."""

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="acceptances")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    terms_version = models.TextField()
    scope_version = models.TextField()
    accepted_at = models.DateTimeField()
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")

    class Meta:
        db_table = "ord_terms_acceptance"


class ReferralCode(CountryScopedModel):
    """A code a client, association or partner shares (FR-ORD-006)."""

    code = models.CharField(max_length=32, unique=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="referral_codes")
    owner_label = models.TextField(blank=True, default="")  # e.g. an association's name
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    reward_amount = amount_field(default=0)
    reward_currency = currency_field(default="USD")
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "ord_referral_code"
        constraints = [
            models.CheckConstraint(condition=Q(discount_pct__gte=0) & Q(discount_pct__lte=50),
                                   name="ord_referral_discount_range"),
            models.CheckConstraint(condition=Q(reward_amount__gte=0), name="ord_referral_reward_not_negative"),
        ]


class ReferralReward(CountryScopedModel):
    """The reward owed to a referrer when a referred client pays (FR-ORD-006).

    Rewards are paid from Tenmina's own operating account, never from client money."""

    STATUSES = ["owed", "paid", "void"]
    referral_code = models.ForeignKey(ReferralCode, on_delete=models.PROTECT, related_name="rewards")
    referrer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    referred_client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    order = models.OneToOneField(Order, on_delete=models.PROTECT, related_name="referral_reward")
    amount = amount_field()
    currency = currency_field()
    status = models.TextField(default="owed", choices=[(s, s) for s in STATUSES])
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_reference = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    void_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "ord_referral_reward"
        constraints = [models.CheckConstraint(condition=Q(amount__gte=0), name="ord_reward_not_negative")]


REFERRAL_REWARD = state.register("referral_reward", "ord_referral_reward", {
    "owed": {"paid", "void"},
})


class ReferenceCounter(models.Model):
    """Gap-free order references per country and year: TMR-GH-2026-00042."""

    country_code = models.CharField(max_length=2)
    year = models.PositiveIntegerField()
    last = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "ord_reference_counter"
        constraints = [models.UniqueConstraint(fields=["country_code", "year"], name="ord_ref_counter_uq")]
