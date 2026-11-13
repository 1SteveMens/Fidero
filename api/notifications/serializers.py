from rest_framework import serializers

from countries.models import Country

from . import catalogue
from .models import ConfirmationCode, DeliveryEvent, Message, PushDevice, Template


class InboxMessageSerializer(serializers.ModelSerializer):
    unread = serializers.SerializerMethodField()
    action_open = serializers.SerializerMethodField(help_text="True while it needs the client (orange in the apps).")

    class Meta:
        model = Message
        fields = ["id", "template", "category", "subject", "body", "link", "subject_type", "subject_id",
                  "needs_action", "action_open", "action_done_at", "read_at", "unread", "created_at"]
        read_only_fields = fields

    def get_unread(self, obj) -> bool:
        return obj.read_at is None

    def get_action_open(self, obj) -> bool:
        return obj.needs_action and obj.action_done_at is None


class UnreadCountSerializer(serializers.Serializer):
    unread = serializers.IntegerField()
    needs_action = serializers.IntegerField()


class InboxMarkedSerializer(serializers.Serializer):
    marked = serializers.IntegerField()


class NotificationPreferenceSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=list(catalogue.CHANNELS))
    enabled = serializers.BooleanField(default=True)
    quiet_start = serializers.TimeField(required=False, allow_null=True)
    quiet_end = serializers.TimeField(required=False, allow_null=True)
    timezone = serializers.CharField(required=False, allow_blank=True, default="")
    muted_categories = serializers.ListField(child=serializers.ChoiceField(choices=list(catalogue.CATEGORIES)),
                                             required=False, default=list)
    address = serializers.CharField(required=False, allow_blank=True, default="")


class NotificationPreferencesUpdateSerializer(serializers.Serializer):
    items = NotificationPreferenceSerializer(many=True)


class PushDeviceSerializer(serializers.ModelSerializer):
    token = serializers.CharField(write_only=True)

    class Meta:
        model = PushDevice
        fields = ["id", "app", "platform", "provider", "token", "install_id", "app_version", "os_version",
                  "last_seen_at", "revoked_at", "created_at"]
        read_only_fields = ["id", "provider", "last_seen_at", "revoked_at", "created_at"]


class NtfDeliveryEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryEvent
        fields = ["id", "provider", "provider_event_id", "status", "occurred_at", "created_at"]


class MessageLogSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    delivery_events = NtfDeliveryEventSerializer(many=True, read_only=True)
    template_version_no = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = ["id", "person", "to_address", "channel", "template", "template_version", "template_version_no",
                  "category", "language", "country", "subject", "body", "link", "subject_type", "subject_id",
                  "status", "needs_action", "read_at", "provider", "provider_ref", "attempts", "error",
                  "scheduled_for", "sent_at", "delivered_at", "failed_at", "fallback_of", "group_id",
                  "delivery_events", "created_at"]
        read_only_fields = fields

    def get_template_version_no(self, obj) -> int | None:
        return obj.template_version.version if obj.template_version_id else None


class NotificationTemplateSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", queryset=Country.objects.all(), required=False,
                                           allow_null=True)

    class Meta:
        model = Template
        fields = ["id", "code", "channel", "language", "country", "version", "subject", "body", "status",
                  "whatsapp_template_name", "created_by", "created_at"]
        read_only_fields = ["id", "version", "status", "created_by", "created_at"]


class CatalogueEntrySerializer(serializers.Serializer):
    code = serializers.CharField()
    category = serializers.CharField()
    variables = serializers.ListField(child=serializers.CharField())
    required = serializers.ListField(child=serializers.CharField())
    phone_allowed = serializers.ListField(child=serializers.CharField(),
                                          help_text="Variables allowed on SMS, WhatsApp and push.")
    default_subject = serializers.CharField(allow_blank=True)
    default_body = serializers.CharField()
    default_phone = serializers.CharField()


class TemplatePreviewSerializer(serializers.Serializer):
    code = serializers.CharField()
    channel = serializers.ChoiceField(choices=list(catalogue.CHANNELS))
    language = serializers.CharField(required=False, default="en")
    country = serializers.CharField(required=False, allow_blank=True)
    context = serializers.DictField(required=False, default=dict)


class TemplatePreviewResultSerializer(serializers.Serializer):
    subject = serializers.CharField(allow_blank=True)
    body = serializers.CharField(allow_blank=True)
    template_version = serializers.IntegerField(allow_null=True)


class FamilyConfirmationSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = ConfirmationCode
        fields = ["id", "country", "subject_type", "subject_id", "purpose", "recipient_person", "recipient_name",
                  "channel", "summary", "expires_at", "attempts", "max_attempts", "status", "confirmed_at",
                  "confirmed_via", "call_recorded_by", "call_outcome", "call_note", "call_checked_by", "created_by",
                  "created_at"]
        read_only_fields = fields


class ConfirmationSendSerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    subject_id = serializers.CharField()
    purpose = serializers.CharField(default="care_visit")
    country = serializers.CharField(max_length=2)
    channel = serializers.ChoiceField(choices=["sms", "whatsapp", "in_app"], default="sms")
    to_address = serializers.CharField(required=False, allow_blank=True, default="")
    recipient_name = serializers.CharField(required=False, allow_blank=True, default="")
    recipient_person = serializers.UUIDField(required=False, allow_null=True)
    summary = serializers.CharField(required=False, allow_blank=True, default="")


class PublicConfirmationSerializer(serializers.Serializer):
    status = serializers.CharField()
    purpose = serializers.CharField()
    summary = serializers.CharField(allow_blank=True)
    expires_at = serializers.DateTimeField()


class LinkDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["confirm", "dispute"], default="confirm")


class CodeAttemptSerializer(serializers.Serializer):
    subject_type = serializers.CharField()
    subject_id = serializers.CharField()
    code = serializers.CharField(max_length=12)


class ConfirmationAttemptResultSerializer(serializers.Serializer):
    ok = serializers.BooleanField()
    status = serializers.CharField()
    attempts_left = serializers.IntegerField()


class ConfirmationCallRecordSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["confirm", "dispute"], default="confirm")
    note = serializers.CharField()


class ConfirmationCallCheckSerializer(serializers.Serializer):
    agree = serializers.BooleanField(default=True)


class DeliveryHookSerializer(serializers.Serializer):
    provider = serializers.CharField()
    event_id = serializers.CharField()
    provider_ref = serializers.CharField(required=False, allow_blank=True, default="")
    status = serializers.CharField()
    occurred_at = serializers.DateTimeField(required=False, allow_null=True)


class ReplyHookSerializer(serializers.Serializer):
    provider = serializers.CharField()
    event_id = serializers.CharField()
    channel = serializers.ChoiceField(choices=["sms", "whatsapp"], default="sms")
    sender = serializers.CharField(help_text="The phone number the reply came from.")
    text = serializers.CharField(allow_blank=True)


class MessagingHookAckSerializer(serializers.Serializer):
    received = serializers.BooleanField()
    duplicate = serializers.BooleanField(required=False)
