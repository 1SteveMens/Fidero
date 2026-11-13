"""EVT API shapes. Money is {"amount", "currency"} (7.1)."""
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from core.money import MoneyField as _MoneyField

from .models import EVENT_KINDS, PAYMENT_KINDS, VENDOR_KINDS, Event, Vendor, VendorPayment

MONEY = {"type": "object", "properties": {"amount": {"type": "string"}, "currency": {"type": "string"}}}


@extend_schema_field(MONEY)
class MoneyField(_MoneyField):
    """core.money.MoneyField with its OpenAPI shape."""


@extend_schema_serializer(component_name="EvtMoneyIn")
class MoneyIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    currency = serializers.CharField(min_length=3, max_length=3)


@extend_schema_serializer(component_name="EvtEventCreate")
class EventCreate(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    kind = serializers.ChoiceField(choices=EVENT_KINDS)
    name = serializers.CharField()
    event_date = serializers.DateField()
    budget = MoneyIn()
    locality = serializers.CharField(required=False, allow_blank=True, default="")
    client_id = serializers.UUIDField(required=False, help_text="Staff only: the client the event is for.")
    confirmer_family_member_id = serializers.UUIDField(required=False, allow_null=True)


@extend_schema_serializer(component_name="EvtBudgetIn")
class BudgetIn(serializers.Serializer):
    budget = MoneyIn()
    reason = serializers.CharField()


@extend_schema_serializer(component_name="EvtConfirmerIn")
class ConfirmerIn(serializers.Serializer):
    family_member_id = serializers.UUIDField()


@extend_schema_serializer(component_name="EvtReasonIn")
class ReasonIn(serializers.Serializer):
    reason = serializers.CharField()


@extend_schema_serializer(component_name="EvtVendorCreate")
class VendorCreate(serializers.Serializer):
    kind = serializers.ChoiceField(choices=VENDOR_KINDS)
    name = serializers.CharField()
    is_organisation = serializers.BooleanField(default=True)
    registration_number = serializers.CharField(required=False, allow_blank=True, default="")
    registration_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    contact_name = serializers.CharField(required=False, allow_blank=True, default="")
    contact_phone = serializers.CharField(required=False, allow_blank=True, default="")
    quote = MoneyIn(required=False)
    quote_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    payee_id = serializers.UUIDField(required=False, allow_null=True,
                                     help_text="Staff: a vendor payee already verified for another event.")


@extend_schema_serializer(component_name="EvtVendorPayeeIn")
class VendorPayeeIn(serializers.Serializer):
    legal_name = serializers.CharField()
    bank_name = serializers.CharField()
    account_number = serializers.CharField()
    account_name_source = serializers.ChoiceField(choices=["bank_name_check", "bank_letter"])
    account_name = serializers.CharField(required=False, allow_blank=True, default="")
    account_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    legal_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    signatory_name = serializers.CharField(required=False, allow_blank=True, default="")
    signatory_id_number = serializers.CharField(required=False, allow_blank=True, default="")
    contact_email = serializers.EmailField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="EvtPaymentCreate")
class PaymentCreate(serializers.Serializer):
    vendor_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=PAYMENT_KINDS)
    amount = MoneyIn()
    quote_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    invoice_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    delivery_evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    description = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="EvtPaymentEvidenceIn")
class PaymentEvidenceIn(serializers.Serializer):
    invoice_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    delivery_evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


@extend_schema_serializer(component_name="EvtClientApprovalIn")
class ClientApprovalIn(serializers.Serializer):
    confirm_amount = MoneyIn(required=False)
    acknowledge_budget_warning = serializers.BooleanField(default=False)


@extend_schema_serializer(component_name="EvtCodeIn")
class CodeIn(serializers.Serializer):
    code = serializers.CharField(min_length=4, max_length=12)


@extend_schema_serializer(component_name="EvtVendor")
class VendorSerializer(serializers.ModelSerializer):
    quote = MoneyField(prefix="quote", read_only=True)
    payee = serializers.SerializerMethodField()
    blockers = serializers.SerializerMethodField()

    class Meta:
        model = Vendor
        fields = ["id", "event", "kind", "name", "is_organisation", "registration_number", "registration_evidence",
                  "contact_name", "contact_phone", "quote", "quote_evidence", "payee", "verification_case", "status",
                  "verified_at", "blockers", "created_at"]

    @extend_schema_field({"type": "object", "nullable": True,
                          "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                                         "status": {"type": "string"}, "account_last4": {"type": "string"}}})
    def get_payee(self, obj):
        p = obj.payee
        return None if p is None else {"id": str(p.pk), "name": p.legal_name, "status": p.verification_status,
                                       "account_last4": p.last4}

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_blockers(self, obj):
        from .services import vendor_blockers

        return vendor_blockers(obj) if obj.status in ("unverified", "verifying") else []


@extend_schema_serializer(component_name="EvtPayment")
class PaymentSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    amount = serializers.SerializerMethodField()
    missing = serializers.SerializerMethodField()
    confirmation_status = serializers.SerializerMethodField()

    class Meta:
        model = VendorPayment
        fields = ["id", "event", "vendor", "vendor_name", "kind", "amount", "description", "quote_evidence",
                  "invoice_evidence", "delivery_evidence_ids", "family_confirmed_at", "confirmation_status",
                  "evidenced_at", "client_approved_at", "release_instruction", "paid_at", "bank_reference", "status",
                  "reject_reason", "missing", "created_at", "row_version"]

    @extend_schema_field(MONEY)
    def get_amount(self, obj):
        return {"amount": f"{obj.amount:.2f}", "currency": obj.currency}

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_missing(self, obj):
        from .services import evidence_missing

        return evidence_missing(obj) if obj.status == "proposed" else []

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_confirmation_status(self, obj):
        from notifications.services import confirmation_status

        if obj.kind == "deposit":
            return None
        c = confirmation_status("event_vendor_payment", obj.pk)
        return c.status if c else None


@extend_schema_serializer(component_name="EvtEvent")
class EventSerializer(serializers.ModelSerializer):
    budget = MoneyField(prefix="budget", read_only=True)
    escrow_reference = serializers.SerializerMethodField()
    escrow_status = serializers.SerializerMethodField()
    confirmer = serializers.SerializerMethodField()
    warnings = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = ["id", "country", "client", "kind", "name", "event_date", "locality", "budget", "budget_history",
                  "escrow", "escrow_reference", "escrow_status", "confirmer", "status", "fee_order_id", "warnings",
                  "closed_at", "cancel_reason", "created_at", "row_version"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_escrow_reference(self, obj):
        return obj.escrow.reference if obj.escrow_id else None

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_escrow_status(self, obj):
        return obj.escrow.status if obj.escrow_id else None

    @extend_schema_field({"type": "object", "nullable": True, "properties": {"id": {"type": "string"},
                                                                           "name": {"type": "string"}}})
    def get_confirmer(self, obj):
        fm = obj.confirmer_family_member
        return None if fm is None else {"id": str(fm.pk), "name": fm.full_name}

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_warnings(self, obj):
        from .services import budget_warnings

        return budget_warnings(obj)


@extend_schema_serializer(component_name="EvtEventDetail")
class EventDetailSerializer(EventSerializer):
    vendors = serializers.SerializerMethodField()
    budget_vs_actual = serializers.SerializerMethodField()

    class Meta(EventSerializer.Meta):
        fields = EventSerializer.Meta.fields + ["vendors", "budget_vs_actual"]

    @extend_schema_field(VendorSerializer(many=True))
    def get_vendors(self, obj):
        return VendorSerializer(obj.vendors.exclude(status="removed").order_by("created_at"), many=True).data

    @extend_schema_field(serializers.DictField())
    def get_budget_vs_actual(self, obj):
        from .services import budget_vs_actual

        return budget_vs_actual(obj)


@extend_schema_serializer(component_name="EvtReceipt")
class ReceiptSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    vendor = serializers.CharField()
    paid_to = serializers.CharField()
    account_last4 = serializers.CharField()
    amount = serializers.DictField()
    kind = serializers.CharField()
    paid_at = serializers.DateTimeField(allow_null=True)
    bank_reference = serializers.CharField()
    instruction_id = serializers.CharField()
    evidence_ids = serializers.ListField(child=serializers.CharField())
    note = serializers.CharField()


@extend_schema_serializer(component_name="EvtEscrowOpened")
class EscrowOpened(serializers.Serializer):
    escrow_id = serializers.UUIDField()
    reference = serializers.CharField()
    status = serializers.CharField()
    pay_to = serializers.DictField()
