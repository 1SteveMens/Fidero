from rest_framework import serializers

from .models import CONTEXT_TYPES, SUBJECT_TYPES, Rating, RatingOpportunity, TrackRecord


class RateIn(serializers.Serializer):
    opportunity_id = serializers.UUIDField(required=False)
    context_type = serializers.ChoiceField(choices=CONTEXT_TYPES, required=False)
    context_id = serializers.UUIDField(required=False)
    subject_type = serializers.ChoiceField(choices=SUBJECT_TYPES, required=False)
    subject_id = serializers.UUIDField(required=False)
    score = serializers.IntegerField()
    comment = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get("opportunity_id") and not all(attrs.get(k) for k in ("context_type", "context_id",
                                                                               "subject_type", "subject_id")):
            raise serializers.ValidationError({"opportunity_id": "Give the opportunity, or the item and subject."})
        return attrs


class HideIn(serializers.Serializer):
    reason = serializers.CharField()


class OpportunitySerializer(serializers.ModelSerializer):
    rated = serializers.SerializerMethodField()

    class Meta:
        model = RatingOpportunity
        fields = ["id", "context_type", "context_id", "context_label", "subject_type", "subject_id", "subject_role",
                  "subject_name", "rated", "created_at"]

    def get_rated(self, o) -> bool:
        return hasattr(o, "rating")


class RatingSerializer(serializers.ModelSerializer):
    """The rater and staff see the comment and its status; a hidden comment shows only its reason to staff."""

    comment = serializers.SerializerMethodField()
    subject_name = serializers.CharField(source="opportunity.subject_name", read_only=True)

    class Meta:
        model = Rating
        fields = ["id", "context_type", "context_id", "subject_type", "subject_id", "subject_role", "subject_name",
                  "score", "comment", "comment_status", "hidden_reason", "moderated_at", "created_at"]

    def get_comment(self, r) -> str:
        user = getattr(self.context.get("request"), "user", None)
        from core.permissions import has_role

        if r.comment_status == "published" or (user and (user.pk == r.rater_id or has_role(user, "RV", "AD"))):
            return r.comment
        return ""


class PublicCommentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Rating
        fields = ["id", "score", "comment", "subject_role", "created_at"]


class TrackRecordSerializer(serializers.ModelSerializer):
    summary = serializers.SerializerMethodField()
    comments = serializers.SerializerMethodField()

    class Meta:
        model = TrackRecord
        fields = ["subject_type", "subject_id", "display_name", "roles", "enough_history", "summary",
                  "deals_completed", "tasks_completed", "tasks_on_time", "milestones_completed",
                  "milestones_with_defects", "milestones_failed", "disputes_total", "disputes_lost",
                  "ratings_count", "average_score", "on_time_pct", "computed_at", "comments"]

    def get_summary(self, t) -> str:
        from .selectors import summary

        return summary(t.subject_type, t.subject_id)["summary"]

    def get_comments(self, t) -> list[dict]:
        from .selectors import published_comments

        return PublicCommentSerializer(published_comments(t.subject_type, t.subject_id), many=True).data


class SummarySerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    subject_id = serializers.UUIDField()
    enough_history = serializers.BooleanField()
    summary = serializers.CharField()
    deals_completed = serializers.IntegerField()
    disputes_lost = serializers.IntegerField()
    average_score = serializers.DecimalField(max_digits=3, decimal_places=2, allow_null=True)
    ratings_count = serializers.IntegerField()
