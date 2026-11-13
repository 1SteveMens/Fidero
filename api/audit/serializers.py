from rest_framework import serializers

from .models import AuditAnchor, AuditEvent, ChainCheck, SecurityAlert


class AuditEventSerializer(serializers.ModelSerializer):
    actor = serializers.CharField(source="actor_label")
    country = serializers.CharField(source="country_code")

    class Meta:
        model = AuditEvent
        fields = ["seq", "occurred_at", "actor_id", "actor", "actor_kind", "action", "entity", "entity_id", "country",
                  "data", "origin_ip", "user_agent", "trace_id", "prev_hash", "hash"]


class AuditSearchSerializer(serializers.Serializer):
    """Query parameters for FR-AUD-003."""

    entity = serializers.CharField(required=False)
    entity_id = serializers.CharField(required=False)
    case_id = serializers.CharField(required=False, help_text="Entries about this case or naming it in their data.")
    action = serializers.CharField(required=False, help_text="Exact action, or a prefix ending in '.' or '*'.")
    actor_id = serializers.UUIDField(required=False)
    country = serializers.CharField(required=False, max_length=2)
    occurred_from = serializers.DateTimeField(required=False)
    occurred_to = serializers.DateTimeField(required=False)
    before_seq = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=200, default=50)


class AuditPageSerializer(serializers.Serializer):
    items = AuditEventSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)


class TrailExportSerializer(serializers.Serializer):
    entity = serializers.CharField()
    entity_id = serializers.CharField()
    exported_at = serializers.DateTimeField()
    entries = serializers.IntegerField()
    entries_intact = serializers.BooleanField()
    sha256 = serializers.CharField()
    items = AuditEventSerializer(many=True)


class ChainCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChainCheck
        fields = ["id", "ran_at", "ok", "checked", "broken_at", "anchors_ok", "anchor_problem", "triggered_by"]


class AuditVerifyResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    checked = serializers.IntegerField()
    broken_at = serializers.IntegerField(allow_null=True)
    anchors_ok = serializers.BooleanField()
    anchor_problem = serializers.CharField(allow_blank=True)
    check_id = serializers.UUIDField()


class AuditAnchorSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditAnchor
        fields = ["id", "seq", "hash", "anchored_at", "location"]


class SecurityAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecurityAlert
        fields = ["id", "created_at", "kind", "severity", "channel", "summary", "entity", "entity_id", "country_code",
                  "audit_seq", "acknowledged_by", "acknowledged_at", "note"]
        read_only_fields = fields


class AlertAcknowledgeSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")
