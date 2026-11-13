from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from countries.models import Country

from .models import Assignment, CheckIn, Device, FraudFlag, SignedManifest, Submission, SubmissionItem


# --------------------------------------------------------------------------- app config and devices

@extend_schema_serializer(component_name="FieldAppConfig")
class AppConfigSerializer(serializers.Serializer):
    app = serializers.CharField()
    platform = serializers.CharField()
    min_version = serializers.CharField()
    latest_version = serializers.CharField()
    min_raised_at = serializers.DateTimeField(allow_null=True)
    store_url = serializers.CharField()
    update_required = serializers.BooleanField()
    update_available = serializers.BooleanField()
    fee_payment_mode = serializers.CharField()


class ChallengeSerializer(serializers.Serializer):
    challenge = serializers.CharField()
    expires_at = serializers.DateTimeField()


class DeviceRegisterSerializer(serializers.Serializer):
    challenge = serializers.CharField()
    platform = serializers.ChoiceField(choices=["android", "ios"])
    app_id = serializers.CharField(help_text="Package name or bundle ID of Tenmina Field.")
    public_key = serializers.CharField(help_text="P-256 (ES256) or Ed25519 public key, base64 DER SPKI or PEM.")
    attestation = serializers.JSONField(help_text="Key attestation and Play Integrity, or the App Attest object.")
    model = serializers.CharField(required=False, allow_blank=True, default="")
    os_version = serializers.CharField(required=False, allow_blank=True, default="")
    app_version = serializers.CharField(required=False, allow_blank=True, default="")


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ["id", "person", "platform", "app_id", "key_alg", "key_security", "attestation_kind",
                  "integrity_status", "model", "os_version", "app_version", "status", "registered_at",
                  "last_seen_at", "revoked_at", "revoke_reason"]
        read_only_fields = fields


@extend_schema_serializer(component_name="FieldReason")
class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField()


class IntegrityCheckSerializer(serializers.Serializer):
    assertion = serializers.JSONField(help_text="A fresh Play Integrity verdict or App Attest assertion.")


# --------------------------------------------------------------------------- manifests (8.4)

class SubjectRefSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.UUIDField()
    requirement_key = serializers.CharField(required=False, allow_blank=True)


class MediaSerializer(serializers.Serializer):
    type = serializers.CharField()
    size_bytes = serializers.IntegerField()
    sha256 = serializers.CharField()


class TimeSyncSerializer(serializers.Serializer):
    server = serializers.DateTimeField()
    offset_ms = serializers.IntegerField(help_text="Server time minus device time at the last sync.")


class LocationSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    accuracy_m = serializers.FloatField()
    provider = serializers.CharField(required=False)
    fix_time = serializers.DateTimeField(required=False)
    mock = serializers.BooleanField(required=False)


class CameraSerializer(serializers.Serializer):
    lens = serializers.CharField(required=False)
    model = serializers.CharField(required=False)
    platform = serializers.CharField(required=False)
    app_version = serializers.CharField(required=False)
    emulator = serializers.BooleanField(required=False)


class ManifestSerializer(serializers.Serializer):
    """Canonical JSON (RFC 8785) of this object is what the device signs."""

    schema = serializers.ChoiceField(choices=["tenmina.evidence.v1", "tenmina.checkin.v1"])
    kind = serializers.ChoiceField(choices=["checkin", "checkout"], required=False,
                                   help_text="Check-in manifests only.")
    client_item_id = serializers.CharField()
    device_id = serializers.UUIDField()
    subject = SubjectRefSerializer()
    media = MediaSerializer(required=False)
    captured_at_device = serializers.DateTimeField()
    elapsed_realtime_ms = serializers.IntegerField(required=False)
    last_server_time_sync = TimeSyncSerializer(required=False)
    location = LocationSerializer(required=False)
    camera = CameraSerializer(required=False)
    previous_item_sha256 = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class SignedItemSerializer(serializers.Serializer):
    manifest = ManifestSerializer()
    signature = serializers.CharField(help_text="DER ECDSA or raw Ed25519 signature, base64url.")
    signature_alg = serializers.ChoiceField(choices=["ES256", "EdDSA"])


class FlagBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = FraudFlag
        fields = ["id", "kind", "status", "detail"]


class UploadSerializer(serializers.Serializer):
    method = serializers.CharField()
    url = serializers.CharField()
    expires_in = serializers.IntegerField()
    headers = serializers.DictField(child=serializers.CharField())


class FieldItemSerializer(serializers.ModelSerializer):
    evidence_id = serializers.SerializerMethodField()
    flags = FlagBriefSerializer(many=True, read_only=True)
    upload = serializers.SerializerMethodField()

    class Meta:
        model = SignedManifest
        fields = ["id", "client_item_id", "kind", "device", "subject_type", "subject_id", "requirement_key",
                  "media_type", "media_sha256", "media_size", "status", "evidence_id", "signature_valid",
                  "captured_at_device", "corrected_capture_at", "received_at", "stored_at", "latitude", "longitude",
                  "accuracy_m", "unassigned_capture", "rejection_reason", "flags", "upload"]
        read_only_fields = fields

    def get_evidence_id(self, obj) -> str:
        return str(obj.evidence_id or obj.reserved_evidence_id)

    @extend_schema_field(UploadSerializer(allow_null=True))
    def get_upload(self, obj):
        from .services import upload_instruction

        return upload_instruction(obj) if obj.status in ("registered", "uploaded") else None


# --------------------------------------------------------------------------- submissions and inspections

class SubmissionItemInSerializer(serializers.Serializer):
    requirement_key = serializers.CharField()
    evidence_id = serializers.UUIDField(required=False, allow_null=True)
    value = serializers.JSONField(required=False, allow_null=True, help_text="Tick or reading for form items.")


class SubmissionRequestSerializer(serializers.Serializer):
    client_submission_id = serializers.CharField(help_text="Client-generated UUID; the idempotency key.")
    subject_type = serializers.CharField(required=False, default="milestone")
    subject_id = serializers.UUIDField(required=False)
    milestone_id = serializers.UUIDField(required=False, help_text="Shorthand for subject_type milestone.")
    items = SubmissionItemInSerializer(many=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("subject_id"):
            if not attrs.get("milestone_id"):
                raise serializers.ValidationError({"subject_id": "Give subject_id or milestone_id."})
            attrs["subject_id"], attrs["subject_type"] = attrs["milestone_id"], "milestone"
        attrs.pop("milestone_id", None)
        return attrs


class SubmissionItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmissionItem
        fields = ["id", "requirement_key", "kind", "evidence", "value"]


class SubmissionSerializer(serializers.ModelSerializer):
    items = SubmissionItemSerializer(many=True, read_only=True)
    open_flags = serializers.SerializerMethodField()

    class Meta:
        model = Submission
        fields = ["id", "client_submission_id", "kind", "person", "subject_type", "subject_id", "status", "outcome",
                  "checklist", "defects", "reason", "note", "received_at", "reviewed_at", "items", "open_flags"]
        read_only_fields = fields

    def get_open_flags(self, obj) -> int:
        ids = [i.evidence_id for i in obj.items.all() if i.evidence_id]
        return FraudFlag.objects.filter(evidence_id__in=ids, status="open").count()


class ChecklistAnswerSerializer(serializers.Serializer):
    key = serializers.CharField()
    result = serializers.ChoiceField(choices=["ok", "not_ok", "na"])
    note = serializers.CharField(required=False, allow_blank=True)


class MoneyInSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(min_length=3, max_length=3)


class DefectInSerializer(serializers.Serializer):
    description = serializers.CharField()
    value = MoneyInSerializer()
    evidence_ids = serializers.ListField(child=serializers.UUIDField())


class InspectionRequestSerializer(serializers.Serializer):
    client_submission_id = serializers.CharField()
    subject_type = serializers.CharField(required=False, default="milestone_inspection")
    subject_id = serializers.UUIDField()
    outcome = serializers.ChoiceField(choices=["pass", "pass_with_defects", "fail"])
    checklist = ChecklistAnswerSerializer(many=True)
    defects = serializers.ListField(child=serializers.DictField(), required=False, default=list,
                                    help_text="[{description, value: {amount, currency}, evidence_ids: [...]}]")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")


# --------------------------------------------------------------------------- check-ins, flags, assignments, sync

class CheckInSerializer(serializers.ModelSerializer):
    flags = FlagBriefSerializer(many=True, read_only=True)

    class Meta:
        model = CheckIn
        fields = ["id", "kind", "person", "device", "subject_type", "subject_id", "latitude", "longitude",
                  "accuracy_m", "registered_lat", "registered_lng", "distance_m", "radius_m", "within_radius",
                  "device_time", "received_at", "signature_valid", "checkin", "duration_minutes", "evidence", "flags"]
        read_only_fields = fields


class FraudFlagSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    person = serializers.SerializerMethodField()

    class Meta:
        model = FraudFlag
        fields = ["id", "country", "kind", "detail", "status", "evidence", "manifest", "checkin", "device",
                  "subject_type", "subject_id", "person", "reviewed_by", "reviewed_at", "review_note", "created_at"]
        read_only_fields = fields

    def get_person(self, obj) -> str | None:
        if obj.manifest_id:
            return str(obj.manifest.person_id)
        return str(obj.device.person_id) if obj.device_id else None


class ReviewSerializer(serializers.Serializer):
    note = serializers.CharField()


class RequiredEvidenceSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField(required=False)
    media = serializers.ChoiceField(choices=["photo", "video", "reading", "tick", "document"], required=False)
    required = serializers.BooleanField(required=False, default=True)


class ChecklistItemSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField(required=False)


class AssignmentSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", queryset=Country.objects.all())
    required_evidence = RequiredEvidenceSerializer(many=True, required=False)
    checklist = ChecklistItemSerializer(many=True, required=False)

    class Meta:
        model = Assignment
        fields = ["id", "country", "person", "subject_type", "subject_id", "kind", "title", "status", "address",
                  "point_lat", "point_lng", "radius_m", "boundary", "buffer_m", "required_evidence", "checklist",
                  "plan_items", "previous_pass_at", "project_key", "accepts_submissions", "state_reason", "due_at",
                  "min_visit_minutes", "details", "created_at", "revoked_at"]
        read_only_fields = ["id", "status", "created_at", "revoked_at"]


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()


class InboxItemSerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    subject_id = serializers.CharField()
    title = serializers.CharField()
    kind = serializers.CharField()
    country = serializers.CharField(allow_null=True)
    status = serializers.CharField()
    address = serializers.CharField(allow_blank=True)
    point = PointSerializer(allow_null=True)
    radius_m = serializers.IntegerField(allow_null=True)
    boundary = serializers.ListField(child=serializers.ListField(child=serializers.FloatField()))
    buffer_m = serializers.IntegerField(allow_null=True)
    required_evidence = RequiredEvidenceSerializer(many=True)
    checklist = ChecklistItemSerializer(many=True)
    plan_items = serializers.ListField(child=serializers.DictField())
    previous_pass_at = serializers.DateTimeField(allow_null=True)
    project_key = serializers.CharField(allow_blank=True)
    accepts_submissions = serializers.BooleanField()
    state_reason = serializers.CharField(allow_blank=True)
    due_at = serializers.DateTimeField(allow_null=True)
    min_visit_minutes = serializers.IntegerField(allow_null=True)
    details = serializers.DictField()
    updated_at = serializers.DateTimeField(allow_null=True)
    source = serializers.CharField(allow_blank=True)


class SubjectKeySerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    subject_id = serializers.CharField()


class SyncDeviceSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    platform = serializers.CharField()
    model = serializers.CharField()


class SyncSerializer(serializers.Serializer):
    token = serializers.CharField(help_text="Pass as `since` next time.")
    server_time = serializers.DateTimeField()
    full = serializers.BooleanField()
    items = InboxItemSerializer(many=True)
    removed = SubjectKeySerializer(many=True)
    settings = serializers.DictField()
    devices = SyncDeviceSerializer(many=True)


class CompleteSerializer(serializers.Serializer):
    status = serializers.CharField()
    evidence_id = serializers.UUIDField()
    flags = FlagBriefSerializer(many=True)
