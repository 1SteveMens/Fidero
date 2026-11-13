from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    AccessLog, Evidence, EvidenceLink, IntegrityIncident, IntegrityRun, IssuedDocument, Preview, UploadSlot,
)


class PreviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Preview
        fields = ["kind", "status", "content_type", "width", "height", "size_bytes"]


class EvidenceLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceLink
        fields = ["id", "subject_type", "subject_id", "role", "linked_by", "created_at"]


class EvidenceSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    preview = serializers.SerializerMethodField()
    links = EvidenceLinkSerializer(many=True, read_only=True)
    release_grade = serializers.BooleanField(source="is_release_grade", read_only=True)

    class Meta:
        model = Evidence
        fields = ["id", "country", "sha256", "size_bytes", "content_type", "original_name", "source", "provenance",
                  "release_grade", "device_id", "signature_valid", "uploaded_by", "uploaded_by_name", "captured_at",
                  "received_at", "latitude", "longitude", "position_accuracy_m", "capture_device", "scan_status",
                  "description", "owner_type", "owner_id", "data_class", "retain_until", "deleted_at", "preview",
                  "links", "created_at"]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj) -> str:
        return obj.uploaded_by.full_name if obj.uploaded_by else ""

    @staticmethod
    def _preview(obj):
        return Preview.objects.filter(evidence=obj).first()

    @extend_schema_field(PreviewSerializer(allow_null=True))
    def get_preview(self, obj):
        p = self._preview(obj)
        return PreviewSerializer(p).data if p else None


class UploadSlotRequestSerializer(serializers.Serializer):
    subject_type = serializers.CharField(help_text="What the file belongs to, e.g. case, order, fee_invoice.")
    subject_id = serializers.UUIDField()
    role = serializers.CharField(required=False, default="supporting", help_text="Evidence kind, e.g. site_plan.")
    content_type = serializers.CharField()
    size_bytes = serializers.IntegerField(min_value=1)
    sha256 = serializers.CharField(min_length=64, max_length=64, help_text="SHA-256 of the file, hex.")
    original_name = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    captured_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True,
                                        default=None)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, required=False, allow_null=True,
                                         default=None)
    position_accuracy_m = serializers.DecimalField(max_digits=8, decimal_places=2, required=False,
                                                   allow_null=True, default=None)
    country = serializers.CharField(required=False, allow_blank=True, default="",
                                    help_text="Country code, used when the subject does not say.")


class UploadInstructionSerializer(serializers.Serializer):
    method = serializers.CharField()
    url = serializers.CharField()
    expires_in = serializers.IntegerField()
    headers = serializers.DictField(child=serializers.CharField())


class UploadSlotSerializer(serializers.ModelSerializer):
    upload = serializers.SerializerMethodField()
    country = serializers.CharField(source="country.code", read_only=True)

    class Meta:
        model = UploadSlot
        fields = ["id", "country", "subject_type", "subject_id", "role", "expected_sha256", "content_type",
                  "size_bytes", "original_name", "status", "expires_at", "evidence", "rejection_reason", "upload",
                  "created_at"]
        read_only_fields = fields

    @extend_schema_field(UploadInstructionSerializer)
    def get_upload(self, obj):
        import base64
        from django.utils import timezone

        left = max(0, int((obj.expires_at - timezone.now()).total_seconds()))
        return {"method": "PUT", "url": f"/v1/uploads/{obj.pk}/content", "expires_in": left,
                "headers": {"Content-Type": "application/octet-stream",
                            "X-Checksum-SHA256": base64.b64encode(bytes.fromhex(obj.expected_sha256)).decode()}}


class FileUploadSerializer(serializers.Serializer):
    file = serializers.FileField()


class SignedLinkSerializer(serializers.Serializer):
    url = serializers.CharField()
    token = serializers.CharField()
    expires_at = serializers.DateTimeField()
    expires_in = serializers.IntegerField()
    variant = serializers.ChoiceField(choices=["preview", "original"])
    content_type = serializers.CharField()


class LinkRequestSerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    subject_id = serializers.UUIDField()
    role = serializers.CharField(required=False, default="supporting")


class AccessLogSerializer(serializers.ModelSerializer):
    person_name = serializers.SerializerMethodField()

    class Meta:
        model = AccessLog
        fields = ["id", "evidence", "person", "person_name", "action", "variant", "link_expires_at", "detail",
                  "created_at"]

    def get_person_name(self, obj) -> str:
        return obj.person.full_name if obj.person else ""


class ScanVerdictSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(choices=["clean", "rejected"])
    detail = serializers.CharField(required=False, allow_blank=True, default="")
    scanner = serializers.CharField(required=False, default="manual")


class FingerprintRequestSerializer(serializers.Serializer):
    sha256 = serializers.CharField(help_text="SHA-256 of the document you were given, 64 hex characters.")


class FingerprintResultSerializer(serializers.Serializer):
    match = serializers.BooleanField()
    released_on = serializers.DateField(allow_null=True)


class IssuedDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = IssuedDocument
        fields = ["id", "evidence", "sha256", "subject_type", "subject_id", "kind", "issued_at"]


class IntegrityRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrityRun
        fields = ["id", "seed", "population", "sample_size", "checked", "mismatches", "created_at", "finished_at",
                  "triggered_by"]


class IntegrityRunRequestSerializer(serializers.Serializer):
    size = serializers.IntegerField(required=False, min_value=1, max_value=10000)
    seed = serializers.CharField(required=False, allow_blank=True)


class IntegrityIncidentSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)

    class Meta:
        model = IntegrityIncident
        fields = ["id", "country", "run", "evidence", "expected_sha256", "actual_sha256", "status", "resolved_by",
                  "resolved_at", "resolution_note", "created_at"]


class ResolveRequestSerializer(serializers.Serializer):
    note = serializers.CharField()
