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


class FakeSmsProvider:
    """The SMS provider port for one-time codes (FR-ACC-015, IF-07). Writes
    each text to the log, so in development the code appears in the API log,
    and keeps it in memory for tests. A real provider implements send_sms()."""

    name = "fake_sms"
    sent: list = []  # {"to", "text", "ref"}, newest last
    fail = False     # tests switch the provider off

    def send_sms(self, *, to: str, text: str) -> dict:
        if type(self).fail:
            log.info("[sms] simulated failure to %s", to)
            return {"ok": False, "error": "SMS provider unavailable (simulated)"}
        ref = f"fake-sms-{uuid.uuid4().hex[:12]}"
        type(self).sent.append({"to": to, "text": text, "ref": ref})
        del type(self).sent[:-200]
        log.info("[sms] to %s: %s", to, text)
        return {"ok": True, "provider_ref": ref}


class _PlannedSmsProvider:
    """Placeholder for a Ghanaian SMS gateway. Not connected: the contract,
    sender ID registration and cost per message are [TO VERIFY]. Until then
    it refuses to send, so a misconfigured server never fails silently."""

    name = "planned"
    env_key = ""

    def send_sms(self, *, to: str, text: str) -> dict:
        return {"ok": False, "error": f"{self.name} is not connected yet [TO VERIFY]. Set {self.env_key} and "
                                      "finish the adapter."}


class HubtelSms(_PlannedSmsProvider):
    """Hubtel SMS API (Ghana) [TO VERIFY]: client id and secret, sender ID 'Tenmina'."""

    name = "hubtel"
    env_key = "TENMINA_HUBTEL_CLIENT_ID and TENMINA_HUBTEL_CLIENT_SECRET"


class ArkeselSms(_PlannedSmsProvider):
    """Arkesel SMS API (Ghana) [TO VERIFY]: API key, sender ID 'Tenmina'."""

    name = "arkesel"
    env_key = "TENMINA_ARKESEL_API_KEY"


def sign(raw: bytes) -> str:
    """For tests and local tools: the signature the console adapter expects."""
    return hmac.new(webhook_secret().encode(), raw, hashlib.sha256).hexdigest()
