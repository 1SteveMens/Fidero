from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import IN_FAVOUR, OUTCOMES, SUBJECT_TYPES, Decision, Dispute, Party, Statement, SubjectLink


class OpenIn(serializers.Serializer):
    subject_type = serializers.ChoiceField(choices=SUBJECT_TYPES)
    subject_id = serializers.UUIDField()
    project_id = serializers.UUIDField(required=False, help_text="For a milestone: its project")
    reason = serializers.CharField()
    category = serializers.ChoiceField(choices=Dispute.CATEGORIES, default="other")
    statement = serializers.CharField(required=False, allow_blank=True)
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class StatementIn(serializers.Serializer):
    text = serializers.CharField()
    evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class DecisionIn(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=OUTCOMES)
    in_favour_of = serializers.ChoiceField(choices=IN_FAVOUR)
    reasons = serializers.CharField()
    details = serializers.DictField(required=False)


class MediationOutcomeIn(DecisionIn):
    mediation_reference = serializers.CharField()


class DecisionApprovalIn(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True)


class ReferralIn(serializers.Serializer):
    mediator = serializers.CharField()
    reason = serializers.CharField()


class WithdrawIn(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True)


class DisputePartySerializer(serializers.ModelSerializer):
    class Meta:
        model = Party
        fields = ["id", "side", "role", "name", "notified_at", "responded_at", "missed_response",
                  "evidence_complete_at"]


class DisputeStatementSerializer(serializers.ModelSerializer):
    party_name = serializers.SerializerMethodField()

    class Meta:
        model = Statement
        fields = ["id", "kind", "party_id", "party_name", "text", "evidence_ids", "created_at"]

    def get_party_name(self, s) -> str:
        return s.party.name if s.party_id else "Tenmina"


class LinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubjectLink
        fields = ["subject_type", "subject_id", "prior_status"]


class DecisionSerializer(serializers.ModelSerializer):
    approvals = serializers.SerializerMethodField()

    class Meta:
        model = Decision
        fields = ["id", "kind", "outcome", "in_favour_of", "reasons", "details", "status", "prepared_by",
                  "approval_request_id", "approvals", "created_at", "decided_at"]

    def get_approvals(self, d) -> int:
        return d.approval_request.approvals.filter(decision="approve").count() if d.approval_request_id else 0


class DisputeListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispute
        fields = ["id", "reference", "status", "category", "subject_type", "subject_id", "subject_label", "reason",
                  "response_due", "evidence_due", "decision_due", "escalated_at", "created_at", "closed_at"]


class DisputeSerializer(DisputeListSerializer):
    parties = DisputePartySerializer(many=True, read_only=True)
    statements = DisputeStatementSerializer(many=True, read_only=True)
    links = LinkSerializer(many=True, read_only=True)
    decisions = serializers.SerializerMethodField()
    my_side = serializers.SerializerMethodField()

    class Meta(DisputeListSerializer.Meta):
        fields = DisputeListSerializer.Meta.fields + [
            "escrow_id", "project_id", "milestone_id", "listing_id", "opened_by_staff", "early_move_note",
            "decision", "decision_outcome", "in_favour_of", "decided_by", "decided_at", "referred_at", "mediator",
            "mediation_reference", "withdrawn_at", "withdraw_reason", "parties", "statements", "links", "decisions",
            "my_side"]

    @extend_schema_field(DecisionSerializer(many=True))
    def get_decisions(self, d):
        from . import services

        user = getattr(self.context.get("request"), "user", None)
        qs = d.decisions.all() if user and services.is_staff(user, d.country) else d.decisions.filter(
            status="approved")
        return DecisionSerializer(qs.select_related("approval_request"), many=True).data

    def get_my_side(self, d) -> str | None:
        from . import services

        user = getattr(self.context.get("request"), "user", None)
        p = services.party_of(user, d) if user else None
        return p.side if p else None
