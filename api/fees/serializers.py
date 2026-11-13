"""FEE API shapes (02 7.4, 7.9). Money is {"amount": "250.00", "currency": "GHS"}."""
from rest_framework import serializers

from core.permissions import has_role

from .models import Beneficiary, Institution, InstitutionContact, Invoice, Payment, RunnerTask, Schedule, Statement

STAFF = ("CM", "RV", "AD")


def _money(amount, currency):
    return None if amount is None else {"amount": f"{amount:.2f}", "currency": currency}


def _is_staff(ctx, country):
    req = ctx.get("request")
    return bool(req and has_role(req.user, *STAFF, country=country))


def _user(ctx):
    req = ctx.get("request")
    return getattr(req, "user", None)


class FeeMoneyIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(max_length=3)


class FeeDocumentFields(serializers.Serializer):
    """Either an evidence id the caller uploaded through /v1/uploads, or the file itself as base64."""

    evidence_id = serializers.UUIDField(required=False, allow_null=True)
    document_base64 = serializers.CharField(required=False, allow_blank=True)
    content_type = serializers.CharField(required=False, default="application/pdf")
    file_name = serializers.CharField(required=False, allow_blank=True, default="")


# ----------------------------------------------------------------- institutions

class FeeContactSerializer(serializers.ModelSerializer):
    has_account = serializers.SerializerMethodField()

    class Meta:
        model = InstitutionContact
        fields = ["id", "full_name", "role_title", "phone", "email", "may_confirm_invoices", "may_send_receipts",
                  "status", "has_account", "created_at"]

    def get_has_account(self, obj) -> bool:
        return obj.person_id is not None


class FeeInstitutionSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    status_text = serializers.SerializerMethodField()
    payee = serializers.SerializerMethodField()
    checklist = serializers.SerializerMethodField()
    contacts = serializers.SerializerMethodField()
    look_alike = serializers.SerializerMethodField()
    eligibility_review = serializers.SerializerMethodField()

    class Meta:
        model = Institution
        fields = ["id", "country", "type", "legal_name", "registration_number", "address", "phone", "email",
                  "status", "status_text", "eligible_for_direct_payment", "not_eligible_reason",
                  "returns_confirmation", "invoice_channel", "verified_at", "verification_case", "payee",
                  "checklist", "contacts", "look_alike", "eligibility_review", "created_at"]

    def get_status_text(self, obj) -> str:
        from .services import NOT_ELIGIBLE_TEXT

        if obj.status == "verified":
            return "Verified. Bills are paid only to its bank account in its own name."
        if obj.status == "not_eligible":
            return NOT_ELIGIBLE_TEXT
        if obj.status == "pending":
            return obj.status_reason or ("Tenmina is checking its registration, its bank account in its own name "
                                         "and a named contact. Nothing is paid until then.")
        return obj.status_reason or obj.status.replace("_", " ")

    def get_payee(self, obj) -> dict | None:
        p = obj.payee
        if p is None:
            return None
        out = {"account_name": p.account_name, "account_last4": p.last4, "bank_name": p.bank_name,
               "verification_status": p.verification_status, "name_match": p.name_match}
        if _is_staff(self.context, obj.country):
            out["id"] = str(p.pk)
        return out

    def get_checklist(self, obj) -> list:
        from .services import verification_checklist

        return verification_checklist(obj)

    def get_contacts(self, obj) -> list:
        if not _is_staff(self.context, obj.country):
            return []
        return FeeContactSerializer(obj.contacts.filter(status="active"), many=True).data

    def get_look_alike(self, obj) -> dict | None:
        if not obj.look_alike_of_id or not _is_staff(self.context, obj.country):
            return None
        return {"of": str(obj.look_alike_of_id), "name": obj.look_alike_of.legal_name,
                "status": obj.look_alike_status}

    def get_eligibility_review(self, obj) -> dict | None:
        if not obj.eligibility_proposed_at or not _is_staff(self.context, obj.country):
            return None
        return {"proposed_by": obj.eligibility_proposed_by.full_name, "proposed_at": obj.eligibility_proposed_at,
                "reason": obj.eligibility_proposed_reason}


class FeeInstitutionIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    type = serializers.CharField()
    legal_name = serializers.CharField()
    registration_number = serializers.CharField(required=False, allow_blank=True, default="")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    returns_confirmation = serializers.BooleanField(required=False, default=False)
    invoice_channel = serializers.ChoiceField(choices=Institution.CHANNELS, required=False, default="manual_upload")
    proposed_bank_name = serializers.CharField(required=False, allow_blank=True, default="")
    proposed_account_number = serializers.CharField(required=False, allow_blank=True, default="")
    proposed_account_name = serializers.CharField(required=False, allow_blank=True, default="")
    registration_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    client_id = serializers.UUIDField(required=False, allow_null=True, help_text="Staff only: the client.")
    family_member_id = serializers.UUIDField(required=False, allow_null=True,
                                             help_text="The pupil or patient, linked at once.")


class FeeInstitutionPatch(serializers.Serializer):
    address = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    returns_confirmation = serializers.BooleanField(required=False)
    invoice_channel = serializers.ChoiceField(choices=Institution.CHANNELS, required=False)
    registration_number = serializers.CharField(required=False, allow_blank=True)
    registration_evidence_id = serializers.UUIDField(required=False, allow_null=True)


class FeeContactIn(serializers.Serializer):
    full_name = serializers.CharField()
    role_title = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    person_id = serializers.UUIDField(required=False, allow_null=True)
    may_confirm_invoices = serializers.BooleanField(required=False, default=True)
    may_send_receipts = serializers.BooleanField(required=False, default=True)
    evidence_id = serializers.UUIDField(required=False, allow_null=True)


class FeePayeeIn(serializers.Serializer):
    bank_name = serializers.CharField()
    account_number = serializers.CharField()
    account_name = serializers.CharField(required=False, allow_blank=True, default="")
    account_name_source = serializers.ChoiceField(choices=["bank_name_check", "bank_letter"])
    account_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    legal_name_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    signatory_name = serializers.CharField(required=False, allow_blank=True, default="")
    signatory_id_number = serializers.CharField(required=False, allow_blank=True, default="")
    signatory_person_id = serializers.UUIDField(required=False, allow_null=True)
    national_id_check_id = serializers.UUIDField(required=False, allow_null=True)
    contact_email = serializers.EmailField(required=False, allow_blank=True, default="")
    contact_phone = serializers.CharField(required=False, allow_blank=True, default="")


class FeePayeeOut(serializers.Serializer):
    id = serializers.UUIDField()
    legal_name = serializers.CharField()
    account_name = serializers.CharField()
    account_last4 = serializers.CharField()
    name_match = serializers.CharField()
    verification_status = serializers.CharField()
    approval_request = serializers.UUIDField(allow_null=True)


class FeeEligibilityIn(serializers.Serializer):
    action = serializers.ChoiceField(choices=["propose", "confirm", "decline"])
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class FeeLookAlikeIn(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["cleared", "confirmed"])
    note = serializers.CharField()


class FeeReasonIn(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class FeeBeneficiaryIn(serializers.Serializer):
    family_member_id = serializers.UUIDField()
    institution_account_ref = serializers.CharField(required=False, allow_blank=True, default="")


class FeeBeneficiarySerializer(serializers.ModelSerializer):
    family_member_name = serializers.CharField(source="family_member.full_name", read_only=True)

    class Meta:
        model = Beneficiary
        fields = ["id", "institution", "family_member", "family_member_name", "institution_account_ref",
                  "tenmina_reference", "status", "created_at"]


# ----------------------------------------------------------------- runner tasks

class FeeRunnerTaskIn(serializers.Serializer):
    kind = serializers.ChoiceField(choices=RunnerTask.KINDS)
    runner_id = serializers.UUIDField()
    due_at = serializers.DateTimeField()
    invoice_id = serializers.UUIDField(required=False, allow_null=True)
    family_member_id = serializers.UUIDField(required=False, allow_null=True)
    deliver_to_family_member_id = serializers.UUIDField(required=False, allow_null=True)
    instructions = serializers.CharField(required=False, allow_blank=True, default="")


class FeeRunnerTaskSerializer(serializers.ModelSerializer):
    institution_name = serializers.CharField(source="institution.legal_name", read_only=True)
    runner_name = serializers.CharField(source="runner.full_name", read_only=True)

    class Meta:
        model = RunnerTask
        fields = ["id", "institution", "institution_name", "kind", "runner", "runner_name", "invoice",
                  "family_member", "deliver_to_family_member", "instructions", "due_at", "evidence", "note",
                  "status", "done_at", "cancel_reason", "created_at"]


class FeeCollectedInvoiceIn(serializers.Serializer):
    reference = serializers.CharField()
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(required=False, allow_blank=True, default="")
    due_on = serializers.DateField(required=False, allow_null=True)
    name_on_invoice = serializers.CharField(required=False, allow_blank=True, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")


class FeeRunnerCompleteIn(FeeDocumentFields):
    note = serializers.CharField(required=False, allow_blank=True, default="")
    invoice = FeeCollectedInvoiceIn(required=False, allow_null=True)


# ----------------------------------------------------------------- invoices

class FeeInvoiceSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    institution = serializers.SerializerMethodField()
    family_member = serializers.SerializerMethodField()
    amount = serializers.SerializerMethodField()
    checked_by_name = serializers.SerializerMethodField()
    contact_confirmed = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()
    service_order = serializers.SerializerMethodField()
    status_text = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = ["id", "country", "institution", "family_member", "schedule", "institution_reference",
                  "description", "amount", "due_on", "name_on_invoice", "institution_name_on_invoice",
                  "submitted_by", "evidence", "evidence_sha256", "check_status", "check_flags", "checked_by_name",
                  "checked_at", "check_note", "contact_confirmed", "route", "client_approved_at", "status",
                  "status_text", "status_reason", "payment", "service_order", "created_at"]

    def get_amount(self, obj) -> dict:
        return _money(obj.amount, obj.currency)

    def get_institution(self, obj) -> dict:
        return {"id": str(obj.institution_id), "name": obj.institution.legal_name, "status": obj.institution.status,
                "eligible_for_direct_payment": obj.institution.eligible_for_direct_payment}

    def get_family_member(self, obj) -> dict:
        user = _user(self.context)
        out = {"id": str(obj.family_member_id), "relationship": obj.family_member.relationship}
        if user is not None and (user.pk == obj.client_id or _is_staff(self.context, obj.country)):
            out["full_name"] = obj.family_member.full_name
        return out

    def get_checked_by_name(self, obj) -> str | None:
        return obj.checked_by.full_name if obj.checked_by_id else None

    def get_contact_confirmed(self, obj) -> dict | None:
        if not obj.contact_confirmed_by_id:
            return None
        return {"name": obj.contact_confirmed_by.full_name, "at": obj.contact_confirmed_at}

    def get_payment(self, obj) -> dict | None:
        p = obj.payments.exclude(status="withdrawn").first()
        return {"id": str(p.pk), "status": p.status, "route": p.route} if p else None

    def get_service_order(self, obj) -> dict | None:
        o = obj.service_order
        if o is None:
            return None
        return {"id": str(o.pk), "reference": o.reference, "status": o.status}

    def get_status_text(self, obj) -> str:
        return {"draft": "Waiting for the institution's bill.", "submitted": "Tenmina is checking the bill with the "
                "institution.", "checked": "Checked with the institution. Approve it to pay.",
                "client_approved": "Approved." if obj.route == "held_funds" else
                "Approved. Pay the institution's verified account, then tell us.",
                "instructed": "Two Tenmina staff approve; then the bank pays the institution.",
                "paid": "Paid. Waiting for the institution's receipt.", "receipted": "Paid. Receipt returned.",
                "rejected": obj.status_reason or "Rejected.", "cancelled": obj.status_reason or "Cancelled."
                }.get(obj.status, obj.status)


class FeeInvoiceIn(FeeDocumentFields):
    institution_id = serializers.UUIDField()
    family_member_id = serializers.UUIDField(required=False, allow_null=True)
    tenmina_reference = serializers.CharField(required=False, allow_blank=True, default="")
    institution_reference = serializers.CharField()
    amount = FeeMoneyIn()
    due_on = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    name_on_invoice = serializers.CharField(required=False, allow_blank=True, default="")
    institution_name_on_invoice = serializers.CharField(required=False, allow_blank=True, default="")
    account_number_on_invoice = serializers.CharField(required=False, allow_blank=True, default="")


class FeeInvoiceDocumentIn(FeeDocumentFields):
    institution_reference = serializers.CharField(required=False, allow_blank=True)
    amount = FeeMoneyIn(required=False)
    due_on = serializers.DateField(required=False, allow_null=True)
    name_on_invoice = serializers.CharField(required=False, allow_blank=True)
    institution_name_on_invoice = serializers.CharField(required=False, allow_blank=True)
    account_number_on_invoice = serializers.CharField(required=False, allow_blank=True)


class FeeCheckIn(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["checked", "rejected"])
    contact_id = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    resolve_flags = serializers.BooleanField(required=False, default=False)


class FeeRouteIn(serializers.Serializer):
    route = serializers.ChoiceField(choices=["client_direct", "held_funds"])
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class FeeClientApprovalIn(serializers.Serializer):
    confirm_amount = FeeMoneyIn()
    confirm_payee_account_name = serializers.CharField(
        help_text="The account name exactly as the bank states it, shown before approval.")
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=500)
    code = serializers.CharField(required=False, allow_blank=True, default="",
                                 help_text="An authenticator code, instead of a recent step-up.")


class FeeApprovalOut(serializers.Serializer):
    invoice_id = serializers.UUIDField()
    status = serializers.CharField()
    route = serializers.CharField()
    institution = serializers.JSONField()
    family_member = serializers.JSONField()
    amount = serializers.JSONField()
    held_funds = serializers.JSONField(required=False, allow_null=True)
    pay_to = serializers.JSONField(required=False, allow_null=True)
    top_up = serializers.JSONField(required=False, allow_null=True)
    next = serializers.CharField(required=False)


class FeePreviewOut(serializers.Serializer):
    invoice_id = serializers.UUIDField()
    route = serializers.CharField()
    institution = serializers.JSONField()
    family_member = serializers.JSONField()
    amount = serializers.JSONField()
    held_funds = serializers.JSONField(required=False, allow_null=True)


# ----------------------------------------------------------------- payments

class FeePaymentSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    invoice = serializers.SerializerMethodField()
    release_status = serializers.SerializerMethodField()
    pay_to = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = ["id", "invoice", "route", "amount", "status", "escrow", "release_instruction", "release_status",
                  "client_paid_on", "client_transfer_reference", "client_reported_at", "institution_confirmed_at",
                  "confirmation_method", "paid_at", "bank_reference", "receipt_due_at", "receipt_received_at",
                  "receipt_evidence", "confirmation_evidence", "pay_to", "withdrawn_reason", "created_at"]

    def get_amount(self, obj) -> dict:
        return _money(obj.amount, obj.currency)

    def get_invoice(self, obj) -> dict:
        i = obj.invoice
        return {"id": str(i.pk), "institution": i.institution.legal_name, "reference": i.institution_reference,
                "family_member_id": str(i.family_member_id)}

    def get_release_status(self, obj) -> str | None:
        return obj.release_instruction.status if obj.release_instruction_id else None

    def get_pay_to(self, obj) -> dict | None:
        user = _user(self.context)
        if obj.route != "client_direct" or obj.status not in ("awaiting_client_payment", "client_reported") \
                or user is None or user.pk != obj.invoice.client_id:
            return None
        from .services import pay_to

        return pay_to(obj.invoice)


class FeeClientPaymentIn(FeeDocumentFields):
    paid_on = serializers.DateField(required=False, allow_null=True)
    reference = serializers.CharField(required=False, allow_blank=True, default="")


class FeeConfirmIn(FeeDocumentFields):
    received = serializers.BooleanField(default=True)
    amount = FeeMoneyIn(required=False)
    method = serializers.ChoiceField(choices=["", "contact_call", "receipt"], required=False, default="")
    contact_id = serializers.UUIDField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class FeeReceiptIn(FeeDocumentFields):
    confirmation_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    confirmation_document_base64 = serializers.CharField(required=False, allow_blank=True)


# ----------------------------------------------------------------- schedules, plans and statements

class FeeScheduleSerializer(serializers.ModelSerializer):
    expected = serializers.SerializerMethodField()
    institution_name = serializers.CharField(source="institution.legal_name", read_only=True)

    class Meta:
        model = Schedule
        fields = ["id", "institution", "institution_name", "family_member", "label", "period", "expected",
                  "next_due_on", "reminder_lead_days", "status", "last_generated_due_on", "created_at"]

    def get_expected(self, obj) -> dict:
        return _money(obj.expected_amount, obj.expected_currency)


class FeeScheduleIn(serializers.Serializer):
    institution_id = serializers.UUIDField()
    family_member_id = serializers.UUIDField()
    period = serializers.ChoiceField(choices=Schedule.PERIODS)
    expected = FeeMoneyIn()
    next_due_on = serializers.DateField()
    reminder_lead_days = serializers.IntegerField(required=False, default=14)
    label = serializers.CharField(required=False, allow_blank=True, default="")


class FeeSchedulePatch(serializers.Serializer):
    expected = FeeMoneyIn(required=False)
    next_due_on = serializers.DateField(required=False)
    reminder_lead_days = serializers.IntegerField(required=False)
    label = serializers.CharField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=["active", "paused", "ended"], required=False)


class FeePlanIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    period_month = serializers.CharField(help_text="YYYY-MM")


class FeeOrderOut(serializers.Serializer):
    id = serializers.UUIDField()
    reference = serializers.CharField()
    kind = serializers.CharField()
    status = serializers.CharField()


class FeeStatementOut(serializers.Serializer):
    family_member = serializers.JSONField()
    lines = serializers.JSONField()
    totals = serializers.JSONField()
    held_at_bank = serializers.JSONField()
    note = serializers.CharField()


class FeeStatementDocSerializer(serializers.ModelSerializer):
    class Meta:
        model = Statement
        fields = ["id", "family_member", "evidence", "sha256", "created_at"]
