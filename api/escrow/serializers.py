"""ESC API serializers. Money is {"amount": "250.00", "currency": "GHS"} (7.1).
Account numbers appear in full only on the bank's payment instructions;
elsewhere only the last four digits are shown."""
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.money import MoneyField as _MoneyField

from .models import (Acceptance, BankEvent, BankPosition, Condition, Escrow, Freeze, FxConversion, FxQuote,
                     FxRateObservation, Party, Payee, PayeeChange, ProgrammeAccount, ProgrammeRate,
                     ReleaseInstruction, StandingApproval, StatementFile, StatementLine)


class MoneyIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    currency = serializers.CharField(max_length=3, min_length=3)


class MoneyOut(serializers.Serializer):
    amount = serializers.CharField()
    currency = serializers.CharField()


@extend_schema_field(MoneyOut)
class MoneyField(_MoneyField):
    """core.money.MoneyField with its OpenAPI shape."""


class BlockingReason(serializers.Serializer):
    rule = serializers.CharField()
    code = serializers.CharField()
    message = serializers.CharField()


# ----------------------------------------------------------------- payees

class PayeeSerializer(serializers.ModelSerializer):
    account_last4 = serializers.CharField(source="last4", read_only=True)
    name_match = serializers.CharField(read_only=True)

    class Meta:
        model = Payee
        fields = ["id", "country", "kind", "subject_type", "subject_id", "person", "organisation", "legal_name",
                  "bank_name", "account_name", "account_last4", "account_name_source", "name_match",
                  "verification_status", "prepared_by", "verified_by", "second_check_by", "verified_at",
                  "valid_until", "suspend_reason", "national_id_check", "account_version", "cooling_off_until",
                  "contact_email", "contact_phone", "row_version", "created_at"]
        read_only_fields = fields


class PayeeCreateSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    kind = serializers.ChoiceField(choices=[c for c, _ in Payee._meta.get_field("kind").choices])
    subject_type = serializers.ChoiceField(choices=Payee.SUBJECT_TYPES)
    subject_id = serializers.UUIDField()
    legal_name = serializers.CharField()
    legal_name_evidence_id = serializers.UUIDField()
    bank_name = serializers.CharField()
    account_number = serializers.CharField()
    account_name = serializers.CharField(required=False, allow_blank=True, default="")
    account_name_source = serializers.CharField()
    account_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    person_id = serializers.UUIDField(required=False, allow_null=True)
    organisation_id = serializers.UUIDField(required=False, allow_null=True)
    national_id_check_id = serializers.UUIDField(required=False, allow_null=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True, default="")
    contact_phone = serializers.CharField(required=False, allow_blank=True, default="")


class PayeeUpdateSerializer(serializers.Serializer):
    """Bank fields are accepted here only to refuse them with `payee-locked`
    (RUL-28): there is no other way in."""

    contact_email = serializers.EmailField(required=False)
    contact_phone = serializers.CharField(required=False)
    national_id_check_id = serializers.UUIDField(required=False)
    legal_name = serializers.CharField(required=False)
    legal_name_evidence_id = serializers.UUIDField(required=False)
    bank_name = serializers.CharField(required=False)
    account_number = serializers.CharField(required=False)
    account_name = serializers.CharField(required=False)
    account_name_source = serializers.CharField(required=False)
    account_name_evidence_id = serializers.UUIDField(required=False)


class PayeeChangeSerializer(serializers.ModelSerializer):
    account_last4 = serializers.SerializerMethodField()
    previous_last4 = serializers.SerializerMethodField()

    class Meta:
        model = PayeeChange
        fields = ["id", "country", "kind", "payee", "replaces_payee", "escrow", "deposit_event", "reason",
                  "request_source", "bank_name", "account_name", "account_last4", "account_name_source",
                  "account_checked_by", "previous_last4", "previous_account_name", "national_id_check",
                  "client_approved_at", "approval_request", "applied_at", "cooling_off_until", "stopped_at",
                  "stop_reason", "requested_by", "requested_at", "status"]
        read_only_fields = fields

    def get_account_last4(self, o) -> str:
        return o.account_number[-4:] if o.account_number else ""

    def get_previous_last4(self, o) -> str:
        return o.previous_account_number[-4:] if o.previous_account_number else ""


class PayeeChangeCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["new_account", "new_payee"])
    reason = serializers.CharField()
    request_source = serializers.CharField()
    escrow_id = serializers.UUIDField(required=False, allow_null=True)
    new_payee_id = serializers.UUIDField(required=False, allow_null=True)
    bank_name = serializers.CharField(required=False, allow_blank=True, default="")
    account_number = serializers.CharField(required=False, allow_blank=True, default="")
    account_name = serializers.CharField(required=False, allow_blank=True, default="")
    account_name_source = serializers.CharField(required=False, allow_blank=True, default="")
    account_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)


class RefundExceptionSerializer(serializers.Serializer):
    reason = serializers.CharField()
    bank_name = serializers.CharField()
    account_number = serializers.CharField()
    account_name = serializers.CharField(required=False, allow_blank=True, default="")
    account_name_source = serializers.CharField()
    account_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)


class IdentityCheckSerializer(serializers.Serializer):
    id_number = serializers.CharField(required=False, allow_blank=True, default="")
    subject_name = serializers.CharField(required=False, allow_blank=True, default="")
    national_id_check_id = serializers.UUIDField(required=False, allow_null=True)


# ----------------------------------------------------------------- generic inputs

class EscrowDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True, default="")
    confirm_amount = MoneyIn(required=False)


class ClientApprovalSerializer(serializers.Serializer):
    """Press and hold in the app, with a fresh MFA step-up or an authenticator code."""

    approve = serializers.BooleanField(default=True)
    code = serializers.CharField(required=False, allow_blank=True, default="")
    gesture = serializers.ChoiceField(choices=["press_and_hold"], default="press_and_hold")
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    escrow_id = serializers.UUIDField(required=False, allow_null=True)


class EscrowReasonSerializer(serializers.Serializer):
    reason = serializers.CharField()


class NoteEvidenceSerializer(serializers.Serializer):
    note = serializers.CharField()
    evidence_id = serializers.UUIDField()
    claim_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)
    claim_reference = serializers.CharField(required=False, allow_blank=True, default="")


class CheckSerializer(serializers.Serializer):
    confirm = serializers.BooleanField(default=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class StopSerializer(serializers.Serializer):
    token = serializers.CharField(required=False, allow_blank=True, default="")
    code = serializers.CharField(required=False, allow_blank=True, default="")
    reason = serializers.CharField(required=False, allow_blank=True, default="")


# ----------------------------------------------------------------- escrows

class PartySerializer(serializers.ModelSerializer):
    accepted_current_terms = serializers.SerializerMethodField()

    class Meta:
        model = Party
        fields = ["id", "role", "person", "organisation", "name", "payee", "national_id_check", "must_accept",
                  "accepted_current_terms"]
        read_only_fields = fields

    def get_accepted_current_terms(self, o) -> bool:
        return o.acceptances.filter(terms_version_id=o.escrow.terms_version_id).exists()


class AcceptanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Acceptance
        fields = ["id", "party", "terms_version", "terms_sha256", "accepted_by", "on_behalf", "evidence",
                  "accepted_at"]
        read_only_fields = fields


class ConditionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Condition
        fields = ["id", "source_condition_id", "key", "text", "status", "release_part", "closed_by", "closed_at",
                  "closed_note", "reopened_by", "reopened_at", "reopen_reason"]
        read_only_fields = fields


class FreezeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Freeze
        fields = ["id", "kind", "source_id", "prior_status", "reason", "frozen_at", "frozen_by", "lifted_at",
                  "lifted_by", "lift_note"]
        read_only_fields = fields


class EscrowSerializer(serializers.ModelSerializer):
    agreed_price = MoneyField(prefix="agreed", read_only=True)
    country = serializers.CharField(source="country.code", read_only=True)
    parties = PartySerializer(many=True, read_only=True)
    conditions = ConditionSerializer(many=True, read_only=True)
    funds = serializers.SerializerMethodField()
    payment_instructions = serializers.SerializerMethodField()
    agreement_blockers = serializers.SerializerMethodField()
    freezes = serializers.SerializerMethodField()

    class Meta:
        model = Escrow
        fields = ["id", "reference", "kind", "title", "country", "client", "asset_id", "report_id", "project_id",
                  "case_id", "bank_partner", "bank_reference", "virtual_account_ref", "agreed_price",
                  "held_back_amount", "held_back_condition", "currency", "conversion_choice", "fx_buffer_pct",
                  "terms_version", "status", "prior_status", "fresh_search_case_id", "fresh_search_result_date",
                  "site_check_date", "agreed_at", "funded_at", "closed_at", "cancel_requested_at", "cancel_reason",
                  "parties", "conditions", "funds", "payment_instructions", "agreement_blockers", "freezes",
                  "row_version", "created_at"]
        read_only_fields = fields

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_funds(self, o):
        from .selectors import confirmed_funds

        return [{k: (str(v) if v is not None and not isinstance(v, (dict, str)) else v) for k, v in f.items()}
                for f in confirmed_funds(o)]

    @extend_schema_field(serializers.DictField())
    def get_payment_instructions(self, o):
        from .services import payment_instructions

        return payment_instructions(o)

    @extend_schema_field(BlockingReason(many=True))
    def get_agreement_blockers(self, o):
        from .services import agreement_blockers

        return agreement_blockers(o) if o.status == "proposed" else []

    @extend_schema_field(FreezeSerializer(many=True))
    def get_freezes(self, o):
        return FreezeSerializer(o.freezes.filter(lifted_at__isnull=True), many=True).data


class EscrowListSerializer(serializers.ModelSerializer):
    agreed_price = MoneyField(prefix="agreed", read_only=True)
    country = serializers.CharField(source="country.code", read_only=True)

    class Meta:
        model = Escrow
        fields = ["id", "reference", "kind", "title", "country", "client", "status", "agreed_price", "currency",
                  "created_at"]
        read_only_fields = fields


class PartyIn(serializers.Serializer):
    role = serializers.ChoiceField(choices=["seller", "developer", "contractor", "supplier", "vendor"])
    name = serializers.CharField(required=False, allow_blank=True, default="")
    person_id = serializers.UUIDField(required=False, allow_null=True)
    organisation_id = serializers.UUIDField(required=False, allow_null=True)
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    national_id_check_id = serializers.UUIDField(required=False, allow_null=True)
    must_accept = serializers.BooleanField(default=True)


class ConditionIn(serializers.Serializer):
    text = serializers.CharField()
    key = serializers.CharField(required=False, allow_blank=True, default="")


class EscrowCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["purchase", "construction", "offplan", "project_fund", "held_funds",
                                            "repair", "event"])
    country = serializers.CharField(max_length=2)
    client_id = serializers.UUIDField(required=False, allow_null=True)
    agreed_price = MoneyIn(required=False)
    title = serializers.CharField(required=False, allow_blank=True, default="")
    report_id = serializers.UUIDField(required=False, allow_null=True)
    asset_id = serializers.UUIDField(required=False, allow_null=True)
    project_id = serializers.UUIDField(required=False, allow_null=True)
    case_id = serializers.UUIDField(required=False, allow_null=True)
    held_back_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, default=0)
    held_back_condition = serializers.CharField(required=False, allow_blank=True, default="")
    parties = PartyIn(many=True, required=False, default=list)
    conditions = ConditionIn(many=True, required=False, default=list)


class AcceptIn(serializers.Serializer):
    party_id = serializers.UUIDField(required=False, allow_null=True)
    evidence_id = serializers.UUIDField(required=False, allow_null=True)


class VirtualAccountIn(serializers.Serializer):
    virtual_account_ref = serializers.CharField()
    programme_account_id = serializers.UUIDField(required=False, allow_null=True)


class TermsVersionIn(serializers.Serializer):
    terms_version_id = serializers.UUIDField()


class FreshSearchIn(serializers.Serializer):
    case_id = serializers.UUIDField()
    registry_result_date = serializers.DateField()
    site_check_date = serializers.DateField()


class CloseConditionIn(serializers.Serializer):
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class BankEventIn(serializers.Serializer):
    kind = serializers.ChoiceField(choices=BankEvent.KINDS)
    amount = MoneyIn()
    bank_reference = serializers.CharField()
    occurred_at = serializers.DateTimeField(required=False)
    virtual_account_ref = serializers.CharField(required=False, allow_blank=True)
    proof_evidence_id = serializers.UUIDField()
    instruction_id = serializers.UUIDField(required=False, allow_null=True)
    source_bank_name = serializers.CharField(required=False, allow_blank=True, default="")
    source_account_number = serializers.CharField(required=False, allow_blank=True, default="")
    source_account_name = serializers.CharField(required=False, allow_blank=True, default="")
    source_account_known = serializers.BooleanField(default=True)
    deposit_route = serializers.ChoiceField(choices=["bank_transfer", "transfer_partner", "bank_correction"],
                                            required=False)
    transfer_partner_id = serializers.UUIDField(required=False, allow_null=True)
    partner_reference = serializers.CharField(required=False, allow_blank=True, default="")
    applied_rate = serializers.DecimalField(max_digits=18, decimal_places=8, required=False, allow_null=True)
    applied_fees = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    misdirected = serializers.BooleanField(default=False)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class BankEventSerializer(serializers.ModelSerializer):
    source_account_last4 = serializers.SerializerMethodField()

    class Meta:
        model = BankEvent
        fields = ["id", "escrow", "kind", "amount", "currency", "occurred_at", "bank_reference",
                  "virtual_account_ref", "source", "status", "proof_evidence", "entered_by", "checked_by",
                  "checked_at", "source_bank_name", "source_account_name", "source_account_last4",
                  "source_account_known", "source_cannot_receive", "deposit_route", "transfer_partner",
                  "instruction", "applied_rate", "applied_fees", "misdirected", "note", "created_at"]
        read_only_fields = fields

    def get_source_account_last4(self, o) -> str:
        return o.source_account_number[-4:] if o.source_account_number else ""


class ReleaseRequestIn(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["release", "partial_release"], required=False)
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    amount = MoneyIn(required=False)
    subject_type = serializers.CharField(required=False, allow_null=True)
    subject_id = serializers.UUIDField(required=False, allow_null=True)
    subject_label = serializers.CharField(required=False, allow_blank=True, default="")
    family_member_id = serializers.UUIDField(required=False, allow_null=True)
    holdback_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, default=0)
    release_part = serializers.ChoiceField(choices=["main", "held_back"], default="main")
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    standing_approval_id = serializers.UUIDField(required=False, allow_null=True)


class ConversionIn(serializers.Serializer):
    quote_id = serializers.UUIDField()


class InstructionSerializer(serializers.ModelSerializer):
    money = serializers.SerializerMethodField()
    escrow_reference = serializers.CharField(source="escrow.reference", read_only=True)
    payee_name = serializers.SerializerMethodField()
    payee_account_last4 = serializers.SerializerMethodField()
    approvals = serializers.SerializerMethodField()
    clock = serializers.SerializerMethodField()
    blocking_reasons = serializers.SerializerMethodField()

    class Meta:
        model = ReleaseInstruction
        fields = ["id", "escrow", "escrow_reference", "kind", "subject_type", "subject_id", "subject_label",
                  "family_member_id", "payee", "payee_name", "payee_account_last4", "payee_account_version", "money",
                  "amount", "currency", "holdback_amount", "to_currency", "fx_quote", "prepared_by", "reason",
                  "status", "client_approved_at", "client_approval_method", "release_part", "approvals", "clock",
                  "document_sha256", "sent_at", "sent_channel", "sent_recipient", "sent_reference",
                  "last_send_error", "shortfall_amount", "refund_source_event", "refund_change",
                  "bank_confirmation_event", "closed_reason", "blocking_reasons", "row_version", "created_at"]
        read_only_fields = fields

    @extend_schema_field(MoneyOut())
    def get_money(self, o):
        return {"amount": f"{o.amount:.2f}", "currency": o.currency}

    def get_payee_name(self, o) -> str:
        return o.payee.account_name if o.payee_id else ""

    def get_payee_account_last4(self, o) -> str:
        return o.payee.last4 if o.payee_id else ""

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_approvals(self, o):
        return [{"slot": a.slot, "approver": a.approver.full_name, "decision": a.decision,
                 "at": a.approved_at.isoformat()}
                for a in o.approval_request.approvals.select_related("approver").order_by("approved_at")]

    @extend_schema_field(serializers.DictField())
    def get_clock(self, o):
        from .services import clock

        return {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in clock(o).items()}

    @extend_schema_field(BlockingReason(many=True))
    def get_blocking_reasons(self, o):
        from .services import release_blockers

        if o.status not in ("awaiting_client", "pending_approval", "approved"):
            return []
        stage = {"awaiting_client": "client", "pending_approval": "staff", "approved": "send"}[o.status]
        return [{k: v for k, v in r.items() if k in ("rule", "code", "message")} for r in release_blockers(o, stage)]


class StatementSerializer(serializers.Serializer):
    escrow_id = serializers.UUIDField()
    reference = serializers.CharField()
    lines = serializers.ListField(child=serializers.DictField())
    funds = serializers.ListField(child=serializers.DictField())


class FundsSerializer(serializers.Serializer):
    currency = serializers.CharField()
    virtual_account_ref = serializers.CharField(allow_null=True)
    held_at_bank = serializers.CharField()
    instructed_awaiting_bank = serializers.CharField()
    awaiting_correction = serializers.CharField()
    available_to_instruct = serializers.CharField()
    last_bank_event_at = serializers.DateTimeField(allow_null=True)
    latest_bank_figure = serializers.DictField(allow_null=True)


class BankPositionIn(serializers.Serializer):
    as_of = serializers.DateField()
    reported_held = MoneyIn()
    proof_evidence_id = serializers.UUIDField()


class BankPositionSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankPosition
        fields = ["id", "escrow", "virtual_account_ref", "as_of", "reported_held_amount", "currency", "source",
                  "derived_held_at_bank", "status", "entered_by", "checked_by", "resolved_by",
                  "resolution_checked_by", "resolution_note", "resolved_at", "created_at"]
        read_only_fields = fields


class HoldIn(serializers.Serializer):
    reason = serializers.CharField()


class StandingApprovalIn(serializers.Serializer):
    subject_kind = serializers.ChoiceField(choices=["care_plan", "errand"])
    subject_id = serializers.UUIDField()
    monthly_max = serializers.DecimalField(max_digits=18, decimal_places=2)
    code = serializers.CharField(required=False, allow_blank=True, default="")


class StandingApprovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = StandingApproval
        fields = ["id", "escrow", "subject_kind", "subject_id", "monthly_max", "currency", "approved_at", "status",
                  "withdrawn_at"]
        read_only_fields = fields


class CancellationIn(serializers.Serializer):
    reason = serializers.CharField()


class BankRejectionIn(serializers.Serializer):
    reason = serializers.CharField()
    proof_evidence_id = serializers.UUIDField()
    source_cannot_receive = serializers.BooleanField(default=False)


# ----------------------------------------------------------------- statements and accounts

class StatementUploadIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    content = serializers.CharField(help_text="The CSV file's text, as the bank sent it.")
    original_name = serializers.CharField(required=False, default="statement.csv")
    account_kind = serializers.ChoiceField(choices=StatementFile.ACCOUNT_KINDS, default="escrow")


class StatementFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatementFile
        fields = ["id", "country", "account_kind", "sha256", "original_name", "line_count", "matched_count",
                  "unmatched_count", "uploaded_by", "created_at"]
        read_only_fields = fields


class StatementLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatementLine
        fields = ["id", "line_no", "booked_on", "kind", "amount", "currency", "virtual_account_ref",
                  "bank_reference", "counterparty_name", "narrative", "match_status", "escrow", "bank_event", "note"]
        read_only_fields = fields


class ProgrammeAccountSerializer(serializers.ModelSerializer):
    account_last4 = serializers.CharField(source="last4", read_only=True)

    class Meta:
        model = ProgrammeAccount
        fields = ["id", "country", "bank_partner", "currency", "kind", "holder", "account_name", "account_last4",
                  "agreement_evidence", "approval_request", "status", "opened_on", "closed_on", "created_at"]
        read_only_fields = fields


class ProgrammeAccountIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    bank_partner_id = serializers.UUIDField()
    currency = serializers.CharField(max_length=3)
    kind = serializers.ChoiceField(choices=ProgrammeAccount.KINDS, default="programme")
    account_number = serializers.CharField()
    account_name = serializers.CharField()
    agreement_evidence_id = serializers.UUIDField()


class ProgrammeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProgrammeRate
        fields = ["id", "country", "bank_partner", "from_currency", "to_currency", "band_from", "band_to",
                  "margin_pct", "tolerance_pct", "fee_schedule", "reference_source", "valid_from", "valid_to",
                  "agreement_evidence", "approval_request", "status", "created_at"]
        read_only_fields = fields


class ProgrammeRateIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    bank_partner_id = serializers.UUIDField()
    from_currency = serializers.CharField(max_length=3)
    to_currency = serializers.CharField(max_length=3)
    band_from = serializers.DecimalField(max_digits=18, decimal_places=2, default=0)
    band_to = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    margin_pct = serializers.DecimalField(max_digits=7, decimal_places=4)
    tolerance_pct = serializers.DecimalField(max_digits=7, decimal_places=4, default=0)
    fee_schedule = serializers.ListField(child=serializers.DictField())
    reference_source_id = serializers.UUIDField()
    valid_from = serializers.DateField()
    valid_to = serializers.DateField(required=False, allow_null=True)
    agreement_evidence_id = serializers.UUIDField()


# ----------------------------------------------------------------- exchange

class QuoteIn(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=FxQuote.PURPOSES, default="deposit")
    route = serializers.ChoiceField(choices=FxQuote.ROUTES)
    amount = MoneyIn()
    provider_partner_id = serializers.UUIDField(required=False, allow_null=True)
    client_rate = serializers.DecimalField(max_digits=18, decimal_places=8, required=False, allow_null=True)


class FxQuoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = FxQuote
        fields = ["id", "escrow", "purpose", "route", "provider_partner", "from_currency", "from_amount",
                  "to_currency", "reference_observation", "reference_rate", "offered_rate", "margin_pct",
                  "programme_rate", "fees", "fees_total_to", "expected_to_amount", "limits_text", "tenmina_margin",
                  "partner_payment_to_tenmina", "partner_payment_currency", "is_estimate", "best_rate_claim",
                  "comparison_run", "shown_text", "shown_sha256", "quoted_at", "expires_at", "accepted_by",
                  "accepted_at"]
        read_only_fields = fields


class AcceptQuoteIn(serializers.Serializer):
    shown_sha256 = serializers.CharField()
    code = serializers.CharField(required=False, allow_blank=True, default="")


class ConversionChoiceIn(serializers.Serializer):
    conversion_choice = serializers.ChoiceField(choices=["on_deposit", "at_release"])
    code = serializers.CharField(required=False, allow_blank=True, default="")


class FxConversionSerializer(serializers.ModelSerializer):
    quote = FxQuoteSerializer(read_only=True)

    class Meta:
        model = FxConversion
        fields = ["id", "escrow", "quote", "route", "instruction", "from_amount", "to_amount", "applied_rate",
                  "applied_fees", "reference_rate", "margin_pct", "programme_rate", "short_of_quote", "status",
                  "findings", "claim_amount", "claimed_at", "claim_reference", "resolved_by",
                  "resolution_checked_by", "resolution_note", "created_at"]
        read_only_fields = fields


class FxAccountIn(serializers.Serializer):
    currency = serializers.CharField(max_length=3)
    virtual_account_ref = serializers.CharField()


class ObservationIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    source_partner_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=FxRateObservation.KINDS)
    from_currency = serializers.CharField(max_length=3)
    to_currency = serializers.CharField(max_length=3)
    rate = serializers.DecimalField(max_digits=18, decimal_places=8)
    send_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    fees_total = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    delivered_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False, allow_null=True)
    proof_evidence_id = serializers.UUIDField()


class ObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = FxRateObservation
        fields = ["id", "country", "source_partner", "kind", "from_currency", "to_currency", "rate", "send_amount",
                  "fees_total", "delivered_amount", "source_published_at", "collected_at", "method", "entered_by",
                  "checked_by"]
        read_only_fields = fields


class CollectIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)


class ComparisonSerializer(serializers.Serializer):
    run_id = serializers.CharField()
    run_date = serializers.CharField()
    pair = serializers.CharField()
    send_amount = serializers.CharField()
    status = serializers.CharField()
    providers_expected = serializers.IntegerField()
    providers_fresh = serializers.IntegerField()
    reference_rate = serializers.CharField(allow_null=True)
    last_success_at = serializers.CharField(allow_null=True)
    items = serializers.ListField(child=serializers.DictField())
    bank_best_rate = serializers.BooleanField()
    statement = serializers.CharField()


class DepositRoutesSerializer(serializers.Serializer):
    escrow_id = serializers.CharField()
    currency = serializers.CharField()
    amount = serializers.CharField()
    to_currency = serializers.CharField()
    tenmina_margin_line = serializers.CharField()
    routes = serializers.ListField(child=serializers.DictField())
    unavailable = serializers.ListField(child=serializers.DictField())
    comparison = serializers.DictField(allow_null=True)


class HeldFundsIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    currency = serializers.CharField(max_length=3, required=False)
