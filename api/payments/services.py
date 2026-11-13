"""PAY Tenmina fee payments: the public interface other modules may call.

FR-PAY-001 card and mobile money through the provider's hosted checkout
FR-PAY-002 no card numbers: brand and last four only, a DB trigger refuses card numbers
FR-PAY-003 numbered receipts and credit notes, by email and in the portal
FR-PAY-004 refunds with a reason and two approvers who did not prepare them
FR-PAY-005 every payment links to a fee order or seller invoice; fee purposes only (RUL-01)
FR-PAY-006 daily settlement reconciliation with a mismatch list
FR-PAY-007 seller invoices (checked plots, listing fees; success fees only if Q-31 allows)
FR-PAY-008 refunds only through the provider to the original payment method; offline to the source account
FR-ORD-004 offline payments recorded by a case manager with proof; over a threshold, two approvals
"""
import csv
import hashlib
import io
import json
import logging
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from administration import flags
from audit.services import record
from core import approvals, state
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict
from core.events import publish
from core.permissions import has_role
from countries.models import Country
from countries.selectors import config
from orders import services as orders
from orders.access import is_staff_for

from . import adapters
from .models import (FeePayment, Invoice, NumberCounter, Receipt, ReconIssue, Refund, SettlementLine, SettlementRun,
                     WebhookEvent)

log = logging.getLogger(__name__)

STAFF = ("CM", "RV", "AD")
LIVE_REFUND = ["requested", "approved", "processing", "completed", "failed"]
PLAIN_REASONS = {
    "card_declined": "Your bank declined the card. Nothing was taken. Try another card or pay by mobile money.",
    "insufficient_funds": "The card or wallet did not have enough money. Nothing was taken. You can try again.",
    "authentication_failed": "The card security check was not completed. Nothing was taken. You can try again.",
    "abandoned": "The payment was not finished. Nothing was taken. You can start again.",
    "wallet_rejected": "The payment prompt was declined on the phone. Nothing was taken. You can try again.",
    "timeout": "We did not hear back from your mobile money provider in time. Nothing was taken. You can try again.",
    "rejected_by_staff": "The bank transfer could not be confirmed. Contact us so we can check it with you.",
    "superseded": "You started a new payment, so this one was closed. Nothing was taken.",
}


def plain_reason(code: str) -> str:
    return PLAIN_REASONS.get(code, "The payment did not go through. Nothing was taken. You can try again.")


def _cfg(country, key, default):
    return config(country, f"payments.{key}", default)


def next_number(series: str, country: Country) -> str:
    year = timezone.now().year
    with transaction.atomic():
        NumberCounter.objects.get_or_create(series=series, country_code=country.code, year=year)
        c = NumberCounter.objects.select_for_update().get(series=series, country_code=country.code, year=year)
        c.last += 1
        c.save(update_fields=["last"])
    width = 5 if series == "INV" else 6
    return f"{series}-{country.code}-{year}-{c.last:0{width}d}"


def _staff(actor, country, roles=STAFF, message="Only Tenmina staff can do this."):
    if not (has_role(actor, *roles) and is_staff_for(actor, country, roles)):
        raise Forbidden(message)


def _staff_people(country, roles=("CM",)):
    from django.db.models import Q

    from accounts.models import Person

    return Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                 role_grants__role__in=list(roles), role_grants__revoked_at__isnull=True,
                                 is_active=True).distinct()


def _notify_staff(country, template, subject, body, obj=None):
    from notifications.services import notify

    for p in _staff_people(country):
        notify(p, template, subject=subject, body=body, subject_obj=obj, link="/back-office/payments")


def _notify(person, template, subject, body, obj=None, needs_action=False, link=""):
    from notifications.services import notify

    if person is not None:
        notify(person, template, subject=subject, body=body, channels=("in_app", "email"), subject_obj=obj,
               needs_action=needs_action, link=link)


def _payload(p: FeePayment, **extra) -> dict:
    order_id = p.order_id or (p.invoice.order_id if p.invoice_id else None)
    return {"payment_id": p.pk, "order_id": order_id, "invoice_id": p.invoice_id, "amount": p.amount,
            "currency": p.currency, "method": p.method, "purpose": p.purpose, "payer_id": p.payer_id,
            "country": p.country.code, "offline": p.method == "bank_transfer_offline", **extra}


# ---------------------------------------------------------------- starting a payment (FR-PAY-001, FR-PAY-005)


def _close_stale_attempts(qs):
    """Before a new attempt, ask the provider about earlier ones. Returns True if one is in fact paid."""
    for p in qs.filter(status="initiated"):
        sync_payment(p)
        p.refresh_from_db()
        if p.status == "confirmed":
            return True
        if p.status == "initiated":
            fail_payment(p, "superseded")
    return False


def _start(*, payer, country, purpose, amount, currency, method, order=None, invoice=None, return_url="",
           wallet_phone=""):
    if method not in ("card", "mobile_money"):
        raise Invalid("Choose card or mobile money.", extra={"errors": [{"pointer": "/method", "message": "Invalid."}]})
    if method == "mobile_money":
        flags.require("payments.mobile_money", country)
    if amount is None or Decimal(amount) <= 0:
        raise Invalid("This order has no price to pay.")
    if return_url and not (return_url.startswith("/") or return_url.startswith("https://")
                           or return_url.startswith("http://localhost")):
        raise Invalid("The return address must be a Tenmina page.")
    provider = adapters.provider()
    p = FeePayment.objects.create(country=country, purpose=purpose, payer=payer, order=order, invoice=invoice,
                                  amount=amount, currency=currency, method=method, provider=provider.name,
                                  return_url=return_url or "", wallet_last4=(wallet_phone or "")[-4:])
    checkout = provider.create_checkout(payment=p, return_url=return_url, wallet_phone=wallet_phone)
    p.provider_ref, p.checkout_url = checkout.provider_ref, checkout.checkout_url
    p.save(update_fields=["provider_ref", "checkout_url"])
    record(actor=payer, action="payment.initiated", entity="fee_payment", entity_id=p.pk,
           data={"amount": p.amount, "currency": p.currency, "method": method, "purpose": purpose,
                 "order_id": order.pk if order else None, "invoice_id": invoice.pk if invoice else None},
           country=country)
    publish("payment.initiated", p.pk, _payload(p))
    return p


@transaction.atomic
def start_order_payment(order, actor, *, method, return_url="", wallet_phone=""):
    """POST /v1/orders/{id}/payments. The amount and purpose come from the order, never from the request."""
    flags.read_only_guard()
    from orders.models import Order

    order = Order.objects.select_for_update().get(pk=order.pk)
    if actor != order.client and actor != order.placed_by:
        raise Forbidden("Only the person who placed the order can pay for it.")
    if order.bill_to == "organisation":
        raise StateConflict("This check is paid by the seller's invoice.")
    if _close_stale_attempts(order.payments.all()):
        raise StateConflict("This order is already paid.")
    order.refresh_from_db()
    info = orders.payable(order)  # status and current terms acceptance (FR-ORD-003, TC-ORD-003-02)
    if method == "mobile_money":
        if not info["local_price"]:
            raise Invalid("Mobile money is not available for this order.")
        amount, currency = info["local_price"]
    else:
        amount, currency = info["price"]
    p = _start(payer=actor, country=order.country, purpose=info["purpose"], amount=amount, currency=currency,
               method=method, order=order, return_url=return_url, wallet_phone=wallet_phone)
    orders.note_payment(order.pk, "initiated")
    return p


@transaction.atomic
def start_invoice_payment(invoice: Invoice, actor, *, method, return_url="", wallet_phone=""):
    flags.read_only_guard()
    invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
    if actor != invoice.bill_to_person and invoice.organisation_id not in _org_ids(actor):
        raise Forbidden("Only the organisation billed can pay this invoice.")
    if invoice.status != "issued":
        raise StateConflict("This invoice cannot be paid now.", extra={"invoice_status": invoice.status})
    if _close_stale_attempts(invoice.payments.all()):
        raise StateConflict("This invoice is already paid.")
    amount, currency = invoice.amount, invoice.currency
    if method == "mobile_money":
        from orders.pricing import _round_local, fx_guides

        c = invoice.country
        rate = fx_guides(c).get(c.currency)
        if currency != c.currency:
            if not rate:
                raise Invalid("Mobile money is not available for this invoice.")
            amount, currency = _round_local(amount * Decimal(str(rate))), c.currency
    return _start(payer=actor, country=invoice.country, purpose=invoice.purpose, amount=amount, currency=currency,
                  method=method, invoice=invoice, return_url=return_url, wallet_phone=wallet_phone)


# ---------------------------------------------------------------- provider state (7.3)


def sync_payment(payment: FeePayment, *, provider=None):
    """Fetch the authoritative state from the provider and act on it. Never trusts a webhook body alone."""
    if payment.method == "bank_transfer_offline" or not payment.provider_ref:
        return payment
    provider = provider or adapters.provider()
    st = provider.verify(payment.provider_ref)
    FeePayment.objects.filter(pk=payment.pk).update(last_checked_at=timezone.now())
    if st is None:
        return payment
    if st.status == "success":
        if Decimal(st.amount) != payment.amount or st.currency != payment.currency:
            _issue("amount_mismatch", payment.country, payment=payment, provider_ref=payment.provider_ref,
                   detail=f"The provider reports {st.currency} {st.amount} for a payment of "
                          f"{payment.currency} {payment.amount}. Not confirmed.")
            return payment
        return confirm_payment(payment, card_brand=st.card_brand, card_last4=st.card_last4,
                               wallet_last4=st.wallet_last4)
    if st.status == "failed":
        return fail_payment(payment, st.failure_code or "failed")
    return payment


@transaction.atomic
def confirm_payment(payment: FeePayment, *, card_brand="", card_last4="", wallet_last4="", actor=None):
    """Idempotent. Publishes payment.confirmed; ORD marks the order paid; a receipt is issued."""
    p = FeePayment.objects.select_for_update(of=("self",)).select_related("order", "invoice", "country").get(
        pk=payment.pk)
    if p.status in ("confirmed", "partially_refunded", "refunded"):
        return p
    p.confirmed_at = timezone.now()
    p.card_brand = (card_brand or "")[:20]
    p.card_last4 = card_last4 if (card_last4 or "").isdigit() and len(card_last4) == 4 else ""
    p.wallet_last4 = wallet_last4 if (wallet_last4 or "").isdigit() and len(wallet_last4) == 4 else p.wallet_last4
    p.failure_code = p.failure_message = ""
    order = p.order or (p.invoice.order if p.invoice_id else None)
    closed_order = order is not None and order.status != "awaiting_payment"
    events = ["payment.confirmed"]
    state.transition(p, "pay_payment", "confirmed", actor=actor, event="payment.confirmed", payload=_payload(p),
                     extra_fields=["confirmed_at", "card_brand", "card_last4", "wallet_last4", "failure_code",
                                   "failure_message"])
    if p.method == "bank_transfer_offline":
        publish("payment.offline_recorded", p.pk, _payload(p, recorded_by=p.recorded_by_id))
        events.append("payment.offline_recorded")
    if p.invoice_id and p.invoice.status == "issued":
        inv = p.invoice
        inv.paid_at = p.confirmed_at
        state.transition(inv, "pay_invoice", "paid", actor=actor, event="seller_invoice.paid",
                         payload={"invoice_id": inv.pk, "payment_id": p.pk, "order_id": inv.order_id},
                         extra_fields=["paid_at"])
    if closed_order:
        paid_by_other = order.status == "paid" and order.paid_payment_id != p.pk
        _issue("duplicate_payment" if paid_by_other else "payment_on_closed_order", p.country, payment=p,
               provider_ref=p.provider_ref or "",
               detail=f"Payment of {p.currency} {p.amount} confirmed for order {order.reference}, which is "
                      f"{order.status}. Review it for a refund to the original method.")
    issue_receipt(p)
    return p


@transaction.atomic
def fail_payment(payment: FeePayment, code: str, *, actor=None):
    p = FeePayment.objects.select_for_update().get(pk=payment.pk)
    if p.status not in ("initiated", "pending_approval"):
        return p
    p.failure_code, p.failure_message, p.failed_at = code, plain_reason(code), timezone.now()
    state.transition(p, "pay_payment", "failed", actor=actor, event="payment.failed",
                     payload=_payload(p, code=code, message=p.failure_message),
                     extra_fields=["failure_code", "failure_message", "failed_at"])
    if code != "superseded":
        _notify(p.payer, "payment_failed", "Your payment did not go through", p.failure_message, obj=p,
                needs_action=True, link=f"/orders/{p.order_id}" if p.order_id else "/invoices")
    return p


def reconcile_pending(now=None):
    """Every 15 minutes (IF-02 fallback): verify open attempts with the provider; time out the rest."""
    now = now or timezone.now()
    done = {"checked": 0, "confirmed": 0, "failed": 0}
    for p in FeePayment.objects.filter(status="initiated").exclude(provider_ref__isnull=True):
        done["checked"] += 1
        p = sync_payment(p)
        p.refresh_from_db()
        if p.status == "confirmed":
            done["confirmed"] += 1
            continue
        if p.status != "initiated":
            done["failed"] += 1
            continue
        age = now - p.created_at
        if p.method == "mobile_money" and age > timedelta(minutes=int(_cfg(p.country, "mobile_money_timeout_minutes", 10))):
            fail_payment(p, "timeout")
            done["failed"] += 1
        elif p.method == "card" and age > timedelta(minutes=int(_cfg(p.country, "card_abandon_minutes", 60))):
            fail_payment(p, "abandoned")
            done["failed"] += 1
    return done


def handle_webhook(body: bytes, headers) -> dict:
    """POST /v1/hooks/payments (7.3): verify the signature, store the body hash, deduplicate on the vendor's
    event ID, then fetch the authoritative state from the provider before acting."""
    provider = adapters.provider()
    digest = hashlib.sha256(body).hexdigest()
    if not provider.verify_signature(body, headers):
        record(action="payment.webhook_rejected", entity="webhook", entity_id=digest[:32],
               data={"provider": provider.name, "body_sha256": digest})
        raise DomainError("The webhook signature is not valid.", code="unauthenticated", status=401)
    try:
        ev = provider.parse_event(body)
    except (ValueError, KeyError, TypeError) as exc:
        raise Invalid("The webhook body could not be read.") from exc
    try:
        with transaction.atomic():
            hook = WebhookEvent.objects.create(provider=provider.name, vendor_event_id=ev.event_id,
                                               event_type=ev.event_type, provider_ref=ev.provider_ref[:200],
                                               body_sha256=digest, signature_ok=True)
    except IntegrityError:
        return {"status": "duplicate", "event_id": ev.event_id}
    outcome = _act_on_event(provider, ev)
    hook.processed_at, hook.outcome = timezone.now(), outcome
    hook.save(update_fields=["processed_at", "outcome"])
    return {"status": "processed", "event_id": ev.event_id, "outcome": outcome}


def _act_on_event(provider, ev) -> str:
    if ev.event_type.startswith("refund"):
        r = Refund.objects.filter(provider_refund_ref=ev.provider_ref).first() or Refund.objects.filter(
            payment__provider_ref=ev.provider_ref, status="processing").first()
        if r is None:
            return "refund_unknown"
        return "refund_seen"
    p = FeePayment.objects.filter(provider_ref=ev.provider_ref).first()
    if p is None:
        st = provider.verify(ev.provider_ref)
        if st is not None and st.status == "success":
            # TC-RUL-01-04: money not linked to a fee order. Flag it for refund review; nothing else changes.
            country = Country.objects.filter(currency=st.currency).first() or Country.objects.filter(
                status="active").order_by("activated_at").first()
            _issue("unlinked_payment", country, provider_ref=ev.provider_ref,
                   detail=f"The provider took {st.currency} {st.amount} under reference {ev.provider_ref}, which "
                          f"is not linked to any Tenmina fee order or invoice. Review it for a refund.")
            return "unlinked"
        return "unknown_reference"
    before = p.status
    p = sync_payment(p, provider=provider)
    p.refresh_from_db()
    return f"{before}->{p.status}"


# ---------------------------------------------------------------- receipts (FR-PAY-003)


def _content_hash(fields: dict) -> str:
    from core.events import _jsonable

    return hashlib.sha256(json.dumps(_jsonable(fields), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _method_detail(p: FeePayment) -> str:
    if p.method == "card":
        return f"{(p.card_brand or 'Card').capitalize()} ending {p.card_last4}" if p.card_last4 else "Card"
    if p.method == "mobile_money":
        return f"Mobile money ending {p.wallet_last4}" if p.wallet_last4 else "Mobile money"
    return f"Bank transfer from {p.source_account_name}, {p.source_bank_name}".strip(", ")


def _describe(p: FeePayment) -> tuple[str, str, str]:
    if p.order_id:
        from orders.catalogue import PRODUCTS

        o = p.order
        name = PRODUCTS[o.kind].name + (f", {o.tier_name}" if o.tier_name else "")
        return f"{name} ({o.reference})", o.reference, ""
    inv = p.invoice
    return f"{inv.description} ({inv.number})", inv.order.reference if inv.order_id else "", inv.number


@transaction.atomic
def issue_receipt(p: FeePayment) -> Receipt:
    existing = Receipt.objects.filter(payment=p, kind="receipt").first()
    if existing:
        return existing
    desc, oref, inv = _describe(p)
    now = timezone.now()
    fields = dict(kind="receipt", payment_id=p.pk, issued_to_id=p.payer_id, issued_to_name=p.payer.full_name,
                  amount=p.amount, currency=p.currency, description=desc, order_reference=oref, invoice_number=inv,
                  method=p.method, method_detail=_method_detail(p), issued_at=now)
    number = next_number("RCT", p.country)
    r = Receipt.objects.create(country=p.country, number=number, sha256=_content_hash({"number": number, **fields}),
                               **fields)
    record(action="receipt.issued", entity="receipt", entity_id=r.pk,
           data={"number": number, "payment_id": p.pk, "amount": p.amount, "currency": p.currency}, country=p.country)
    publish("receipt.issued", r.pk, {"receipt_id": r.pk, "payment_id": p.pk, "number": number})
    _notify(p.payer, "fee_receipt", f"Receipt {number}",
            f"Thank you. We received {p.currency} {p.amount:.2f} for {desc}. Receipt number {number}.", obj=r,
            link=f"/payments/{p.pk}/receipt")
    return r


def _credit_note(refund: Refund) -> Receipt:
    existing = Receipt.objects.filter(refund=refund).first()
    if existing:
        return existing
    p = refund.payment
    desc, oref, inv = _describe(p)
    original = Receipt.objects.filter(payment=p, kind="receipt").first()
    fields = dict(kind="credit_note", payment_id=p.pk, refund_id=refund.pk, issued_to_id=p.payer_id,
                  issued_to_name=p.payer.full_name, amount=refund.amount, currency=refund.currency,
                  description=f"Refund of {desc}" + (f", against receipt {original.number}" if original else ""),
                  order_reference=oref, invoice_number=inv, method=p.method, method_detail=_method_detail(p),
                  issued_at=timezone.now())
    number = next_number("CRN", p.country)
    r = Receipt.objects.create(country=p.country, number=number, sha256=_content_hash({"number": number, **fields}),
                               **fields)
    record(action="credit_note.issued", entity="receipt", entity_id=r.pk,
           data={"number": number, "refund_id": refund.pk}, country=p.country)
    _notify(p.payer, "fee_credit_note", f"Refund {number}",
            f"We refunded {refund.currency} {refund.amount:.2f} to {_method_detail(p)}. Credit note {number}.",
            obj=r, link=f"/payments/{p.pk}/receipt")
    return r


# ---------------------------------------------------------------- offline payments (FR-ORD-004)


def _offline_threshold(country, currency):
    th = _cfg(country, "offline_two_person_threshold", {"USD": "500.00", "GHS": "7500.00"})  # [TO VERIFY]
    return Decimal(str(th[currency])) if currency in th else None


def _proof(actor, country, proof_evidence_id=None, proof_file=None):
    from evidence.models import Evidence
    from evidence.services import store

    if proof_file is not None:
        data = proof_file.read()
        if not data:
            raise Invalid("The proof file is empty.", code="evidence-rejected")
        return store(data=data, country=country, uploaded_by=actor,
                     content_type=getattr(proof_file, "content_type", "") or "application/octet-stream",
                     original_name=getattr(proof_file, "name", ""), source="upload",
                     description="Proof of an offline fee payment")
    if proof_evidence_id:
        ev = Evidence.objects.filter(pk=proof_evidence_id, country=country).first()
        if ev is None:
            raise Invalid("The proof file was not found.", code="evidence-rejected")
        return ev
    raise Invalid("Attach proof of payment, such as the bank's transfer advice.", code="proof-required",
                  extra={"errors": [{"pointer": "/proof", "message": "Proof of payment is required."}]})


@transaction.atomic
def record_offline_payment(actor, *, order=None, invoice=None, amount, currency, reference, received_on,
                           source_bank_name, source_account_name, source_account_number="", proof_evidence_id=None,
                           proof_file=None, payer=None):
    """A case manager records a bank transfer or cash-office payment of a fee, with proof (FR-ORD-004).

    The account it came from is recorded, because a refund goes back only there (FR-PAY-008, I-40)."""
    flags.read_only_guard()
    if (order is None) == (invoice is None):
        raise Invalid("Link the payment to one fee order or one invoice (FR-PAY-005).")
    country = (order or invoice).country
    _staff(actor, country, ("CM", "AD"), "Only a case manager can record an offline payment.")
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    currency = (currency or "").upper()
    if order is not None:
        from orders.models import Order

        order = Order.objects.select_for_update().get(pk=order.pk)
        if order.bill_to == "organisation":
            raise StateConflict("This check is paid by the seller's invoice. Record the payment against it.")
        info = orders.payable(order)
        allowed = {info["price"]}
        if info["local_price"]:
            allowed.add(info["local_price"])
        if (amount, currency) not in {(Decimal(a), c) for a, c in allowed}:
            raise Invalid("The amount must equal the price shown to the client.", code="amount-mismatch",
                          extra={"allowed": [{"amount": f"{a:.2f}", "currency": c} for a, c in allowed]})
        purpose, payer = info["purpose"], payer or order.client
        if order.payments.filter(status__in=["initiated", "pending_approval"]).exists():
            _close_stale_attempts(order.payments.filter(status="initiated"))
            if order.payments.filter(status="pending_approval").exists():
                raise StateConflict("An offline payment for this order is already waiting for approval.")
    else:
        invoice = Invoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != "issued":
            raise StateConflict("This invoice cannot be paid now.")
        if (amount, currency) != (invoice.amount, invoice.currency):
            raise Invalid("The amount must equal the invoice.", code="amount-mismatch")
        purpose, payer = invoice.purpose, payer or invoice.bill_to_person or actor
    if not (reference or "").strip():
        raise Invalid("Give the bank's transaction reference.", extra={"errors": [
            {"pointer": "/reference", "message": "Required."}]})
    if not (source_account_name or "").strip() or not (source_bank_name or "").strip():
        raise Invalid("Record the bank and account name the money came from; a refund can go only there.",
                      extra={"errors": [{"pointer": "/source_account_name", "message": "Required."}]})
    proof = _proof(actor, country, proof_evidence_id, proof_file)
    threshold = _offline_threshold(country, currency)
    needs_approval = threshold is not None and amount > threshold
    p = FeePayment.objects.create(
        country=country, purpose=purpose, payer=payer, order=order, invoice=invoice, amount=amount,
        status="pending_approval" if needs_approval else "initiated",
        currency=currency, method="bank_transfer_offline", provider="offline", recorded_by=actor,
        proof_evidence=proof, offline_reference=reference.strip(), received_on=received_on,
        source_bank_name=source_bank_name.strip(), source_account_name=source_account_name.strip(),
        source_account_number=(source_account_number or "").strip())
    from evidence.services import link

    link(proof, "fee_payment", p.pk, role="proof_of_payment", by=actor)
    record(actor=actor, action="payment.offline_recorded", entity="fee_payment", entity_id=p.pk,
           data={"amount": amount, "currency": currency, "reference": reference, "proof": proof.pk,
                 "order_id": order.pk if order else None, "invoice_id": invoice.pk if invoice else None},
           country=country)
    if needs_approval:
        req = approvals.request_approval("offline_fee_payment", p.pk, actor, required=2, country=country,
                                         summary=f"Offline payment {currency} {amount} ({reference})")
        p.approval_request = req
        p.save(update_fields=["approval_request"])
        if order is not None:
            orders.note_payment(order.pk, "pending_approval", "Your bank transfer is being checked.")
        return p
    return confirm_payment(p, actor=actor)


def decide_offline(actor, payment: FeePayment, *, decision, mfa_at, note=""):
    if payment.status != "pending_approval" or payment.approval_request_id is None:
        raise StateConflict("This payment is not waiting for approval.")
    _staff(actor, payment.country, STAFF)
    approvals.decide(payment.approval_request, actor, decision=decision, mfa_at=mfa_at, note=note,
                     allowed=lambda person: has_role(person, *STAFF))
    payment.refresh_from_db()
    return payment


# ---------------------------------------------------------------- refunds (FR-PAY-004, FR-PAY-008, RUL-29)


def refundable_amount(payment: FeePayment) -> Decimal:
    used = payment.refunds.filter(status__in=LIVE_REFUND).aggregate(s=Sum("amount"))["s"] or Decimal("0")
    return payment.amount - used


@transaction.atomic
def request_refund(actor, payment: FeePayment, *, amount=None, reason: str):
    """A refund has a reason and two approvers who did not prepare it. It takes no destination: the money
    goes back through the provider to the original card or wallet, or to the account an offline payment came from."""
    flags.read_only_guard()
    _staff(actor, payment.country, STAFF, "Only Tenmina staff can prepare a refund.")
    if not (reason or "").strip():
        raise Invalid("Give the reason for the refund.", extra={"errors": [{"pointer": "/reason",
                                                                             "message": "Required."}]})
    p = FeePayment.objects.select_for_update().get(pk=payment.pk)
    if p.status not in ("confirmed", "partially_refunded"):
        raise StateConflict("Only a confirmed payment can be refunded.", extra={"payment_status": p.status})
    amount = p.amount if amount in (None, "") else Decimal(str(amount)).quantize(Decimal("0.01"))
    left = refundable_amount(p)
    if amount <= 0 or amount > left:
        raise Invalid(f"The refund can be at most {p.currency} {left:.2f}.", code="refund-too-large",
                      extra={"refundable": {"amount": f"{left:.2f}", "currency": p.currency}})
    r = Refund.objects.create(country=p.country, payment=p, amount=amount, currency=p.currency,
                              reason=reason.strip(), requested_by=actor)
    req = approvals.request_approval("refund", r.pk, actor, required=2, country=p.country,
                                     summary=f"Refund {p.currency} {amount} of {_describe(p)[0]}")
    r.approval_request = req
    r.save(update_fields=["approval_request"])
    record(actor=actor, action="refund.requested", entity="fee_refund", entity_id=r.pk,
           data={"payment_id": p.pk, "amount": amount, "currency": p.currency, "reason": reason}, country=p.country)
    publish("refund.requested", r.pk, {"refund_id": r.pk, "payment_id": p.pk, "order_id": p.order_id,
                                       "amount": amount, "currency": p.currency})
    return r


def request_refund_for_order(actor, order_id, *, amount=None, reason):
    """For CASE (FR-CASE-012): refund the confirmed payment of an order."""
    p = FeePayment.objects.filter(order_id=order_id, status__in=["confirmed", "partially_refunded"]).first()
    if p is None:
        raise NotFound("This order has no confirmed payment to refund.")
    return request_refund(actor, p, amount=amount, reason=reason)


def refused_destination(actor, payment_or_none, fields, country=None):
    """TC-PAY-008-02, TC-RUL-29-04: a refund request that names a card, wallet or account is refused and audited."""
    record(actor=actor, action="refund.destination_refused", entity="fee_payment",
           entity_id=getattr(payment_or_none, "pk", "unknown"), data={"fields": sorted(fields)},
           country=country or getattr(payment_or_none, "country", None))


def decide_refund(actor, refund: Refund, *, decision, mfa_at, note=""):
    if refund.status != "requested" or refund.approval_request_id is None:
        raise StateConflict("This refund is not waiting for approval.")
    _staff(actor, refund.country, STAFF)
    approvals.decide(refund.approval_request, actor, decision=decision, mfa_at=mfa_at, note=note,
                     allowed=lambda person: has_role(person, *STAFF))
    refund.refresh_from_db()
    return refund


@transaction.atomic
def on_refund_approved(refund_id):
    r = Refund.objects.select_for_update().filter(pk=refund_id).first()
    if r is None or r.status != "requested":
        return r
    r.approved_at = timezone.now()
    state.transition(r, "pay_refund", "approved", event="refund.approved",
                     payload={"refund_id": r.pk, "payment_id": r.payment_id, "order_id": r.payment.order_id,
                              "amount": r.amount, "currency": r.currency}, extra_fields=["approved_at"])
    return execute_refund(r)


@transaction.atomic
def on_refund_rejected(refund_id):
    r = Refund.objects.select_for_update().filter(pk=refund_id).first()
    if r is not None and r.status == "requested":
        state.transition(r, "pay_refund", "rejected", event="refund.rejected", payload={"refund_id": r.pk})
    return r


def execute_refund(r: Refund):
    """Send the refund the only way it can go (FR-PAY-008)."""
    p = r.payment
    r.attempts += 1
    r.save(update_fields=["attempts"])
    if p.method == "bank_transfer_offline":
        if r.status != "processing":
            state.transition(r, "pay_refund", "processing", event="refund.processing",
                             payload={"refund_id": r.pk, "manual": True})
        _notify_staff(p.country, "offline_refund_due", "Pay back an offline fee payment",
                      f"Pay {r.currency} {r.amount:.2f} back to {p.source_account_name} at {p.source_bank_name}"
                      f"{' ending ' + p.source_account_number[-4:] if p.source_account_number else ''}, the account "
                      f"it came from, then record the bank's reference and proof.", obj=r)
        return r
    try:
        res = adapters.provider().refund(provider_ref=p.provider_ref, amount=r.amount, currency=r.currency,
                                         idempotency_key=str(r.pk))
    except Exception as exc:  # noqa: BLE001  the provider is down: keep the refund open
        log.warning("refund %s failed at provider: %s", r.pk, exc)
        res = adapters.RefundResult(ok=False, failure="The payment provider could not be reached.")
    if res.ok:
        return complete_refund(r, res.refund_ref)
    if res.pending:
        if r.status != "processing":
            state.transition(r, "pay_refund", "processing", event="refund.processing", payload={"refund_id": r.pk})
        return r
    r.failure_message = res.failure[:500]
    if r.status != "failed":
        state.transition(r, "pay_refund", "failed", event="refund.failed",
                         payload={"refund_id": r.pk, "payment_id": p.pk, "order_id": p.order_id,
                                  "message": r.failure_message}, extra_fields=["failure_message"])
    else:
        r.save(update_fields=["failure_message"])
    if not ReconIssue.objects.filter(refund=r, kind="refund_failed", status="open").exists():
        _issue("refund_failed", p.country, payment=p, refund=r, provider_ref=p.provider_ref or "",
               detail=f"The provider could not refund {r.currency} {r.amount:.2f} to the original payment method: "
                      f"{r.failure_message} The refund stays open. It can go only to the original method, or "
                      f"through the RUL-29 exception path.")
    return r


@transaction.atomic
def retry_refund(actor, refund: Refund):
    _staff(actor, refund.country, STAFF)
    r = Refund.objects.select_for_update().get(pk=refund.pk)
    if r.status != "failed":
        raise StateConflict("Only a failed refund can be tried again.")
    if r.payment.method == "bank_transfer_offline":
        raise StateConflict("An offline refund is completed by recording the bank's proof.")
    record(actor=actor, action="refund.retried", entity="fee_refund", entity_id=r.pk, data={}, country=r.country)
    return execute_refund(r)


@transaction.atomic
def complete_refund(r: Refund, refund_ref: str, *, actor=None, proof=None):
    r = Refund.objects.select_for_update().get(pk=r.pk)
    if r.status == "completed":
        return r
    p = FeePayment.objects.select_for_update().get(pk=r.payment_id)
    p.refunded_amount = p.refunded_amount + r.amount
    full = p.refunded_amount >= p.amount
    state.transition(p, "pay_payment", "refunded" if full else "partially_refunded", actor=actor,
                     event="payment.refunded", payload=_payload(p, refunded=p.refunded_amount),
                     extra_fields=["refunded_amount"])
    r.provider_refund_ref, r.completed_at, r.completed_by, r.proof_evidence = refund_ref, timezone.now(), actor, proof
    state.transition(r, "pay_refund", "completed", actor=actor, event="refund.completed",
                     payload={"refund_id": r.pk, "payment_id": p.pk, "order_id": p.order_id,
                              "invoice_id": p.invoice_id, "amount": r.amount, "currency": r.currency,
                              "provider_refund_ref": refund_ref, "payment_fully_refunded": full},
                     extra_fields=["provider_refund_ref", "completed_at", "completed_by", "proof_evidence"])
    ReconIssue.objects.filter(refund=r, status="open").update(status="resolved", resolved_at=timezone.now(),
                                                               resolution="Refund completed.")
    _credit_note(r)
    return r


@transaction.atomic
def record_offline_refund(actor, refund: Refund, *, bank_reference, proof_evidence_id=None, proof_file=None):
    """The bank paid an offline fee back to the account it came from. Proof is required."""
    _staff(actor, refund.country, ("CM", "AD"))
    r = Refund.objects.select_for_update().get(pk=refund.pk)
    if r.payment.method != "bank_transfer_offline":
        raise StateConflict("Card and mobile money refunds go through the payment provider only.")
    if r.status != "processing":
        raise StateConflict("This refund is not waiting to be paid back.")
    if not (bank_reference or "").strip():
        raise Invalid("Give the bank's reference for the refund.")
    proof = _proof(actor, r.country, proof_evidence_id, proof_file)
    from evidence.services import link

    link(proof, "fee_refund", r.pk, role="refund_proof", by=actor)
    return complete_refund(r, bank_reference.strip(), actor=actor, proof=proof)


def withdraw_refund(actor, refund: Refund):
    if actor != refund.requested_by and not has_role(actor, "AD"):
        raise Forbidden()
    if refund.status != "requested":
        raise StateConflict("Only a refund still waiting for approval can be withdrawn.")
    with transaction.atomic():
        if refund.approval_request_id:
            approvals.withdraw(refund.approval_request, actor)
        state.transition(refund, "pay_refund", "withdrawn", actor=actor)
    return refund


# ---------------------------------------------------------------- seller invoices (FR-PAY-007)


def _org_ids(user):
    from orders.access import organisation_ids

    return organisation_ids(user)


def may_see_invoice(user, invoice: Invoice) -> bool:
    if has_role(user, *STAFF) and is_staff_for(user, invoice.country):
        return True
    return user == invoice.bill_to_person or invoice.organisation_id in _org_ids(user)


@transaction.atomic
def create_invoice(*, organisation, kind, country=None, amount=None, currency=None, description="", order=None,
                   subject_type="", subject_id=None, bill_to_person=None, actor=None, issue=True):
    from orders.pricing import invoice_price

    country = country or organisation.country
    purpose = {"checked_plot_fee": "report_fee", "listing_fee": "listing_fee", "success_fee": "success_fee",
               "api_fee": "api_fee"}.get(kind, "report_fee")
    if amount is None:
        if order is not None:
            amount, currency = order.price_amount, order.price_currency
        else:
            money, _ = invoice_price(country, kind.replace("checked_plot_fee", "listing_verification"))
            amount, currency = money.amount, money.currency
    if order is not None:
        existing = Invoice.objects.filter(order=order).exclude(status="void").first()
        if existing:
            return existing
    if subject_id is not None:
        existing = Invoice.objects.filter(kind=kind, subject_type=subject_type, subject_id=subject_id).exclude(
            status="void").first()
        if existing:
            return existing
    inv = Invoice.objects.create(
        country=country, number=next_number("INV", country), kind=kind, purpose=purpose, organisation=organisation,
        bill_to_person=bill_to_person, order=order, subject_type=subject_type, subject_id=subject_id,
        description=description or kind.replace("_", " ").capitalize(), amount=amount, currency=currency,
        created_by=actor)
    record(actor=actor, action="seller_invoice.created", entity="seller_invoice", entity_id=inv.pk,
           data={"number": inv.number, "kind": kind, "amount": amount, "currency": currency}, country=country)
    if issue:
        issue_invoice(inv, actor=actor)
    return inv


@transaction.atomic
def issue_invoice(inv: Invoice, actor=None):
    inv.issued_at = timezone.now()
    inv.due_on = (inv.issued_at + timedelta(days=int(_cfg(inv.country, "invoice_due_days", 14)))).date()
    state.transition(inv, "pay_invoice", "issued", actor=actor, event="seller_invoice.issued",
                     payload={"invoice_id": inv.pk, "number": inv.number, "organisation_id": inv.organisation_id,
                              "order_id": inv.order_id, "amount": inv.amount, "currency": inv.currency},
                     extra_fields=["issued_at", "due_on"])
    _notify(inv.bill_to_person, "seller_invoice_issued", f"Invoice {inv.number}",
            f"Tenmina invoice {inv.number} for {inv.currency} {inv.amount:.2f}: {inv.description}. "
            f"Due {inv.due_on:%d %B %Y}.", obj=inv, needs_action=True, link=f"/seller-invoices/{inv.pk}")
    return inv


def void_invoice(actor, inv: Invoice, reason: str):
    _staff(actor, inv.country, ("CM", "AD"))
    if not (reason or "").strip():
        raise Invalid("Give a reason.")
    if inv.payments.filter(status__in=["initiated", "pending_approval"]).exists():
        raise StateConflict("A payment of this invoice is in progress.")
    inv.void_reason = reason.strip()
    return state.transition(inv, "pay_invoice", "void", actor=actor, reason=reason, extra_fields=["void_reason"])


def invoice_for_order(order_id):
    from orders.models import Order

    order = Order.objects.filter(pk=order_id).first()
    if order is None or order.bill_to != "organisation" or order.organisation_id is None:
        return None
    return create_invoice(organisation=order.organisation, kind="checked_plot_fee", country=order.country,
                          order=order, bill_to_person=order.placed_by,
                          description=f"Check of plot {order.plot_number or ''} at {order.locality} "
                                      f"({order.reference}). Same fee whatever the verdict.".replace("  ", " "))


def invoice_for_listing(payload: dict, kind: str):
    """listing.submitted (listing fee) and listing.sold (success fee, only if Q-31 allows it)."""
    from accounts.models import Organisation, Person

    org = Organisation.objects.filter(pk=payload.get("organisation_id")).first()
    listing_id = payload.get("listing_id") or payload.get("id")
    if org is None or not listing_id:
        log.warning("%s without organisation_id or listing_id: %s", kind, payload)
        return None
    if kind == "success_fee" and not _cfg(org.country, "success_fees", False):
        record(action="seller_invoice.success_fee_not_charged", entity="listing", entity_id=listing_id,
               data={"reason": "Q-31: success fees are off"}, country=org.country)
        return None
    person = Person.objects.filter(pk=payload.get("submitted_by") or payload.get("seller_person_id")).first()
    label = "Listing fee" if kind == "listing_fee" else "Success fee (flat, disclosed to buyers)"
    return create_invoice(organisation=org, kind=kind, subject_type="listing", subject_id=listing_id,
                          bill_to_person=person, description=f"{label} for listing {payload.get('reference', '')}".strip())


# ---------------------------------------------------------------- reconciliation (FR-PAY-006)


def _issue(kind, country, *, payment=None, refund=None, line=None, run=None, provider_ref="", detail=""):
    if kind in ("unlinked_payment", "missing_settlement", "duplicate_payment", "payment_on_closed_order",
                "amount_mismatch") and ReconIssue.objects.filter(
            kind=kind, status="open", payment=payment, provider_ref=provider_ref, line=line).exists():
        return None
    i = ReconIssue.objects.create(country=country, kind=kind, payment=payment, refund=refund, line=line, run=run,
                                  provider_ref=provider_ref, detail=detail)
    record(action=f"recon_issue.{kind}", entity="recon_issue", entity_id=i.pk, data={"detail": detail},
           country=country)
    publish("payment.recon_issue", i.pk, {"issue_id": i.pk, "kind": kind, "payment_id": getattr(payment, "pk", None)})
    if kind in ("unlinked_payment", "refund_failed", "duplicate_payment", "payment_on_closed_order"):
        _notify_staff(country, f"pay_{kind}", "A fee payment needs a look", detail, obj=i)
    return i


def parse_settlement_file(data: bytes) -> list[adapters.SettlementItem]:
    """JSON (a list, or {"lines": [...]}) or CSV with provider_ref, amount, currency[, fee, settled_at]."""
    if not data or not data.strip():
        raise Invalid("The settlement file is empty.", code="settlement-file-invalid")
    text = data.decode("utf-8-sig", errors="strict") if isinstance(data, bytes) else data
    try:
        if text.lstrip()[:1] in "[{":
            rows = json.loads(text)
            rows = rows.get("lines", []) if isinstance(rows, dict) else rows
        else:
            rows = list(csv.DictReader(io.StringIO(text)))
        out = []
        for row in rows:
            ref = str(row["provider_ref"]).strip()
            if not ref:
                raise ValueError("empty reference")
            settled = row.get("settled_at") or None
            out.append(adapters.SettlementItem(
                provider_ref=ref, amount=Decimal(str(row["amount"])).quantize(Decimal("0.01")),
                currency=str(row["currency"]).strip().upper(), fee=Decimal(str(row.get("fee") or "0")),
                settled_at=datetime.fromisoformat(settled) if isinstance(settled, str) else settled))
        return out
    except (ValueError, KeyError, TypeError, InvalidOperation, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise Invalid(f"The settlement file could not be read: {exc}.", code="settlement-file-invalid") from exc


@transaction.atomic
def import_settlement(actor, *, country: Country, settlement_date: date, items=None, file_bytes: bytes = None,
                      provider_name=None):
    """Match each settlement line to a payment and list every mismatch for a case manager."""
    provider_name = provider_name or adapters.provider().name
    try:
        if file_bytes is not None:
            items = parse_settlement_file(file_bytes)
            digest = hashlib.sha256(file_bytes).hexdigest()
            source = "upload"
        else:
            items = items if items is not None else adapters.provider().settlement(settlement_date)
            digest = _content_hash({"date": settlement_date, "lines": [
                {"ref": i.provider_ref, "amount": i.amount, "currency": i.currency} for i in items]})
            source = "provider"
    except Invalid:
        _notify_staff(country, "pay_settlement_rejected", "A settlement file was rejected",
                      f"The {provider_name} settlement file for {settlement_date} could not be read.")
        record(actor=actor, action="settlement.rejected", entity="settlement", entity_id=str(settlement_date),
               data={"provider": provider_name}, country=country)
        raise
    existing = SettlementRun.objects.filter(provider=provider_name, file_sha256=digest).first()
    if existing:
        existing.duplicate = True
        return existing
    run = SettlementRun.objects.create(country=country, provider=provider_name, settlement_date=settlement_date,
                                       source=source, file_sha256=digest, line_count=len(items), run_by=actor)
    matched = issues = 0
    for it in items:
        p = FeePayment.objects.filter(provider_ref=it.provider_ref).first()
        status = "matched"
        if p is None:
            status = "unmatched"
        elif SettlementLine.objects.filter(payment=p, match_status="matched").exists():
            status = "duplicate"
        elif it.amount != p.amount or it.currency != p.currency:
            status = "amount_mismatch"
        line = SettlementLine.objects.create(
            country=country, run=run, provider_ref=it.provider_ref, amount=it.amount, currency=it.currency,
            fee_amount=it.fee, net_amount=it.amount - it.fee, settled_at=it.settled_at,
            payment=p if status != "unmatched" else None, match_status=status)
        if status == "matched":
            matched += 1
            continue
        issues += 1
        detail = {
            "unmatched": f"Settlement line {it.provider_ref} for {it.currency} {it.amount} matches no Tenmina payment.",
            "duplicate": f"Payment {it.provider_ref} was settled twice.",
            "amount_mismatch": f"Settlement of {it.currency} {it.amount} for {it.provider_ref} differs from the "
                               f"payment of {p.currency} {p.amount}." if p else "",
        }[status]
        _issue({"unmatched": "unmatched_line", "duplicate": "duplicate_line",
                "amount_mismatch": "amount_mismatch"}[status], country, payment=p, line=line, run=run,
               provider_ref=it.provider_ref, detail=detail)
    window = int(_cfg(country, "settlement_window_days", 7))
    unsettled = (FeePayment.objects.filter(country=country, provider=provider_name, status__in=[
        "confirmed", "partially_refunded", "refunded"], confirmed_at__date__lte=settlement_date,
        confirmed_at__date__gte=settlement_date - timedelta(days=window))
        .exclude(settlement_lines__match_status__in=["matched", "amount_mismatch"]))
    for p in unsettled:
        if _issue("missing_settlement", country, payment=p, run=run, provider_ref=p.provider_ref or "",
                  detail=f"Payment {p.provider_ref} of {p.currency} {p.amount} confirmed on "
                         f"{p.confirmed_at:%d %B %Y} has no settlement line yet."):
            issues += 1
    run.matched, run.issues = matched, issues
    run.save(update_fields=["matched", "issues"])
    record(actor=actor, action="settlement.imported", entity="settlement_run", entity_id=run.pk,
           data={"lines": len(items), "matched": matched, "issues": issues, "date": settlement_date}, country=country)
    if issues:
        _notify_staff(country, "pay_reconciliation_issues", "Settlement mismatches to check",
                      f"{issues} mismatch(es) in the {provider_name} settlement for {settlement_date:%d %B %Y}.",
                      obj=run)
    run.duplicate = False
    return run


def daily_reconcile(settlement_date=None):
    """The daily job: yesterday's settlement for every active country."""
    d = settlement_date or (timezone.now() - timedelta(days=1)).date()
    return [import_settlement(None, country=c, settlement_date=d)
            for c in Country.objects.filter(status__in=["active", "manual_phase"])]


def resolve_issue(actor, issue: ReconIssue, resolution: str):
    _staff(actor, issue.country, STAFF)
    if not (resolution or "").strip():
        raise Invalid("Say how the mismatch was resolved.")
    issue.resolution, issue.resolved_by, issue.resolved_at = resolution.strip(), actor, timezone.now()
    return state.transition(issue, "pay_recon_issue", "resolved", actor=actor, reason=resolution,
                            event="payment.recon_issue_resolved",
                            extra_fields=["resolution", "resolved_by", "resolved_at"])
