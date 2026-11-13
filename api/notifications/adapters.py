"""Messaging and push ports (ADR-10, IF-07, IF-12).

The console adapters log instead of sending and keep what they "sent" in
memory, so development and tests can read a code that went by SMS. Set
`ConsoleMessaging.fail_channels = {"whatsapp"}` in a test to simulate a
provider failure. Real adapters (WhatsApp Business, an SMS gateway, SES,
APNs, FCM) implement the same methods.
"""
import hashlib
import hmac
import logging
import os
import uuid

log = logging.getLogger("tenmina.messaging")

WEBHOOK_SECRET_ENV = "TENMINA_MESSAGING_WEBHOOK_SECRET"
DEV_WEBHOOK_SECRET = "dev-messaging-webhook-secret"


def webhook_secret() -> str:
    return os.environ.get(WEBHOOK_SECRET_ENV, DEV_WEBHOOK_SECRET)


class ConsoleMessaging:
    """SMS, WhatsApp and email to the log (dev and tests)."""

    name = "console"
    outbox: list = []
    fail_channels: set = set()

    def send(self, message) -> dict:
        if message.channel in self.fail_channels:
            log.info("[%s] simulated failure to %s", message.channel, message.person or message.to_address)
            return {"ok": False, "error": f"{message.channel} provider unavailable (simulated)"}
        ref = f"console-{uuid.uuid4().hex[:12]}"
        ConsoleMessaging.outbox.append({"channel": message.channel, "to": message.to_address, "body": message.body,
                                        "subject": message.subject, "ref": ref, "message_id": str(message.pk)})
        log.info("[%s] to %s: %s", message.channel, message.person or message.to_address, message.body[:200])
        return {"ok": True, "provider_ref": ref}

    # Inbound webhooks (7.3): verify the signature, then ask the provider for the
    # authoritative state rather than trusting the body.
    def verify_signature(self, raw: bytes, signature: str) -> bool:
        expected = hmac.new(webhook_secret().encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, (signature or "").strip())

    def fetch_status(self, provider_ref: str, claimed: str) -> str:
        return claimed


class ConsolePush(ConsoleMessaging):
    """APNs and FCM to the log. Tokens starting with 'invalid' are reported invalid."""

    name = "console_push"
    sent: list = []

    def send_push(self, device, title: str, body: str, data=None) -> str:
        if device.token.startswith("invalid"):
            return "invalid_token"
        if "push" in self.fail_channels:
            return "failed"
        ConsolePush.sent.append({"device": str(device.pk), "title": title, "body": body, "data": data or {}})
        log.info("[push/%s] %s: %s", device.provider, title, body[:120])
        return "ok"

    def send(self, message) -> dict:  # a push Message is sent per device by the service
        return {"ok": True, "provider_ref": ""}


def sign(raw: bytes) -> str:
    """For tests and local tools: the signature the console adapter expects."""
    return hmac.new(webhook_secret().encode(), raw, hashlib.sha256).hexdigest()
