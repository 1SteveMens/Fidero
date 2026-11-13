"""PRO API serializers. Money is {"amount": "250.00", "currency": "GHS"} (7.1).

RUL-26: input serializers reject unknown fields, so a rate can never be sent
with a verdict, outcome or any other result attached (US-PRO-003 AC1). Pay
screens show no verdict: no serializer here carries one."""
from rest_framework import serializers

from .models import (EXPENSE_KINDS, HOLD_REASONS, ROLES, UNITS, Agreement, Document, ExpenseClaim, Payable,
                     PaymentLine, PaymentRun, RateCard, Scope)


class Strict(serializers.Serializer):
    """Refuses fields it does not know (TC-RUL-26-02)."""

    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown = sorted(set(data.keys()) - set(self.fields))
            if unknown:
                raise serializers.ValidationError({k: "This field does not exist." for k in unknown})
        return super().to_internal_value(data)


class ProMoney(serializers.Serializer):
    amount = serializers.CharField(read_only=True)
    currency = serializers.CharField(read_only=True)

    def __init__(self, amount_attr, currency_attr="currency", **kw):
        kw.setdefault("source", "*")
        kw.setdefault("read_only", True)
        super().__init__(**kw)
        self._a, self._c = amount_attr, currency_attr

    def to_representation(self, obj):
        amount = getattr(obj, self._a, None)
        if amount is None:
            return None
        return {"amount": f"{amount:.2f}", "currency": getattr(obj, self._c)}


class ProReason(serializers.Serializer):
    rule = serializers.CharField()
    code = serializers.CharField(required=False)
    message = serializers.CharField()


# ------------------------------------------------------------------ agreements

class ProAgreementSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    professional_name = serializers.CharField(source="professional.full_name", read_only=True)
    destination = serializers.SerializerMethodField()
    payable_now = serializers.SerializerMethodField()

    class Meta:
        model = Agreement
        fields = ["id", "reference", "country", "professional", "professional_name", "role", "contracting_party",
                  "organisation", "agreement_evidence", "tax_status", "payee", "bank_account", "destination",
                  "payable_now", "valid_from", "valid_to", "status", "status_reason", "row_version", "created_at"]
        read_only_fields = fields

    def get_destination(self, a) -> dict | None:
        d = a.payee or a.bank_account
        if d is None:
            return None
        return {"kind": "payee" if a.payee_id else "bank_account", "bank_name": d.bank_name,
                "account_name": d.account_name, "account_last4": d.last4,
                "verification_status": d.verification_status, "name_match": d.name_match}

    def get_payable_now(self, a) -> list[dict]:
        from .services import destination_reasons

        return destination_reasons(a)


class ProAgreementIn(Strict):
    country = serializers.CharField(max_length=2)
    professional_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=ROLES)
    agreement_evidence_id = serializers.UUIDField()
    contracting_party = serializers.ChoiceField(choices=Agreement.PARTIES, default="person")
    organisation_id = serializers.UUIDField(required=False, allow_null=True)
    tax_status = serializers.ChoiceField(choices=Agreement.TAX_STATUSES, default="not_registered")
    tax_id = serializers.CharField(required=False, allow_blank=True, default="")
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    bank_account_id = serializers.UUIDField(required=False, allow_null=True)
    valid_from = serializers.DateField(required=False)
    valid_to = serializers.DateField(required=False, allow_null=True)


class ProAgreementUpdate(Strict):
    tax_status = serializers.ChoiceField(choices=Agreement.TAX_STATUSES, required=False)
    tax_id = serializers.CharField(required=False, allow_blank=True)
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    bank_account_id = serializers.UUIDField(required=False, allow_null=True)
    valid_from = serializers.DateField(required=False)
    valid_to = serializers.DateField(required=False, allow_null=True)


class ProReasonIn(Strict):
    reason = serializers.CharField()


class ProEndIn(Strict):
    reason = serializers.CharField()
    valid_to = serializers.DateField(required=False)


# ------------------------------------------------------------------ rate cards

class ProScopeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Scope
        fields = ["key", "description", "known_at"]


class ProRateCardSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    rate = ProMoney("rate")
    scope_key = serializers.CharField(source="scope_key_id", read_only=True)
    approval_request = serializers.UUIDField(source="approval_request_id", read_only=True)

    class Meta:
        model = RateCard
        fields = ["id", "country", "role", "agreement", "unit", "scope_key", "rate", "version", "valid_from",
                  "valid_to", "state", "created_by", "approval_request", "approved_by", "approved_at", "row_version",
                  "created_at"]
        read_only_fields = fields


class ProRateCardIn(Strict):
    """One flat amount per unit and scope; there is no field for a verdict or outcome (RUL-26)."""

    country = serializers.CharField(max_length=2)
    role = serializers.ChoiceField(choices=ROLES)
    unit = serializers.ChoiceField(choices=UNITS)
    scope_key = serializers.CharField(default="standard")
    rate = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    currency = serializers.CharField(max_length=3, required=False)
    valid_from = serializers.DateField()
    agreement_id = serializers.UUIDField(required=False, allow_null=True)


class ProRateCardUpdate(Strict):
    rate = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0, required=False)
    valid_from = serializers.DateField(required=False)


class ProDecisionIn(Strict):
    decision = serializers.ChoiceField(choices=["approve", "reject"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True, default="")


# ------------------------------------------------------------------ payables

class ProPayableSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    professional = serializers.UUIDField(source="agreement.professional_id", read_only=True)
    professional_name = serializers.CharField(source="agreement.professional.full_name", read_only=True)
    role = serializers.CharField(source="agreement.role", read_only=True)
    case_reference = serializers.CharField(source="case.reference", read_only=True, default=None)
    unit_rate = ProMoney("unit_rate")
    gross = ProMoney("gross")
    withholding = ProMoney("withholding")
    other_deductions = ProMoney("other_deductions")
    net = serializers.SerializerMethodField()
    config_version = serializers.IntegerField(source="country_config.version", read_only=True)
    overdue = serializers.SerializerMethodField()
    run_reference = serializers.CharField(source="payment_line.run.reference", read_only=True, default=None)

    class Meta:
        model = Payable
        fields = ["id", "country", "agreement", "professional", "professional_name", "role", "work_kind",
                  "work_ref", "work_period", "case", "case_reference", "subject_type", "subject_id", "assigned_at",
                  "accepted_at", "rate_card", "unit_rate", "quantity", "gross", "withholding_rate", "withholding",
                  "other_deductions", "net", "config_version", "due_by", "overdue", "status", "hold_reason",
                  "hold_note", "cancel_reason", "payment_line", "run_reference", "paid_at", "created_at"]
        read_only_fields = fields

    def get_net(self, p) -> dict:
        return {"amount": f"{p.gross - p.withholding - p.other_deductions:.2f}", "currency": p.currency}

    def get_overdue(self, p) -> bool:
        from .services import is_overdue

        return is_overdue(p)


class ProHoldIn(Strict):
    reason = serializers.CharField()  # checked in the service: only a review hold (RUL-26)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class ProNoteIn(Strict):
    note = serializers.CharField(required=False, allow_blank=True, default="")


# ------------------------------------------------------------------ expenses

class ProExpenseSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    claimant_name = serializers.CharField(source="claimant.full_name", read_only=True)
    amount = ProMoney("amount")
    limit = ProMoney("limit_amount")
    approval_request = serializers.UUIDField(source="approval_request_id", read_only=True)

    class Meta:
        model = ExpenseClaim
        fields = ["id", "country", "agreement", "claimant", "claimant_name", "case", "project_id", "errand_id",
                  "kind", "description", "amount", "limit", "incurred_on", "receipt_evidence", "receipt_sha256",
                  "needs_second_approval", "approved_by", "approved_at", "approval_request", "decision_note",
                  "payment_line", "status", "created_at"]
        read_only_fields = fields


class ProExpenseIn(Strict):
    kind = serializers.ChoiceField(choices=EXPENSE_KINDS)
    description = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    currency = serializers.CharField(max_length=3, required=False)
    incurred_on = serializers.DateField()
    receipt_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    case_id = serializers.UUIDField(required=False, allow_null=True)
    project_id = serializers.UUIDField(required=False, allow_null=True)
    errand_id = serializers.UUIDField(required=False, allow_null=True)
    agreement_id = serializers.UUIDField(required=False, allow_null=True)


# ------------------------------------------------------------------ runs

class ProLineSerializer(serializers.ModelSerializer):
    professional_name = serializers.CharField(source="agreement.professional.full_name", read_only=True)
    role = serializers.CharField(source="agreement.role", read_only=True)
    gross = ProMoney("gross")
    withholding = ProMoney("withholding")
    other_deductions = ProMoney("other_deductions")
    reimbursed_expenses = ProMoney("reimbursed_expenses")
    net = ProMoney("net")
    destination = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()

    class Meta:
        model = PaymentLine
        fields = ["id", "position", "reference", "agreement", "professional_name", "role", "destination",
                  "account_name", "account_last4", "gross", "withholding", "other_deductions", "reimbursed_expenses",
                  "net", "bank_reference", "outcome", "failure_reason", "resolution", "resolution_note",
                  "letter_evidence", "letter_recorded_by", "resolved_by", "resolved_at", "confirmed_at", "items"]
        read_only_fields = fields

    def get_destination(self, ln) -> str:
        return "payee" if ln.payee_id else "bank_account"

    def get_items(self, ln) -> list[dict]:
        out = [{"kind": "payable", "id": str(p.pk), "work_kind": p.work_kind, "gross": f"{p.gross:.2f}"}
               for p in ln.payables.all()]
        out += [{"kind": "expense", "id": str(c.pk), "expense_kind": c.kind, "amount": f"{c.amount:.2f}"}
                for c in ln.expenses.all()]
        return out


class ProRunSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    operating_account = serializers.SerializerMethodField()
    total_gross = ProMoney("total_gross")
    total_net = ProMoney("total_net")
    approval_request = serializers.UUIDField(source="approval_request_id", read_only=True)
    file_downloadable = serializers.SerializerMethodField()

    class Meta:
        model = PaymentRun
        fields = ["id", "reference", "country", "operating_account", "file_format", "cut_off_at", "currency",
                  "total_gross", "total_net", "line_count", "excluded", "prepared_by", "approval_request",
                  "approved_by", "approved_at", "file_sha256", "file_downloadable", "uploaded_by", "uploaded_at",
                  "confirmation_evidence", "status", "status_reason", "row_version", "created_at"]
        read_only_fields = fields

    def get_operating_account(self, r) -> dict:
        a = r.operating_account
        return {"id": str(a.pk), "kind": a.kind, "name": a.name, "bank_name": a.bank_name,
                "account_last4": (a.account_number or "")[-4:]}

    def get_file_downloadable(self, r) -> bool:
        return bool(r.file_evidence_id) and r.status in ("file_issued", "partly_confirmed", "confirmed", "closed")


class ProRunDetailSerializer(ProRunSerializer):
    lines = ProLineSerializer(many=True, read_only=True)

    class Meta(ProRunSerializer.Meta):
        fields = ProRunSerializer.Meta.fields + ["lines"]
        read_only_fields = fields


class ProRunIn(Strict):
    country = serializers.CharField(max_length=2)
    operating_account_id = serializers.UUIDField(required=False, allow_null=True)
    cut_off_at = serializers.DateTimeField(required=False)


class ProConfirmationIn(Strict):
    """The bank's or provider's confirmation file, as text (CSV) or base64."""

    content = serializers.CharField(required=False, allow_blank=True)
    content_base64 = serializers.CharField(required=False, allow_blank=True)
    content_type = serializers.CharField(required=False, default="text/csv")
    filename = serializers.CharField(required=False, default="confirmation.csv")


class ProResolutionIn(Strict):
    resolution = serializers.ChoiceField(choices=PaymentLine.RESOLUTIONS)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    letter_evidence_id = serializers.UUIDField(required=False, allow_null=True)


class ProLetterCheckIn(Strict):
    accept = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


# ------------------------------------------------------------------ documents and reports

class ProDocumentSerializer(serializers.ModelSerializer):
    gross = ProMoney("gross")
    withholding = ProMoney("withholding")
    other_deductions = ProMoney("other_deductions")
    reimbursed_expenses = ProMoney("reimbursed_expenses")
    net = ProMoney("net")
    sha256 = serializers.CharField(source="evidence.sha256", read_only=True)
    line_reference = serializers.CharField(source="payment_line.reference", read_only=True, default=None)

    class Meta:
        model = Document
        fields = ["id", "agreement", "kind", "payment_line", "line_reference", "tax_year", "gross", "withholding",
                  "other_deductions", "reimbursed_expenses", "net", "sha256", "issued_at"]
        read_only_fields = fields


class ProStatementsIn(Strict):
    country = serializers.CharField(max_length=2)
    tax_year = serializers.IntegerField(min_value=2000, max_value=2100)


class ProJobSerializer(serializers.Serializer):
    state = serializers.CharField()
    work_kind = serializers.CharField()
    work_ref = serializers.CharField()
    case_id = serializers.CharField(allow_null=True)
    case_reference = serializers.CharField(allow_null=True)
    title = serializers.CharField(required=False)
    assigned_at = serializers.CharField(allow_null=True)
    accepted_at = serializers.CharField(allow_null=True)
    rate = ProMoney("rate", allow_null=True)
    unit = serializers.CharField(allow_null=True)
    payable_id = serializers.CharField(allow_null=True)
    payable_status = serializers.CharField(allow_null=True)

    def to_representation(self, obj):
        return obj


class ProMyAgreementSerializer(ProAgreementSerializer):
    rate_cards = serializers.SerializerMethodField()

    class Meta(ProAgreementSerializer.Meta):
        fields = [f for f in ProAgreementSerializer.Meta.fields if f not in ("agreement_evidence",)] + ["rate_cards"]
        read_only_fields = fields

    def get_rate_cards(self, a) -> list[dict]:
        from .services import current_cards

        return [{"unit": c.unit, "scope_key": c.scope_key_id, "rate": {"amount": f"{c.rate:.2f}",
                                                                        "currency": c.currency},
                 "version": c.version, "valid_from": c.valid_from.isoformat()} for c in current_cards(a)]


class ProCostRow(serializers.Serializer):
    case_id = serializers.CharField()
    reference = serializers.CharField(allow_null=True)
    line = serializers.CharField(allow_null=True)
    currency = serializers.CharField()
    payables = serializers.CharField()
    expenses = serializers.CharField()
    total = serializers.CharField()


class ProCountIn(Strict):
    country = serializers.CharField(max_length=2, required=False)


HOLD_CHOICES = HOLD_REASONS
