"""TSK API shapes. Money is {"amount", "currency"} (7.1)."""
from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from core.money import MoneyField as _MoneyField


@extend_schema_field({"type": "object", "nullable": True, "properties": {
    "amount": {"type": "string", "example": "150.00"}, "currency": {"type": "string", "example": "GHS"}}})
class MoneyField(_MoneyField):
    """core.money.MoneyField with its OpenAPI shape."""

from .models import Agent, Errand, ErrandDocument, ErrandStep, Handover


class ErrandMoney(serializers.Serializer):
    amount = serializers.CharField(allow_null=True)
    currency = serializers.CharField()


class ErrandChecklistEntry(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    required = serializers.BooleanField()
    hint = serializers.CharField(allow_blank=True)


class ErrandCatalogueStep(serializers.Serializer):
    seq = serializers.IntegerField()
    key = serializers.CharField()
    description = serializers.CharField()
    official_fee = serializers.CharField()
    documents = serializers.ListField(child=serializers.CharField())


class CatalogueItemSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()
    agency = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)
    checklist = ErrandChecklistEntry(many=True)
    official_fees = ErrandMoney()
    tenmina_charge = ErrandMoney()
    target_days = serializers.IntegerField(allow_null=True)
    steps = ErrandCatalogueStep(many=True)
    orderable = serializers.BooleanField()
    problems = serializers.ListField(child=serializers.CharField())


class CatalogueSerializer(serializers.Serializer):
    country = serializers.CharField()
    items = CatalogueItemSerializer(many=True)


class ErrandDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrandDocument
        fields = ["key", "label", "required", "status", "reject_reason", "evidence", "uploaded_at", "reviewed_at"]


class ErrandStepSerializer(serializers.ModelSerializer):
    official_fee = MoneyField(prefix="official_fee")
    has_receipt = serializers.SerializerMethodField()
    has_acknowledgement = serializers.SerializerMethodField()
    plain = serializers.SerializerMethodField()

    class Meta:
        model = ErrandStep
        fields = ["id", "seq", "key", "description", "official_fee", "status", "plain", "has_acknowledgement",
                  "has_receipt", "acknowledgement_evidence", "receipt_evidence", "release_instruction_id",
                  "needs_documents", "started_at", "paid_at", "done_at"]

    def get_has_receipt(self, obj) -> bool:
        return obj.receipt_evidence_id is not None

    def get_has_acknowledgement(self, obj) -> bool:
        return obj.acknowledgement_evidence_id is not None

    def get_plain(self, obj) -> str:
        return {"pending": "Not started.", "in_progress": "The agent is working on it.",
                "fee_instructed": "The official fee is being paid to the agency by the bank.",
                "fee_paid": "The agency was paid. Waiting for its receipt.",
                "receipted": "The agency's receipt is in.", "done": "Done.",
                "blocked": f"Blocked: {obj.blocked_reason}"}.get(obj.status, obj.status)


class ErrandHandoverSerializer(serializers.ModelSerializer):
    class Meta:
        model = Handover
        fields = ["id", "method", "receiver_name", "receiver_person", "receiver_family_member", "courier_name",
                  "tracking_reference", "proof_kind", "evidence", "recorded_by", "handed_at", "confirmed_at",
                  "confirmed_via"]


class ErrandAgentBrief(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(source="person.full_name")


class ErrandPayeeBrief(serializers.Serializer):
    id = serializers.UUIDField()
    legal_name = serializers.CharField()
    kind = serializers.CharField()
    last4 = serializers.CharField()


class ErrandSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    official_fees = MoneyField(prefix="official_fees")
    tenmina_charge = MoneyField(prefix="tenmina_charge")
    documents = ErrandDocumentSerializer(many=True, read_only=True)
    steps = ErrandStepSerializer(many=True, read_only=True)
    agent = ErrandAgentBrief(read_only=True, allow_null=True)
    agency_payee = ErrandPayeeBrief(read_only=True, allow_null=True)
    handover = serializers.SerializerMethodField()
    status_text = serializers.SerializerMethodField()
    blocking_reasons = serializers.SerializerMethodField()

    class Meta:
        model = Errand
        fields = ["id", "reference", "status", "status_text", "blocking_reasons", "name", "catalogue_key",
                  "catalogue_version", "client", "for_family_member", "official_fees", "tenmina_charge",
                  "fee_order_id", "fee_paid_at", "escrow", "agent", "agency_payee", "agency_approved_at",
                  "target_days", "submitted_at", "due_on", "documents", "steps", "result_evidence",
                  "result_uploaded_at", "result_checked_at", "result_note", "completed_at", "handover",
                  "handed_over_at", "cancel_reason", "notes", "created_at"]

    def get_name(self, obj) -> str:
        return obj.item.get("name") or obj.catalogue_key

    def get_handover(self, obj) -> ErrandHandoverSerializer(allow_null=True):
        h = getattr(obj, "handover", None)
        return ErrandHandoverSerializer(h).data if h else None

    def get_status_text(self, obj) -> str:
        from .services import status_text

        return status_text(obj)

    def get_blocking_reasons(self, obj) -> serializers.ListField(child=serializers.DictField()):
        from .services import funding_blockers

        return funding_blockers(obj) if obj.status in ("ordered", "documents_pending") else []


class FieldErrandSerializer(ErrandSerializer):
    """The agent's view: steps, the documents the steps need, no client contact details or money held."""

    documents = serializers.SerializerMethodField()

    class Meta(ErrandSerializer.Meta):
        fields = ["id", "reference", "status", "name", "agency_payee", "steps", "documents", "due_on",
                  "result_uploaded_at", "result_note", "handover"]

    def get_documents(self, obj) -> ErrandDocumentSerializer(many=True):
        keys = set()
        for s in obj.steps.exclude(status="done"):
            keys.update(s.needs_documents or [])
        return ErrandDocumentSerializer(obj.documents.filter(key__in=keys).exclude(status="deleted"), many=True).data


class ErrandCreateInput(serializers.Serializer):
    code = serializers.CharField()
    country = serializers.CharField(required=False, help_text="Defaults to the client's home country")
    for_family_member_id = serializers.UUIDField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    client_id = serializers.UUIDField(required=False, help_text="Staff ordering for a client")


class DocumentUploadInput(serializers.Serializer):
    file = serializers.FileField(required=False)
    evidence_id = serializers.UUIDField(required=False)


class DocumentReviewInput(serializers.Serializer):
    accept = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True)


class ErrandSubmitInput(serializers.Serializer):
    terms_version = serializers.CharField()
    scope_version = serializers.CharField()


class PaymentRoutesSerializer(serializers.Serializer):
    tenmina_charge = serializers.DictField()
    official_fees = serializers.DictField()
    blocking_reasons = serializers.ListField(child=serializers.DictField())


class ErrandAssignInput(serializers.Serializer):
    agent_id = serializers.UUIDField()
    agency_payee_id = serializers.UUIDField(required=False, allow_null=True)


class ErrandStandingApprovalInput(serializers.Serializer):
    monthly_max = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    code = serializers.CharField(required=False)


class ErrandInstructionResult(serializers.Serializer):
    instruction_id = serializers.UUIDField()
    status = serializers.CharField()
    amount = serializers.DictField()
    payee = serializers.CharField()
    client_approval = serializers.CharField()


class ResultCheckInput(serializers.Serializer):
    accept = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True)


class ErrandHandoverInput(serializers.Serializer):
    method = serializers.ChoiceField(choices=Handover.METHODS)
    proof_kind = serializers.ChoiceField(choices=Handover.PROOFS)
    evidence_id = serializers.UUIDField(required=False)
    file = serializers.FileField(required=False)
    receiver_person_id = serializers.UUIDField(required=False, allow_null=True)
    family_member_id = serializers.UUIDField(required=False, allow_null=True)
    receiver_name = serializers.CharField(required=False, allow_blank=True)
    courier_name = serializers.CharField(required=False, allow_blank=True)
    tracking_reference = serializers.CharField(required=False, allow_blank=True)


class ErrandReasonInput(serializers.Serializer):
    reason = serializers.CharField()


class AgentSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="person.full_name", read_only=True)
    vetting = serializers.SerializerMethodField()
    blocking_reasons = serializers.SerializerMethodField()
    open_errands = serializers.SerializerMethodField()

    class Meta:
        model = Agent
        fields = ["id", "country", "person", "name", "vetting", "agency_org", "pro_agreement_id", "status",
                  "status_reason", "blocking_reasons", "open_errands", "created_at"]

    def get_vetting(self, obj) -> dict:
        v = obj.vetting
        return {"id": str(v.pk), "status": v.status,
                "valid_until": v.valid_until.isoformat() if v.valid_until else None}

    def get_blocking_reasons(self, obj) -> serializers.ListField(child=serializers.DictField()):
        from .services import agent_blockers

        return agent_blockers(obj)

    def get_open_errands(self, obj) -> int:
        return obj.errands.filter(status__in=["assigned", "in_progress", "result_uploaded"]).count()


class AgentInput(serializers.Serializer):
    person_id = serializers.UUIDField()
    vetting_id = serializers.UUIDField(required=False)
    agency_org_id = serializers.UUIDField(required=False, allow_null=True)
    pro_agreement_id = serializers.UUIDField(required=False, allow_null=True)


class AgentUpdateInput(serializers.Serializer):
    agency_org_id = serializers.UUIDField(required=False, allow_null=True)
    pro_agreement_id = serializers.UUIDField(required=False, allow_null=True)


class StepProofInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["acknowledgement", "receipt"])
    evidence_id = serializers.UUIDField()


class ErrandResultInput(serializers.Serializer):
    evidence_id = serializers.UUIDField()


class ErrandDocumentLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_at = serializers.CharField()
