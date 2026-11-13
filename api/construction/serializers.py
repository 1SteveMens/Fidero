"""BLD API serializers. Money is {"amount": "250.00", "currency": "GHS"} (7.1). A payee's full account number
appears only on the client_direct payment confirmation the client pays from; elsewhere the last four digits."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.money import MoneyField as _MoneyField

from .models import (BillOfQuantities, ConflictLink, Defect, Inspection, InspectionItem, MaterialsOrder, Milestone,
                     PanelMember, Payment, Project, Reprice, Variation)


from escrow.serializers import BlockingReason, MoneyIn, MoneyOut  # noqa: E402 - one shape for money and reasons


@extend_schema_field(MoneyOut)
class MoneyField(_MoneyField):
    """core.money.MoneyField with its OpenAPI shape."""


class Money2(serializers.Field):
    """A model with `<x>` and `<y>` fields that do not follow `<prefix>_amount`."""

    def __init__(self, amount, currency, **kw):
        self.a, self.c = amount, currency
        kw.setdefault("source", "*")
        kw["read_only"] = True
        super().__init__(**kw)

    def to_representation(self, obj):
        v = getattr(obj, self.a)
        return None if v is None else {"amount": f"{v:.2f}", "currency": getattr(obj, self.c)}


Money2 = extend_schema_field(MoneyOut)(Money2)


# ----------------------------------------------------------------- panel

class PanelMemberSerializer(serializers.ModelSerializer):
    person_id = serializers.UUIDField(read_only=True, allow_null=True)
    organisation_id = serializers.UUIDField(read_only=True, allow_null=True)
    country = serializers.CharField(source="country.code", read_only=True)
    payee_id = serializers.UUIDField(read_only=True, allow_null=True)
    payee_verified = serializers.SerializerMethodField()

    class Meta:
        model = PanelMember
        fields = ["id", "kind", "name", "country", "person_id", "organisation_id", "registration_number",
                  "contact_phone", "contact_email", "specialities", "status", "status_reason", "check_case_id",
                  "check_outcome", "payee_id", "payee_verified", "approved_at", "removed_at", "removal_finding",
                  "created_at"]

    def get_payee_verified(self, obj) -> bool:
        return bool(obj.payee_id and obj.payee.verification_status == "verified")


class PanelMemberPublicSerializer(serializers.ModelSerializer):
    """What a client sees when choosing: active members only, no contact details."""

    track_record = serializers.SerializerMethodField()

    class Meta:
        model = PanelMember
        fields = ["id", "kind", "name", "specialities", "status", "track_record"]

    def get_track_record(self, obj) -> dict:
        from .panel import track_record

        return track_record(obj)


class PanelMemberInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=PanelMember.KINDS)
    name = serializers.CharField()
    person_id = serializers.UUIDField(required=False, allow_null=True)
    organisation_id = serializers.UUIDField(required=False, allow_null=True)
    country = serializers.CharField(required=False, help_text="Country code; defaults to your own.")
    registration_number = serializers.CharField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    contact_email = serializers.CharField(required=False, allow_blank=True)
    specialities = serializers.ListField(child=serializers.CharField(), required=False)


class DocumentInput(serializers.Serializer):
    kind = serializers.CharField()
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class BldReasonInput(serializers.Serializer):
    reason = serializers.CharField()


class PanelRemovalInput(serializers.Serializer):
    finding = serializers.CharField(help_text="The finding a reviewer confirmed, e.g. evidence for work not done.")
    flag_id = serializers.UUIDField(required=False, allow_null=True, help_text="An upheld Tenmina Field flag.")


class ConflictLinkSerializer(serializers.ModelSerializer):
    inspector_id = serializers.UUIDField(read_only=True)
    contractor_id = serializers.UUIDField(read_only=True)
    inspector_name = serializers.CharField(source="inspector.name", read_only=True)
    contractor_name = serializers.CharField(source="contractor.name", read_only=True)

    class Meta:
        model = ConflictLink
        fields = ["id", "inspector_id", "inspector_name", "contractor_id", "contractor_name", "reason", "note",
                  "created_at"]


class ConflictLinkInput(serializers.Serializer):
    other_id = serializers.UUIDField(help_text="The contractor (for an inspector) or the inspector (for a "
                                               "contractor).")
    reason = serializers.ChoiceField(choices=ConflictLink.REASONS)
    note = serializers.CharField(required=False, allow_blank=True)


class PayeeLinkInput(serializers.Serializer):
    payee_id = serializers.UUIDField(required=False, allow_null=True, help_text="An existing payee in the registry.")
    legal_name = serializers.CharField(required=False)
    legal_name_evidence_id = serializers.UUIDField(required=False)
    bank_name = serializers.CharField(required=False)
    account_number = serializers.CharField(required=False)
    account_name = serializers.CharField(required=False, allow_blank=True)
    account_name_source = serializers.ChoiceField(choices=["bank_name_check", "bank_letter"], required=False)
    account_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    national_id_check_id = serializers.UUIDField(required=False, allow_null=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    contact_email = serializers.CharField(required=False, allow_blank=True)


class TrackRecordSerializer(serializers.Serializer):
    projects = serializers.IntegerField()
    projects_completed = serializers.IntegerField()
    milestones_paid = serializers.IntegerField()
    inspections = serializers.IntegerField()
    inspections_passed = serializers.IntegerField()
    inspections_failed = serializers.IntegerField()
    defects_recorded = serializers.IntegerField()
    removed = serializers.BooleanField()
    removal_finding = serializers.CharField()


# ----------------------------------------------------------------- projects

class MilestoneSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    amount = Money2("amount", "currency")
    guide_amount = Money2("guide_amount", "guide_currency")
    inspector_id = serializers.UUIDField(read_only=True, allow_null=True)
    accepts_submissions = serializers.SerializerMethodField()
    waiting_reason = serializers.SerializerMethodField()

    class Meta:
        model = Milestone
        fields = ["id", "project_id", "seq", "key", "name", "share_pct", "amount", "guide_amount", "status",
                  "prior_status", "freeze_kind", "inspector_id", "required_evidence", "checklist", "visit_required",
                  "submitted_at", "submissions", "fraud_flagged", "concerns", "return_reasons",
                  "evidence_checked_at", "inspected_at", "client_approved_at", "paid_at", "accepts_submissions",
                  "waiting_reason"]

    def get_accepts_submissions(self, obj) -> bool:
        from .milestones import submission_state

        return submission_state(obj)[0]

    def get_waiting_reason(self, obj) -> str:
        from .milestones import submission_state

        return submission_state(obj)[1]


class ProjectSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    client_id = serializers.UUIDField(read_only=True)
    asset_id = serializers.UUIDField(read_only=True, allow_null=True)
    contractor_id = serializers.UUIDField(read_only=True, allow_null=True)
    contractor_name = serializers.CharField(source="contractor.name", read_only=True, allow_null=True)
    inspector_id = serializers.UUIDField(read_only=True, allow_null=True)
    quantity_surveyor_id = serializers.UUIDField(read_only=True, allow_null=True)
    escrow_id = serializers.UUIDField(read_only=True, allow_null=True)
    budget = MoneyField(prefix="budget", read_only=True)
    guide_budget = Money2("guide_amount", "guide_currency")

    class Meta:
        model = Project
        fields = ["id", "type", "title", "description", "country", "status", "client_id", "asset_id", "report_id",
                  "contractor_id", "contractor_name", "inspector_id", "quantity_surveyor_id", "runner_name",
                  "budget", "guide_budget", "payment_route", "escrow_id", "offplan_case_id", "budget_approved_at",
                  "contract_signed_at", "handover_confirmed_at", "practical_completion_on", "defects_period_ends_on",
                  "started_at", "completed_at", "status_reason", "created_at"]


class ProjectDetailSerializer(ProjectSerializer):
    milestones = MilestoneSerializer(many=True, read_only=True)
    start_blockers = serializers.SerializerMethodField()

    class Meta(ProjectSerializer.Meta):
        fields = ProjectSerializer.Meta.fields + ["milestones", "start_blockers"]

    @extend_schema_field(BlockingReason(many=True))
    def get_start_blockers(self, obj):
        from .projects import start_blockers

        return start_blockers(obj) if obj.status == "setup" else []


class StageInput(serializers.Serializer):
    key = serializers.CharField(required=False)
    name = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    visit_required = serializers.BooleanField(required=False, default=True)


class SupplierInlineInput(serializers.Serializer):
    name = serializers.CharField()
    contact_name = serializers.CharField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    contact_email = serializers.CharField(required=False, allow_blank=True)
    bank_name = serializers.CharField(required=False, allow_blank=True)
    account_number = serializers.CharField(required=False, allow_blank=True)
    account_name = serializers.CharField(required=False, allow_blank=True)
    what_they_supply = serializers.CharField(required=False, allow_blank=True)


class ProjectInput(serializers.Serializer):
    type = serializers.ChoiceField(choices=["construction", "completion", "offplan", "funds"])
    title = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    asset_id = serializers.UUIDField(required=False, allow_null=True, help_text="The verified plot or building.")
    budget = MoneyIn(help_text="Your first estimate; the quantity surveyor's bill of quantities replaces it.")
    client_id = serializers.UUIDField(required=False, allow_null=True, help_text="Staff only: the client.")
    payment_route = serializers.ChoiceField(choices=["escrow", "client_direct"], required=False, allow_null=True)
    contractor_id = serializers.UUIDField(required=False, allow_null=True, help_text="Off-plan: the developer.")
    country = serializers.CharField(required=False, help_text="Project funds: the country code.")
    stages = StageInput(many=True, required=False, help_text="Project funds: stages that total the budget.")
    runner = serializers.DictField(required=False, help_text="Project funds: the person running it: "
                                                             "{person_id} or {name, phone, id_number}.")
    suppliers = SupplierInlineInput(many=True, required=False, help_text="Project funds: named suppliers.")


class BoqItemInput(serializers.Serializer):
    description = serializers.CharField()
    quantity = serializers.DecimalField(max_digits=14, decimal_places=3, required=False)
    unit = serializers.CharField(required=False, allow_blank=True)
    rate = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)


class SplitInput(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    share_pct = serializers.DecimalField(max_digits=5, decimal_places=2)


class BoqInput(serializers.Serializer):
    items = BoqItemInput(many=True)
    split = SplitInput(many=True, required=False, help_text="Defaults to the country's standard schedule.")
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    note = serializers.CharField(required=False, allow_blank=True)


class BoqSerializer(serializers.ModelSerializer):
    total = Money2("total_amount", "total_currency")
    evidence_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = BillOfQuantities
        fields = ["id", "version", "items", "split", "total", "status", "evidence_id", "accepted_at", "note",
                  "created_at"]


class MemberIdInput(serializers.Serializer):
    member_id = serializers.UUIDField()


class EvidenceIdsInput(serializers.Serializer):
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    note = serializers.CharField(required=False, allow_blank=True)


class RequiredEvidenceInput(serializers.Serializer):
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    note = serializers.CharField(required=False, allow_blank=True)


class ResumeInput(serializers.Serializer):
    contractor_id = serializers.UUIDField(required=False, allow_null=True)


class VariationSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    milestone_id = serializers.UUIDField(read_only=True)
    cost_change = MoneyField(prefix="cost_change", read_only=True)
    agreement_evidence_id = serializers.UUIDField(read_only=True, allow_null=True)

    class Meta:
        model = Variation
        fields = ["id", "project_id", "milestone_id", "description", "cost_change", "time_effect_days", "status",
                  "client_agreed_at", "contractor_agreed_at", "agreed_at", "decline_reason", "agreement_evidence_id",
                  "created_at"]


class VariationInput(serializers.Serializer):
    milestone_id = serializers.UUIDField()
    description = serializers.CharField()
    cost_change = MoneyIn()
    time_effect_days = serializers.IntegerField(required=False, default=0)


class VariationDecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["agree", "decline"])
    reason = serializers.CharField(required=False, allow_blank=True)


class DashboardSerializer(serializers.Serializer):
    """FR-BLD-009. Every money value is {amount, currency}."""

    project_id = serializers.UUIDField()
    title = serializers.CharField()
    type = serializers.CharField()
    status = serializers.CharField()
    route = serializers.CharField()
    budget = MoneyOut()
    guide_budget = MoneyOut(allow_null=True)
    variations_agreed = MoneyOut()
    paid = MoneyOut()
    remaining = MoneyOut()
    defect_value_held = MoneyOut()
    retention_held = MoneyOut()
    held_at_bank = MoneyOut(allow_null=True)
    defects_period_ends_on = serializers.DateField(allow_null=True)
    contractor = serializers.CharField(allow_null=True)
    inspector = serializers.CharField(allow_null=True)
    milestones = serializers.ListField(child=serializers.DictField())
    inspections = serializers.ListField(child=serializers.DictField())
    payments = serializers.ListField(child=serializers.DictField())
    photo_timeline = serializers.ListField(child=serializers.DictField())
    needs_action = serializers.BooleanField()
    funds = serializers.DictField(required=False, help_text="Project funds: suppliers, invoices, checks.")


# ----------------------------------------------------------------- milestones, inspections, defects

class EvidenceReviewInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "return"])
    reason = serializers.CharField(required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True)


class ScheduleInput(serializers.Serializer):
    inspector_id = serializers.UUIDField(required=False, allow_null=True)
    scheduled_for = serializers.DateField(required=False, allow_null=True)


class ClientApprovalInput(serializers.Serializer):
    confirm_amount = MoneyIn(required=False, allow_null=True, help_text="Required when the re-priced amount "
                                                                        "changed (RUL-18).")
    code = serializers.CharField(required=False, allow_blank=True, help_text="An authenticator code instead of a "
                                                                             "recent step-up.")


class RepriceSerializer(serializers.ModelSerializer):
    guide = Money2("guide_amount", "guide_currency")
    amount = Money2("local_amount", "local_currency")
    previous = Money2("previous_amount", "local_currency")
    changed = serializers.BooleanField(read_only=True)

    class Meta:
        model = Reprice
        fields = ["id", "guide", "amount", "previous", "changed", "rate", "rate_date", "shown_to_client_at",
                  "client_approved_at", "created_at"]


class InspectionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = InspectionItem
        fields = ["key", "label", "result", "note"]


class DefectSerializer(serializers.ModelSerializer):
    value = MoneyField(prefix="value", read_only=True)
    inspection_id = serializers.UUIDField(read_only=True)
    milestone_id = serializers.UUIDField(read_only=True, allow_null=True)
    project_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Defect
        fields = ["id", "inspection_id", "milestone_id", "project_id", "description", "value", "status",
                  "photo_evidence_ids", "closing_evidence_ids", "fixed_at", "closed_at", "note"]


class InspectionSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    milestone_id = serializers.UUIDField(read_only=True, allow_null=True)
    inspector_id = serializers.UUIDField(read_only=True, allow_null=True)
    inspector_name = serializers.CharField(source="inspector.name", read_only=True, allow_null=True)
    defect_value = Money2("defect_value", "defect_currency")
    items = InspectionItemSerializer(many=True, read_only=True)
    defects = DefectSerializer(many=True, read_only=True)
    independence_statement = serializers.SerializerMethodField()

    class Meta:
        model = Inspection
        fields = ["id", "project_id", "milestone_id", "kind", "order_id", "concern", "inspector_id",
                  "inspector_name", "scheduled_for", "checklist", "status", "outcome", "defect_value", "reason",
                  "note", "needs_review", "declared_no_link_at", "recorded_at", "items", "defects",
                  "independence_statement"]

    def get_independence_statement(self, obj) -> str:
        return "You have no link to this contractor."


class DeclarationInput(serializers.Serializer):
    has_link = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True)


class ConfirmInput(serializers.Serializer):
    confirm = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True)


class ExtraAssignInput(serializers.Serializer):
    inspector_id = serializers.UUIDField()
    scheduled_for = serializers.DateField()


# ----------------------------------------------------------------- payments

class ProjectPaymentSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    milestone_id = serializers.UUIDField(read_only=True, allow_null=True)
    amount = Money2("amount", "currency")
    holdback = Money2("holdback_amount", "currency")
    payee = serializers.SerializerMethodField()
    instruction_id = serializers.UUIDField(read_only=True, allow_null=True)
    reprice = RepriceSerializer(read_only=True, allow_null=True)
    pay_to = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ["id", "project_id", "milestone_id", "part", "subject_type", "subject_id", "label", "amount",
                  "holdback", "payee", "route", "status", "instruction_id", "reprice", "client_approved_at",
                  "release_approved_at", "client_paid_at", "client_paid_reference", "paid_at", "bank_reference",
                  "closed_reason", "pay_to", "created_at"]

    def get_payee(self, obj) -> dict:
        p = obj.payee
        return {"id": str(p.pk), "name": p.legal_name, "account_name": p.account_name, "bank_name": p.bank_name,
                "account_last4": p.account_number[-4:], "verified": p.verification_status == "verified"}

    def get_pay_to(self, obj) -> dict | None:
        """client_direct only, once two staff confirmed: the account the client pays from their own bank."""
        req = self.context.get("request")
        if obj.route != "client_direct" or obj.status != "release_approved" or req is None \
                or req.user.pk != obj.project.client_id:
            return None
        p = obj.payee
        return {"account_name": p.account_name, "bank_name": p.bank_name, "account_number": p.account_number,
                "amount": f"{obj.amount:.2f}", "currency": obj.currency, "reference": f"TNM-{str(obj.pk)[-8:]}"}


class StaffDecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    note = serializers.CharField(required=False, allow_blank=True)


class ClientPaymentInput(serializers.Serializer):
    reference = serializers.CharField()
    evidence_id = serializers.UUIDField(required=False, allow_null=True)


class ReceiptInput(serializers.Serializer):
    evidence_id = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True)


class MaterialsInput(serializers.Serializer):
    milestone_id = serializers.UUIDField()
    supplier_payee_id = serializers.UUIDField()
    description = serializers.CharField()
    amount = MoneyIn()
    items = serializers.ListField(child=serializers.DictField(), required=False)
    quote_evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class MaterialsOrderSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    milestone_id = serializers.UUIDField(read_only=True)
    supplier = serializers.CharField(source="supplier_payee.legal_name", read_only=True)
    amount = Money2("amount", "currency")

    class Meta:
        model = MaterialsOrder
        fields = ["id", "project_id", "milestone_id", "supplier", "description", "items", "amount", "status",
                  "delivered_at", "delivery_evidence_ids", "created_at"]
