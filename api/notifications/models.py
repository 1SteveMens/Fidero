"""Notifications (NTF). Foundation part: the message log and notify().
Templates per language and channel, preferences, content policy, delivery
events and push devices are added by the NTF build."""
from django.conf import settings
from django.db import models

from core.models import BaseModel


class Message(BaseModel):
    CHANNELS = ["in_app", "email", "sms", "whatsapp", "push"]
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="messages")
    to_address = models.TextField(blank=True, default="")  # phone or email for people without an account
    channel = models.TextField(choices=[(c, c) for c in CHANNELS], default="in_app")
    template = models.TextField()
    subject = models.TextField(blank=True, default="")
    body = models.TextField()
    link = models.TextField(blank=True, default="")
    subject_type = models.TextField(blank=True, default="")
    subject_id = models.TextField(blank=True, default="")
    status = models.TextField(default="queued")  # queued | sent | delivered | failed | read
    read_at = models.DateTimeField(null=True, blank=True)
    needs_action = models.BooleanField(default=False)  # orange in the apps: needs the client

    class Meta:
        db_table = "ntf_message"
        indexes = [models.Index(fields=["person", "status"])]
