"""CARE Care visits (02 section 6.12; FR-CARE-001 to FR-CARE-006, RUL-23, ADR-19, ADR-20).

A care plan names a registered family member, the visit schedule, the plan
items and who in the family may confirm a visit. A vetted carer from the
panel checks in and out at the registered address in Tenmina Field, records
each plan item, and the family confirms the visit out of band (the code is
held hashed by NTF and never reaches the carer's app). Only a confirmed visit
is paid: from the client's held funds to the carer's or agency's verified
payee, or by Tenmina under PRO for carers it contracts (RUL-27).
"""
from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

ITEM_KINDS = ["medicine", "meal", "reading", "companionship", "transport", "groceries", "hospital_visit", "other"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class Carer(CountryScopedModel):
    """FR-CARE-002: the panel. Only a person with a live `carer` vetting can be active."""

    STATUSES = ["active", "suspended", "removed"]
    PAY_ROUTES = ["held_funds", "tenmina"]  # client's held funds to a carer/agency payee, or PRO (RUL-27)
    person = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="carer_profile")
    vetting = models.ForeignKey("accounts.Vetting", on_delete=models.PROTECT, related_name="+")
    agency_org = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    pay_route = models.TextField(default="held_funds", choices=[(r, r) for r in PAY_ROUTES])
    payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    languages = models.JSONField(default=list, blank=True)
    areas = models.TextField(blank=True, default="")
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    status_reason = models.TextField(blank=True, default="")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")

    class Meta:
        db_table = "care_carer"
        constraints = [
            models.CheckConstraint(condition=~Q(pay_route="held_funds") | Q(payee__isnull=False),
                                   name="care_carer_held_funds_needs_payee"),
            models.CheckConstraint(condition=~Q(status="removed") | ~Q(status_reason=""),
                                   name="care_carer_removed_reason"),
        ]

    def __str__(self):
        return self.person.full_name


CARER = state.register("care_carer", "care_carer", {
    "active": {"suspended", "removed"},
    "suspended": {"active", "removed"},
})


class CarePlan(CountryScopedModel):
    """FR-CARE-001. `confirmers` are acc_family_member ids with may_confirm_visits (trigger)."""

    STATUSES = ["draft", "active", "paused", "ended"]
    CHANNELS = ["sms", "whatsapp", "app"]
    reference = models.TextField(unique=True)
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="care_plans")
    family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    template_version = models.ForeignKey("administration.ConfigVersion", null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="+")
    address = models.TextField()
    point_lat = models.DecimalField(max_digits=9, decimal_places=6)
    point_lng = models.DecimalField(max_digits=9, decimal_places=6)
    schedule = models.JSONField()  # {"weekly": ["tue", "fri"], "window": "09:00-12:00"}
    visit_fee_amount = amount_field()
    visit_fee_currency = currency_field()
    confirmers = ArrayField(models.UUIDField())
    confirm_channel = models.TextField(default="sms", choices=[(c, c) for c in CHANNELS])
    carer = models.ForeignKey(Carer, null=True, blank=True, on_delete=models.PROTECT, related_name="plans")
    case_manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    fee_order_id = models.UUIDField(null=True, blank=True)  # ord_order for Tenmina's service fee
    fee_paid_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    carer_approved_at = models.DateTimeField(null=True, blank=True)  # the client agreed the carer as payee
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True, default="")
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    status_reason = models.TextField(blank=True, default="")
    ended_at = models.DateTimeField(null=True, blank=True)
    data_class = models.TextField(default="health_care")

    class Meta:
        db_table = "care_plan"
        constraints = [
            models.CheckConstraint(condition=Q(visit_fee_amount__gt=0), name="care_plan_fee_positive"),
            models.CheckConstraint(condition=~Q(status="active") | Q(carer__isnull=False),
                                   name="care_plan_active_needs_carer"),
        ]

    def __str__(self):
        return self.reference


PLAN = state.register("care_plan", "care_plan", {
    "draft": {"active", "ended"},
    "active": {"paused", "ended"},
    "paused": {"active", "ended"},
})


class CarePlanItem(BaseModel):
    """FR-CARE-001: a task on every visit. `photo_allowed` is the agreed photo for this item (TC-CARE-003-03)."""

    plan = models.ForeignKey(CarePlan, on_delete=models.PROTECT, related_name="items")
    key = models.SlugField(max_length=64)
    kind = models.TextField(choices=[(k, k) for k in ITEM_KINDS])
    label = models.TextField()
    instructions = models.TextField(blank=True, default="")
    photo_required = models.BooleanField(default=False)
    photo_allowed = models.BooleanField(default=False)
    reading_required = models.BooleanField(default=False)
    reading_kind = models.TextField(blank=True, default="")  # blood_pressure, blood_sugar, temperature, weight
    active = models.BooleanField(default=True)
    added_in_version = models.PositiveIntegerField(default=1)
    removed_in_version = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "care_plan_item"
        ordering = ["position", "created_at"]
        constraints = [
            models.UniqueConstraint(fields=["plan", "key"], condition=Q(active=True), name="care_plan_item_key_uq"),
            models.CheckConstraint(condition=~Q(photo_required=True) | Q(photo_allowed=True),
                                   name="care_plan_item_photo_allowed"),
            models.CheckConstraint(condition=~Q(reading_required=True) | ~Q(reading_kind=""),
                                   name="care_plan_item_reading_kind"),
        ]


class Visit(CountryScopedModel):
    """FR-CARE-003 to FR-CARE-005, RUL-23."""

    STATUSES = ["scheduled", "checked_in", "checked_out", "confirmed", "unconfirmed", "missed", "disputed",
                "instructed", "paid", "cancelled"]
    plan = models.ForeignKey(CarePlan, on_delete=models.PROTECT, related_name="visits")
    carer = models.ForeignKey(Carer, on_delete=models.PROTECT, related_name="visits")
    plan_version = models.PositiveIntegerField(default=1)
    window_start = models.DateTimeField()
    window_end = models.DateTimeField()
    checkin = models.ForeignKey("mobile.CheckIn", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    checkout = models.ForeignKey("mobile.CheckIn", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    fee_amount = amount_field()
    fee_currency = currency_field()
    status = models.TextField(default="scheduled", choices=[(s, s) for s in STATUSES])
    submitted_at = models.DateTimeField(null=True, blank=True)  # every plan item answered after check-out
    confirmed_at = models.DateTimeField(null=True, blank=True)
    late_minutes = models.PositiveIntegerField(null=True, blank=True)
    alert_sent_at = models.DateTimeField(null=True, blank=True)  # FR-CARE-005 missed or unconfirmed alert
    late_alert_sent_at = models.DateTimeField(null=True, blank=True)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    checkout_missing_at = models.DateTimeField(null=True, blank=True)
    review_queued_at = models.DateTimeField(null=True, blank=True)  # 72 hours after check-out, FR-CARE-004
    needs_review_reason = models.TextField(blank=True, default="")
    instruction_id = models.UUIDField(null=True, blank=True)  # esc_release_instruction (held funds route)
    work_accepted_at = models.DateTimeField(null=True, blank=True)  # PRO route: work.accepted published
    paid_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")
    data_class = models.TextField(default="health_care")

    class Meta:
        db_table = "care_visit"
        indexes = [models.Index(fields=["plan", "window_start"]), models.Index(fields=["status", "window_end"])]
        constraints = [
            models.CheckConstraint(condition=Q(window_end__gt=models.F("window_start")),
                                   name="care_visit_window"),
            models.CheckConstraint(
                condition=~Q(status__in=["checked_out", "confirmed", "unconfirmed", "instructed", "paid"])
                | (Q(checkin__isnull=False) & Q(checkout__isnull=False)), name="care_visit_checked_in_and_out"),
            models.CheckConstraint(condition=~Q(status__in=["confirmed", "instructed", "paid"])
                                   | Q(confirmed_at__isnull=False), name="care_visit_confirmed_at"),
            models.UniqueConstraint(fields=["plan", "window_start"], condition=~Q(status="cancelled"),
                                    name="care_visit_one_per_window"),
        ]


VISIT = state.register("care_visit", "care_visit", {
    "scheduled": {"checked_in", "missed", "cancelled"},
    "missed": {"checked_in", "cancelled"},
    "checked_in": {"checked_out", "cancelled"},
    "checked_out": {"confirmed", "unconfirmed", "disputed"},
    "unconfirmed": {"confirmed", "disputed"},
    "disputed": {"confirmed", "unconfirmed"},
    "confirmed": {"instructed"},
    "instructed": {"confirmed", "paid"},
})


class VisitItem(BaseModel):
    """FR-CARE-003: one plan item on one visit, copied from the plan version the visit was scheduled under."""

    OUTCOMES = ["pending", "done", "not_done", "not_applicable"]
    visit = models.ForeignKey(Visit, on_delete=models.PROTECT, related_name="items")
    plan_item = models.ForeignKey(CarePlanItem, on_delete=models.PROTECT, related_name="+")
    key = models.SlugField(max_length=64)
    kind = models.TextField()
    label = models.TextField()
    photo_required = models.BooleanField(default=False)
    photo_allowed = models.BooleanField(default=False)
    reading_required = models.BooleanField(default=False)
    reading_kind = models.TextField(blank=True, default="")
    outcome = models.TextField(default="pending", choices=[(o, o) for o in OUTCOMES])
    reason = models.TextField(blank=True, default="")
    reading = models.JSONField(null=True, blank=True)
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    recorded_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")

    class Meta:
        db_table = "care_visit_item"
        constraints = [
            models.UniqueConstraint(fields=["visit", "key"], name="care_visit_item_uq"),
            models.CheckConstraint(condition=~Q(outcome="not_done") | ~Q(reason=""),
                                   name="care_visit_item_not_done_reason"),
            models.CheckConstraint(condition=~(Q(outcome="done") & Q(photo_required=True)) | Q(evidence__isnull=False),
                                   name="care_visit_item_photo"),
            models.CheckConstraint(condition=~(Q(outcome="done") & Q(reading_required=True))
                                   | Q(reading__isnull=False), name="care_visit_item_reading"),
            models.CheckConstraint(condition=Q(evidence__isnull=True) | Q(photo_allowed=True),
                                   name="care_visit_item_agreed_photo_only"),
        ]


class Confirmation(BaseModel):
    """FR-CARE-004, ADR-20. The code itself lives hashed in ntf_confirmation_code and is never returned by
    any API the carer can call; this row records who it went to and how the visit was confirmed."""

    METHODS = ["code", "link", "app", "reply", "call", "reviewer"]
    CHANNELS = ["sms", "whatsapp", "app"]
    visit = models.OneToOneField(Visit, on_delete=models.PROTECT, related_name="confirmation")
    ntf_confirmation_id = models.UUIDField(null=True, blank=True)
    code_expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)  # the 5th wrong attempt
    sent_to_family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    sent_channel = models.TextField(choices=[(c, c) for c in CHANNELS])
    sent_at = models.DateTimeField(null=True, blank=True)
    reminded_at = models.DateTimeField(null=True, blank=True)
    attempt_family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True,
                                              on_delete=models.PROTECT, related_name="+")  # who is trying now
    attempt_method = models.TextField(blank=True, default="")
    family_confirmed_at = models.DateTimeField(null=True, blank=True)  # family said yes; evidence may still need review
    confirmed_by_family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True,
                                                   on_delete=models.PROTECT, related_name="+")
    method = models.TextField(null=True, blank=True, choices=[(m, m) for m in METHODS])
    disputed_at = models.DateTimeField(null=True, blank=True)
    recorded_by_staff = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    call_family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="+")
    call_note = models.TextField(blank=True, default="")
    call_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    reviewer_decision = models.TextField(null=True, blank=True,
                                         choices=[("confirmed", "confirmed"), ("not_confirmed", "not_confirmed")])
    reviewer_note = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "care_confirmation"
        constraints = [
            models.CheckConstraint(condition=Q(attempts__lte=5), name="care_confirmation_attempts"),
            models.CheckConstraint(condition=~Q(method="call") | (
                Q(recorded_by_staff__isnull=False) & Q(call_checked_by__isnull=False)
                & ~Q(call_checked_by=models.F("recorded_by_staff"))), name="care_confirmation_call_checked"),
            models.CheckConstraint(condition=~Q(method="reviewer") | (
                Q(reviewer__isnull=False) & Q(reviewer_decision="confirmed") & ~Q(reviewer_note="")),
                name="care_confirmation_reviewer"),
            models.CheckConstraint(condition=Q(reviewer_decision__isnull=True) | (
                Q(reviewer__isnull=False) & ~Q(reviewer_note="")), name="care_confirmation_decision_note"),
            models.CheckConstraint(condition=Q(confirmed_at__isnull=True) | (
                Q(method__isnull=False) & (Q(method="reviewer") | Q(confirmed_by_family_member__isnull=False))),
                name="care_confirmation_confirmed_by"),
        ]


class Concern(CountryScopedModel):
    """FR-CARE-006; data class health_care. The narrative is restricted (staff with the health role only);
    the client sees the outcome text, never the carer's private notes."""

    KINDS = ["health", "safety", "welfare"]
    SEVERITIES = ["low", "medium", "high", "urgent"]
    STATUSES = ["open", "acknowledged", "actioned", "closed"]
    reference = models.TextField(unique=True)
    visit = models.ForeignKey(Visit, null=True, blank=True, on_delete=models.PROTECT, related_name="concerns")
    plan = models.ForeignKey(CarePlan, on_delete=models.PROTECT, related_name="concerns")
    raised_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    severity = models.TextField(choices=[(s, s) for s in SEVERITIES])
    narrative = models.TextField()  # encrypted with the health and care KMS key in production (10.6)
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    raised_at = models.DateTimeField(auto_now_add=True)
    routed_to_reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="+")
    client_notified_at = models.DateTimeField(null=True, blank=True)
    reviewer_notified_at = models.DateTimeField(null=True, blank=True)
    paged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    action_taken = models.TextField(blank=True, default="")  # staff only
    client_outcome = models.TextField(blank=True, default="")  # what the client sees
    actioned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    actioned_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="open", choices=[(s, s) for s in STATUSES])
    data_class = models.TextField(default="health_care")

    class Meta:
        db_table = "care_concern"
        constraints = [
            models.CheckConstraint(condition=~Q(status__in=["actioned", "closed"]) | ~Q(client_outcome=""),
                                   name="care_concern_outcome"),
        ]


CONCERN = state.register("care_concern", "care_concern", {
    "open": {"acknowledged", "actioned"},
    "acknowledged": {"actioned"},
    "actioned": {"closed"},
})
