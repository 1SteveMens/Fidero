"""Payment provider port (IF-02, `FeeGateway` in 02 section 9) and its adapters (ADR-10).

The port takes Tenmina's own fees only. Card details are entered only on the
provider's hosted page; Tenmina receives at most the brand and last four
digits (FR-PAY-002). Refunds go only against the original transaction
(FR-PAY-008): the port has no way to name another card, wallet or account.

`FakePaymentProvider` simulates a hosted checkout on the API itself
(`/v1/payments/{id}/fake-checkout`), signed webhooks, verification by
reference, refunds and the daily settlement report, so the whole flow runs
offline. A real adapter (Paystack is the working choice [TO VERIFY]) replaces
it through settings.TENMINA["ADAPTERS"]["payments"].
"""
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.conf import settings
from django.utils import timezone


@dataclass
class Checkout:
    provider_ref: str
    checkout_url: str


@dataclass
class ProviderState:
    """The authoritative state of one transaction, as the provider reports it."""

    provider_ref: str
    status: str                 # pending | success | failed
    amount: Decimal
    currency: str
    method: str = ""
    card_brand: str = ""
    card_last4: str = ""
    wallet_last4: str = ""
    failure_code: str = ""
    paid_at: object = None


@dataclass
class RefundResult:
    ok: bool
    refund_ref: str = ""
    failure: str = ""
    pending: bool = False


@dataclass
class WebhookEvent:
    event_id: str
    event_type: str
    provider_ref: str
    data: dict = field(default_factory=dict)


@dataclass
class SettlementItem:
    provider_ref: str
    amount: Decimal
    currency: str
    fee: Decimal = Decimal("0")
    settled_at: object = None


class PaymentProvider:
    """The port. Every adapter implements these methods."""

    name = "base"
    hosted_checkout = True

    def create_checkout(self, *, payment, return_url: str, wallet_phone: str = "") -> Checkout:
        raise NotImplementedError

    def verify(self, provider_ref: str) -> ProviderState | None:
        raise NotImplementedError

    def refund(self, *, provider_ref: str, amount: Decimal, currency: str, idempotency_key: str) -> RefundResult:
        raise NotImplementedError

    def verify_signature(self, body: bytes, headers) -> bool:
        raise NotImplementedError

    def parse_event(self, body: bytes) -> WebhookEvent:
        raise NotImplementedError

    def settlement(self, settlement_date: date) -> list[SettlementItem]:
        raise NotImplementedError


def webhook_secret() -> str:
    return (settings.TENMINA.get("PAYMENTS_WEBHOOK_SECRET") or os.environ.get("TENMINA_PAYMENTS_WEBHOOK_SECRET")
            or "dev-only-fake-payments-webhook-secret")


FAKE_FEE_RATE = Decimal("0.0195")  # provider fee in the fake settlement report [TO VERIFY]
FAKE_OUTCOMES = {
    # outcome: (status, failure_code)
    "success": ("success", ""),
    "decline": ("failed", "card_declined"),
    "insufficient_funds": ("failed", "insufficient_funds"),
    "3ds_failed": ("failed", "authentication_failed"),
    "abandon": ("failed", "abandoned"),
    "approve_prompt": ("success", ""),       # mobile money: the client approves the prompt on the phone
    "reject_prompt": ("failed", "wallet_rejected"),
    "timeout": ("pending", ""),              # mobile money: no answer; our timeout job fails it later
}


class FakePaymentProvider(PaymentProvider):
    name = "fake"
    SIGNATURE_HEADER = "X-Fake-Signature"

    def _model(self):
        from .models import FakeProviderTransaction

        return FakeProviderTransaction

    def create_checkout(self, *, payment, return_url="", wallet_phone=""):
        ref = f"fake_{secrets.token_hex(10)}"
        self._model().objects.create(reference=ref, amount=payment.amount, currency=payment.currency,
                                     method=payment.method, session_token=secrets.token_urlsafe(16),
                                     wallet_last4=(wallet_phone or "")[-4:])
        return Checkout(provider_ref=ref, checkout_url=f"/v1/payments/{payment.pk}/fake-checkout")

    def verify(self, provider_ref):
        t = self._model().objects.filter(reference=provider_ref).first()
        if t is None:
            return None
        return ProviderState(provider_ref=t.reference, status=t.status, amount=t.amount, currency=t.currency,
                             method=t.method, card_brand=t.card_brand, card_last4=t.card_last4,
                             wallet_last4=t.wallet_last4, failure_code=t.failure_code, paid_at=t.paid_at)

    def complete(self, provider_ref, outcome, *, refundable=True):
        """What the client does on the hosted page. Returns the webhook the provider would send, or None."""
        if outcome not in FAKE_OUTCOMES:
            raise ValueError(outcome)
        t = self._model().objects.get(reference=provider_ref)
        status, code = FAKE_OUTCOMES[outcome]
        t.status, t.failure_code, t.refundable = status, code, refundable
        if status == "success":
            t.paid_at = timezone.now()
            if t.method == "card":
                t.card_brand, t.card_last4 = "visa", "4242"   # test card; only brand and last 4 ever leave
        t.save()
        if status == "pending":
            return None
        kind = "charge.success" if status == "success" else "charge.failed"
        return self.signed_event(kind, provider_ref)

    def signed_event(self, kind, provider_ref, event_id=None):
        body = json.dumps({"id": event_id or f"evt_{secrets.token_hex(8)}", "type": kind,
                           "data": {"reference": provider_ref}}).encode()
        sig = hmac.new(webhook_secret().encode(), body, hashlib.sha256).hexdigest()
        return body, {self.SIGNATURE_HEADER: sig}

    def verify_signature(self, body, headers):
        sig = headers.get(self.SIGNATURE_HEADER) or headers.get(f"HTTP_{self.SIGNATURE_HEADER.upper().replace('-', '_')}")
        if not sig:
            return False
        expected = hmac.new(webhook_secret().encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, sig)

    def parse_event(self, body):
        d = json.loads(body)
        return WebhookEvent(event_id=str(d["id"]), event_type=str(d.get("type", "")),
                            provider_ref=str((d.get("data") or {}).get("reference", "")), data=d.get("data") or {})

    def refund(self, *, provider_ref, amount, currency, idempotency_key):
        t = self._model().objects.filter(reference=provider_ref).first()
        if t is None or t.status != "success":
            return RefundResult(ok=False, failure="The original payment was not found at the provider.")
        if not t.refundable:
            return RefundResult(ok=False, failure="The card or wallet that paid can no longer receive money.")
        if t.refunded + amount > t.amount or currency != t.currency:
            return RefundResult(ok=False, failure="The refund is larger than what is left of the payment.")
        t.refunded += amount
        t.save(update_fields=["refunded", "updated_at", "row_version"])
        return RefundResult(ok=True, refund_ref=f"fake_rf_{hashlib.sha256(idempotency_key.encode()).hexdigest()[:16]}")

    def settlement(self, settlement_date):
        out = []
        for t in self._model().objects.filter(status="success", paid_at__date=settlement_date):
            out.append(SettlementItem(provider_ref=t.reference, amount=t.amount, currency=t.currency,
                                      fee=(t.amount * FAKE_FEE_RATE).quantize(Decimal("0.01")), settled_at=t.paid_at))
        return out


class OfflineRefunds:
    """Manual adapter for fees paid offline (FR-ORD-004): staff pay the money back to the account it came from
    and record the bank's reference and proof (FR-PAY-008, I-40). There is no way to name another account."""

    name = "offline"


def provider() -> PaymentProvider:
    from core.adapters import get_adapter

    return get_adapter("payments", default="payments.adapters.FakePaymentProvider")
