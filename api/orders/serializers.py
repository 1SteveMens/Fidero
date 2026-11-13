from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.money import MoneyField as _MoneyField

from . import catalogue, services
from .models import Order, ReferralCode, ReferralReward, TermsAcceptance


class MoneySchema(serializers.Serializer):
    amount = serializers.CharField(help_text='Decimal string, e.g. "250.00".')
    currency = serializers.CharField(help_text="ISO 4217 code.")


@extend_schema_field(MoneySchema)
class MoneyField(_MoneyField):
    """core.money.MoneyField with its OpenAPI shape, so the generated clients are typed."""


class OrderAssetSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["plot", "building", "offplan_unit"], source="asset_type", required=False)
    locality = serializers.CharField(required=False, allow_blank=True)
    plot_number = serializers.CharField(required=False, allow_blank=True)
    site_plan_ref = serializers.CharField(required=False, allow_blank=True)
    ghana_post_gps = serializers.CharField(required=False, allow_blank=True)
    asset_id = serializers.UUIDField(read_only=True)


class OrderSellerSerializer(serializers.Serializer):
    name = serializers.CharField(source="seller_name", required=False, allow_blank=True)
    phone = serializers.CharField(source="seller_phone", required=False, allow_blank=True)
    email = serializers.EmailField(source="seller_email", required=False, allow_blank=True)


class OrderTermsStateSerializer(serializers.Serializer):
    terms_version = serializers.CharField()
    scope_version = serializers.CharField()
    accepted_at = serializers.DateTimeField(source="terms_accepted_at", allow_null=True)
    current = serializers.SerializerMethodField()

    def get_current(self, obj) -> bool:
        return services.terms_current(obj)


class OrderNextLinksSerializer(serializers.Serializer):
    pay = serializers.CharField(allow_null=True)
    submit = serializers.CharField(allow_null=True)
    documents = serializers.CharField()


class OrderSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    client_name = serializers.CharField(source="client.full_name", read_only=True)
    product_name = serializers.SerializerMethodField()
    product_line = serializers.SerializerMethodField()
    asset = OrderAssetSerializer(source="*", read_only=True)
    seller = OrderSellerSerializer(source="*", read_only=True)
    list_price = MoneyField(prefix="list_price", read_only=True)
    price = MoneyField(prefix="price", read_only=True)
    local_price = MoneyField(prefix="local_price", read_only=True)
    discount = serializers.SerializerMethodField()
    referral_code = serializers.SlugRelatedField(slug_field="code", read_only=True)
    terms = OrderTermsStateSerializer(source="*", read_only=True)
    can_pay = serializers.SerializerMethodField()
    missing = serializers.SerializerMethodField()
    next = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = ["id", "reference", "country", "kind", "product_name", "product_line", "status", "client",
                  "client_name", "placed_by", "bill_to", "organisation", "asset", "seller", "subject_type",
                  "subject_id", "parent_order", "details", "notes", "tier", "tier_name", "list_price", "discount",
                  "price", "local_price", "guides", "price_source", "config_version", "quoted_at", "turnaround_days",
                  "lead_source", "lead_source_detail", "referral_code", "terms", "submitted_at", "paid_at",
                  "paid_method", "cancelled_at", "cancel_reason", "refunded_at", "case_id",
                  "last_payment_status", "last_payment_message", "can_pay", "missing", "next", "created_at",
                  "updated_at", "row_version"]
        read_only_fields = fields

    def get_product_name(self, obj) -> str:
        return catalogue.PRODUCTS[obj.kind].name

    def get_product_line(self, obj) -> str:
        return catalogue.product_line(obj.kind, obj.asset_type)

    @extend_schema_field(MoneySchema)
    def get_discount(self, obj):
        return {"amount": f"{obj.discount_amount:.2f}", "currency": obj.price_currency or obj.list_price_currency}

    def get_can_pay(self, obj) -> bool:
        return obj.status == "awaiting_payment" and services.terms_current(obj) and \
            obj.last_payment_status not in ("initiated", "pending_approval")

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_missing(self, obj):
        return services.validation_errors(obj) if obj.status == "draft" else []

    @extend_schema_field(OrderNextLinksSerializer)
    def get_next(self, obj):
        return {"pay": f"/v1/orders/{obj.pk}/payments" if obj.status == "awaiting_payment" else None,
                "submit": f"/v1/orders/{obj.pk}/submit" if obj.status == "draft" else None,
                "documents": f"/v1/orders/{obj.pk}/documents"}


class OrderWriteSerializer(serializers.Serializer):
    """Fields a client may send. Prices are never accepted: the server quotes (TC-ORD-002-02)."""

    asset = OrderAssetSerializer(required=False)
    seller = OrderSellerSerializer(required=False)
    subject_type = serializers.CharField(required=False, allow_blank=True)
    subject_id = serializers.UUIDField(required=False, allow_null=True)
    parent_order_id = serializers.UUIDField(required=False, allow_null=True)
    details = serializers.DictField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    tier = serializers.CharField(required=False, allow_blank=True)
    lead_source = serializers.ChoiceField(choices=catalogue.LEAD_SOURCES, required=False, allow_blank=True)
    lead_source_detail = serializers.CharField(required=False, allow_blank=True)
    referral_code = serializers.CharField(required=False, allow_blank=True)
    upload_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    organisation_id = serializers.UUIDField(required=False, allow_null=True)

    def flat(self):
        """validated data with nested asset and seller flattened to model field names."""
        data = dict(self.validated_data)
        for k, v in (data.pop("asset", None) or {}).items():
            data[k] = v
        for k, v in (data.pop("seller", None) or {}).items():
            data[k] = v
        return data


class OrderCreateSerializer(OrderWriteSerializer):
    country = serializers.CharField(max_length=2)
    kind = serializers.ChoiceField(choices=catalogue.KINDS)
    draft = serializers.BooleanField(required=False, default=False,
                                     help_text="Save what you have so far without submitting (US-ORD-001 AC3).")
    on_behalf_of = serializers.UUIDField(required=False, allow_null=True,
                                         help_text="Case managers only: the client the order is for.")
    accept_terms = serializers.BooleanField(required=False, default=False)
    terms_version = serializers.CharField(required=False, allow_blank=True)
    scope_version = serializers.CharField(required=False, allow_blank=True)


class TermsAcceptanceInput(serializers.Serializer):
    terms_version = serializers.CharField()
    scope_version = serializers.CharField()


class OrderSubmitInput(serializers.Serializer):
    accept_terms = serializers.BooleanField(required=False, default=False)
    terms_version = serializers.CharField(required=False, allow_blank=True)
    scope_version = serializers.CharField(required=False, allow_blank=True)


class OrderReasonInput(serializers.Serializer):
    reason = serializers.CharField()


class ReferralInput(serializers.Serializer):
    code = serializers.CharField()


class OrderDocumentUploadInput(serializers.Serializer):
    file = serializers.FileField()
    role = serializers.ChoiceField(choices=["site_plan", "indenture", "seller_id", "building_permit", "document"],
                                   required=False, default="document")


class OrderDocumentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    sha256 = serializers.CharField()
    size_bytes = serializers.IntegerField()
    content_type = serializers.CharField()
    original_name = serializers.CharField()
    description = serializers.CharField()
    created_at = serializers.DateTimeField()


class TermsAcceptanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = TermsAcceptance
        fields = ["id", "order", "person", "terms_version", "scope_version", "accepted_at", "ip_address"]


class ExtraInspectionInput(serializers.Serializer):
    concern = serializers.CharField(help_text="What worries you about the build.")
    details = serializers.DictField(required=False)
    lead_source = serializers.ChoiceField(choices=catalogue.LEAD_SOURCES, required=False)
    country = serializers.CharField(max_length=2, required=False)
    accept_terms = serializers.BooleanField(required=False, default=False)
    terms_version = serializers.CharField(required=False, allow_blank=True)
    scope_version = serializers.CharField(required=False, allow_blank=True)


# ---------------------------------------------------------------- catalogue


class CatalogueProductSerializer(serializers.Serializer):
    kind = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    line = serializers.CharField()
    tiered = serializers.BooleanField()
    asset_types = serializers.ListField(child=serializers.CharField())
    bill_to = serializers.CharField()
    roles = serializers.ListField(child=serializers.CharField())
    available = serializers.BooleanField()
    price = MoneySchema(allow_null=True)
    local_price = MoneySchema(allow_null=True)


class TierQuoteSerializer(serializers.Serializer):
    kind = serializers.CharField()
    code = serializers.CharField()
    tier = serializers.CharField()
    tier_name = serializers.CharField()
    price = MoneySchema(help_text="Charged by card.")
    local_price = MoneySchema(allow_null=True, help_text="Charged by mobile money.")
    guides = serializers.DictField(child=serializers.CharField(), help_text="Guides only, never charged.")
    guide_for_you = MoneySchema(allow_null=True)
    source = serializers.CharField()
    config_version = serializers.IntegerField(allow_null=True)
    turnaround_days = serializers.IntegerField(allow_null=True)
    requires_same_seller = serializers.BooleanField()


class OrderLockedTextSerializer(serializers.Serializer):
    version = serializers.CharField()
    title = serializers.CharField()
    text = serializers.CharField()


class OrderTermsSerializer(serializers.Serializer):
    terms = OrderLockedTextSerializer()
    scope = OrderLockedTextSerializer()
    terms_version = serializers.CharField()
    scope_version = serializers.CharField()


class LeadSourceSummarySerializer(serializers.Serializer):
    lead_source = serializers.CharField()
    orders = serializers.IntegerField()
    paid = serializers.IntegerField()


# ---------------------------------------------------------------- referrals


class ReferralCodeSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    reward = MoneyField(prefix="reward", read_only=True)
    uses = serializers.SerializerMethodField()

    class Meta:
        model = ReferralCode
        fields = ["id", "code", "country", "owner", "owner_label", "discount_pct", "reward", "valid_from",
                  "valid_until", "max_uses", "uses", "active", "created_at"]
        read_only_fields = fields

    def get_uses(self, obj) -> int:
        return obj.rewards.exclude(status="void").count()


class ReferralCodeCreateSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    owner_label = serializers.CharField()
    code = serializers.CharField(required=False, max_length=32)
    owner = serializers.UUIDField(required=False, allow_null=True)
    discount_pct = serializers.DecimalField(max_digits=5, decimal_places=2, required=False)
    reward = MoneyField(prefix="reward", required=False)
    valid_until = serializers.DateTimeField(required=False, allow_null=True)
    max_uses = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class ReferralRewardSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="referral_code.code", read_only=True)
    order_reference = serializers.CharField(source="order.reference", read_only=True)
    reward = serializers.SerializerMethodField()

    class Meta:
        model = ReferralReward
        fields = ["id", "code", "referrer", "referred_client", "order", "order_reference", "reward", "status",
                  "paid_at", "paid_reference", "void_reason", "created_at"]
        read_only_fields = fields

    @extend_schema_field(MoneySchema)
    def get_reward(self, obj):
        return {"amount": f"{obj.amount:.2f}", "currency": obj.currency}


class ReferralRewardPaidInput(serializers.Serializer):
    reference = serializers.CharField()
