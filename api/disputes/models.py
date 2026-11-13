"""DSP Disputes (01 C4.14, C8 Dispute; 02 section 6.6).

A party to an escrow, project, milestone or listing opens a dispute with a reason and evidence. Every release
linked to it is frozen (RUL-15) until it closes or the party who raised it withdraws. Each step has a deadline
in working days (FR-DSP-003). Two Tenmina staff approve the decision (approval `dispute_decision`), or a
reviewer refers it to mediation and the outcome is approved the same way (FR-DSP-004, FR-DSP-005).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel

STATUSES = ["open", "awaiting_response", "evidence", "decision", "closed", "referred", "withdrawn"]
OPEN_STATUSES = ["open", "awaiting_response", "evidence", "decision", "referred"]
SUBJECT_TYPES = ["escrow", "milestone", "listing", "project"]
OUTCOMES = ["continue", "refund", "partial_refund", "other"]
IN_FAVOUR = ["raised_by", "respondent", "split", "none"]


class Dispute(CountryScopedModel):
    CATEGORIES = ["work_quality", "payment", "title_or_documents", "misrepresentation", "delay", "other"]
    reference = models.TextField(unique=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    opened_by_staff = models.BooleanField(default=False)
    category = models.TextField(choices=[(c, c) for c in CATEGORIES], default="other")
    reason = models.TextField()
    status = models.TextField(default="open", choices=[(s, s) for s in STATUSES])
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    subject_label = models.TextField(blank=True, default="")
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    project_id = models.UUIDField(null=True, blank=True)
    milestone_id = models.UUIDField(null=True, blank=True)
    listing = models.ForeignKey("listings.Listing", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    response_due = models.DateField(null=True, blank=True)
    evidence_due = models.DateField(null=True, blank=True)
    decision_due = models.DateField(null=True, blank=True)
    early_move_note = models.TextField(blank=True, default="")
    escalated_at = models.DateTimeField(null=True, blank=True)
    decision = models.TextField(blank=True, default="")  # the reasons, as approved
    decision_outcome = models.TextField(blank=True, default="", choices=[(o, o) for o in [""] + OUTCOMES])
    in_favour_of = models.TextField(blank=True, default="", choices=[(o, o) for o in [""] + IN_FAVOUR])
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    referred_at = models.DateTimeField(null=True, blank=True)
    referred_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    referral_reason = models.TextField(blank=True, default="")
    mediator = models.TextField(blank=True, default="")
    mediation_reference = models.TextField(blank=True, default="")
    closed_at = models.DateTimeField(null=True, blank=True)
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    withdraw_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "dsp_dispute"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["subject_type", "subject_id"], name="dsp_dispute_subject_idx"),
                   models.Index(fields=["country", "status"], name="dsp_dispute_status_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=STATUSES), name="dsp_dispute_status_valid"),
            models.CheckConstraint(condition=~Q(status="closed") | ~Q(decision=""), name="dsp_closed_has_decision"),
            models.CheckConstraint(condition=~Q(status="withdrawn") | Q(withdrawn_at__isnull=False),
                                   name="dsp_withdrawn_has_time"),
            models.CheckConstraint(condition=~Q(reason=""), name="dsp_dispute_reason"),
        ]

    def __str__(self):
        return self.reference


DISPUTE = state.register("dispute", "dsp_dispute", {
    "open": {"awaiting_response", "referred", "withdrawn"},
    "awaiting_response": {"evidence", "referred", "withdrawn"},
    "evidence": {"decision", "referred", "withdrawn"},
    "decision": {"closed", "referred"},
    "referred": {"closed"},
})


class Party(BaseModel):
    SIDES = ["raised_by", "respondent", "other"]
    dispute = models.ForeignKey(Dispute, on_delete=models.PROTECT, related_name="parties")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    side = models.TextField(choices=[(s, s) for s in SIDES])
    role = models.TextField(blank=True, default="")  # buyer, seller, developer, contractor, supplier, tenmina
    name = models.TextField()
    notified_at = models.DateTimeField(null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    missed_response = models.BooleanField(default=False)
    evidence_complete_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dsp_party"
        constraints = [models.CheckConstraint(condition=Q(person__isnull=False) | Q(organisation__isnull=False),
                                              name="dsp_party_who")]


class Statement(BaseModel):
    """What a party or Tenmina said, with its evidence. Append-only (dbsql)."""

    KINDS = ["statement", "response", "evidence", "staff_note"]
    dispute = models.ForeignKey(Dispute, on_delete=models.PROTECT, related_name="statements")
    party = models.ForeignKey(Party, null=True, blank=True, on_delete=models.PROTECT, related_name="statements")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    text = models.TextField()
    evidence_ids = models.JSONField(default=list)

    class Meta:
        db_table = "dsp_statement"
        ordering = ["created_at"]


class SubjectLink(BaseModel):
    """Each subject a dispute froze and its state at that moment, so a withdrawal restores it (01 C8)."""

    TYPES = ["escrow", "milestone", "listing", "release_instruction", "project"]
    dispute = models.ForeignKey(Dispute, on_delete=models.PROTECT, related_name="links")
    subject_type = models.TextField(choices=[(t, t) for t in TYPES])
    subject_id = models.UUIDField()
    prior_status = models.TextField()

    class Meta:
        db_table = "dsp_subject_link"
        indexes = [models.Index(fields=["subject_type", "subject_id"], name="dsp_link_subject_idx")]
        constraints = [models.UniqueConstraint(fields=["dispute", "subject_type", "subject_id"],
                                               name="dsp_link_once")]


class Decision(BaseModel):
    """A decision or a mediation outcome waiting for two staff approvals (approval `dispute_decision`)."""

    KINDS = ["decision", "mediation_outcome"]
    STATUSES = ["pending", "approved", "rejected"]
    dispute = models.ForeignKey(Dispute, on_delete=models.PROTECT, related_name="decisions")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    outcome = models.TextField(choices=[(o, o) for o in OUTCOMES])
    in_favour_of = models.TextField(choices=[(o, o) for o in IN_FAVOUR])
    reasons = models.TextField()
    details = models.JSONField(default=dict)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "dsp_decision"
        constraints = [
            models.CheckConstraint(condition=~Q(reasons=""), name="dsp_decision_reasons"),
            models.UniqueConstraint(fields=["dispute"], condition=Q(status="pending"), name="dsp_one_pending_decision"),
        ]


DECISION = state.register("dispute_decision", "dsp_decision", {
    "pending": {"approved", "rejected"},
})
