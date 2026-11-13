"""PRJ API serializers."""
from rest_framework import serializers

from construction.serializers import Money2, MoneyIn

from .models import NO_ADVICE_STATEMENT, Agreement, AmlReview, BackgroundCheck, Invoice, Supplier


class SupplierSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    payee_id = serializers.UUIDField(read_only=True, allow_null=True)
    payee_verified = serializers.SerializerMethodField()
    account_last4 = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = ["id", "project_id", "name", "what_they_supply", "contact_name", "contact_phone", "contact_email",
                  "registration_number", "bank_name", "account_last4", "account_name", "status", "missing",
                  "check_case_id", "payee_id", "payee_verified", "status_reason", "created_at"]

    def get_payee_verified(self, obj) -> bool:
        return bool(obj.payee_id and obj.payee.verification_status == "verified")

    def get_account_last4(self, obj) -> str:
        return (obj.account_number or "")[-4:]


class SupplierInput(serializers.Serializer):
    name = serializers.CharField(required=False)
    what_they_supply = serializers.CharField(required=False, allow_blank=True)
    contact_name = serializers.CharField(required=False, allow_blank=True)
    contact_phone = serializers.CharField(required=False, allow_blank=True)
    contact_email = serializers.CharField(required=False, allow_blank=True)
    registration_number = serializers.CharField(required=False, allow_blank=True)
    bank_name = serializers.CharField(required=False, allow_blank=True)
    account_number = serializers.CharField(required=False, allow_blank=True)
    account_name = serializers.CharField(required=False, allow_blank=True)


class SupplierPayeeInput(serializers.Serializer):
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    legal_name_evidence_id = serializers.UUIDField(required=False)
    account_name = serializers.CharField(required=False, allow_blank=True)
    account_name_source = serializers.ChoiceField(choices=["bank_name_check", "bank_letter"], required=False)
    account_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    national_id_check_id = serializers.UUIDField(required=False, allow_null=True,
                                                 help_text="The identity check on the person who signs for the "
                                                           "supplier (RUL-31).")


class CheckSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    supplier_id = serializers.UUIDField(read_only=True, allow_null=True)
    national_id_result = serializers.CharField(source="national_id_check.result", read_only=True, allow_null=True)

    class Meta:
        model = BackgroundCheck
        fields = ["id", "project_id", "subject_kind", "supplier_id", "subject_name", "level", "status", "case_id",
                  "national_id_result", "note", "decided_at", "created_at"]


class StartChecksInput(serializers.Serializer):
    runner_id_number = serializers.CharField(required=False, allow_blank=True,
                                             help_text="The national identity number of the person running it.")


class RunnerCheckInput(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["passed", "failed"])
    note = serializers.CharField(required=False, allow_blank=True)
    evidence_id = serializers.UUIDField(required=False, allow_null=True)
    id_number = serializers.CharField(required=False, allow_blank=True)


class AmlSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    threshold = Money2("threshold_amount", "threshold_currency")
    budget = Money2("budget_in_threshold_currency", "threshold_currency")

    class Meta:
        model = AmlReview
        fields = ["id", "project_id", "threshold", "budget", "status", "source_of_funds", "purpose",
                  "evidence_ids", "decided_at", "note"]


class AmlInput(serializers.Serializer):
    source_of_funds = serializers.CharField()
    purpose = serializers.CharField()
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class AmlDecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"])
    note = serializers.CharField(required=False, allow_blank=True)


class AgreementSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    no_advice_statement = serializers.SerializerMethodField()

    class Meta:
        model = Agreement
        fields = ["id", "project_id", "version", "text", "text_sha256", "no_advice_statement", "accepted_at"]

    def get_no_advice_statement(self, obj) -> str:
        return NO_ADVICE_STATEMENT


class InvoiceSerializer(serializers.ModelSerializer):
    project_id = serializers.UUIDField(read_only=True)
    milestone_id = serializers.UUIDField(read_only=True)
    supplier_id = serializers.UUIDField(read_only=True)
    supplier_name = serializers.CharField(source="supplier.name", read_only=True)
    amount = Money2("amount", "currency")
    evidence_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Invoice
        fields = ["id", "project_id", "milestone_id", "supplier_id", "supplier_name", "number", "amount",
                  "description", "evidence_id", "status", "accepted_at", "reject_reason", "paid_at", "created_at"]


class InvoiceInput(serializers.Serializer):
    supplier_id = serializers.UUIDField()
    milestone_id = serializers.UUIDField()
    number = serializers.CharField()
    amount = MoneyIn()
    description = serializers.CharField(required=False, allow_blank=True)
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


class InvoiceDecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["accept", "reject"])
    reason = serializers.CharField(required=False, allow_blank=True)


class StageCloseInput(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class StageClosed(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
