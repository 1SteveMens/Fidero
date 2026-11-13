"""PTR API serializers (02 7.8)."""
from rest_framework import serializers

from .models import SCOPES, WEBHOOK_EVENTS, ApiClient, PartnerOrder, UsageStatement, WebhookDelivery, WebhookSubscription


class PtrTokenIn(serializers.Serializer):
    grant_type = serializers.ChoiceField(choices=["client_credentials"])
    client_id = serializers.CharField()
    client_secret = serializers.CharField()
    scope = serializers.CharField(required=False, allow_blank=True)


class PtrTokenOut(serializers.Serializer):
    access_token = serializers.CharField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()
    scope = serializers.CharField()


class PtrPoint(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lng = serializers.FloatField(min_value=-180, max_value=180)


class PtrStatusQueryIn(serializers.Serializer):
    plot_reference = serializers.CharField(required=False, allow_blank=False)
    point = PtrPoint(required=False)

    def validate(self, attrs):
        if bool(attrs.get("plot_reference")) == bool(attrs.get("point")):
            raise serializers.ValidationError("Send either plot_reference or point.")
        return attrs


class PtrStatusOut(serializers.Serializer):
    status = serializers.ChoiceField(choices=["no_report", "in_progress", "report_exists", "verified", "ambiguous"])
    verdict = serializers.CharField(required=False)
    report_date = serializers.DateField(required=False)
    report_reference = serializers.CharField(required=False)
    full_report_available = serializers.BooleanField(required=False)
    report_id = serializers.UUIDField(required=False)


class PtrSectionOut(serializers.Serializer):
    number = serializers.CharField()
    title = serializers.CharField()
    verdict = serializers.CharField(allow_null=True)
    findings = serializers.CharField()


class PtrReportOut(serializers.Serializer):
    report_reference = serializers.CharField()
    verdict = serializers.CharField(allow_null=True)
    report_date = serializers.DateField()
    pdf_sha256 = serializers.CharField()
    consent_id = serializers.CharField()
    sections = PtrSectionOut(many=True)


class PtrOrderIn(serializers.Serializer):
    client_email = serializers.EmailField()
    locality = serializers.CharField()
    plot_number = serializers.CharField(required=False, allow_blank=True, default="")
    site_plan_ref = serializers.CharField(required=False, allow_blank=True, default="")
    asset_type = serializers.ChoiceField(choices=["plot", "building"], default="plot")
    seller_name = serializers.CharField(required=False, allow_blank=True, default="")
    seller_phone = serializers.CharField(required=False, allow_blank=True, default="")
    tier = serializers.CharField(required=False, default="standard")
    partner_reference = serializers.CharField(required=False, allow_blank=True, default="")


class PtrOrderSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    partner = serializers.CharField(source="client.name", read_only=True)

    class Meta:
        model = PartnerOrder
        fields = ["id", "reference", "country", "partner", "partner_reference", "asset_type", "locality",
                  "plot_number", "site_plan_ref", "seller_name", "tier", "status", "order_id", "case_id",
                  "decided_at", "created_at"]
        read_only_fields = fields


class PtrUsageOut(serializers.Serializer):
    client_id = serializers.CharField()
    partner = serializers.CharField()
    month = serializers.DateField()
    call_count = serializers.IntegerField()
    billable_count = serializers.IntegerField()
    order_count = serializers.IntegerField()
    by_result = serializers.DictField(child=serializers.IntegerField())
    closed = serializers.BooleanField()


class PtrWebhookIn(serializers.Serializer):
    url = serializers.URLField()
    events = serializers.ListField(child=serializers.ChoiceField(choices=WEBHOOK_EVENTS), min_length=1)


class PtrWebhookSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookSubscription
        fields = ["id", "url", "events", "status", "failing_since", "created_at"]
        read_only_fields = fields


class PtrWebhookCreated(PtrWebhookSerializer):
    secret = serializers.CharField(read_only=True)

    class Meta(PtrWebhookSerializer.Meta):
        fields = PtrWebhookSerializer.Meta.fields + ["secret"]
        read_only_fields = fields


class PtrDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookDelivery
        fields = ["id", "event_id", "event_type", "attempts", "next_attempt_at", "last_status_code", "last_error",
                  "delivered_at", "status", "created_at"]
        read_only_fields = fields


# ------------------------------------------------------------------ administration and the client's portal

class PtrClientSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    partner_name = serializers.CharField(source="partner.name", read_only=True)

    class Meta:
        model = ApiClient
        fields = ["id", "country", "partner", "partner_name", "name", "client_id", "scopes", "rate_limit_per_minute",
                  "monthly_quota", "contact_person", "status", "secret_rotated_at", "revoked_at", "last_used_at",
                  "created_at"]
        read_only_fields = fields


class PtrClientCreated(PtrClientSerializer):
    client_secret = serializers.CharField(read_only=True)

    class Meta(PtrClientSerializer.Meta):
        fields = PtrClientSerializer.Meta.fields + ["client_secret"]
        read_only_fields = fields


class PtrClientIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    partner_id = serializers.UUIDField()
    name = serializers.CharField()
    scopes = serializers.ListField(child=serializers.ChoiceField(choices=SCOPES))
    rate_limit_per_minute = serializers.IntegerField(min_value=1, default=60)
    monthly_quota = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    contact_person_id = serializers.UUIDField(required=False, allow_null=True)


class PtrClientUpdate(serializers.Serializer):
    name = serializers.CharField(required=False)
    scopes = serializers.ListField(child=serializers.ChoiceField(choices=SCOPES), required=False)
    rate_limit_per_minute = serializers.IntegerField(min_value=1, required=False)
    monthly_quota = serializers.IntegerField(min_value=1, required=False, allow_null=True)


class PtrStatusIn(serializers.Serializer):
    status = serializers.ChoiceField(choices=["active", "suspended", "revoked"])
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class PtrMonthIn(serializers.Serializer):
    month = serializers.RegexField(r"^\d{4}-\d{2}$")


class PtrStatementSerializer(serializers.ModelSerializer):
    class Meta:
        model = UsageStatement
        fields = ["id", "client", "month", "call_count", "billable_count", "order_count", "by_result", "closed_by",
                  "created_at"]
        read_only_fields = fields


class PtrDirectoryItem(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    partner_name = serializers.CharField()
