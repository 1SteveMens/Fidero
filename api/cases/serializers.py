"""CASE API shapes. Clients see the tracker (status messages, requests, messages); staff and assigned
professionals also see tasks. Nothing from the safety log appears outside its own endpoint."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (Case, CostItem, DocumentRequest, Message, Party, RiskScreen, SafetyIncident, SafetyReader,
                     SearchCopyCheck, SearchRequest, StatusMessage, Task)


@extend_schema_field({"type": "object", "nullable": True, "properties": {"id": {"type": "string", "format": "uuid"},
                                                                       "name": {"type": "string"}}})
class PersonRefField(serializers.Field):
    def to_representation(self, p):
        return None if p is None else {"id": str(p.pk), "name": p.full_name}


class StatusMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatusMessage
        fields = ["id", "template_key", "text", "message_date", "next_expected_date", "created_at"]


class TaskSerializer(serializers.ModelSerializer):
    case_reference = serializers.CharField(source="case.reference", read_only=True)
    assignee = PersonRefField(read_only=True)
    second_assignee = PersonRefField(read_only=True)
    waiting_for = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    missing_evidence = serializers.SerializerMethodField()
    notice = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = ["id", "case", "case_reference", "step_key", "title", "position", "owner_role", "assignee",
                  "second_assignee", "assigned_at", "due_at", "due_change_reason", "required_evidence", "depends_on",
                  "waiting_for", "site_visit", "search_kind", "review_step", "status", "completed_at", "is_overdue",
                  "missing_evidence", "notice", "row_version"]

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_waiting_for(self, obj):
        from .services import waiting_for

        return waiting_for(obj)

    @extend_schema_field(serializers.BooleanField())
    def get_is_overdue(self, obj):
        from django.utils import timezone

        return obj.status in ("open", "in_progress") and obj.due_at < timezone.now()

    @extend_schema_field(serializers.ListField(child=serializers.CharField()))
    def get_missing_evidence(self, obj):
        from .services import missing_evidence

        return missing_evidence(obj) if obj.status in ("open", "in_progress") else []

    @extend_schema_field(serializers.CharField())
    def get_notice(self, obj):
        from .templates import SEARCH_NOTICE

        return SEARCH_NOTICE if (obj.site_visit or obj.search_kind) else ""


class ClientStepSerializer(serializers.ModelSerializer):
    """The client's view of a step: no names, no evidence."""

    class Meta:
        model = Task
        fields = ["step_key", "title", "status", "due_at", "completed_at"]


class DocumentRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentRequest
        fields = ["id", "case", "title", "description", "due_on", "status", "received_at", "received_evidence",
                  "created_at"]


class MessageSerializer(serializers.ModelSerializer):
    sender = PersonRefField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "side", "sender", "body", "created_at"]


class CaseSerializer(serializers.ModelSerializer):
    client = PersonRefField(read_only=True)
    case_manager = PersonRefField(read_only=True)
    country = serializers.CharField(source="country.code", read_only=True)
    template_version = serializers.IntegerField(source="template_version.version", read_only=True)
    template_version_id = serializers.UUIDField(read_only=True)
    latest_status = serializers.SerializerMethodField()

    class Meta:
        model = Case
        fields = ["id", "reference", "country", "title", "product_line", "status", "order", "asset", "client",
                  "subject_type", "subject_id", "case_manager", "template_version", "template_version_id",
                  "risk_flag", "hold_reason", "outcome", "accepted_at", "closed_at", "latest_status", "created_at",
                  "row_version"]

    @extend_schema_field(StatusMessageSerializer(allow_null=True))
    def get_latest_status(self, obj):
        m = obj.status_messages.order_by("-created_at").first()
        return StatusMessageSerializer(m).data if m else None


class CaseDetailSerializer(CaseSerializer):
    status_messages = StatusMessageSerializer(many=True, read_only=True)
    steps = serializers.SerializerMethodField()
    tasks = serializers.SerializerMethodField()
    document_requests = DocumentRequestSerializer(many=True, read_only=True)
    reports = serializers.SerializerMethodField()

    class Meta(CaseSerializer.Meta):
        fields = CaseSerializer.Meta.fields + ["status_messages", "steps", "tasks", "document_requests", "reports",
                                               "parent_case", "cancel_reason", "refund_decision", "outcome_note"]

    @extend_schema_field(ClientStepSerializer(many=True))
    def get_steps(self, obj):
        return ClientStepSerializer(obj.tasks.exclude(status="cancelled"), many=True).data

    @extend_schema_field(TaskSerializer(many=True, allow_null=True))
    def get_tasks(self, obj):
        from . import services

        user = self.context["request"].user
        if services.is_case_staff(user, obj):
            return TaskSerializer(obj.tasks.all(), many=True).data
        if services.is_assigned(user, obj):
            from django.db.models import Q

            return TaskSerializer(obj.tasks.filter(Q(assignee=user) | Q(second_assignee=user)), many=True).data
        return None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_reports(self, obj):
        user = self.context["request"].user
        from . import services

        staff_or_pro = services.is_case_staff(user, obj) or services.is_assigned(user, obj)
        out = []
        for r in obj.reports.order_by("version"):
            if not staff_or_pro and r.status not in ("released", "superseded"):
                continue
            out.append({"id": str(r.pk), "reference": r.reference, "version": r.version, "status": r.status,
                        "released_at": r.released_at})
        return out


class OpenCaseInput(serializers.Serializer):
    order_id = serializers.UUIDField()


class ReasonInput(serializers.Serializer):
    reason = serializers.CharField()
    client_message = serializers.CharField(required=False, allow_blank=True)


class CancelInput(serializers.Serializer):
    reason = serializers.CharField()
    refund_decision = serializers.ChoiceField(choices=["refund", "no_refund"])
    refund_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)


class DecisionInput(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["verified", "not_verified"])
    note = serializers.CharField(required=False, allow_blank=True)


class TaskUpdateInput(serializers.Serializer):
    assignee_id = serializers.UUIDField(required=False, allow_null=True)
    second_assignee_id = serializers.UUIDField(required=False, allow_null=True)
    due_at = serializers.DateTimeField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)


class CompleteInput(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class EvidenceInput(serializers.Serializer):
    kind = serializers.CharField()
    evidence_id = serializers.UUIDField(required=False)
    file = serializers.FileField(required=False)


class TaskEvidenceLinkSerializer(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    kind = serializers.CharField()
    sha256 = serializers.CharField()


class DocumentRequestInput(serializers.Serializer):
    title = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    due_on = serializers.DateField(required=False, allow_null=True)


class DocumentResponseInput(serializers.Serializer):
    evidence_id = serializers.UUIDField(required=False)
    file = serializers.FileField(required=False)


class MessageInput(serializers.Serializer):
    body = serializers.CharField()


class RiskScreenSerializer(serializers.ModelSerializer):
    screened_by = PersonRefField(read_only=True)

    class Meta:
        model = RiskScreen
        fields = ["id", "case", "task", "screened_by", "outcome", "hazards", "people_required", "disputed_at_screen",
                  "valid_until", "notes", "created_at"]


class RiskScreenInput(serializers.Serializer):
    task_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=RiskScreen.OUTCOMES)
    hazards = serializers.CharField(required=False, allow_blank=True)
    people_required = serializers.IntegerField(required=False, min_value=1, default=1)
    valid_days = serializers.IntegerField(required=False, min_value=1, max_value=90)
    notes = serializers.CharField(required=False, allow_blank=True)


class SafetyIncidentInput(serializers.Serializer):
    occurred_at = serializers.DateTimeField(required=False)
    severity = serializers.ChoiceField(choices=SafetyIncident.SEVERITIES)
    narrative = serializers.CharField()
    persons_named = serializers.CharField(required=False, allow_blank=True)
    location_note = serializers.CharField(required=False, allow_blank=True)


class SafetyIncidentLoggedSerializer(serializers.Serializer):
    """Write only: the reporter gets a receipt, not the log."""

    id = serializers.UUIDField()
    logged_at = serializers.DateTimeField()
    message = serializers.CharField()


class SafetyIncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafetyIncident
        fields = ["id", "case_id", "country_code", "subject_type", "subject_id", "reported_by", "occurred_at",
                  "severity", "narrative", "persons_named", "location_note", "created_at"]


class SafetyReaderSerializer(serializers.ModelSerializer):
    person = PersonRefField(read_only=True)
    country = serializers.CharField(source="country.code", read_only=True, allow_null=True)

    class Meta:
        model = SafetyReader
        fields = ["id", "person", "country", "reason", "created_at", "revoked_at"]


class SafetyReaderInput(serializers.Serializer):
    person_id = serializers.UUIDField()
    country = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class CostItemSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()

    class Meta:
        model = CostItem
        fields = ["id", "item_type", "amount", "incurred_on", "description", "source", "source_id", "created_at"]

    @extend_schema_field(serializers.DictField())
    def get_amount(self, obj):
        return {"amount": f"{obj.amount:.2f}", "currency": obj.currency}


class CostInput(serializers.Serializer):
    item_type = serializers.ChoiceField(choices=CostItem.ITEM_TYPES)
    amount = serializers.DictField()
    incurred_on = serializers.DateField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)


class CostSummarySerializer(serializers.Serializer):
    items = CostItemSerializer(many=True)
    by_item = serializers.DictField()
    totals = serializers.DictField()


class CostPerReportSerializer(serializers.Serializer):
    reports = serializers.IntegerField()
    totals = serializers.DictField()
    per_report = serializers.DictField()


class PartySerializer(serializers.ModelSerializer):
    check = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = ["id", "case", "role", "name", "person", "for_organisation", "organisation_name", "status",
                  "removed_reason", "national_id_check", "check", "created_at"]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_check(self, obj):
        c = obj.national_id_check
        if c is None:
            return None
        return {"result": c.result, "channel": c.channel, "reference": c.provider_reference,
                "checked_at": c.checked_at}


class PartyInput(serializers.Serializer):
    role = serializers.ChoiceField(choices=Party.ROLES)
    name = serializers.CharField()
    person_id = serializers.UUIDField(required=False)
    for_organisation_id = serializers.UUIDField(required=False)
    organisation_name = serializers.CharField(required=False, allow_blank=True)
    id_number = serializers.CharField(required=False, allow_blank=True)
    national_id_check_id = serializers.UUIDField(required=False)
    adapter = serializers.ChoiceField(choices=["api", "staff_portal"], required=False, default="api")


class PartyCheckInput(serializers.Serializer):
    id_number = serializers.CharField()
    adapter = serializers.ChoiceField(choices=["api", "staff_portal"], required=False, default="api")


class RemovalInput(serializers.Serializer):
    reason = serializers.CharField()


class SearchRequestSerializer(serializers.ModelSerializer):
    submitted_by = PersonRefField(read_only=True)
    result_received_by = PersonRefField(read_only=True)
    confirmed_by = PersonRefField(read_only=True)
    registry = serializers.CharField(source="registry_partner.name", read_only=True)
    usable = serializers.BooleanField(read_only=True)

    class Meta:
        model = SearchRequest
        fields = ["id", "case", "task", "registry_partner", "registry", "channel", "tenmina_account_ref",
                  "submitted_by", "submitted_at", "registry_reference", "search_on", "result_evidence",
                  "result_received_by", "result_received_at", "registry_result_date", "result_summary",
                  "confirmed_by", "confirmed_with", "confirmed_at", "status", "rejected_reason", "usable"]


class SearchSubmitInput(serializers.Serializer):
    task_id = serializers.UUIDField()
    channel = serializers.ChoiceField(choices=SearchRequest.CHANNELS)
    tenmina_account_ref = serializers.CharField()
    registry_reference = serializers.CharField(required=False, allow_blank=True)
    submitted_at = serializers.DateTimeField(required=False)
    search_on = serializers.CharField(required=False, allow_blank=True)
    registry_partner_id = serializers.UUIDField(required=False)


class SearchResultInput(serializers.Serializer):
    registry_result_date = serializers.DateField()
    registry_reference = serializers.CharField(required=False, allow_blank=True)
    summary = serializers.CharField(required=False, allow_blank=True)
    evidence_id = serializers.UUIDField(required=False)
    file = serializers.FileField(required=False)
    confirmed_with = serializers.CharField(required=False, allow_blank=True)
    confirmed_at = serializers.DateTimeField(required=False)


class SearchConfirmInput(serializers.Serializer):
    confirmed_with = serializers.CharField()
    confirmed_at = serializers.DateTimeField()


class CopyCompareInput(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    matches = serializers.BooleanField()
    note = serializers.CharField(required=False, allow_blank=True)


class CopyCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = SearchCopyCheck
        fields = ["id", "search_request", "evidence", "matches", "note", "created_at"]


class FreshSearchInput(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)
