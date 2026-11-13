from rest_framework import serializers

from .models import Cell, Country, CountryConfig


class CellSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cell
        fields = ["id", "name", "aws_region", "aws_account", "api_host", "portal_host", "data_location_notes",
                  "status", "created_at", "row_version"]
        read_only_fields = ["id", "created_at", "row_version"]


class CellUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cell
        fields = ["aws_region", "aws_account", "api_host", "portal_host", "data_location_notes", "status"]
        extra_kwargs = {f: {"required": False} for f in fields}


class PublicCountrySerializer(serializers.ModelSerializer):
    languages = serializers.SerializerMethodField()
    phone_prefix = serializers.SerializerMethodField()

    class Meta:
        model = Country
        fields = ["code", "name", "currency", "timezone", "languages", "phone_prefix"]

    def get_languages(self, obj) -> list[str]:
        return (obj.config() or {}).get("languages") or []

    def get_phone_prefix(self, obj) -> str:
        return (obj.config() or {}).get("phone_prefix") or ""


class AdminCountrySerializer(serializers.ModelSerializer):
    cell = serializers.SlugRelatedField(slug_field="name", queryset=Cell.objects.all(), required=False,
                                        allow_null=True)
    current_config_version = serializers.SerializerMethodField()
    activation_blockers = serializers.SerializerMethodField()

    class Meta:
        model = Country
        fields = ["id", "code", "name", "currency", "timezone", "status", "activated_at", "cell", "data_location",
                  "data_location_ruling", "evidence_prefix", "backup_location", "kms_key_alias", "current_config",
                  "current_config_version", "activation_request", "manual_phase_started_at", "validation_started_at",
                  "gate_passed", "gate_decided_at", "gate_decided_by", "gate_note", "gate_evidence",
                  "activation_blockers", "created_at", "row_version"]
        read_only_fields = ["id", "status", "activated_at", "current_config", "activation_request",
                            "manual_phase_started_at", "validation_started_at", "gate_passed", "gate_decided_at",
                            "gate_decided_by", "gate_note", "gate_evidence", "created_at", "row_version"]

    def get_current_config_version(self, obj) -> int | None:
        c = obj.configs.filter(status="published").order_by("-version").first()
        return c.version if c else None

    def get_activation_blockers(self, obj) -> list[dict]:
        from .services import activation_blockers

        return activation_blockers(obj) if obj.status in ("manual_phase", "validating") else []


class AdminCountryUpdateSerializer(serializers.ModelSerializer):
    cell = serializers.SlugRelatedField(slug_field="name", queryset=Cell.objects.all(), required=False,
                                        allow_null=True)

    class Meta:
        model = Country
        fields = ["name", "currency", "timezone", "cell", "data_location", "data_location_ruling", "evidence_prefix",
                  "backup_location", "kms_key_alias"]
        extra_kwargs = {f: {"required": False} for f in fields}


class CountryConfigSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    publication_blockers = serializers.SerializerMethodField()

    class Meta:
        model = CountryConfig
        fields = ["id", "country", "version", "status", "schema_version", "data", "content_sha256", "copied_from",
                  "prepared_by", "approval_request", "published_at", "publication_blockers", "created_at",
                  "row_version"]
        read_only_fields = fields

    def get_publication_blockers(self, obj) -> list[dict]:
        from .services import publication_blockers

        return publication_blockers(obj) if obj.status in ("draft", "pending_approval") else []


class ConfigCreateSerializer(serializers.Serializer):
    data = serializers.JSONField(required=False, help_text="The pack. Omit to start from the current version.")
    copy_from = serializers.CharField(required=False, help_text="A config id, or a country code for its "
                                                                "published version (FR-CTY-004).")


class ConfigEditSerializer(serializers.Serializer):
    data = serializers.JSONField()


class GateDecisionSerializer(serializers.Serializer):
    passed = serializers.BooleanField()
    note = serializers.CharField()
    evidence_id = serializers.UUIDField(required=False, allow_null=True)


class CtyReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CtyDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class CtyApprovalStateSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    status = serializers.CharField()
    approvals = serializers.IntegerField()
    required = serializers.IntegerField()


class DataLocationSerializer(serializers.Serializer):
    country = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField()
    cell = serializers.CharField(allow_blank=True)
    region = serializers.CharField(allow_blank=True)
    data_location = serializers.CharField(allow_blank=True)
    data_location_ruling = serializers.CharField(allow_blank=True)
    evidence_prefix = serializers.CharField(allow_blank=True)
    backup_location = serializers.CharField(allow_blank=True)
    kms_key_alias = serializers.CharField(allow_blank=True)


class DirectoryLookupSerializer(serializers.Serializer):
    signin = serializers.CharField(required=False, help_text="Email or phone used to sign in.")
    reference = serializers.CharField(required=False, help_text="A reference such as TMR-NG-2027-00042.")


class DirectoryAnswerSerializer(serializers.Serializer):
    cell = serializers.CharField(allow_null=True)
    api_host = serializers.CharField(allow_blank=True)
    portal_host = serializers.CharField(allow_blank=True)


class CountryMetricsSerializer(serializers.Serializer):
    country = serializers.CharField()
    name = serializers.CharField()
    status = serializers.CharField()
    currency = serializers.CharField()
    counts = serializers.DictField(child=serializers.IntegerField())
    metrics = serializers.DictField()
