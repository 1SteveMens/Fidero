from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from countries.models import Country

from .models import (
    AppVersion, ChangeRequest, ConfigVersion, FeatureFlag, FxRate, LockedTextVersion, Partner, Price,
)
from .registry import REGISTRY


class CountryCodeField(serializers.SlugRelatedField):
    def __init__(self, **kw):
        kw.setdefault("slug_field", "code")
        if not kw.get("read_only"):
            kw.setdefault("queryset", Country.objects.all())
        super().__init__(**kw)

    def to_internal_value(self, data):
        return super().to_internal_value(str(data).upper())


class ConfigVersionSerializer(serializers.ModelSerializer):
    country = CountryCodeField(required=False, allow_null=True)

    class Meta:
        model = ConfigVersion
        fields = ["id", "kind", "country", "product_line", "version", "name", "content", "content_sha256",
                  "schema_version", "state", "copied_from", "created_by", "published_by", "published_at",
                  "created_at", "row_version"]
        read_only_fields = ["id", "version", "content_sha256", "state", "copied_from", "created_by", "published_by",
                            "published_at", "created_at", "row_version"]


class ConfigVersionEditSerializer(serializers.Serializer):
    content = serializers.JSONField(required=False)
    name = serializers.CharField(required=False, allow_blank=True)


class MoneyValueSerializer(serializers.Serializer):
    amount = serializers.CharField(help_text="Decimal as a string, e.g. 350.00")
    currency = serializers.CharField(help_text="ISO 4217")


class AdminPriceSerializer(serializers.ModelSerializer):
    country = CountryCodeField(read_only=True)
    price = serializers.SerializerMethodField()

    class Meta:
        model = Price
        fields = ["id", "country", "product_line", "tier", "audience", "price", "valid_from", "valid_to", "note",
                  "created_by"]

    @extend_schema_field(MoneyValueSerializer)
    def get_price(self, obj):
        return {"amount": f"{obj.price_amount:.2f}", "currency": obj.price_currency}


class PriceItemSerializer(serializers.Serializer):
    tier = serializers.CharField()
    product_line = serializers.CharField(required=False, default="land")
    audience = serializers.CharField(required=False, default="standard")
    price = MoneyValueSerializer()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class PriceUpdateSerializer(serializers.Serializer):
    country = CountryCodeField()
    items = PriceItemSerializer(many=True)


class FxGuideRateSerializer(serializers.ModelSerializer):
    country = CountryCodeField()

    class Meta:
        model = FxRate
        fields = ["id", "country", "base_currency", "quote_currency", "rate", "rate_date", "source", "created_at"]
        read_only_fields = ["id", "source", "created_at"]
        extra_kwargs = {"rate_date": {"required": False}, "rate": {"coerce_to_string": True}}


class FxGuideSerializer(serializers.Serializer):
    base_currency = serializers.CharField()
    quote_currency = serializers.CharField()
    rate = serializers.DecimalField(max_digits=18, decimal_places=6)
    rate_date = serializers.DateField()
    source = serializers.CharField()
    note = serializers.CharField()


class RegistryPartnerSerializer(serializers.ModelSerializer):
    country = CountryCodeField()
    account_number = serializers.SerializerMethodField(help_text="Masked: only the last four digits.")
    pending_bank_change = serializers.SerializerMethodField()

    class Meta:
        model = Partner
        fields = ["id", "country", "kind", "name", "status", "organisation", "person", "adapter_port", "adapter_path",
                  "contact_name", "contact_email", "contact_phone", "licence_number", "licence_body",
                  "is_national_id_system", "details", "bank_name", "bank_branch", "account_name", "account_number",
                  "bank_change_request", "pending_bank_change", "deactivated_at", "created_at", "row_version"]
        read_only_fields = ["id", "status", "bank_name", "bank_branch", "account_name", "bank_change_request",
                            "deactivated_at", "created_at", "row_version"]

    def get_account_number(self, obj) -> str:
        n = obj.account_number or ""
        return ("*" * max(len(n) - 4, 0) + n[-4:]) if n else ""

    def get_pending_bank_change(self, obj) -> str | None:
        cr = ChangeRequest.objects.filter(kind="partner_bank", target=str(obj.pk), status="pending").first()
        return str(cr.pk) if cr else None


class PartnerBankDetailsSerializer(serializers.Serializer):
    bank_name = serializers.CharField()
    bank_branch = serializers.CharField(required=False, allow_blank=True, default="")
    account_name = serializers.CharField()
    account_number = serializers.CharField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RegistryPartnerCreateSerializer(serializers.ModelSerializer):
    country = CountryCodeField()
    bank = PartnerBankDetailsSerializer(required=False, help_text="Optional. Waits for a second administrator.")

    class Meta:
        model = Partner
        fields = ["country", "kind", "name", "organisation", "person", "adapter_port", "adapter_path", "contact_name",
                  "contact_email", "contact_phone", "licence_number", "licence_body", "is_national_id_system",
                  "details", "bank"]


class RegistryPartnerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = ["name", "organisation", "person", "adapter_port", "adapter_path", "contact_name", "contact_email",
                  "contact_phone", "licence_number", "licence_body", "is_national_id_system", "details"]
        extra_kwargs = {f: {"required": False} for f in fields}


class AdmReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class LockedTextSerializer(serializers.ModelSerializer):
    country = CountryCodeField()
    missing_signoffs = serializers.SerializerMethodField()

    class Meta:
        model = LockedTextVersion
        fields = ["id", "country", "kind", "version", "title", "text", "text_sha256", "status", "proposed_by",
                  "approval_request", "lawyer_approval_evidence", "lawyer_approved_by", "lawyer_approved_at",
                  "insurer_approval_evidence", "insurer_approved_by", "insurer_approved_at", "missing_signoffs",
                  "copied_from", "published_at", "created_at", "row_version"]
        read_only_fields = [f for f in fields if f not in ("country", "title", "text")]

    def get_missing_signoffs(self, obj) -> list[str]:
        from .services import missing_signoffs

        return missing_signoffs(obj)


class LockedTextEditSerializer(serializers.Serializer):
    text = serializers.CharField(required=False)
    title = serializers.CharField(required=False, allow_blank=True)


class PublicLockedTextSerializer(serializers.ModelSerializer):
    country = CountryCodeField(read_only=True)

    class Meta:
        model = LockedTextVersion
        fields = ["id", "country", "kind", "version", "title", "text", "text_sha256", "published_at"]


class SignoffSerializer(serializers.Serializer):
    party = serializers.ChoiceField(choices=["lawyer", "insurer"])
    approved_by_name = serializers.CharField()
    evidence_id = serializers.UUIDField(required=False, help_text="An evidence record already uploaded.")
    document_base64 = serializers.CharField(required=False, help_text="Or the signed approval itself, base64.")
    filename = serializers.CharField(required=False, default="approval.pdf")
    content_type = serializers.CharField(required=False, default="application/pdf")


class AdmDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class AdmApprovalStateSerializer(serializers.Serializer):
    request_id = serializers.UUIDField()
    status = serializers.CharField()
    approvals = serializers.IntegerField()
    required = serializers.IntegerField()


class ChangeRequestSerializer(serializers.ModelSerializer):
    country = CountryCodeField(read_only=True)
    approval_status = serializers.SerializerMethodField()

    class Meta:
        model = ChangeRequest
        fields = ["id", "kind", "target", "country", "old_value", "new_value", "reason", "status", "requested_by",
                  "approval_request", "approval_status", "applied_at", "created_at", "row_version"]
        read_only_fields = fields

    def get_approval_status(self, obj) -> str | None:
        return obj.approval_request.status if obj.approval_request_id else None

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if obj.kind == "partner_bank":
            from .services import _mask_bank

            data["new_value"] = _mask_bank(obj.new_value or {})
        return data


class AdminSettingSerializer(serializers.Serializer):
    key = serializers.CharField()
    country = serializers.CharField(allow_null=True)
    value = serializers.JSONField()
    default = serializers.JSONField()
    is_set = serializers.BooleanField(help_text="False while the value is an unset [TO VERIFY] default.")
    type = serializers.CharField()
    unit = serializers.CharField()
    min = serializers.JSONField(allow_null=True)
    max = serializers.JSONField(allow_null=True)
    choices = serializers.ListField(child=serializers.CharField())
    affects_release = serializers.BooleanField()
    second_admin = serializers.BooleanField()
    to_verify = serializers.BooleanField()
    description = serializers.CharField()
    source = serializers.CharField()
    pending_change = serializers.UUIDField(allow_null=True)


class SettingUpdateSerializer(serializers.Serializer):
    value = serializers.JSONField()
    country = CountryCodeField(required=False, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ChangeOutcomeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["applied", "pending_approval"])
    change_request = ChangeRequestSerializer(allow_null=True)
    setting = AdminSettingSerializer(allow_null=True, required=False)


class FeatureFlagSerializer(serializers.ModelSerializer):
    country = CountryCodeField(read_only=True)
    policy = serializers.SerializerMethodField()

    class Meta:
        model = FeatureFlag
        fields = ["id", "name", "country", "enabled", "value", "owner", "reason", "removal_date", "changed_by",
                  "updated_at", "policy"]
        read_only_fields = fields

    def get_policy(self, obj) -> str:
        from .services import flag_policy

        return flag_policy(obj.name)


class FlagChangeSerializer(serializers.Serializer):
    name = serializers.CharField()
    enabled = serializers.BooleanField()
    country = CountryCodeField(required=False, allow_null=True)
    value = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class FlagOutcomeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["applied", "pending_approval"])
    flag = FeatureFlagSerializer(allow_null=True)
    change_request = ChangeRequestSerializer(allow_null=True)


class AppVersionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppVersion
        fields = ["id", "app", "platform", "min_version", "latest_version", "store_url", "previous_min_version",
                  "min_raised_at", "changed_by", "updated_at"]
        read_only_fields = ["id", "previous_min_version", "min_raised_at", "changed_by", "updated_at"]


class AppVersionUpdateSerializer(serializers.Serializer):
    app = serializers.ChoiceField(choices=AppVersion.APPS)
    platform = serializers.ChoiceField(choices=AppVersion.PLATFORMS)
    min_version = serializers.CharField(required=False)
    latest_version = serializers.CharField(required=False)
    store_url = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class AppVersionOutcomeSerializer(serializers.Serializer):
    app_version = AppVersionSerializer()
    change_request = ChangeRequestSerializer(allow_null=True)


class AppConfigQuerySerializer(serializers.Serializer):
    app = serializers.ChoiceField(choices=AppVersion.APPS)
    platform = serializers.ChoiceField(choices=AppVersion.PLATFORMS)
    version = serializers.CharField()
    country = serializers.CharField(required=False, max_length=2)


class AppConfigSerializer(serializers.Serializer):
    app = serializers.CharField()
    platform = serializers.CharField()
    version = serializers.CharField()
    min_version = serializers.CharField(allow_null=True)
    latest_version = serializers.CharField(allow_null=True)
    update_required = serializers.BooleanField()
    update_available = serializers.BooleanField()
    store_url = serializers.CharField(allow_blank=True)
    fee_payment_mode = serializers.ChoiceField(choices=["web", "in_app_provider"])


def setting_view(key, country, pending=None) -> dict:
    from .selectors import setting, setting_is_set

    d = REGISTRY[key]
    return {"key": key, "country": getattr(country, "code", None), "value": setting(key, country),
            "default": d.default, "is_set": setting_is_set(key, country), "type": d.type, "unit": d.unit,
            "min": d.min, "max": d.max, "choices": list(d.choices), "affects_release": d.affects_release,
            "second_admin": d.second_admin, "to_verify": d.to_verify, "description": d.description,
            "source": d.source, "pending_change": pending}

