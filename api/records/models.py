"""REC Records programme (document 02: 4.2, 6.8; FR-REC-001 to FR-REC-004; BR-13).

A traditional authority's allocation records (stools, skins, family heads)
captured as plots with boundaries, allottees, dates and scanned documents;
matched to verification cases by boundary so the chain of ownership can be
pre-filled for the lawyer to confirm; the revenue share owed to each authority
from cases that used its records; and confirmation by the authority's own
representative (role AR)."""
from django.conf import settings
from django.contrib.gis.db import models as gis
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field


class Authority(CountryScopedModel):
    KINDS = ["stool", "skin", "family", "clan", "tendamba", "other"]
    STATUSES = ["active", "suspended"]

    name = models.TextField()
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    region = models.TextField(blank=True, default="")
    district = models.TextField(blank=True, default="")
    agreement_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="+")  # the records programme agreement with the authority
    share_per_case = amount_field(default=0)  # revenue share per case that used the records [TO VERIFY]
    share_currency = currency_field()
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "rec_authority"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["country", "name"], name="rec_authority_name_uq"),
                       models.CheckConstraint(condition=Q(share_per_case__gte=0), name="rec_share_not_negative")]

    def __str__(self):
        return self.name


class Representative(CountryScopedModel):
    """An authorised representative (AR) of one authority, e.g. the stool secretary (FR-REC-004)."""

    authority = models.ForeignKey(Authority, on_delete=models.PROTECT, related_name="representatives")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="rec_representations")
    title = models.TextField(blank=True, default="")
    authorisation_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                               on_delete=models.PROTECT, related_name="+")
    active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rec_representative"
        constraints = [models.UniqueConstraint(fields=["authority", "person"], condition=Q(active=True),
                                               name="rec_one_active_representation")]


class Allottee(CountryScopedModel):
    KINDS = ["person", "family", "company", "other"]

    authority = models.ForeignKey(Authority, on_delete=models.PROTECT, related_name="allottees")
    name = models.TextField()
    kind = models.TextField(default="person", choices=[(k, k) for k in KINDS])
    phone = models.CharField(max_length=32, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "rec_allottee"


class Allocation(CountryScopedModel):
    """One allocation from the authority's register (FR-REC-001)."""

    STATUSES = ["captured", "flagged", "confirmed", "disputed", "revoked"]

    authority = models.ForeignKey(Authority, on_delete=models.PROTECT, related_name="allocations")
    reference = models.TextField()  # the register's own number, e.g. "Oyarifa stool book 3, p. 41"
    allottee = models.ForeignKey(Allottee, on_delete=models.PROTECT, related_name="allocations")
    allocated_on = models.DateField()
    previous = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="later")  # an earlier allocation of the same land (the chain)
    geom = gis.MultiPolygonField(srid=4326)
    area_sqm = models.DecimalField(max_digits=14, decimal_places=2)
    locality = models.TextField(blank=True, default="")
    plot_number = models.TextField(blank=True, default="")
    document_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="captured", choices=[(s, s) for s in STATUSES])
    status_note = models.TextField(blank=True, default="")
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    confirmed_name = models.TextField(blank=True, default="")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rec_allocation"
        ordering = ["authority", "allocated_on"]
        constraints = [
            models.UniqueConstraint(fields=["authority", "reference"], name="rec_allocation_ref_uq"),
            models.CheckConstraint(condition=~Q(status="confirmed") | (Q(confirmed_by__isnull=False)
                                                                       & Q(confirmed_at__isnull=False)),
                                   name="rec_confirmed_has_name_and_time"),
        ]


ALLOCATION = state.register("rec_allocation", "rec_allocation", {
    "captured": {"confirmed", "flagged", "disputed", "revoked"},
    "flagged": {"captured", "revoked"},
    "confirmed": {"disputed", "revoked"},
    "disputed": {"captured", "revoked"},
})


class AllocationOverlap(BaseModel):
    """Two allocations on the register that overlap (US-REC-001 AC2): flagged for review."""

    allocation = models.ForeignKey(Allocation, on_delete=models.PROTECT, related_name="overlaps")
    other = models.ForeignKey(Allocation, on_delete=models.PROTECT, related_name="+")
    share = models.DecimalField(max_digits=7, decimal_places=4)  # of `allocation`
    status = models.TextField(default="open", choices=[("open", "open"), ("resolved", "resolved")])
    resolution_note = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")

    class Meta:
        db_table = "rec_allocation_overlap"
        constraints = [models.UniqueConstraint(fields=["allocation", "other"], name="rec_overlap_pair_uq")]


class Match(CountryScopedModel):
    """A verification case's plot against a record (FR-REC-002). An exact match pre-fills the chain of ownership
    for the lawyer to confirm; a near match is flagged for review with nothing pre-filled."""

    KINDS = ["exact", "near"]
    STATUSES = ["proposed", "review", "confirmed", "rejected"]

    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="+")
    asset = models.ForeignKey("geo.Asset", on_delete=models.PROTECT, related_name="+")
    boundary = models.ForeignKey("geo.BoundaryVersion", on_delete=models.PROTECT, related_name="+")
    allocation = models.ForeignKey(Allocation, on_delete=models.PROTECT, related_name="matches")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    share_of_plot = models.DecimalField(max_digits=7, decimal_places=4)
    share_of_record = models.DecimalField(max_digits=7, decimal_places=4)
    prefill = models.JSONField(default=list, blank=True)  # chain of ownership entries, exact matches only
    status = models.TextField(default="proposed", choices=[(s, s) for s in STATUSES])
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    applied_to_report_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "rec_match"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["case", "boundary", "allocation"], name="rec_match_once"),
            models.CheckConstraint(condition=Q(kind="exact") | Q(prefill=[]), name="rec_near_match_no_prefill"),
        ]


MATCH = state.register("rec_match", "rec_match", {
    "proposed": {"confirmed", "rejected"},
    "review": {"confirmed", "rejected"},
})


class RevenueShare(CountryScopedModel):
    """FR-REC-003: what is owed to one authority for a period, from cases that used its records."""

    STATUSES = ["computed", "approved", "paid"]

    authority = models.ForeignKey(Authority, on_delete=models.PROTECT, related_name="revenue_shares")
    period_start = models.DateField()
    period_end = models.DateField()
    case_count = models.PositiveIntegerField()
    amount = amount_field()
    currency = currency_field()
    status = models.TextField(default="computed", choices=[(s, s) for s in STATUSES])
    computed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    paid_reference = models.TextField(blank=True, default="")

    class Meta:
        db_table = "rec_revenue_share"
        ordering = ["-period_start"]
        constraints = [
            models.UniqueConstraint(fields=["authority", "period_start", "period_end"], name="rec_share_period_uq"),
            models.CheckConstraint(condition=Q(period_end__gte=models.F("period_start")), name="rec_share_dates"),
            models.CheckConstraint(condition=Q(approved_by__isnull=True) | ~Q(approved_by=models.F("computed_by")),
                                   name="rec_share_second_person"),
        ]


REVENUE_SHARE = state.register("rec_revenue_share", "rec_revenue_share", {
    "computed": {"approved"},
    "approved": {"paid"},
})


class RevenueShareItem(BaseModel):
    share = models.ForeignKey(RevenueShare, on_delete=models.CASCADE, related_name="items")
    match = models.ForeignKey(Match, on_delete=models.PROTECT, related_name="+")
    case = models.ForeignKey("cases.Case", on_delete=models.PROTECT, related_name="+")
    amount = amount_field()

    class Meta:
        db_table = "rec_revenue_share_item"
        constraints = [models.UniqueConstraint(fields=["match"], name="rec_match_shared_once")]
