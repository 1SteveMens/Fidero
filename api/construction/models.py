"""BLD Construction, off-plan and buildings (document 02: 4.2, 5.4, 6.6; document 01 C4.10, C8 Milestone).

One project and milestone engine serves all project types: a self-build with a
contractor, an off-plan purchase from a developer, the completion of an
existing building, and project funds (PRJ adds its suppliers, invoices and
checks on top of the same tables).

Money never sits here. A milestone is paid either through the licensed bank
(the `escrow` route: a construction, off-plan or project fund escrow and one
partial release per milestone) or, at launch, by the client directly to the
builder's verified account after Tenmina inspects and confirms the stage
(the `client_direct` route, decision 2026-11-12-two-front-doors). The route is
a country setting (`construction.payment_route`), copied onto each project.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

PROJECT_TYPES = ["construction", "completion", "offplan", "funds"]
BUILD_TYPES = ["construction", "completion", "offplan"]
ROUTES = ["escrow", "client_direct"]
ESCROW_KIND = {"construction": "construction", "completion": "construction", "offplan": "offplan",
               "funds": "project_fund"}
# The escrow subject type a milestone payment uses (escrow.models.SUBJECT_TYPES).
RELEASE_SUBJECT = {"construction": "milestone", "completion": "milestone", "offplan": "offplan_stage",
                   "funds": "project_invoice"}


# ----------------------------------------------------------------- panel (FR-BLD-003)

class PanelMember(CountryScopedModel):
    """A vetted contractor, inspector, quantity surveyor or developer, with
    documents (evidence links on subject `panel_member`), status and track record."""

    KINDS = ["contractor", "inspector", "quantity_surveyor", "developer"]
    STATUSES = ["pending", "vetted", "active", "suspended", "removed"]
    ROLE_FOR_KIND = {"contractor": "CT", "inspector": "IN", "quantity_surveyor": "QS", "developer": "DV"}

    kind = models.TextField(choices=[(k, k) for k in KINDS])
    name = models.TextField()
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="panel_memberships")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    registration_number = models.TextField(blank=True, default="")
    contact_phone = models.TextField(blank=True, default="")
    contact_email = models.TextField(blank=True, default="")
    specialities = models.JSONField(default=list, blank=True)
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    check_case_id = models.UUIDField(null=True, blank=True)  # contractor_check or offplan_check case
    check_outcome = models.TextField(blank=True, default="")  # verified | not_verified
    payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    status_reason = models.TextField(blank=True, default="")
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)
    removal_finding = models.TextField(blank=True, default="")  # the confirmed finding, feeds the track record

    class Meta:
        db_table = "bld_panel_member"
        indexes = [models.Index(fields=["country", "kind", "status"])]
        constraints = [
            models.CheckConstraint(condition=Q(person__isnull=False) | Q(organisation__isnull=False),
                                   name="bld_panel_member_has_party"),
            models.CheckConstraint(condition=~Q(status="active") | Q(approved_at__isnull=False),
                                   name="bld_panel_active_is_approved"),
            models.CheckConstraint(condition=~Q(status="removed") | (Q(removed_at__isnull=False) & ~Q(
                removal_finding="")), name="bld_panel_removed_has_finding"),
        ]

    def __str__(self):
        return f"{self.name} ({self.kind})"


PANEL = state.register("panel_member", "bld_panel_member", {
    "pending": {"vetted", "removed"},
    "vetted": {"active", "pending", "removed"},
    "active": {"suspended", "removed"},
    "suspended": {"active", "removed"},
})


class ConflictLink(BaseModel):
    """RUL-10: a recorded link between an inspector and a contractor. An
    inspector with any link is never assigned to that contractor's work."""

    REASONS = ["employee", "payee", "nominee", "relative", "shared_organisation", "business_partner",
               "declared_by_inspector", "other"]
    inspector = models.ForeignKey(PanelMember, on_delete=models.PROTECT, related_name="conflicts_as_inspector")
    contractor = models.ForeignKey(PanelMember, on_delete=models.PROTECT, related_name="conflicts_as_contractor")
    reason = models.TextField(choices=[(r, r) for r in REASONS])
    note = models.TextField(blank=True, default="")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "bld_conflict_link"
        constraints = [models.UniqueConstraint(fields=["inspector", "contractor"], name="bld_conflict_link_pair"),
                       models.CheckConstraint(condition=~Q(inspector=models.F("contractor")),
                                              name="bld_conflict_not_self")]


# ----------------------------------------------------------------- projects (FR-BLD-001, FR-BLD-011, FR-PRJ-001)

class Project(CountryScopedModel):
    STATUSES = ["setup", "active", "paused", "completed", "cancelled"]

    type = models.TextField(choices=[(t, t) for t in PROJECT_TYPES])
    title = models.TextField()
    description = models.TextField(blank=True, default="")
    asset = models.ForeignKey("geo.Asset", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    report_id = models.UUIDField(null=True, blank=True)  # the released report that verified the plot
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="bld_projects")
    case_manager = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    contractor = models.ForeignKey(PanelMember, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="projects_as_contractor")  # the developer, for off-plan
    inspector = models.ForeignKey(PanelMember, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="projects_as_inspector")
    quantity_surveyor = models.ForeignKey(PanelMember, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="projects_as_qs")
    qs_assigned_at = models.DateTimeField(null=True, blank=True)
    runner_person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                      related_name="+")  # the person running a funded project
    runner_name = models.TextField(blank=True, default="")
    runner_phone = models.TextField(blank=True, default="")
    schedule_version = models.ForeignKey("administration.ConfigVersion", null=True, blank=True,
                                         on_delete=models.PROTECT, related_name="+")
    budget_amount = amount_field()
    budget_currency = currency_field()
    guide_amount = amount_field(null=True, blank=True)  # the budget in the price currency (RUL-18)
    guide_currency = currency_field(blank=True, default="")
    payment_route = models.TextField(choices=[(r, r) for r in ROUTES])
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    offplan_case_id = models.UUIDField(null=True, blank=True)  # the developer's off-plan check (FR-BLD-011)
    status = models.TextField(default="setup", choices=[(s, s) for s in STATUSES])
    prior_status = models.TextField(blank=True, default="")
    budget_approved_at = models.DateTimeField(null=True, blank=True)
    budget_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    contract_signed_at = models.DateTimeField(null=True, blank=True)
    contract_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    handover_confirmed_at = models.DateTimeField(null=True, blank=True)  # site handover, for mobilisation
    handover_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                              on_delete=models.PROTECT, related_name="+")
    practical_completion_on = models.DateField(null=True, blank=True)  # the handover milestone was paid
    defects_period_ends_on = models.DateField(null=True, blank=True)  # FR-BLD-012
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status_reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    data_class = models.TextField(default="case")

    class Meta:
        db_table = "bld_project"
        indexes = [models.Index(fields=["client", "status"]), models.Index(fields=["country", "type", "status"])]
        constraints = [
            models.CheckConstraint(condition=Q(type="funds") | Q(asset__isnull=False), name="bld_project_asset"),
            models.CheckConstraint(condition=Q(budget_amount__gt=0), name="bld_project_budget_positive"),
            models.CheckConstraint(condition=~Q(status="active") | Q(started_at__isnull=False),
                                   name="bld_project_active_started"),
        ]

    @property
    def is_build(self):
        return self.type in BUILD_TYPES

    @property
    def release_subject(self):
        return RELEASE_SUBJECT[self.type]


PROJECT = state.register("project", "bld_project", {
    "setup": {"active", "cancelled"},
    "active": {"paused", "completed", "cancelled"},
    "paused": {"active", "cancelled"},
})


class BillOfQuantities(CountryScopedModel):
    """FR-BLD-002: the quantity surveyor's bill of quantities and the milestone split it proposes."""

    STATUSES = ["submitted", "accepted", "superseded"]
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="boqs")
    version = models.PositiveIntegerField()
    items = models.JSONField(default=list)  # [{description, quantity, unit, rate, amount}]
    split = models.JSONField(default=list)  # [{key, name, share_pct}]
    total_amount = amount_field()
    total_currency = currency_field()
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="submitted", choices=[(s, s) for s in STATUSES])
    accepted_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bld_boq"
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="bld_boq_version"),
                       models.CheckConstraint(condition=Q(total_amount__gt=0), name="bld_boq_total_positive")]


# ----------------------------------------------------------------- milestones (FR-BLD-005, 01 C8 Milestone)

MILESTONE_STATUSES = ["not_started", "submitted", "evidence_checked", "returned", "inspection_scheduled",
                      "inspected", "client_approved", "release_approved", "paid", "frozen"]
BEFORE_PAID = [s for s in MILESTONE_STATUSES if s not in ("paid", "frozen")]


class Milestone(CountryScopedModel):
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="milestones")
    seq = models.PositiveSmallIntegerField()
    key = models.TextField()  # mobilisation, foundation, ... retention, or a fund stage
    name = models.TextField()
    share_pct = models.DecimalField(max_digits=5, decimal_places=2)
    amount = amount_field()  # in the project's currency, after agreed variations
    currency = currency_field()
    guide_amount = amount_field(null=True, blank=True)  # in the price currency (RUL-18)
    guide_currency = currency_field(blank=True, default="")
    status = models.TextField(default="not_started", choices=[(s, s) for s in MILESTONE_STATUSES])
    prior_status = models.TextField(blank=True, default="")  # restored when a freeze lifts
    freeze_kind = models.TextField(blank=True, default="")  # dispute | contractor_removed
    freeze_source_id = models.UUIDField(null=True, blank=True)
    inspector = models.ForeignKey(PanelMember, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    required_evidence = models.JSONField(default=list, blank=True)  # [{key, label, media, required}]
    checklist = models.JSONField(default=list, blank=True)  # [{key, label}] for the inspector
    visit_required = models.BooleanField(default=True)  # funds stages: a visit only where configured
    submission_id = models.UUIDField(null=True, blank=True)  # mob_submission or the portal submission
    evidence_ids = models.JSONField(default=list, blank=True)
    captured_from = models.DateTimeField(null=True, blank=True)  # earliest capture time of the evidence set
    submitted_at = models.DateTimeField(null=True, blank=True)
    submissions = models.PositiveSmallIntegerField(default=0)
    fraud_flagged = models.BooleanField(default=False)  # MOB flags on the evidence, cleared only by a reviewer
    concerns = models.JSONField(default=list, blank=True)  # BLD flags: unagreed variation, ... (RUL-19)
    return_reasons = models.JSONField(default=list, blank=True)  # every earlier reason is kept
    evidence_checked_at = models.DateTimeField(null=True, blank=True)
    evidence_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                            on_delete=models.PROTECT, related_name="+")
    inspected_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)
    client_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                           on_delete=models.PROTECT, related_name="+")
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bld_milestone"
        ordering = ["project", "seq"]
        constraints = [
            models.UniqueConstraint(fields=["project", "seq"], name="bld_milestone_seq"),
            models.CheckConstraint(condition=Q(share_pct__gt=0) & Q(share_pct__lte=100), name="bld_milestone_share"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="bld_milestone_amount"),
        ]

    @property
    def is_mobilisation(self):
        return self.seq == 0 and self.key == "mobilisation" and self.project.is_build

    @property
    def is_retention(self):
        return self.key == "retention" and self.project.is_build

    @property
    def label(self):
        return f"{self.project.title}: {self.name}"


MILESTONE = state.register("milestone", "bld_milestone", {
    # RUL-09: only milestone 0 (mobilisation) jumps from not started to client approved (checked in services).
    "not_started": {"submitted", "client_approved", "frozen"},
    "submitted": {"evidence_checked", "returned", "frozen"},
    "returned": {"submitted", "frozen"},
    # Funds stages with no visit configured are confirmed at the desk (FR-PRJ-003, checked in services).
    "evidence_checked": {"inspection_scheduled", "inspected", "returned", "frozen"},
    "inspection_scheduled": {"inspected", "evidence_checked", "frozen"},
    "inspected": {"client_approved", "returned", "paid", "frozen"},
    # Back to inspected when a re-price, a decline or a bank rejection invalidates the approval (RUL-18).
    "client_approved": {"release_approved", "inspected", "frozen"},
    "release_approved": {"paid", "inspected", "frozen"},
    "frozen": {"not_started", "submitted", "evidence_checked", "returned", "inspection_scheduled", "inspected",
               "client_approved", "release_approved"},
})


class Reprice(CountryScopedModel):
    """RUL-18: each milestone's cost re-priced in the local currency against
    the guide rate before release; the change is shown to the client."""

    milestone = models.ForeignKey(Milestone, on_delete=models.PROTECT, related_name="reprices")
    guide_amount = amount_field()
    guide_currency = currency_field()
    local_amount = amount_field()
    local_currency = currency_field()
    previous_amount = amount_field()
    fx_rate = models.ForeignKey("administration.FxRate", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    rate = models.DecimalField(max_digits=18, decimal_places=6)
    rate_date = models.DateField()
    shown_to_client_at = models.DateTimeField(null=True, blank=True)
    client_approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bld_reprice"
        ordering = ["-created_at"]

    @property
    def changed(self):
        return self.local_amount != self.previous_amount


# ----------------------------------------------------------------- inspections (FR-BLD-004, FR-MOB-007)

class Inspection(CountryScopedModel):
    KINDS = ["milestone", "extra", "retention"]
    STATUSES = ["scheduled", "recorded", "cancelled"]
    OUTCOMES = ["pass", "pass_with_defects", "fail"]
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="inspections")
    milestone = models.ForeignKey(Milestone, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="inspections")
    inspector = models.ForeignKey(PanelMember, null=True, blank=True, on_delete=models.PROTECT,
                                  related_name="inspections")
    kind = models.TextField(default="milestone", choices=[(k, k) for k in KINDS])
    order_id = models.UUIDField(null=True, blank=True)  # an extra inspection the client ordered (FR-ORD-007)
    concern = models.TextField(blank=True, default="")
    scheduled_for = models.DateField(null=True, blank=True)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    assigned_at = models.DateTimeField(null=True, blank=True)
    checklist = models.JSONField(default=list, blank=True)
    declared_no_link_at = models.DateTimeField(null=True, blank=True)  # "You have no link to this contractor"
    status = models.TextField(default="scheduled", choices=[(s, s) for s in STATUSES])
    outcome = models.TextField(null=True, blank=True, choices=[(o, o) for o in OUTCOMES])
    defect_value = amount_field(default=0)
    defect_currency = currency_field(blank=True, default="")
    reason = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    submission_id = models.UUIDField(null=True, blank=True)
    needs_review = models.BooleanField(default=False)  # defects worth more than the milestone (TC-RUL-09-04)
    recorded_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bld_inspection"
        constraints = [
            models.CheckConstraint(condition=Q(defect_value__gte=0), name="bld_inspection_defect_value"),
            models.CheckConstraint(condition=~Q(outcome="pass_with_defects") | Q(defect_value__gt=0),
                                   name="bld_inspection_defects_valued"),
            models.CheckConstraint(condition=~Q(status="recorded") | (Q(outcome__isnull=False) & Q(
                recorded_at__isnull=False) & Q(inspector__isnull=False)), name="bld_inspection_recorded"),
            models.CheckConstraint(condition=~Q(status="scheduled") | Q(inspector__isnull=True) | Q(
                scheduled_for__isnull=False), name="bld_inspection_has_date"),
        ]


INSPECTION = state.register("bld_inspection", "bld_inspection", {
    "scheduled": {"recorded", "cancelled"},
})


class InspectionItem(BaseModel):
    inspection = models.ForeignKey(Inspection, on_delete=models.PROTECT, related_name="items")
    key = models.TextField()
    label = models.TextField(blank=True, default="")
    result = models.TextField(choices=[(r, r) for r in ("ok", "not_ok", "na")])
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bld_inspection_item"
        constraints = [models.UniqueConstraint(fields=["inspection", "key"], name="bld_inspection_item_key")]


class Defect(CountryScopedModel):
    """FR-BLD-006: the defect value is held back and released when the defect
    is closed with evidence and the inspector confirms it."""

    STATUSES = ["open", "fixed", "closed"]
    inspection = models.ForeignKey(Inspection, on_delete=models.PROTECT, related_name="defects")
    milestone = models.ForeignKey(Milestone, null=True, blank=True, on_delete=models.PROTECT, related_name="defects")
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="defects")
    description = models.TextField()
    value_amount = amount_field()
    value_currency = currency_field()
    photo_evidence_ids = models.JSONField(default=list, blank=True)
    status = models.TextField(default="open", choices=[(s, s) for s in STATUSES])
    closing_evidence_ids = models.JSONField(default=list, blank=True)
    fixed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    fixed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")  # the assigned inspector
    closed_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bld_defect"
        constraints = [
            models.CheckConstraint(condition=Q(value_amount__gt=0), name="bld_defect_value_positive"),
            models.CheckConstraint(condition=Q(status="open") | ~Q(closing_evidence_ids=[]),
                                   name="bld_defect_closed_with_evidence"),
            models.CheckConstraint(condition=~Q(status="closed") | Q(confirmed_by__isnull=False),
                                   name="bld_defect_closed_confirmed"),
        ]


DEFECT = state.register("bld_defect", "bld_defect", {"open": {"fixed", "closed"}, "fixed": {"closed", "open"}})


# ----------------------------------------------------------------- variations (FR-BLD-008, RUL-19)

class Variation(CountryScopedModel):
    STATUSES = ["proposed", "agreed", "declined", "withdrawn"]
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="variations")
    milestone = models.ForeignKey(Milestone, on_delete=models.PROTECT, related_name="variations")
    description = models.TextField()
    cost_change_amount = amount_field()  # may be negative (scope removed)
    cost_change_currency = currency_field()
    time_effect_days = models.IntegerField(default=0)
    proposed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    client_agreed_at = models.DateTimeField(null=True, blank=True)
    contractor_agreed_at = models.DateTimeField(null=True, blank=True)
    contractor_agreed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="+")
    agreed_at = models.DateTimeField(null=True, blank=True)
    declined_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    decline_reason = models.TextField(blank=True, default="")
    status = models.TextField(default="proposed", choices=[(s, s) for s in STATUSES])
    agreement_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                           related_name="+")  # the written record both sides agreed

    class Meta:
        db_table = "bld_variation"
        constraints = [models.CheckConstraint(condition=~Q(status="agreed") | (Q(
            client_agreed_at__isnull=False) & Q(contractor_agreed_at__isnull=False)), name="bld_variation_both_agree")]


VARIATION = state.register("bld_variation", "bld_variation", {
    "proposed": {"agreed", "declined", "withdrawn"},
})


# ----------------------------------------------------------------- payments on both routes

class Payment(CountryScopedModel):
    """One payment for a milestone (main part, defect holdback), a materials
    order or a project fund invoice. On the escrow route it mirrors one
    release instruction; on the client_direct route Tenmina confirms the
    stage and the client pays the verified payee's account directly."""

    PARTS = ["main", "defect_holdback", "materials", "invoice"]
    STATUSES = ["preparing", "awaiting_client", "client_approved", "release_approved", "paid", "withdrawn",
                "rejected"]
    LIVE = ["preparing", "awaiting_client", "client_approved", "release_approved"]
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="payments")
    milestone = models.ForeignKey(Milestone, null=True, blank=True, on_delete=models.PROTECT, related_name="payments")
    part = models.TextField(choices=[(p, p) for p in PARTS])
    subject_type = models.TextField()  # escrow subject: milestone, offplan_stage, project_invoice
    subject_id = models.UUIDField()
    label = models.TextField(blank=True, default="")
    payee = models.ForeignKey("escrow.Payee", on_delete=models.PROTECT, related_name="+")
    amount = amount_field()
    currency = currency_field()
    holdback_amount = amount_field(default=0)
    reprice = models.ForeignKey(Reprice, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    route = models.TextField(choices=[(r, r) for r in ROUTES])
    instruction = models.ForeignKey("escrow.ReleaseInstruction", null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")  # client_direct: two staff confirm
    status = models.TextField(default="preparing", choices=[(s, s) for s in STATUSES])
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    client_approved_at = models.DateTimeField(null=True, blank=True)
    release_approved_at = models.DateTimeField(null=True, blank=True)
    client_paid_at = models.DateTimeField(null=True, blank=True)  # client_direct: the client says they paid
    client_paid_reference = models.TextField(blank=True, default="")
    client_paid_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                             related_name="+")
    receipt_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                             on_delete=models.PROTECT, related_name="+")
    receipt_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    paid_at = models.DateTimeField(null=True, blank=True)
    bank_reference = models.TextField(blank=True, default="")
    closed_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bld_payment"
        indexes = [models.Index(fields=["subject_type", "subject_id"])]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="bld_payment_amount_positive"),
            models.CheckConstraint(condition=Q(holdback_amount__gte=0), name="bld_payment_holdback"),
            models.UniqueConstraint(fields=["subject_type", "subject_id", "part"],
                                    condition=Q(status__in=["preparing", "awaiting_client", "client_approved",
                                                            "release_approved"]),
                                    name="bld_payment_one_live"),
            models.CheckConstraint(condition=~Q(route="escrow", status__in=[
                "awaiting_client", "client_approved", "release_approved", "paid"]) | Q(instruction__isnull=False),
                name="bld_payment_escrow_has_instruction"),
            models.CheckConstraint(condition=~Q(route="client_direct", status="paid") | Q(
                receipt_confirmed_by__isnull=False), name="bld_payment_direct_receipt"),
        ]


PAYMENT = state.register("bld_payment", "bld_payment", {
    "preparing": {"awaiting_client", "withdrawn", "rejected"},
    "awaiting_client": {"client_approved", "withdrawn", "rejected"},
    "client_approved": {"release_approved", "withdrawn", "rejected"},
    "release_approved": {"paid", "rejected", "withdrawn"},
})


# ----------------------------------------------------------------- materials (FR-BLD-013, R3)

class MaterialsOrder(CountryScopedModel):
    STATUSES = ["requested", "approved", "paid", "delivered", "cancelled"]
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="materials_orders")
    milestone = models.ForeignKey(Milestone, on_delete=models.PROTECT, related_name="materials_orders")
    supplier_payee = models.ForeignKey("escrow.Payee", on_delete=models.PROTECT, related_name="+")
    description = models.TextField()
    items = models.JSONField(default=list, blank=True)
    amount = amount_field()
    currency = currency_field()
    quote_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="requested", choices=[(s, s) for s in STATUSES])
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_evidence_ids = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "bld_materials_order"
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name="bld_materials_amount")]


MATERIALS = state.register("bld_materials_order", "bld_materials_order", {
    "requested": {"approved", "cancelled"},
    "approved": {"paid", "cancelled"},
    "paid": {"delivered"},
})
