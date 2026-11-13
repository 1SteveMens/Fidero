"""TSK Paperwork and errands (02 section 6.13; FR-TSK-001 to FR-TSK-005, RUL-22, RUL-23, RUL-27).

The client orders an errand from the country's catalogue, uploads the checklist documents, pays Tenmina's
charge through the payment provider and the official fees into held funds at the partner bank. A vetted agent
records each step with its acknowledgement or receipt in Tenmina Field. Official fees go to the agency's
verified account only, never to the agent. The errand is complete only when Tenmina checks the resulting
document; then `work.accepted` creates the agent's payable in PRO, paid from Tenmina's own account.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field


class Agent(CountryScopedModel):
    """FR-TSK-003: the agent panel over acc_vetting. The agent's own pay comes from PRO, never an escrow."""

    STATUSES = ["active", "suspended", "removed"]
    person = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="errand_agent")
    vetting = models.ForeignKey("accounts.Vetting", on_delete=models.PROTECT, related_name="+")
    agency_org = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")  # the agent's employer, if any; never an official-fee payee
    pro_agreement_id = models.UUIDField(null=True, blank=True)  # pro_agreement with role errand_agent
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    status_reason = models.TextField(blank=True, default="")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "tsk_agent"

    def __str__(self):
        return self.person.full_name


AGENT = state.register("tsk_agent", "tsk_agent", {
    "active": {"suspended", "removed"},
    "suspended": {"active", "removed"},
})


class Errand(CountryScopedModel):
    STATUSES = ["ordered", "documents_pending", "funded", "assigned", "in_progress", "result_uploaded",
                "completed", "handed_over", "cancelled"]
    reference = models.TextField(unique=True)
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="errands")
    for_family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    catalogue_version = models.ForeignKey("countries.CountryConfig", on_delete=models.PROTECT, related_name="+")
    catalogue_key = models.TextField()
    item = models.JSONField()  # the catalogue item as ordered: open errands keep their fees (US-TSK-001 AC2)
    official_fees_amount = amount_field()
    official_fees_currency = currency_field()
    tenmina_charge_amount = amount_field()
    tenmina_charge_currency = currency_field()
    fee_order_id = models.UUIDField(null=True, blank=True)  # ord_order, PAY purpose errand_fee (FR-TSK-002)
    fee_paid_at = models.DateTimeField(null=True, blank=True)
    escrow = models.ForeignKey("escrow.Escrow", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    agent = models.ForeignKey(Agent, null=True, blank=True, on_delete=models.PROTECT, related_name="errands")
    agency_payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    agency_approved_at = models.DateTimeField(null=True, blank=True)  # the client agreed the agency payee
    target_days = models.PositiveSmallIntegerField()
    submitted_at = models.DateTimeField(null=True, blank=True)
    due_on = models.DateField(null=True, blank=True)
    near_warned_at = models.DateTimeField(null=True, blank=True)
    overdue_warned_at = models.DateTimeField(null=True, blank=True)
    assigned_at = models.DateTimeField(null=True, blank=True)
    result_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    result_uploaded_at = models.DateTimeField(null=True, blank=True)
    result_checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    result_checked_at = models.DateTimeField(null=True, blank=True)
    result_note = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)
    work_accepted_at = models.DateTimeField(null=True, blank=True)
    handed_over_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    status = models.TextField(default="ordered", choices=[(s, s) for s in STATUSES])
    data_class = models.TextField(default="identity_documents")

    class Meta:
        db_table = "tsk_errand"
        constraints = [
            models.CheckConstraint(condition=Q(official_fees_amount__gte=0), name="tsk_errand_fees_positive"),
            models.CheckConstraint(condition=~Q(status__in=["completed", "handed_over"]) | (
                Q(result_evidence__isnull=False) & Q(result_checked_by__isnull=False)),
                name="tsk_errand_completed_needs_checked_result"),
            models.CheckConstraint(condition=~Q(status__in=["assigned", "in_progress", "result_uploaded", "completed",
                                                            "handed_over"])
                                   | (Q(agent__isnull=False)
                                      & (Q(agency_payee__isnull=False) | Q(official_fees_amount=0))),
                                   name="tsk_errand_assigned_needs_agent_and_agency"),
        ]

    def __str__(self):
        return self.reference


ERRAND = state.register("tsk_errand", "tsk_errand", {
    "ordered": {"documents_pending", "funded", "cancelled"},
    "documents_pending": {"ordered", "cancelled"},
    "funded": {"assigned", "documents_pending", "cancelled"},
    "assigned": {"in_progress", "cancelled"},
    "in_progress": {"result_uploaded"},
    "result_uploaded": {"completed", "in_progress"},
    "completed": {"handed_over"},
})


class ErrandDocument(BaseModel):
    """FR-TSK-002: one checklist document. Deleted under the identity documents rule after handover."""

    STATUSES = ["missing", "uploaded", "accepted", "rejected", "deleted"]
    errand = models.ForeignKey(Errand, on_delete=models.PROTECT, related_name="documents")
    key = models.TextField()
    label = models.TextField()
    required = models.BooleanField(default=True)
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    status = models.TextField(default="missing", choices=[(s, s) for s in STATUSES])
    reject_reason = models.TextField(blank=True, default="")
    uploaded_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    data_class = models.TextField(default="identity_documents")

    class Meta:
        db_table = "tsk_errand_document"
        constraints = [
            models.UniqueConstraint(fields=["errand", "key"], name="tsk_errand_document_uq"),
            models.CheckConstraint(condition=~Q(status__in=["uploaded", "accepted"]) | Q(evidence__isnull=False),
                                   name="tsk_document_has_evidence"),
            models.CheckConstraint(condition=~Q(status="rejected") | ~Q(reject_reason=""),
                                   name="tsk_document_reject_reason"),
        ]


class ErrandStep(BaseModel):
    """FR-TSK-003: a step with its acknowledgement or receipt. A step with a fee cannot be receipted or done
    without its receipt (RUL-23)."""

    STATUSES = ["pending", "in_progress", "fee_instructed", "fee_paid", "receipted", "done", "blocked"]
    errand = models.ForeignKey(Errand, on_delete=models.PROTECT, related_name="steps")
    seq = models.PositiveSmallIntegerField()
    key = models.TextField()
    description = models.TextField()
    official_fee_amount = amount_field(default=0)
    official_fee_currency = currency_field()
    needs_documents = models.JSONField(default=list, blank=True)  # checklist keys the agent may open
    release_instruction_id = models.UUIDField(null=True, blank=True)  # payee = the errand's agency
    acknowledgement_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    receipt_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    checkin = models.ForeignKey("mobile.CheckIn", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    blocked_reason = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    done_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tsk_errand_step"
        ordering = ["seq"]
        constraints = [
            models.UniqueConstraint(fields=["errand", "seq"], name="tsk_errand_step_seq_uq"),
            models.CheckConstraint(condition=Q(official_fee_amount__gte=0), name="tsk_step_fee_positive"),
            models.CheckConstraint(condition=Q(official_fee_amount=0) | ~Q(status__in=["receipted", "done"])
                                   | Q(receipt_evidence__isnull=False), name="tsk_step_fee_needs_receipt"),
            models.CheckConstraint(condition=~Q(status="done") | Q(receipt_evidence__isnull=False)
                                   | Q(acknowledgement_evidence__isnull=False), name="tsk_step_done_needs_proof"),
        ]


STEP = state.register("tsk_errand_step", "tsk_errand_step", {
    "pending": {"in_progress", "blocked"},
    "in_progress": {"fee_instructed", "done", "blocked"},
    "fee_instructed": {"in_progress", "fee_paid"},
    "fee_paid": {"receipted"},
    "receipted": {"done"},
    "blocked": {"in_progress", "pending"},
})


class Handover(BaseModel):
    """FR-TSK-005: who received the document, how, with a signature or photo."""

    METHODS = ["client", "representative", "family_member", "courier"]
    PROOFS = ["signature", "photo"]
    errand = models.OneToOneField(Errand, on_delete=models.PROTECT, related_name="handover")
    method = models.TextField(choices=[(m, m) for m in METHODS])
    receiver_person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    receiver_family_member = models.ForeignKey("accounts.FamilyMember", null=True, blank=True,
                                               on_delete=models.PROTECT, related_name="+")
    receiver_name = models.TextField()
    courier_name = models.TextField(blank=True, default="")
    tracking_reference = models.TextField(blank=True, default="")
    proof_kind = models.TextField(choices=[(p, p) for p in PROOFS])
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    handed_at = models.DateTimeField()
    confirmation_id = models.UUIDField(null=True, blank=True)  # ntf_confirmation_code to a family receiver
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_via = models.TextField(blank=True, default="")

    class Meta:
        db_table = "tsk_handover"
        constraints = [
            models.CheckConstraint(condition=~Q(method="courier") | (~Q(courier_name="") & ~Q(tracking_reference="")),
                                   name="tsk_handover_courier_tracking"),
            models.CheckConstraint(condition=~Q(method="representative") | Q(receiver_person__isnull=False),
                                   name="tsk_handover_representative_named"),
            models.CheckConstraint(condition=~Q(method="family_member") | Q(receiver_family_member__isnull=False),
                                   name="tsk_handover_family_named"),
        ]
