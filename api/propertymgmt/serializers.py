"""PMG API shapes. Money is {"amount", "currency"} (7.1). A tenant sees only their tenancy, rent record
and the repairs they reported; never the owner's other data (TC-PMG-006-02)."""
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers

from core.money import MoneyField as _MoneyField

from .models import (CONDITIONS, INSPECTION_KINDS, OUTCOMES, RENT_PERIODS, Inspection, ManagedProperty, RentPeriod,
                     Repair, RepairQuote, StatementImport, StatementMandate, Tenancy)

MONEY = {"type": "object", "properties": {"amount": {"type": "string"}, "currency": {"type": "string"}}}


@extend_schema_field(MONEY)
class MoneyField(_MoneyField):
    """core.money.MoneyField with its OpenAPI shape."""
PERSON = {"type": "object", "nullable": True, "properties": {"id": {"type": "string", "format": "uuid"},
                                                             "name": {"type": "string"}}}


@extend_schema_field(PERSON)
@extend_schema_serializer(component_name="PmgPersonRef")
class PersonRef(serializers.Field):
    def to_representation(self, p):
        return None if p is None else {"id": str(p.pk), "name": p.full_name}


@extend_schema_serializer(component_name="PmgMoneyIn")
class MoneyIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    currency = serializers.CharField(min_length=3, max_length=3)


@extend_schema_serializer(component_name="PmgLocationIn")
class LocationIn(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()


# --------------------------------------------------------------------------- properties

@extend_schema_serializer(component_name="PmgPropertyCreate")
class PropertyCreate(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    title = serializers.CharField()
    locality = serializers.CharField()
    owner_id = serializers.UUIDField(required=False, help_text="Staff only: the owner a case manager registers for.")
    address = serializers.CharField(required=False, allow_blank=True, default="")
    region = serializers.CharField(required=False, allow_blank=True, default="")
    district = serializers.CharField(required=False, allow_blank=True, default="")
    ghana_post_gps = serializers.CharField(required=False, allow_blank=True, default="",
                                           help_text="The country's digital address, saved as text.")
    location = LocationIn(required=False)
    asset_id = serializers.UUIDField(required=False, help_text="An existing house of the owner's.")
    ownership_evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    inspection_interval_months = serializers.IntegerField(required=False, min_value=1, max_value=24)


@extend_schema_serializer(component_name="PmgRentAccountIn")
class RentAccountIn(serializers.Serializer):
    bank_account_id = serializers.UUIDField()


@extend_schema_serializer(component_name="PmgMandateIn")
class MandateIn(serializers.Serializer):
    mandate_evidence_id = serializers.UUIDField()
    valid_from = serializers.DateField(required=False)
    valid_to = serializers.DateField(required=False, allow_null=True)
    bank_acknowledgement_evidence_id = serializers.UUIDField(required=False, allow_null=True,
                                                             help_text="Staff: the bank's acknowledgement.")
    statement_ref = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="PmgAcknowledgementIn")
class AcknowledgementIn(serializers.Serializer):
    evidence_id = serializers.UUIDField()
    statement_ref = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="PmgReasonIn")
class ReasonIn(serializers.Serializer):
    reason = serializers.CharField()


@extend_schema_serializer(component_name="PmgStatementUploadIn")
class StatementUploadIn(serializers.Serializer):
    content = serializers.CharField(help_text="The statement CSV: account_number,booked_on,kind,amount,currency,"
                                              "bank_reference,counterparty_name,narrative")
    original_name = serializers.CharField(required=False, default="statement.csv")
    source = serializers.ChoiceField(choices=StatementImport.SOURCES, default="manual")
    owner_confirmed = serializers.BooleanField(default=False)


@extend_schema_serializer(component_name="PmgMandate")
class MandateSerializer(serializers.ModelSerializer):
    account_last4 = serializers.CharField(source="bank_account.last4", read_only=True)

    class Meta:
        model = StatementMandate
        fields = ["id", "property", "status", "account_last4", "statement_ref", "valid_from", "valid_to",
                  "mandate_evidence", "bank_acknowledgement_evidence", "acknowledged_at", "revoked_at",
                  "revoke_reason", "created_at"]


@extend_schema_serializer(component_name="PmgStatementImport")
class StatementImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = StatementImport
        fields = ["id", "property", "mandate", "statement_file", "source", "original_name", "accepted_count",
                  "refused_count", "matched_count", "created_at"]


@extend_schema_serializer(component_name="PmgRentAccount")
class RentAccountSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    bank_name = serializers.CharField()
    account_name = serializers.CharField()
    last4 = serializers.CharField()
    verification_status = serializers.CharField()


@extend_schema_serializer(component_name="PmgProperty")
class PropertySerializer(serializers.ModelSerializer):
    owner = PersonRef(read_only=True)
    asset_reference = serializers.CharField(source="asset.reference", read_only=True)
    locality = serializers.CharField(source="asset.locality", read_only=True)
    address = serializers.CharField(source="asset.address", read_only=True)
    rent_account = serializers.SerializerMethodField()
    mandate = serializers.SerializerMethodField()
    blockers = serializers.SerializerMethodField()
    onboarding_inspection = serializers.SerializerMethodField()
    active_tenancy = serializers.SerializerMethodField()

    class Meta:
        model = ManagedProperty
        fields = ["id", "country", "title", "owner", "asset", "asset_reference", "locality", "address", "status",
                  "onboarding_case", "ownership_outcome", "ownership_verified_at", "rent_account", "mandate",
                  "inspection_interval_months", "next_inspection_due_on", "managed_at", "ended_at", "end_reason",
                  "fee_order_id", "blockers", "onboarding_inspection", "active_tenancy", "created_at", "row_version"]

    @extend_schema_field(RentAccountSerializer(allow_null=True))
    def get_rent_account(self, obj):
        a = obj.rent_account
        return None if a is None else {"id": str(a.pk), "bank_name": a.bank_name, "account_name": a.account_name,
                                       "last4": a.last4, "verification_status": a.verification_status}

    @extend_schema_field(MandateSerializer(allow_null=True))
    def get_mandate(self, obj):
        m = obj.mandates.filter(status__in=["signed", "active"]).first()
        return MandateSerializer(m).data if m else None

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_blockers(self, obj):
        from .services import activation_blockers

        return activation_blockers(obj) if obj.status == "onboarding" else []

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_onboarding_inspection(self, obj):
        from .services import onboarding_inspection

        i = onboarding_inspection(obj)
        return str(i.pk) if i else None

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_active_tenancy(self, obj):
        t = obj.tenancies.filter(status="active").first()
        return str(t.pk) if t else None


# --------------------------------------------------------------------------- tenancies and rent

@extend_schema_serializer(component_name="PmgTenancyCreate")
class TenancyCreate(serializers.Serializer):
    tenant_email = serializers.EmailField()
    tenant_name = serializers.CharField()
    tenant_phone = serializers.CharField(required=False, allow_blank=True, default="")
    tenant_id_number = serializers.CharField(required=False, allow_blank=True, default="",
                                             help_text="The tenant's national identity number, checked with the "
                                                       "national identity system.")
    agreement_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    rent = MoneyIn()
    period = serializers.ChoiceField(choices=list(RENT_PERIODS))
    due_day = serializers.IntegerField(min_value=1, max_value=28)
    starts_on = serializers.DateField()
    ends_on = serializers.DateField(required=False, allow_null=True)
    tenant_reference = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="PmgEndTenancyIn")
class EndTenancyIn(serializers.Serializer):
    reason = serializers.CharField()
    terminated = serializers.BooleanField(default=False)


@extend_schema_serializer(component_name="PmgPaymentDetails")
class PaymentDetailsSerializer(serializers.Serializer):
    pay_to = serializers.CharField()
    account_holder = serializers.CharField()
    bank_name = serializers.CharField()
    account_name = serializers.CharField()
    account_number = serializers.CharField()
    reference = serializers.CharField()
    amount = serializers.DictField()
    note = serializers.CharField()


@extend_schema_serializer(component_name="PmgRentPeriod")
class RentPeriodSerializer(serializers.ModelSerializer):
    expected = MoneyField(prefix="expected", read_only=True)
    received = serializers.SerializerMethodField()
    status_text = serializers.SerializerMethodField()
    manual_match_pending = serializers.SerializerMethodField()

    class Meta:
        model = RentPeriod
        fields = ["id", "tenancy", "period_start", "due_on", "expected", "received", "received_on", "status",
                  "status_text", "match_method", "statement_line", "manual_match_pending", "late_alert_sent_at"]

    @extend_schema_field(MONEY | {"nullable": True})
    def get_received(self, obj):
        return None if obj.received_amount is None else {"amount": f"{obj.received_amount:.2f}",
                                                         "currency": obj.expected_currency}

    @extend_schema_field(serializers.CharField())
    def get_status_text(self, obj):
        from .services import live_mandate, rent_status_text

        return rent_status_text(obj, live_mandate(obj.tenancy.property) is not None)

    @extend_schema_field(serializers.BooleanField())
    def get_manual_match_pending(self, obj):
        return obj.pending_line_id is not None


@extend_schema_serializer(component_name="PmgTenancy")
class TenancySerializer(serializers.ModelSerializer):
    tenant = PersonRef(read_only=True)
    property_title = serializers.CharField(source="property.title", read_only=True)
    rent = MoneyField(prefix="rent", read_only=True)
    payment_details = serializers.SerializerMethodField()
    periods = serializers.SerializerMethodField()

    class Meta:
        model = Tenancy
        fields = ["id", "property", "property_title", "tenant", "agreement_evidence", "rent", "period", "due_day",
                  "starts_on", "ends_on", "tenant_reference", "status", "ended_at", "end_reason",
                  "payment_details", "periods", "created_at"]

    @extend_schema_field(PaymentDetailsSerializer())
    def get_payment_details(self, obj):
        from .services import payment_details

        return payment_details(obj)

    @extend_schema_field(RentPeriodSerializer(many=True))
    def get_periods(self, obj):
        return RentPeriodSerializer(obj.periods.all(), many=True).data


@extend_schema_serializer(component_name="PmgManualMatchIn")
class ManualMatchIn(serializers.Serializer):
    statement_line_id = serializers.UUIDField()


@extend_schema_serializer(component_name="PmgMatchCheckIn")
class MatchCheckIn(serializers.Serializer):
    agree = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="PmgStatementLine")
class StatementLineSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    booked_on = serializers.DateField()
    amount = serializers.DictField()
    bank_reference = serializers.CharField()
    counterparty_name = serializers.CharField()
    narrative = serializers.CharField()


# --------------------------------------------------------------------------- inspections

@extend_schema_serializer(component_name="PmgInspection")
class InspectionSerializer(serializers.ModelSerializer):
    inspector = PersonRef(read_only=True)
    property_title = serializers.CharField(source="property.title", read_only=True)
    photos = serializers.SerializerMethodField()

    class Meta:
        model = Inspection
        fields = ["id", "property", "property_title", "repair", "kind", "inspector", "scheduled_for", "assigned_at",
                  "status", "outcome", "condition_rating", "rooms", "checklist", "defects", "notes", "photos",
                  "submitted_at", "submission_id", "cancel_reason", "created_at", "row_version"]

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_photos(self, obj):
        return [{"evidence_id": str(i), "preview": f"/v1/evidence/{i}"} for i in obj.photo_ids]


@extend_schema_serializer(component_name="PmgInspectionCreate")
class InspectionCreate(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["periodic", "onboarding"], default="periodic")
    scheduled_for = serializers.DateField(required=False)
    inspector_id = serializers.UUIDField(required=False)


@extend_schema_serializer(component_name="PmgRepairInspectionCreate")
class RepairInspectionCreate(serializers.Serializer):
    scheduled_for = serializers.DateField(required=False)
    inspector_id = serializers.UUIDField(required=False)


@extend_schema_serializer(component_name="PmgAssignIn")
class AssignIn(serializers.Serializer):
    inspector_id = serializers.UUIDField()


@extend_schema_serializer(component_name="PmgRoomIn")
class RoomIn(serializers.Serializer):
    room = serializers.CharField()
    condition = serializers.ChoiceField(choices=CONDITIONS, required=False, allow_blank=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)


@extend_schema_serializer(component_name="PmgInspectionResultIn")
class InspectionResultIn(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=OUTCOMES)
    condition_rating = serializers.ChoiceField(choices=CONDITIONS, required=False, allow_blank=True, default="")
    rooms = RoomIn(many=True, required=False)
    photo_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    checklist = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    defects = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="PmgTimelineItem")
class TimelineItem(serializers.Serializer):
    date = serializers.DateField()
    kind = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField()
    detail = serializers.CharField()
    photos = serializers.ListField(child=serializers.DictField())
    amount = serializers.DictField(required=False)
    id = serializers.UUIDField()


# --------------------------------------------------------------------------- repairs

@extend_schema_serializer(component_name="PmgRepairCreate")
class RepairCreate(serializers.Serializer):
    property_id = serializers.UUIDField()
    title = serializers.CharField()
    description = serializers.CharField()
    photo_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    urgent = serializers.BooleanField(default=False)


@extend_schema_serializer(component_name="PmgQuoteIn")
class QuoteIn(serializers.Serializer):
    contractor_id = serializers.UUIDField()
    payee_id = serializers.UUIDField()
    amount = MoneyIn()
    evidence_id = serializers.UUIDField()
    valid_until = serializers.DateField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="PmgQuoteApprovalIn")
class QuoteApprovalIn(serializers.Serializer):
    quote_id = serializers.UUIDField()
    confirm_amount = MoneyIn()


@extend_schema_serializer(component_name="PmgWorkDoneIn")
class WorkDoneIn(serializers.Serializer):
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1)
    note = serializers.CharField(required=False, allow_blank=True, default="")


@extend_schema_serializer(component_name="PmgCloseRepairIn")
class CloseRepairIn(serializers.Serializer):
    reason = serializers.CharField()
    reject = serializers.BooleanField(default=False)


@extend_schema_serializer(component_name="PmgQuote")
class QuoteSerializer(serializers.ModelSerializer):
    contractor = PersonRef(read_only=True)
    amount = MoneyField(prefix="quote", read_only=True)
    payee = serializers.SerializerMethodField()
    track_record = serializers.SerializerMethodField()

    class Meta:
        model = RepairQuote
        fields = ["id", "repair", "contractor", "payee", "amount", "description", "quote_evidence", "valid_until",
                  "status", "track_record", "created_at"]

    @extend_schema_field({"type": "object", "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                                                           "status": {"type": "string"},
                                                           "account_last4": {"type": "string"}}})
    def get_payee(self, obj):
        p = obj.payee
        return {"id": str(p.pk), "name": p.legal_name, "status": p.verification_status, "account_last4": p.last4}

    @extend_schema_field({"type": "object", "properties": {"completed": {"type": "integer"},
                                                           "disputes": {"type": "integer"}}})
    def get_track_record(self, obj):
        done = RepairQuote.objects.filter(contractor=obj.contractor, repair__status="paid").count()
        return {"completed": done, "disputes": 0}


@extend_schema_serializer(component_name="PmgRepair")
class RepairSerializer(serializers.ModelSerializer):
    property_title = serializers.CharField(source="property.title", read_only=True)
    reported_by = PersonRef(read_only=True)
    quotes = serializers.SerializerMethodField()
    escrow_reference = serializers.SerializerMethodField()
    quotes_needed = serializers.SerializerMethodField()
    approval_blockers = serializers.SerializerMethodField()

    class Meta:
        model = Repair
        fields = ["id", "property", "property_title", "reported_by", "reporter_role", "title", "description",
                  "urgent", "status", "quotes", "quotes_needed", "approval_blockers", "approved_quote",
                  "owner_approved_at", "single_quote_exception_reason", "escrow", "escrow_reference",
                  "inspection", "work_done_at", "release_instruction", "paid_at", "closed_reason", "created_at",
                  "row_version"]

    def _can_see_quotes(self, obj):
        from .services import is_owner, is_staff

        u = self.context.get("request").user if self.context.get("request") else None
        return u is not None and (is_owner(u, obj.property) or is_staff(u, obj.country))

    @extend_schema_field(QuoteSerializer(many=True))
    def get_quotes(self, obj):
        if not self._can_see_quotes(obj):
            return []
        return QuoteSerializer(obj.quotes.select_related("contractor", "payee").order_by("quote_amount"),
                               many=True).data

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_escrow_reference(self, obj):
        return obj.escrow.reference if obj.escrow_id else None

    @extend_schema_field(serializers.IntegerField())
    def get_quotes_needed(self, obj):
        from .services import quotes_needed

        return quotes_needed(obj)

    @extend_schema_field(serializers.ListField(child=serializers.DictField()))
    def get_approval_blockers(self, obj):
        from .services import approval_blockers

        return approval_blockers(obj) if obj.status in ("reported", "quoting", "quotes_ready") else []


@extend_schema_serializer(component_name="PmgQuoteApprovalResult")
class QuoteApprovalResult(serializers.Serializer):
    repair_id = serializers.UUIDField()
    status = serializers.CharField()
    approved_quote = serializers.DictField()
    quotes_considered = serializers.IntegerField()
    escrow = serializers.DictField()
    next = serializers.CharField()


@extend_schema_serializer(component_name="PmgInstructionResult")
class InstructionResult(serializers.Serializer):
    repair_id = serializers.UUIDField()
    instruction_id = serializers.UUIDField()
    status = serializers.CharField()
    amount = serializers.DictField()
    payee = serializers.CharField()


@extend_schema_serializer(component_name="PmgJobResult")
class JobResult(serializers.Serializer):
    result = serializers.DictField()


INSPECTION_KIND_CHOICES = INSPECTION_KINDS
