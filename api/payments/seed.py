"""PAY demo data over ORD's seeded orders: a card payment, a failed mobile money attempt, offline payments
(one confirmed, one waiting for approval), a completed refund, a refund waiting for approval, a seller invoice
paid and one open, and a settlement run with a mismatch. Idempotent."""
from decimal import Decimal

from django.utils import timezone

from . import adapters, services
from .models import FeePayment, Invoice, ReconIssue, Refund, SettlementRun


def _card(order, person, outcome="success"):
    p = services.start_order_payment(order, person, method="card", return_url="/orders")
    hook = adapters.provider().complete(p.provider_ref, outcome)
    if hook:
        services.handle_webhook(*hook)
    p.refresh_from_db()
    return p


def _momo(order, person, outcome):
    p = services.start_order_payment(order, person, method="mobile_money", wallet_phone="+233241234567")
    hook = adapters.provider().complete(p.provider_ref, outcome)
    if hook:
        services.handle_webhook(*hook)
    p.refresh_from_db()
    return p


def _proof(person, gh, label):
    from evidence.services import store

    return store(data=f"%PDF-1.4 demo bank advice {label}".encode(), country=gh, uploaded_by=person,
                 content_type="application/pdf", original_name=f"{label}.pdf")


def run(ctx):
    if not isinstance(adapters.provider(), adapters.FakePaymentProvider):
        return  # demo payments need the fake provider
    gh, people, orders = ctx["gh"], ctx["people"], ctx.get("orders", {})
    if not orders:
        return
    now = timezone.now()

    def fresh(key):
        o = orders.get(key)
        if o is not None:
            o.refresh_from_db()
        return o

    o = fresh("ama_land_card")
    if o and o.status == "awaiting_payment":
        _card(o, people["client"])

    o = fresh("kofi_land_momo_failed")
    if o and o.status == "awaiting_payment" and not o.payments.exists():
        _momo(o, people["client2"], "reject_prompt")

    o = fresh("kofi_land_offline_paid")
    if o and o.status == "awaiting_payment":
        services.record_offline_payment(
            people["cm"], order=o, amount=o.price_amount, currency=o.price_currency, reference="GCB-TRF-889201",
            received_on=now.date(), source_bank_name="GCB Bank", source_account_name="Kofi Boateng",
            source_account_number="1021130045671", proof_evidence_id=_proof(people["cm"], gh, "gcb-advice").pk)

    o = fresh("kofi_house_offline_pending")
    if o and o.status == "awaiting_payment" and not o.payments.exists():
        services.record_offline_payment(
            people["cm"], order=o, amount=o.price_amount, currency=o.price_currency, reference="ECO-TRF-55120",
            received_on=now.date(), source_bank_name="Ecobank Ghana", source_account_name="Kofi Boateng",
            source_account_number="0441009912001", proof_evidence_id=_proof(people["cm"], gh, "eco-advice").pk)

    o = fresh("kofi_fresh_search_referred")
    if o and o.status == "awaiting_payment":
        _momo(o, people["client2"], "approve_prompt")

    o = fresh("ama_land_refunded")
    if o and o.status == "awaiting_payment":
        p = _card(o, people["client"])
        r = services.request_refund(people["cm"], p, reason="The seller withdrew the plot before searches began.")
        services.decide_refund(people["reviewer"], r, decision="approve", mfa_at=timezone.now())
        services.decide_refund(people["reviewer2"], r, decision="approve", mfa_at=timezone.now())

    # A refund waiting for its approvals: part of the card payment on Ama's land check.
    paid = FeePayment.objects.filter(order=fresh("ama_land_card"), status="confirmed").first()
    if paid and not Refund.objects.filter(payment=paid).exists():
        services.request_refund(people["cm"], paid, amount=Decimal("50.00"),
                                reason="Rush turnaround promised but the registry search took the standard time.")

    # Seller invoices: the first checked plot paid by card, the second left open.
    for key, pay_it in (("ato_checked_plot_1", True), ("ato_checked_plot_2", False)):
        inv = Invoice.objects.filter(order=fresh(key)).exclude(status="void").first() if fresh(key) else None
        if inv and pay_it and inv.status == "issued":
            p = services._start(payer=people["seller"], country=inv.country, purpose=inv.purpose, amount=inv.amount,
                                currency=inv.currency, method="card", invoice=inv)
            services.handle_webhook(*adapters.provider().complete(p.provider_ref, "success"))

    # Today's settlement, plus one line from the provider that matches nothing.
    if not SettlementRun.objects.filter(country=gh).exists():
        services.import_settlement(people["cm"], country=gh, settlement_date=now.date())
    if not ReconIssue.objects.filter(kind="unmatched_line").exists():
        services.import_settlement(people["cm"], country=gh, settlement_date=now.date(), items=[
            adapters.SettlementItem(provider_ref="psk_demo_unknown_0042", amount=Decimal("35.00"), currency="USD",
                                    fee=Decimal("0.68"), settled_at=now)])
