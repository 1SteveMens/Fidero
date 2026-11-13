"""LST Verified listings (02 section 6.6, 01 C4.12, C8 Listing).

A listing is a plot, building, estate plot or off-plan unit a seller,
developer, family or stool offers through Tenmina. It is public only while a
released, green, in-date report backs it (RUL-12) and its badge has not
expired or been suspended (RUL-13). Buyers always see the full report (RUL-14).
"""
from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

LISTING_STATUSES = ["draft", "in_verification", "rejected", "live", "suspended", "expired", "reserved", "sold",
                    "withdrawn", "removed"]
ACTIVE_STATUSES = ["draft", "in_verification", "live", "suspended", "expired", "reserved"]
PUBLIC_STATUSES = ["live", "reserved"]


class Listing(CountryScopedModel):
    KINDS = ["plot", "building", "estate_plot", "offplan_unit"]
    ORIGINS = ["seller", "developer", "family", "stool"]

    reference = models.TextField(unique=True)
    slug = models.SlugField(max_length=120, blank=True, default="")
    asset = models.ForeignKey("geo.Asset", on_delete=models.PROTECT, related_name="+")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    origin = models.TextField(choices=[(o, o) for o in ORIGINS], default="seller")
    kind = models.TextField(choices=[(k, k) for k in KINDS], default="plot")
    title = models.TextField()
    description = models.TextField(blank=True, default="")
    estate_name = models.TextField(blank=True, default="")
    records_reference = models.TextField(blank=True, default="")  # REC record for family and stool listings
    price_amount = amount_field()
    price_currency = currency_field()
    size_sqm = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    region = models.TextField(blank=True, default="")
    district = models.TextField(blank=True, default="")
    locality = models.TextField(blank=True, default="")
    status = models.TextField(default="draft", choices=[(s, s) for s in LISTING_STATUSES])
    status_reason = models.TextField(blank=True, default="")
    report = models.ForeignKey("reports.Report", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    checks_date = models.DateField(null=True, blank=True)  # the date of the checks behind the badge (FR-LST-003)
    badge_expires_at = models.DateTimeField(null=True, blank=True)
    verification_order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="+")
    seller_paid_check = models.BooleanField(default=True)  # disclosed to buyers (client terms clause 1.3)
    fee_invoice_id = models.UUIDField(null=True, blank=True)  # pay_invoice for the listing fee
    fee_paid_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    live_at = models.DateTimeField(null=True, blank=True)
    sold_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    view_count = models.PositiveIntegerField(default=0)
    search_doc = SearchVectorField(null=True, blank=True)

    class Meta:
        db_table = "lst_listing"
        indexes = [GinIndex(fields=["search_doc"], name="lst_listing_search_gin"),
                   models.Index(fields=["country", "status", "price_amount"], name="lst_listing_search_idx"),
                   models.Index(fields=["organisation", "status"], name="lst_listing_org_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=LISTING_STATUSES), name="lst_listing_status_valid"),
            models.CheckConstraint(
                condition=~Q(status__in=PUBLIC_STATUSES) | (Q(report__isnull=False) & Q(badge_expires_at__isnull=False)),
                name="lst_live_has_report_and_badge"),
            models.CheckConstraint(condition=Q(price_amount__gt=0), name="lst_listing_price_positive"),
            models.UniqueConstraint(fields=["asset"], condition=Q(status__in=ACTIVE_STATUSES),
                                    name="lst_one_active_listing_per_asset"),
        ]

    def __str__(self):
        return self.reference


LISTING = state.register("listing", "lst_listing", {
    "draft": {"in_verification", "withdrawn", "removed"},
    "in_verification": {"live", "rejected", "withdrawn", "removed"},
    "live": {"reserved", "suspended", "expired", "withdrawn", "removed"},
    "reserved": {"sold", "live", "suspended", "expired", "removed"},
    "suspended": {"live", "reserved", "expired", "withdrawn", "removed"},
    "expired": {"in_verification", "sold", "withdrawn", "removed"},
    "rejected": {"removed"},
})


class ListingMedia(CountryScopedModel):
    """Photos and documents of a listing. Documents (site plan, indenture) are not public."""

    KINDS = ["photo", "site_plan", "document", "floor_plan", "video"]
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="media")
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    kind = models.TextField(choices=[(k, k) for k in KINDS], default="photo")
    caption = models.TextField(blank=True, default="")
    position = models.PositiveSmallIntegerField(default=0)
    public = models.BooleanField(default=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "lst_listing_media"
        ordering = ["listing", "position", "created_at"]
        constraints = [models.UniqueConstraint(fields=["listing", "evidence"], name="lst_media_once")]


class Enquiry(CountryScopedModel):
    """A buyer's question about a listing, or a 'looking for land' enquiry with no listing yet.
    Enquiries go through Tenmina: there is no direct chat between buyers and sellers (01 B9)."""

    STATUSES = ["open", "answered", "closed"]
    reference = models.TextField(unique=True)
    listing = models.ForeignKey(Listing, null=True, blank=True, on_delete=models.PROTECT, related_name="enquiries")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    message = models.TextField()
    wanted_region = models.TextField(blank=True, default="")
    wanted_locality = models.TextField(blank=True, default="")
    budget_amount = amount_field(null=True, blank=True)
    budget_currency = currency_field(blank=True, default="")
    status = models.TextField(default="open", choices=[(s, s) for s in STATUSES])
    answer = models.TextField(blank=True, default="")
    answered_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    answered_at = models.DateTimeField(null=True, blank=True)
    seller_note = models.TextField(blank=True, default="")  # the seller's answer, relayed by Tenmina
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "lst_enquiry"
        ordering = ["-created_at"]


ENQUIRY = state.register("listing_enquiry", "lst_enquiry", {
    "open": {"answered", "closed"},
    "answered": {"open", "closed"},
})


class Reservation(CountryScopedModel):
    """FR-LST-005: a buyer reserves a live listing; a fresh search runs and a purchase escrow is proposed."""

    STATUSES = ["active", "completed", "lapsed", "withdrawn", "ended"]
    FRESH = ["pending", "passed", "failed"]
    reference = models.TextField(unique=True)
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="reservations")
    buyer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    expires_at = models.DateTimeField()
    fresh_search_case_id = models.UUIDField(null=True, blank=True)
    fresh_search_status = models.TextField(default="pending", choices=[(s, s) for s in FRESH])
    fresh_search_date = models.DateField(null=True, blank=True)
    fresh_search_note = models.TextField(blank=True, default="")
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    ended_at = models.DateTimeField(null=True, blank=True)
    end_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "lst_reservation"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["listing"], condition=Q(status="active"),
                                    name="lst_one_active_reservation"),  # TC-STM-LST-19
            models.CheckConstraint(condition=Q(status="active") | Q(ended_at__isnull=False),
                                   name="lst_reservation_ended_at"),
        ]


RESERVATION = state.register("listing_reservation", "lst_reservation", {
    "active": {"completed", "lapsed", "withdrawn", "ended"},
})


class Suspension(CountryScopedModel):
    """Why a listing is suspended (RUL-13, RUL-15, FR-LST-008). The listing goes back live only
    when every suspension is lifted, by its source closing or by a reviewer."""

    KINDS = ["monitoring_alert", "dispute", "fresh_search_failed", "misconduct", "report_corrected"]
    listing = models.ForeignKey(Listing, on_delete=models.PROTECT, related_name="suspensions")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    source_id = models.UUIDField(null=True, blank=True)
    reason = models.TextField()
    prior_status = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="+")
    lift_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "lst_suspension"
        constraints = [models.UniqueConstraint(fields=["listing", "kind", "source_id"],
                                               condition=Q(lifted_at__isnull=True), name="lst_suspension_open_once")]


class Removal(CountryScopedModel):
    """FR-LST-008: a reviewer removes a listing, or a seller and all their listings, for misconduct.
    Append-only (dbsql)."""

    SCOPES = ["listing", "seller"]
    scope = models.TextField(choices=[(s, s) for s in SCOPES])
    listing = models.ForeignKey(Listing, null=True, blank=True, on_delete=models.PROTECT, related_name="removals")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    reason = models.TextField()
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    listings_removed = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "lst_removal"
        constraints = [models.CheckConstraint(condition=~Q(reason=""), name="lst_removal_reason")]


class SellerScreening(CountryScopedModel):
    """The 'established seller' screening of docs/decisions/2026-11-12-checked-plots-and-established-sellers.md.
    Being established earns no shortcut on checks; it is shown to buyers as a fact, never instead of a report."""

    CHECKS = ["registered_company", "agency_licence", "estate_title", "court_search", "no_overlap",
              "buyer_references", "seller_agreement"]
    STATUSES = ["in_progress", "established", "not_established"]
    organisation = models.ForeignKey("accounts.Organisation", on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="in_progress", choices=[(s, s) for s in STATUSES])
    checks = models.JSONField(default=dict)  # key -> {status, note, evidence_id, checked_by, checked_at}
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "lst_seller_screening"
        constraints = [models.UniqueConstraint(fields=["organisation"], condition=Q(status="in_progress"),
                                               name="lst_one_open_screening")]


SCREENING = state.register("seller_screening", "lst_seller_screening", {
    "in_progress": {"established", "not_established"},
    "established": {"in_progress"},
    "not_established": {"in_progress"},
})
