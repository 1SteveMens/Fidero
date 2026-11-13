from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from accounts.models import Person
from accounts.serializers import DecisionSerializer, PersonSummarySerializer, ReasonSerializer  # noqa: F401
from countries.models import Country
from evidence.models import Evidence

from .models import (DATA_CLASSES, BulkExport, Consent, DataCatalogueEntry, DataLocation, DataRequest, LegalHold,
                     PrivacyAcceptance, PrivacyNotice, RetentionRule, RetentionRun)
from .services import EXPORT_FIELDS

CountryCode = lambda **kw: serializers.SlugRelatedField(slug_field="code", queryset=Country.objects.all(), **kw)  # noqa: E731


class PrivacyNoticeSerializer(serializers.ModelSerializer):
    country = CountryCode(required=False, allow_null=True)

    class Meta:
        model = PrivacyNotice
        validators = []  # uniqueness is checked in services and the database
        fields = ["id", "country", "version", "title", "summary", "text", "status", "published_at"]
        read_only_fields = ["id", "status", "published_at"]


class AcceptNoticeSerializer(serializers.Serializer):
    version = serializers.CharField()


class PrivacyAcceptanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrivacyAcceptance
        fields = ["id", "version", "accepted_at", "source"]


class ConsentSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = Consent
        fields = ["id", "country", "person", "subject_name", "purpose", "text_version", "partner_client_id",
                  "report_id", "case_id", "recording_evidence", "role_in_recording", "given_at", "withdrawn_at",
                  "recorded_by"]
        read_only_fields = fields


class GiveConsentSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=["partner_status", "partner_full_report", "case_study", "marketing"])
    text_version = serializers.CharField(default="1")
    partner_client_id = serializers.UUIDField(required=False, allow_null=True)
    report_id = serializers.UUIDField(required=False, allow_null=True)
    case_id = serializers.UUIDField(required=False, allow_null=True)


class VideoConsentSerializer(serializers.Serializer):
    subject_name = serializers.CharField(required=False, allow_blank=True, default="")
    person = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all(), required=False, allow_null=True)
    subject_phone = serializers.CharField(required=False, allow_blank=True, default="")
    recording_evidence = serializers.PrimaryKeyRelatedField(queryset=Evidence.objects.all())
    text_version = serializers.CharField()
    case_id = serializers.UUIDField(required=False, allow_null=True)
    role_in_recording = serializers.CharField(required=False, allow_blank=True, default="")


class RecordingLinkSerializer(serializers.Serializer):
    evidence = serializers.PrimaryKeyRelatedField(queryset=Evidence.objects.all())
    case_id = serializers.UUIDField()


class RecordingLinkResultSerializer(serializers.Serializer):
    evidence = serializers.UUIDField()
    case_id = serializers.UUIDField()
    role = serializers.CharField()


class DataRequestSerializer(serializers.ModelSerializer):
    subject = PersonSummarySerializer(read_only=True)
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    overdue = serializers.SerializerMethodField()

    class Meta:
        model = DataRequest
        fields = ["id", "country", "subject", "requested_by", "type", "source", "details", "due_on", "overdue",
                  "status", "export_evidence", "export_sha256", "corrections", "kept_statement", "open_matters",
                  "completed_at", "completed_by", "rejection_reason", "created_at"]
        read_only_fields = fields

    def get_overdue(self, obj) -> bool:
        from django.utils import timezone

        return obj.status in ("open", "in_progress") and obj.due_on < timezone.localdate()


class CreateDataRequestSerializer(serializers.Serializer):
    subject = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all(), required=False)
    type = serializers.ChoiceField(choices=["access", "correction", "erasure"])
    details = serializers.CharField(required=False, allow_blank=True, default="")


class CorrectionSerializer(serializers.Serializer):
    field = serializers.ChoiceField(choices=["full_name", "email", "phone", "preferred_language",
                                             "residence_country"])
    value = serializers.CharField(allow_blank=True)


class KeptItemSerializer(serializers.Serializer):
    data_class = serializers.CharField()
    what = serializers.CharField(allow_blank=True)
    why = serializers.CharField(allow_blank=True)
    until = serializers.CharField()


class OpenMatterSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField()
    reason = serializers.CharField(allow_blank=True)


class DeletionPreviewSerializer(serializers.Serializer):
    deleted = serializers.ListField(child=serializers.CharField())
    kept = KeptItemSerializer(many=True)
    open_matters = OpenMatterSerializer(many=True)
    can_complete_now = serializers.BooleanField()


class DeletionConfirmSerializer(serializers.Serializer):
    confirm = serializers.BooleanField()
    source = serializers.ChoiceField(choices=["app", "portal"], default="app")


class RetentionRuleSerializer(serializers.ModelSerializer):
    country = CountryCode(required=False, allow_null=True)
    period_label = serializers.SerializerMethodField()

    class Meta:
        model = RetentionRule
        validators = []  # uniqueness is checked in services and the database
        fields = ["id", "country", "data_class", "description", "period_days", "period_label", "anchor", "action",
                  "kept_on_deletion", "reason", "status", "updated_by", "updated_at"]
        read_only_fields = ["id", "status", "updated_by", "updated_at", "period_label"]

    def get_period_label(self, obj) -> str:
        return f"{obj.period_days} days" if obj.period_days is not None else "[TO VERIFY]"


class RetentionRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = RetentionRun
        fields = ["id", "started_by", "created_at", "finished_at", "results"]


class LegalHoldSerializer(serializers.ModelSerializer):
    country = CountryCode(required=False)

    class Meta:
        model = LegalHold
        fields = ["id", "country", "subject_type", "subject_id", "reason", "placed_by", "placed_at", "status",
                  "lift_requested_by", "lift_reason", "approval_request", "lifted_at"]
        read_only_fields = ["id", "placed_by", "placed_at", "status", "lift_requested_by", "lift_reason",
                            "approval_request", "lifted_at"]


class BulkExportSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = BulkExport
        fields = ["id", "country", "requested_by", "purpose", "scope", "approval_request", "status", "file_sha256",
                  "row_count", "produced_at", "link_expires_at", "download_count", "created_at"]
        read_only_fields = fields


class CreateBulkExportSerializer(serializers.Serializer):
    purpose = serializers.CharField()
    country = CountryCode()
    roles = serializers.ListField(child=serializers.CharField(max_length=4), default=["CL"])
    fields = serializers.ListField(child=serializers.ChoiceField(choices=sorted(EXPORT_FIELDS)),
                                   default=["full_name", "email"])


class DataCatalogueSerializer(serializers.ModelSerializer):
    data_class = serializers.ChoiceField(choices=[*DATA_CLASSES, "none"], default="none")

    class Meta:
        model = DataCatalogueEntry
        fields = ["id", "table_name", "field_name", "purpose", "data_class", "personal", "special_category",
                  "notes"]


@extend_schema_serializer(component_name="DataProtectionLocation")
class DataLocationSerializer(serializers.ModelSerializer):
    country = CountryCode(required=False, allow_null=True)

    class Meta:
        model = DataLocation
        fields = ["id", "country", "cell", "service", "vendor", "region", "data_classes", "transfer_basis", "notes"]


class CatalogueGapsSerializer(serializers.Serializer):
    added = serializers.IntegerField()
    uncatalogued = serializers.ListField(child=serializers.CharField())
