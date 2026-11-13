"""CARE API shapes. Money is {"amount", "currency"} (7.1). No serializer ever carries a confirmation code
(ADR-20), and the client's views never carry the carer's private concern notes (US-CARE-006 AC2)."""
from rest_framework import serializers

from drf_spectacular.utils import extend_schema_field

from core.money import MoneyField as _MoneyField


@extend_schema_field({"type": "object", "nullable": True, "properties": {
    "amount": {"type": "string", "example": "150.00"}, "currency": {"type": "string", "example": "GHS"}}})
class MoneyField(_MoneyField):
    """core.money.MoneyField with its OpenAPI shape."""

from .models import ITEM_KINDS, CarePlan, CarePlanItem, Carer, Concern, Visit, VisitItem


class CareMoneyInput(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    currency = serializers.CharField(min_length=3, max_length=3)


class CarePointSerializer(serializers.Serializer):
    lat = serializers.DecimalField(max_digits=9, decimal_places=6)
    lng = serializers.DecimalField(max_digits=9, decimal_places=6)


class CareScheduleSerializer(serializers.Serializer):
    weekly = serializers.ListField(child=serializers.CharField(), help_text="mon to sun")
    window = serializers.CharField(help_text="HH:MM-HH:MM in the country's time zone")


class PlanItemInput(serializers.Serializer):
    key = serializers.CharField(max_length=64)
    kind = serializers.ChoiceField(choices=ITEM_KINDS, default="other")
    label = serializers.CharField(required=False, allow_blank=True)
    instructions = serializers.CharField(required=False, allow_blank=True)
    photo_required = serializers.BooleanField(default=False)
    photo_allowed = serializers.BooleanField(default=False)
    reading_required = serializers.BooleanField(default=False)
    reading_kind = serializers.CharField(required=False, allow_blank=True)


class PlanItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarePlanItem
        fields = ["id", "key", "kind", "label", "instructions", "photo_required", "photo_allowed",
                  "reading_required", "reading_kind", "added_in_version"]


class CarePersonBrief(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()


class CareFamilyBrief(serializers.Serializer):
    id = serializers.UUIDField()
    full_name = serializers.CharField()
    relationship = serializers.CharField()


class CarerBrief(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField(source="person.full_name")
    status = serializers.CharField()
    pay_route = serializers.CharField()


class CareStandingApprovalBrief(serializers.Serializer):
    id = serializers.UUIDField()
    monthly_max = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField()
    status = serializers.CharField()
    approved_at = serializers.DateTimeField()


class CarePlanSerializer(serializers.ModelSerializer):
    family_member = CareFamilyBrief(read_only=True)
    carer = CarerBrief(read_only=True, allow_null=True)
    visit_fee = MoneyField(prefix="visit_fee")
    point = serializers.SerializerMethodField()
    items = serializers.SerializerMethodField()
    confirmers = serializers.SerializerMethodField()
    standing_approval = serializers.SerializerMethodField()
    next_visit_at = serializers.SerializerMethodField()
    needs_client = serializers.SerializerMethodField()

    class Meta:
        model = CarePlan
        fields = ["id", "reference", "status", "status_reason", "client", "family_member", "address", "point",
                  "schedule", "visit_fee", "confirmers", "confirm_channel", "carer", "case_manager", "escrow",
                  "fee_order_id", "fee_paid_at", "terms_accepted_at", "carer_approved_at", "version", "notes",
                  "items", "standing_approval", "next_visit_at", "needs_client", "created_at", "updated_at"]

    def get_point(self, obj) -> CarePointSerializer:
        return {"lat": str(obj.point_lat), "lng": str(obj.point_lng)}

    def get_items(self, obj) -> PlanItemSerializer(many=True):
        return PlanItemSerializer(obj.items.filter(active=True), many=True).data

    def get_confirmers(self, obj) -> CareFamilyBrief(many=True):
        from accounts.models import FamilyMember

        return [{"id": str(f.pk), "full_name": f.full_name, "relationship": f.relationship}
                for f in FamilyMember.objects.filter(pk__in=obj.confirmers)]

    def get_standing_approval(self, obj) -> CareStandingApprovalBrief(allow_null=True):
        from escrow.services import standing_approval_for

        sa = standing_approval_for("care_plan", obj.pk)
        return CareStandingApprovalBrief(sa).data if sa else None

    def get_next_visit_at(self, obj) -> serializers.DateTimeField(allow_null=True):
        from django.utils import timezone

        v = obj.visits.filter(status="scheduled", window_start__gte=timezone.now()).order_by("window_start").first()
        return v.window_start.isoformat() if v else None

    def get_needs_client(self, obj) -> serializers.CharField(allow_blank=True):
        if obj.status == "draft" and obj.carer_id:
            return "activate"
        if obj.status in ("active", "paused") and obj.carer_id and obj.carer.pay_route == "held_funds" \
                and obj.carer_approved_at is None:
            return "approve_carer"
        return ""


class CarePlanCreateInput(serializers.Serializer):
    client_id = serializers.UUIDField(required=False, help_text="Staff creating a plan for a client")
    family_member_id = serializers.UUIDField()
    items = PlanItemInput(many=True)
    schedule = CareScheduleSerializer()
    visit_fee = CareMoneyInput()
    confirmers = serializers.ListField(child=serializers.UUIDField())
    address = serializers.CharField(required=False, allow_blank=True)
    point = CarePointSerializer(required=False)
    confirm_channel = serializers.ChoiceField(choices=CarePlan.CHANNELS, default="sms")
    notes = serializers.CharField(required=False, allow_blank=True)


class CarePlanUpdateInput(serializers.Serializer):
    items = PlanItemInput(many=True, required=False)
    schedule = CareScheduleSerializer(required=False)
    visit_fee = CareMoneyInput(required=False)
    confirmers = serializers.ListField(child=serializers.UUIDField(), required=False)
    address = serializers.CharField(required=False, allow_blank=True)
    point = CarePointSerializer(required=False)
    confirm_channel = serializers.ChoiceField(choices=CarePlan.CHANNELS, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)


class CareAssignInput(serializers.Serializer):
    carer_id = serializers.UUIDField()


class CarePlanActivateInput(serializers.Serializer):
    terms_version = serializers.CharField()
    scope_version = serializers.CharField()


class CareReasonInput(serializers.Serializer):
    reason = serializers.CharField()


class CareOptionalReasonInput(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class CareStandingApprovalInput(serializers.Serializer):
    monthly_max = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0)
    code = serializers.CharField(required=False, help_text="Authenticator code instead of a step-up")


class CarerSerializer(serializers.ModelSerializer):
    person = CarePersonBrief(read_only=True)
    vetting = serializers.SerializerMethodField()
    payee = serializers.SerializerMethodField()
    track_record = serializers.SerializerMethodField()

    class Meta:
        model = Carer
        fields = ["id", "country", "person", "vetting", "agency_org", "pay_route", "payee", "languages", "areas",
                  "status", "status_reason", "track_record", "removed_at", "created_at"]

    def get_vetting(self, obj) -> dict:
        v = obj.vetting
        return {"id": str(v.pk), "status": v.status, "valid_until": v.valid_until.isoformat() if v.valid_until
                else None, "references": bool(v.references_evidence_id),
                "background_check": bool(v.background_check_evidence_id), "training": bool(v.training_evidence_id),
                "national_id_check": bool(v.national_id_check_id), "checklist_version": v.checklist_version}

    def get_payee(self, obj) -> dict:
        p = obj.payee
        if p is None:
            return None
        return {"id": str(p.pk), "kind": p.kind, "legal_name": p.legal_name, "status": p.verification_status,
                "last4": p.last4}

    def get_track_record(self, obj) -> dict:
        from .services import track_record

        return track_record(obj)


class CarerInput(serializers.Serializer):
    person_id = serializers.UUIDField()
    vetting_id = serializers.UUIDField(required=False)
    pay_route = serializers.ChoiceField(choices=Carer.PAY_ROUTES, default="held_funds")
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    agency_org_id = serializers.UUIDField(required=False, allow_null=True)
    languages = serializers.ListField(child=serializers.CharField(), required=False)
    areas = serializers.CharField(required=False, allow_blank=True)


class CarerUpdateInput(serializers.Serializer):
    pay_route = serializers.ChoiceField(choices=Carer.PAY_ROUTES, required=False)
    payee_id = serializers.UUIDField(required=False, allow_null=True)
    agency_org_id = serializers.UUIDField(required=False, allow_null=True)
    languages = serializers.ListField(child=serializers.CharField(), required=False)
    areas = serializers.CharField(required=False, allow_blank=True)


class RemoveCarerInput(serializers.Serializer):
    reason = serializers.CharField()
    replacement_id = serializers.UUIDField(required=False, allow_null=True)


class VisitItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitItem
        fields = ["key", "kind", "label", "photo_required", "photo_allowed", "reading_required", "reading_kind",
                  "outcome", "reason", "reading", "evidence", "recorded_at"]


class CareCheckSummary(serializers.Serializer):
    at = serializers.DateTimeField()
    within_radius = serializers.BooleanField()
    distance_m = serializers.DecimalField(max_digits=10, decimal_places=2)
    evidence = serializers.UUIDField()


class ConfirmationSummary(serializers.Serializer):
    sent_to = serializers.CharField()
    channel = serializers.CharField()
    sent_at = serializers.DateTimeField(allow_null=True)
    code_expires_at = serializers.DateTimeField(allow_null=True)
    attempts = serializers.IntegerField()
    locked = serializers.BooleanField()
    confirmed_by = serializers.DictField(allow_null=True)
    family_confirmed_at = serializers.DateTimeField(allow_null=True)
    call_waiting_for_check = serializers.BooleanField()
    reviewer_decision = serializers.CharField(allow_null=True)
    confirmed_at = serializers.DateTimeField(allow_null=True)


def _check(ci):
    if ci is None:
        return None
    return {"at": ci.device_time, "within_radius": ci.within_radius, "distance_m": ci.distance_m,
            "evidence": ci.evidence_id}


class VisitSerializer(serializers.ModelSerializer):
    fee = MoneyField(prefix="fee")
    plan_reference = serializers.CharField(source="plan.reference", read_only=True)
    family_member = CareFamilyBrief(source="plan.family_member", read_only=True)
    carer = CarerBrief(read_only=True)
    check_in = serializers.SerializerMethodField()
    check_out = serializers.SerializerMethodField()
    items = VisitItemSerializer(many=True, read_only=True)
    items_done = serializers.SerializerMethodField()
    confirmation = serializers.SerializerMethodField()
    payment = serializers.SerializerMethodField()

    class Meta:
        model = Visit
        fields = ["id", "plan", "plan_reference", "family_member", "carer", "plan_version", "window_start",
                  "window_end", "status", "check_in", "check_out", "late_minutes", "items", "items_done",
                  "submitted_at", "confirmed_at", "confirmation", "needs_review_reason", "review_queued_at",
                  "fee", "instruction_id", "work_accepted_at", "paid_at", "payment", "cancel_reason"]

    def get_check_in(self, obj) -> CareCheckSummary(allow_null=True):
        return CareCheckSummary(_check(obj.checkin)).data if obj.checkin_id else None

    def get_check_out(self, obj) -> CareCheckSummary(allow_null=True):
        return CareCheckSummary(_check(obj.checkout)).data if obj.checkout_id else None

    def get_items_done(self, obj) -> int:
        return obj.items.filter(outcome="done").count()

    def get_confirmation(self, obj) -> ConfirmationSummary(allow_null=True):
        from notifications.services import confirmation_status

        c = getattr(obj, "confirmation", None)
        if c is None:
            return None
        ntf = confirmation_status("care_visit", obj.pk)
        by = None
        if c.confirmed_by_family_member_id:
            by = {"relationship": c.confirmed_by_family_member.relationship,
                  "name": c.confirmed_by_family_member.full_name, "method": c.method,
                  "at": c.family_confirmed_at.isoformat() if c.family_confirmed_at else None}
        elif c.method == "reviewer":
            by = {"relationship": "Tenmina reviewer", "name": "", "method": "reviewer",
                  "at": c.decided_at.isoformat() if c.decided_at else None}
        return {"sent_to": c.sent_to_family_member.full_name, "channel": c.sent_channel, "sent_at": c.sent_at,
                "code_expires_at": c.code_expires_at, "attempts": ntf.attempts if ntf else c.attempts,
                "locked": bool(c.locked_at) or (ntf is not None and ntf.status == "locked"), "confirmed_by": by,
                "family_confirmed_at": c.family_confirmed_at,
                "call_waiting_for_check": ntf is not None and ntf.status == "pending_check",
                "reviewer_decision": c.reviewer_decision, "confirmed_at": c.confirmed_at}

    def get_payment(self, obj) -> serializers.CharField():
        if obj.status == "paid":
            return "Paid."
        if obj.carer.pay_route == "tenmina":
            return ("Tenmina pays the carer for this visit from its own account." if obj.confirmed_at else
                    "The carer is paid only once the visit is confirmed.")
        if obj.status == "instructed":
            return "The payment instruction is with the approvers and the bank."
        if obj.status == "confirmed":
            return "The carer is paid for this visit in the next weekly batch after two Tenmina staff approve."
        if obj.status in ("missed", "cancelled"):
            return "Not paid."
        return "Not paid until the family confirms the visit."


class FieldVisitSerializer(VisitSerializer):
    """What the carer's app sees: no confirmation details, nothing about the family's code (ADR-20)."""

    class Meta(VisitSerializer.Meta):
        fields = ["id", "plan_reference", "family_member", "window_start", "window_end", "status", "check_in",
                  "check_out", "items", "items_done", "submitted_at", "confirmed_at", "payment"]


class CareConfirmationInput(serializers.Serializer):
    method = serializers.ChoiceField(choices=["code", "link", "app", "call"])
    code = serializers.RegexField(r"^[0-9]{6}$", required=False)
    family_member_id = serializers.UUIDField(required=False)
    call_note = serializers.CharField(required=False, max_length=1000)


class CareCallCheckInput(serializers.Serializer):
    agree = serializers.BooleanField(default=True)


class ReviewerDecisionInput(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["confirmed", "not_confirmed"])
    note = serializers.CharField(allow_blank=True)


class CareInstructionResult(serializers.Serializer):
    instruction_id = serializers.UUIDField()
    status = serializers.CharField()
    amount = serializers.DictField()
    client_approval = serializers.CharField()


class CareBatchResult(serializers.Serializer):
    prepared = serializers.ListField(child=serializers.DictField())
    blocked = serializers.ListField(child=serializers.DictField())
    awaiting_confirmation = serializers.ListField(child=serializers.DictField())
    paid_by_tenmina = serializers.ListField(child=serializers.CharField())


class CareItemInput(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["done", "not_done", "not_applicable"])
    reason = serializers.CharField(required=False, allow_blank=True)
    reading = serializers.DictField(required=False, allow_null=True)
    evidence_id = serializers.UUIDField(required=False, allow_null=True)


class ConcernInput(serializers.Serializer):
    kind = serializers.ChoiceField(choices=Concern.KINDS)
    severity = serializers.ChoiceField(choices=Concern.SEVERITIES)
    narrative = serializers.CharField()
    evidence_id = serializers.UUIDField(required=False, allow_null=True)


class ConcernSerializer(serializers.ModelSerializer):
    """Staff view: the restricted log."""

    family_member = CareFamilyBrief(source="plan.family_member", read_only=True)
    raised_by = CarePersonBrief(read_only=True)

    class Meta:
        model = Concern
        fields = ["id", "reference", "plan", "visit", "family_member", "raised_by", "kind", "severity", "narrative",
                  "evidence", "raised_at", "routed_to_reviewer", "client_notified_at", "reviewer_notified_at",
                  "paged_at", "acknowledged_by", "acknowledged_at", "action_taken", "client_outcome", "actioned_at",
                  "closed_at", "status"]


class ClientConcernSerializer(serializers.ModelSerializer):
    """The client's view: the outcome, never the carer's notes (US-CARE-006 AC2)."""

    family_member = CareFamilyBrief(source="plan.family_member", read_only=True)

    class Meta:
        model = Concern
        fields = ["id", "reference", "plan", "visit", "family_member", "kind", "severity", "raised_at", "status",
                  "client_outcome", "actioned_at", "closed_at"]


class ConcernActionInput(serializers.Serializer):
    action_taken = serializers.CharField()
    client_outcome = serializers.CharField()


class CareStatementSerializer(serializers.Serializer):
    plan_id = serializers.UUIDField()
    by_status = serializers.DictField()
