from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from orders.serializers import MoneyField, MoneySchema

from . import services
from .adapters import FAKE_OUTCOMES
from .models import FeePayment, Invoice, Receipt, ReconIssue, Refund, SettlementLine, SettlementRun


class StrictSerializer(serializers.Serializer):
    """Refuses fields it does not know. A payment or refund request can never carry an amount, purpose,
    card, wallet or account of the caller's choosing (FR-PAY-005, FR-PAY-008, TC-RUL-01-03, TC-PAY-008-02)."""

    def unknown_fields(self):
        data = self.initial_data if hasattr(self.initial_data, "keys") else {}
        return sorted(set(data.keys()) - set(self.fields))

    def validate(self, attrs):
        unknown = self.unknown_fields()
        if unknown:
            raise serializers.ValidationError({k: "This field is not accepted." for k in unknown})
        return attrs


class PaySourceAccountSerializer(serializers.Serializer):
    bank = serializers.CharField(source="source_bank_name")
    name = serializers.CharField(source="source_account_name")
    number_last4 = serializers.SerializerMethodField()

    def get_number_last4(self, obj) -> str:
        return obj.source_account_number[-4:] if obj.source_account_number else ""


class PaymentSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    order_reference = serializers.CharField(source="order.reference", read_only=True, default=None)
    invoice_number = serializers.CharField(source="invoice.number", read_only=True, default=None)
    refunded = serializers.SerializerMethodField()
    refundable = serializers.SerializerMethodField()
    can_retry = serializers.SerializerMethodField()
    receipt = serializers.SerializerMethodField()
    source_account = serializers.SerializerMethodField()

    class Meta:
        model = FeePayment
        fields = ["id", "order", "order_reference", "invoice", "invoice_number", "purpose", "amount", "method",
                  "provider", "provider_ref", "checkout_url", "return_url", "card_brand", "card_last4",
                  "wallet_last4", "status", "failure_code", "failure_message", "can_retry", "confirmed_at",
                  "failed_at", "refunded", "refundable", "receipt", "offline_reference", "received_on",
                  "source_account", "recorded_by", "approval_request", "created_at", "updated_at"]
        read_only_fields = fields

    @extend_schema_field(MoneySchema)
    def get_amount(self, obj):
        return {"amount": f"{obj.amount:.2f}", "currency": obj.currency}

    @extend_schema_field(MoneySchema)
    def get_refunded(self, obj):
        return {"amount": f"{obj.refunded_amount:.2f}", "currency": obj.currency}

    @extend_schema_field(MoneySchema)
    def get_refundable(self, obj):
        left = services.refundable_amount(obj) if obj.status in ("confirmed", "partially_refunded") else 0
        return {"amount": f"{left:.2f}", "currency": obj.currency}

    def get_can_retry(self, obj) -> bool:
        if obj.status != "failed":
            return False
        if obj.order_id:
            return obj.order.status == "awaiting_payment"
        return bool(obj.invoice_id and obj.invoice.status == "issued")

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_receipt(self, obj):
        r = obj.receipts.filter(kind="receipt").first()
        return {"id": str(r.pk), "number": r.number, "href": f"/v1/payments/{obj.pk}/receipt"} if r else None

    @extend_schema_field(PaySourceAccountSerializer(allow_null=True))
    def get_source_account(self, obj):
        if obj.method != "bank_transfer_offline":
            return None
        return PaySourceAccountSerializer(obj).data


class PaymentStartInput(StrictSerializer):
    method = serializers.ChoiceField(choices=["card", "mobile_money"])
    return_url = serializers.CharField(required=False, allow_blank=True)
    wallet_phone = serializers.CharField(required=False, allow_blank=True,
                                         help_text="Mobile money number for the prompt. Only the last 4 are kept.")


class PaymentStartedSerializer(serializers.Serializer):
    payment = PaymentSerializer()
    checkout_url = serializers.CharField()


class FakeCheckoutInput(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=sorted(FAKE_OUTCOMES))
    refundable = serializers.BooleanField(required=False, default=True,
                                          help_text="False simulates a card or wallet that is later closed.")


class FakeCheckoutInfoSerializer(serializers.Serializer):
    payment_id = serializers.UUIDField()
    provider_ref = serializers.CharField()
    merchant = serializers.CharField()
    amount = MoneySchema()
    method = serializers.CharField()
    status = serializers.CharField()
    outcomes = serializers.ListField(child=serializers.CharField())
    note = serializers.CharField()


class WebhookAckSerializer(serializers.Serializer):
    status = serializers.CharField()
    event_id = serializers.CharField()
    outcome = serializers.CharField(required=False)


class ReceiptSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    refund = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Receipt
        fields = ["id", "number", "kind", "country", "payment", "refund", "issued_to", "issued_to_name", "amount",
                  "description", "order_reference", "invoice_number", "method", "method_detail", "issued_at",
                  "sha256"]
        read_only_fields = fields

    @extend_schema_field(MoneySchema)
    def get_amount(self, obj):
        return {"amount": f"{obj.amount:.2f}", "currency": obj.currency}


class PaymentReceiptsSerializer(serializers.Serializer):
    receipt = ReceiptSerializer(allow_null=True)
    credit_notes = ReceiptSerializer(many=True)


class OfflinePaymentInput(StrictSerializer):
    order_id = serializers.UUIDField(required=False)
    invoice_id = serializers.UUIDField(required=False)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(max_length=3)
    reference = serializers.CharField(help_text="The bank's or wallet's transaction reference.")
    received_on = serializers.DateField()
    source_bank_name = serializers.CharField()
    source_account_name = serializers.CharField()
    source_account_number = serializers.CharField(required=False, allow_blank=True)
    proof_evidence_id = serializers.UUIDField(required=False)
    proof = serializers.FileField(required=False)


class PayDecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True)


class PayApprovalStateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    required = serializers.IntegerField()
    approvals = serializers.IntegerField()
    prepared_by = serializers.UUIDField(source="prepared_by_id")


class RefundSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    order = serializers.UUIDField(source="payment.order_id", read_only=True, allow_null=True)
    destination = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()
    credit_note = serializers.SerializerMethodField()

    class Meta:
        model = Refund
        fields = ["id", "payment", "order", "amount", "reason", "status", "requested_by", "destination",
                  "approval", "provider_refund_ref", "attempts", "failure_message", "approved_at", "completed_at",
                  "completed_by", "credit_note", "created_at"]
        read_only_fields = fields

    @extend_schema_field(MoneySchema)
    def get_amount(self, obj):
        return {"amount": f"{obj.amount:.2f}", "currency": obj.currency}

    def get_destination(self, obj) -> str:
        """Read-only: where the money goes. It cannot be chosen (FR-PAY-008)."""
        p = obj.payment
        if p.method == "bank_transfer_offline":
            return f"Back to the account it came from: {p.source_account_name}, {p.source_bank_name}"
        return f"Back through the payment provider to the original payment: {services._method_detail(p)}"

    @extend_schema_field(PayApprovalStateSerializer(allow_null=True))
    def get_approval(self, obj):
        req = obj.approval_request
        if req is None:
            return None
        return {"id": str(req.pk), "status": req.status, "required": req.required,
                "approvals": req.approvals.filter(decision="approve").count(), "prepared_by": str(req.prepared_by_id)}

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_credit_note(self, obj):
        r = Receipt.objects.filter(refund=obj).first()
        return r.number if r else None


class RefundCreateInput(StrictSerializer):
    payment_id = serializers.UUIDField(required=False)
    order_id = serializers.UUIDField(required=False)
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False,
                                      help_text="Defaults to everything still refundable.")
    reason = serializers.CharField(allow_blank=True)


class OfflineRefundCompletionInput(StrictSerializer):
    bank_reference = serializers.CharField()
    proof_evidence_id = serializers.UUIDField(required=False)
    proof = serializers.FileField(required=False)


class SettlementLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = SettlementLine
        fields = ["id", "provider_ref", "amount", "currency", "fee_amount", "net_amount", "settled_at", "payment",
                  "match_status"]


class SettlementRunSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    duplicate = serializers.SerializerMethodField()

    class Meta:
        model = SettlementRun
        fields = ["id", "country", "provider", "settlement_date", "source", "file_sha256", "line_count", "matched",
                  "issues", "run_by", "duplicate", "created_at"]

    def get_duplicate(self, obj) -> bool:
        return bool(getattr(obj, "duplicate", False))


class SettlementRunDetailSerializer(SettlementRunSerializer):
    lines = SettlementLineSerializer(many=True, read_only=True)

    class Meta(SettlementRunSerializer.Meta):
        fields = SettlementRunSerializer.Meta.fields + ["lines"]


class SettlementRunInput(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    settlement_date = serializers.DateField()
    file = serializers.FileField(required=False, help_text="The provider's settlement file (CSV or JSON). "
                                                           "Without it, the report is fetched from the provider.")


class ReconIssueSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = ReconIssue
        fields = ["id", "country", "kind", "payment", "refund", "line", "run", "provider_ref", "detail", "status",
                  "resolved_by", "resolved_at", "resolution", "created_at"]
        read_only_fields = fields


class ReconResolutionInput(serializers.Serializer):
    resolution = serializers.CharField()


class SellerInvoiceSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)

    class Meta:
        model = Invoice
        fields = ["id", "number", "kind", "purpose", "country", "organisation", "organisation_name",
                  "bill_to_person", "order", "subject_type", "subject_id", "description", "amount", "status",
                  "issued_at", "due_on", "paid_at", "void_reason", "created_at"]
        read_only_fields = fields

    @extend_schema_field(MoneySchema)
    def get_amount(self, obj):
        return {"amount": f"{obj.amount:.2f}", "currency": obj.currency}


class SellerInvoiceCreateInput(serializers.Serializer):
    organisation_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=Invoice.KINDS)
    description = serializers.CharField()
    amount = MoneyField(prefix="amount", required=False, help_text="Defaults to the configured price.")
    bill_to_person = serializers.UUIDField(required=False, allow_null=True)
    subject_type = serializers.CharField(required=False, allow_blank=True)
    subject_id = serializers.UUIDField(required=False, allow_null=True)
    issue = serializers.BooleanField(required=False, default=True)


class InvoiceVoidInput(serializers.Serializer):
    reason = serializers.CharField()
