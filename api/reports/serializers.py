"""RPT API shapes."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import AnonymisedCopy, Condition, Incident, Recheck, RecheckDraw, Report, Section, Signature


class SignatureSerializer(serializers.ModelSerializer):
    valid = serializers.SerializerMethodField()

    class Meta:
        model = Signature
        fields = ["id", "role", "signer", "signer_name", "licence_number", "licence_body", "signed_at",
                  "content_sha256", "invalidated_at", "invalidated_reason", "valid"]

    @extend_schema_field(serializers.BooleanField())
    def get_valid(self, obj):
        from .services import valid_signature

        return obj.invalidated_at is None and valid_signature(obj.section) is not None


class SectionSerializer(serializers.ModelSerializer):
    signatures = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Section
        fields = ["id", "number", "label", "position", "key", "title", "owner_role", "locked", "in_verdict_rule",
                  "needs_signature", "findings", "verdict", "proposed_verdict", "proposed_reasons", "edited_at",
                  "signatures", "can_edit"]

    @extend_schema_field(SignatureSerializer(many=True))
    def get_signatures(self, obj):
        return SignatureSerializer(obj.signatures.order_by("signed_at"), many=True).data

    @extend_schema_field(serializers.BooleanField())
    def get_can_edit(self, obj):
        from .services import can_edit_section

        req = self.context.get("request")
        return bool(req and obj.report.status == "draft" and can_edit_section(req.user, obj.report, obj))


class ConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condition
        fields = ["id", "position", "key", "text", "responsible", "closing_evidence", "release_part", "created_at"]


class ReportSerializer(serializers.ModelSerializer):
    case_reference = serializers.CharField(source="case.reference", read_only=True)
    scope_version = serializers.IntegerField(source="scope_text_version.version", read_only=True)
    template_version_number = serializers.IntegerField(source="template_version.version", read_only=True)

    class Meta:
        model = Report
        fields = ["id", "reference", "case", "case_reference", "version", "status", "overall_verdict",
                  "template_version", "template_version_number", "scope_text_version", "scope_version",
                  "submitted_at", "released_at", "pdf_sha256", "supersedes", "correction_reason", "release_error",
                  "created_at", "row_version"]


class ReportDetailSerializer(ReportSerializer):
    sections = serializers.SerializerMethodField()
    conditions = ConditionSerializer(many=True, read_only=True)
    allowed_verdicts = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()

    class Meta(ReportSerializer.Meta):
        fields = ReportSerializer.Meta.fields + ["sections", "conditions", "allowed_verdicts", "approvals"]

    @extend_schema_field(SectionSerializer(many=True))
    def get_sections(self, obj):
        return SectionSerializer(obj.sections.order_by("position"), many=True, context=self.context).data

    @extend_schema_field(serializers.DictField())
    def get_allowed_verdicts(self, obj):
        from .services import allowed_verdicts

        allowed, reasons = allowed_verdicts(obj)
        return {"allowed": allowed, "reasons": reasons}

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_approvals(self, obj):
        req = obj.approval_request
        if req is None:
            return []
        return [{"slot": a.slot, "approver": str(a.approver_id), "decision": a.decision, "at": a.approved_at}
                for a in req.approvals.order_by("approved_at")]


class ClientReportSerializer(ReportSerializer):
    """What a client or representative sees: the released version, its verdict and the hash."""

    conditions = ConditionSerializer(many=True, read_only=True)

    class Meta(ReportSerializer.Meta):
        fields = ["id", "reference", "case", "case_reference", "version", "status", "overall_verdict",
                  "released_at", "pdf_sha256", "supersedes", "correction_reason", "scope_version", "conditions"]


class SectionInput(serializers.Serializer):
    findings = serializers.DictField(required=False)
    verdict = serializers.ChoiceField(choices=["red", "amber", "green"], required=False, allow_null=True)
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class VerdictInput(serializers.Serializer):
    overall_verdict = serializers.ChoiceField(choices=["red", "amber", "green"])


class ConditionInput(serializers.Serializer):
    text = serializers.CharField()
    responsible = serializers.ChoiceField(choices=Condition.RESPONSIBLE)
    closing_evidence = serializers.CharField()
    key = serializers.CharField(required=False, allow_blank=True)


class ApprovalInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "return"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True)


class CorrectionInput(serializers.Serializer):
    reason = serializers.CharField()
    incident_id = serializers.UUIDField(required=False)


class SkipInput(serializers.Serializer):
    reason = serializers.CharField()


class PdfLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
    expires_at = serializers.DateTimeField()
    sha256 = serializers.CharField()
    content_type = serializers.CharField()


class VerificationInput(serializers.Serializer):
    reference = serializers.CharField()
    sha256 = serializers.CharField(required=False)
    file = serializers.FileField(required=False)


class VerificationResultSerializer(serializers.Serializer):
    match = serializers.BooleanField()
    released_on = serializers.DateField(allow_null=True)
    superseded = serializers.BooleanField()


class AnonymisedCopySerializer(serializers.ModelSerializer):
    class Meta:
        model = AnonymisedCopy
        fields = ["id", "report", "evidence", "consent_id", "removed", "created_at"]


class RecheckSerializer(serializers.ModelSerializer):
    case_reference = serializers.CharField(source="case.reference", read_only=True)

    class Meta:
        model = Recheck
        fields = ["id", "draw", "subject_type", "subject_id", "case", "case_reference", "report", "assignee",
                  "assignee_role", "assigned_at", "due_at", "status", "result", "findings", "result_at", "incident",
                  "skip_reason", "carried_from"]


class RecheckDrawSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)

    class Meta:
        model = RecheckDraw
        fields = ["id", "country", "sample_month", "sample_pct", "population_count", "population_sha256", "seed",
                  "selected_count", "method", "drawn_at"]


class RecheckMonthSerializer(serializers.Serializer):
    draw = RecheckDrawSerializer(allow_null=True)
    items = RecheckSerializer(many=True)
    summary = serializers.DictField()


class DrawInput(serializers.Serializer):
    month = serializers.DateField()
    country = serializers.CharField(default="GH")


class AssignInput(serializers.Serializer):
    person_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=["LW", "SV"])


class RecheckCandidateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    role = serializers.CharField()
    licence_number = serializers.CharField()
    licence_expires_on = serializers.DateField()


class ResultInput(serializers.Serializer):
    result = serializers.ChoiceField(choices=Recheck.RESULTS)
    findings = serializers.CharField(required=False, allow_blank=True)


class IncidentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Incident
        fields = ["id", "case", "recheck", "report", "condition_id", "kind", "summary", "owner", "correction_report",
                  "client_notified_at", "status", "closure_note", "closed_at", "created_at"]


class CloseInput(serializers.Serializer):
    note = serializers.CharField()
