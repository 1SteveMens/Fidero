from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from accounts.models import Organisation, RoleGrant
from administration.models import FeatureFlag
from audit.models import AuditEvent
from core.events import publish
from core.ids import uuid7
from core.models import OutboxEvent
from notifications.models import Message
from orders.models import Order
from orders.tests.helpers import checkout, pay, place_order, site_plan, start_payment, terms
from payments import adapters, services
from payments.models import FakeProviderTransaction, FeePayment, Invoice, Receipt, ReconIssue, Refund


def _approve(api, mfa, person, url, decision="approve"):
    c = api(person)
    mfa(c, person)
    return c.post(url, {"decision": decision}, format="json")


def _order(api, people, gh, who="client", **over):
    return place_order(api(people[who]), people[who], gh, **over)


# ---------------------------------------------------------------- card and mobile money (US-PAY-001a/b, 003)


def test_card_payment_journey_marks_order_paid_and_issues_receipt(seeded, api, people, gh):
    """US-PAY-001a, US-PAY-003, US-ORD-004: provider confirms, order paid, numbered receipt by email and portal."""
    c = api(people["client"])
    o = _order(api, people, gh)
    started = c.post(f"/v1/orders/{o['id']}/payments", {"method": "card"}, format="json")
    assert started.status_code == 201
    p = started.json()["payment"]
    assert started.json()["checkout_url"] == f"/v1/payments/{p['id']}/fake-checkout"
    assert p["amount"] == {"amount": "350.00", "currency": "USD"} and p["purpose"] == "report_fee"
    assert c.get(f"/v1/orders/{o['id']}").json()["last_payment_status"] == "initiated"
    assert c.get(f"/v1/payments/{p['id']}/fake-checkout").json()["merchant"] == "Tenmina fees only"
    done = checkout(c, p["id"])
    assert done["status"] == "confirmed" and done["card_last4"] == "4242"
    order = c.get(f"/v1/orders/{o['id']}").json()
    assert order["status"] == "paid" and order["paid_method"] == "card"
    assert OutboxEvent.objects.filter(topic="order.paid", aggregate_id=o["id"]).count() == 1
    assert OutboxEvent.objects.filter(topic="payment.confirmed", aggregate_id=p["id"]).count() == 1
    rec = c.get(f"/v1/payments/{p['id']}/receipt").json()["receipt"]
    assert rec["number"].startswith("RCT-GH-") and rec["amount"] == {"amount": "350.00", "currency": "USD"}
    assert rec["method_detail"] == "Visa ending 4242" and o["reference"] in rec["description"]
    assert Message.objects.filter(person=people["client"], template="fee_receipt", channel="email").exists()
    assert c.get("/v1/receipts").json()["items"][0]["number"] == rec["number"]


def test_same_webhook_twice_records_one_payment(seeded, api, people, gh):
    """US-PAY-001a AC2, TC-ORD-004-02: duplicate callbacks record one payment and one receipt."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = start_payment(c, o["id"])
    provider = adapters.provider()
    body, headers = provider.complete(p["provider_ref"], "success")
    hook = api()
    h = {"HTTP_X_FAKE_SIGNATURE": headers["X-Fake-Signature"]}
    r1 = hook.post("/v1/hooks/payments", body, content_type="application/json", **h)
    r2 = hook.post("/v1/hooks/payments", body, content_type="application/json", **h)
    assert r1.json()["status"] == "processed" and r2.json()["status"] == "duplicate"
    body2, headers2 = provider.signed_event("charge.success", p["provider_ref"])
    hook.post("/v1/hooks/payments", body2, content_type="application/json",
              HTTP_X_FAKE_SIGNATURE=headers2["X-Fake-Signature"])
    assert FeePayment.objects.filter(order_id=o["id"], status="confirmed").count() == 1
    assert Receipt.objects.filter(payment_id=p["id"]).count() == 1
    assert OutboxEvent.objects.filter(topic="order.paid", aggregate_id=o["id"]).count() == 1


def test_pending_webhook_creates_nothing(seeded, api, people, gh):
    """TC-ORD-004-02: a webhook for a payment the provider still has pending changes nothing."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = start_payment(c, o["id"], "mobile_money")
    body, headers = adapters.provider().signed_event("charge.pending", p["provider_ref"])
    api().post("/v1/hooks/payments", body, content_type="application/json",
               HTTP_X_FAKE_SIGNATURE=headers["X-Fake-Signature"])
    assert Order.objects.get(pk=o["id"]).status == "awaiting_payment"
    assert not OutboxEvent.objects.filter(topic="order.paid", aggregate_id=o["id"]).exists()


def test_declined_card_shows_a_plain_reason_and_can_retry(seeded, api, people, gh):
    """US-PAY-001a AC3, TC-PAY-001-02, TC-PAY-003-02: plain reason, retry allowed, no receipt."""
    c = api(people["client"])
    o = _order(api, people, gh)
    failed = pay(c, o["id"], outcome="decline")
    assert failed["status"] == "failed" and "declined" in failed["failure_message"]
    assert failed["can_retry"] is True
    assert not Receipt.objects.filter(payment_id=failed["id"]).exists()
    order = c.get(f"/v1/orders/{o['id']}").json()
    assert order["status"] == "awaiting_payment" and order["can_pay"] is True
    assert "declined" in order["last_payment_message"]
    assert Message.objects.filter(person=people["client"], template="payment_failed", needs_action=True).exists()
    ok = pay(c, o["id"])
    assert ok["status"] == "confirmed"
    assert c.get(f"/v1/orders/{o['id']}").json()["status"] == "paid"


def test_mobile_money_is_charged_in_cedis(seeded, api, people, gh):
    """US-PAY-001b, FR-ORD-002: mobile money charged in GHS at the price shown."""
    c = api(people["client2"])
    o = _order(api, people, gh, who="client2")
    p = start_payment(c, o["id"], "mobile_money", wallet_phone="+233241234567")
    assert p["amount"] == {"amount": "5425.00", "currency": "GHS"} and p["wallet_last4"] == "4567"
    done = checkout(c, p["id"], "approve_prompt")
    assert done["status"] == "confirmed"
    assert Order.objects.get(pk=o["id"]).status == "paid"


def test_mobile_money_behind_its_flag(seeded, api, people, gh):
    FeatureFlag.objects.filter(name="payments.mobile_money", country__isnull=True).update(enabled=False)
    o = _order(api, people, gh)
    r = api(people["client"]).post(f"/v1/orders/{o['id']}/payments", {"method": "mobile_money"}, format="json")
    assert r.status_code == 404 and r.json()["code"] == "feature-off"


def test_mobile_money_timeout_and_abandoned_card(seeded, api, people, gh):
    """US-PAY-001b AC2: no confirmation in time leaves the order unpaid with a retry option."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = start_payment(c, o["id"], "mobile_money")
    checkout(c, p["id"], "timeout")
    assert FeePayment.objects.get(pk=p["id"]).status == "initiated"
    later = timezone.now() + timedelta(minutes=11)
    result = services.reconcile_pending(now=later)
    assert result["failed"] == 1
    pay_row = FeePayment.objects.get(pk=p["id"])
    assert pay_row.status == "failed" and pay_row.failure_code == "timeout"
    order = c.get(f"/v1/orders/{o['id']}").json()
    assert order["status"] == "awaiting_payment" and order["can_pay"] is True
    card = start_payment(c, o["id"], "card")
    services.reconcile_pending(now=timezone.now() + timedelta(minutes=30))
    assert FeePayment.objects.get(pk=card["id"]).status == "initiated"
    services.reconcile_pending(now=timezone.now() + timedelta(minutes=61))
    assert FeePayment.objects.get(pk=card["id"]).failure_code == "abandoned"


def test_reconcile_job_confirms_a_missed_webhook(seeded, api, people, gh):
    """IF-02 fallback: a missed webhook is caught by verifying open attempts with the provider."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = start_payment(c, o["id"])
    adapters.provider().complete(p["provider_ref"], "success")  # webhook never delivered
    assert services.reconcile_pending()["confirmed"] == 1
    assert Order.objects.get(pk=o["id"]).status == "paid"


def test_forged_webhook_is_rejected_and_audited(seeded, api, people, gh):
    """TC-SEC-20: an unsigned or wrongly signed webhook is rejected; no case, no change."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = start_payment(c, o["id"])
    FakeProviderTransaction.objects.filter(reference=p["provider_ref"]).update(status="success")
    body, _ = adapters.provider().signed_event("charge.success", p["provider_ref"])
    r = api().post("/v1/hooks/payments", body, content_type="application/json", HTTP_X_FAKE_SIGNATURE="bad")
    assert r.status_code == 401
    r = api().post("/v1/hooks/payments", body, content_type="application/json")
    assert r.status_code == 401
    assert Order.objects.get(pk=o["id"]).status == "awaiting_payment"
    assert AuditEvent.objects.filter(action="payment.webhook_rejected").count() == 2


def test_webhook_for_money_not_linked_to_a_fee_order(seeded, api, people, gh):
    """TC-RUL-01-04: flagged for refund review; nothing else changes."""
    FakeProviderTransaction.objects.create(reference="fake_stray", amount=Decimal("5000.00"), currency="USD",
                                           method="card", status="success", session_token="x")
    body, headers = adapters.provider().signed_event("charge.success", "fake_stray")
    r = api().post("/v1/hooks/payments", body, content_type="application/json",
                   HTTP_X_FAKE_SIGNATURE=headers["X-Fake-Signature"])
    assert r.json()["outcome"] == "unlinked"
    issue = ReconIssue.objects.get(kind="unlinked_payment")
    assert issue.provider_ref == "fake_stray" and issue.status == "open"
    assert not FeePayment.objects.filter(provider_ref="fake_stray").exists()
    assert Message.objects.filter(person=people["cm"], template="pay_unlinked_payment").exists()


# ---------------------------------------------------------------- fees only (US-PAY-005, RUL-01, US-PAY-002)


def test_tampered_payment_request_is_refused_and_audited(seeded, api, people, gh):
    """TC-RUL-01-03: changing the amount or purpose is rejected with a validation error and audited."""
    o = _order(api, people, gh)
    before = FeePayment.objects.count()
    r = api(people["client"]).post(f"/v1/orders/{o['id']}/payments",
                                   {"method": "card", "amount": "250000.00", "purpose": "escrow_deposit"},
                                   format="json")
    assert r.status_code == 400 and r.json()["code"] == "validation-error"
    assert {e["pointer"] for e in r.json()["errors"]} == {"/amount", "/purpose"}
    assert FeePayment.objects.count() == before
    assert AuditEvent.objects.filter(action="payment.tampered_request_refused").exists()


def test_payment_needs_current_terms_and_an_open_order(seeded, api, people, gh):
    """TC-ORD-003-02: payment cannot start without acceptance of the terms in force."""
    c = api(people["client"])
    draft = c.post("/v1/orders", {"country": "GH", "kind": "verification", "draft": True}, format="json").json()
    assert c.post(f"/v1/orders/{draft['id']}/payments", {"method": "card"}, format="json").status_code == 409
    o = _order(api, people, gh)
    cfg = gh.configs.get(status="published")
    cfg.data = {**cfg.data, "legal_texts": {"client_terms": {"version": "client-terms-2027-01-v2", "text": "New"}}}
    cfg.save(update_fields=["data"])
    r = c.post(f"/v1/orders/{o['id']}/payments", {"method": "card"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "terms-not-accepted"
    r = c.post(f"/v1/orders/{o['id']}/terms-acceptance",
               {"terms_version": "client-terms-2027-01-v2", "scope_version": terms(gh)["scope_version"]},
               format="json")
    assert r.status_code == 200
    assert c.post(f"/v1/orders/{o['id']}/payments", {"method": "card"}, format="json").status_code == 201


def test_fee_purposes_only_and_every_payment_linked(seeded, people, gh):
    """FR-PAY-005, ADR-03: no purpose for purchase, construction, project or premium money; always linked."""
    from payments.models import PURPOSES

    for word in ("purchase", "escrow_deposit", "construction", "project", "premium", "deposit", "rent"):
        assert word not in PURPOSES
    with pytest.raises(IntegrityError), transaction.atomic():
        FeePayment.objects.create(country=gh, purpose="report_fee", payer=people["client"], amount=Decimal("10"),
                                  currency="USD", method="card", provider="fake")
    o = Order.objects.create(country=gh, reference="TMR-T-1", client=people["client"], placed_by=people["client"],
                             kind="verification")
    with pytest.raises(IntegrityError), transaction.atomic():
        FeePayment.objects.create(country=gh, purpose="escrow_deposit", payer=people["client"], order=o,
                                  amount=Decimal("10"), currency="USD", method="card", provider="fake")


def test_no_balance_or_wallet_columns(seeded):
    """ADR-03: no table in ORD or PAY stores a balance or a wallet."""
    with connection.cursor() as cur:
        cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                        WHERE (table_name LIKE 'pay\\_%' OR table_name LIKE 'ord\\_%')
                          AND (column_name LIKE '%balance%' OR column_name LIKE '%wallet\\_balance%'
                               OR column_name = 'wallet')""")
        assert cur.fetchall() == []


def test_route_inventory_takes_only_fee_money(seeded):
    """TC-RUL-01-02, US-PAY-005 AC3: the only routes that start a payment hang off a fee order or invoice."""
    from django.urls import get_resolver

    def walk(patterns, prefix=""):
        for p in patterns:
            if hasattr(p, "url_patterns"):
                yield from walk(p.url_patterns, prefix + str(p.pattern))
            else:
                yield prefix + str(p.pattern), p

    money_words = ("payment", "pay", "deposit", "checkout", "charge", "refund")
    routes = [r for r, p in walk(get_resolver().url_patterns)
              if getattr(p.callback, "__module__", "").startswith("payments.") and any(w in r for w in money_words)]
    routes = [r.replace("^", "").replace("$", "") for r in routes]
    starting = {r for r in routes if r.endswith("payments")}
    allowed = {"v1/orders/<uuid:order_id>/payments", "v1/hooks/payments", "v1/payments", "v1/offline-payments",
               "v1/seller-invoices/(?P<pk>[0-9a-fA-F-]{36})/payments"}
    assert starting == allowed, starting


def test_card_numbers_are_never_stored(seeded, api, people, gh):
    """FR-PAY-002, TC-PAY-002-01: only brand and last four; the database refuses a card number."""
    c = api(people["client"])
    o = _order(api, people, gh)
    pay(c, o["id"])
    with connection.cursor() as cur:
        cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                        WHERE (table_name LIKE 'pay\\_%' OR table_name LIKE 'ord\\_%' OR table_name = 'aud_event'
                               OR table_name = 'core_outbox_event' OR table_name = 'ntf_message')
                          AND data_type IN ('text', 'character varying', 'jsonb')""")
        cols = cur.fetchall()
        for table, col in cols:
            cur.execute(f'SELECT count(*) FROM {table} WHERE "{col}"::text LIKE %s', ["%4242424242424242%"])
            assert cur.fetchone()[0] == 0, (table, col)
    p = FeePayment.objects.get(order_id=o["id"])
    with pytest.raises(IntegrityError), transaction.atomic():
        FeePayment.objects.filter(pk=p.pk).update(failure_message="card 4111 1111 1111 1111 declined")
    with pytest.raises(IntegrityError), transaction.atomic():
        FeePayment.objects.filter(pk=p.pk).update(card_last4="4x11")


def test_payment_facts_and_receipts_cannot_be_changed(seeded, api, people, gh):
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"])
    with pytest.raises(IntegrityError), transaction.atomic():
        FeePayment.objects.filter(pk=p["id"]).update(amount=Decimal("1.00"))
    with pytest.raises(Exception), transaction.atomic():
        Receipt.objects.filter(payment_id=p["id"]).update(amount=Decimal("1.00"))


def test_clients_see_only_their_own_payments(seeded, api, people, gh):
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"])
    other = api(people["client2"])
    assert other.get(f"/v1/payments/{p['id']}").status_code == 404
    assert other.get(f"/v1/payments/{p['id']}/receipt").status_code == 404
    assert other.post(f"/v1/orders/{o['id']}/payments", {"method": "card"}, format="json").status_code == 404
    assert api(people["cm"]).get(f"/v1/payments/{p['id']}/receipt").status_code == 200


def test_late_confirmation_of_a_replaced_attempt_is_flagged(seeded, api, people, gh):
    """Two confirmed payments for one order: the second is listed for a refund review."""
    c = api(people["client"])
    o = _order(api, people, gh)
    first = start_payment(c, o["id"])
    second = start_payment(c, o["id"])
    assert FeePayment.objects.get(pk=first["id"]).failure_code == "superseded"
    checkout(c, second["id"])
    body, headers = adapters.provider().complete(first["provider_ref"], "success")
    services.handle_webhook(body, headers)
    assert FeePayment.objects.get(pk=first["id"]).status == "confirmed"
    assert ReconIssue.objects.filter(kind="duplicate_payment", payment_id=first["id"]).exists()
    assert Order.objects.get(pk=o["id"]).paid_payment_id == FeePayment.objects.get(pk=second["id"]).pk


# ---------------------------------------------------------------- refunds (US-PAY-004, US-PAY-008)


def test_refund_journey_to_the_original_card(seeded, api, people, gh, mfa):
    """US-PAY-004, US-PAY-008, TC-PAY-008-01: reason, two other approvers, provider refund, credit note."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"])
    r = api(people["cm"]).post("/v1/refunds", {"payment_id": p["id"], "reason": "Seller withdrew before searches"},
                               format="json")
    assert r.status_code == 201, r.content
    refund = r.json()
    assert refund["status"] == "requested" and "Visa ending 4242" in refund["destination"]
    url = f"/v1/refunds/{refund['id']}/approvals"
    assert _approve(api, mfa, people["cm"], url).json()["code"] == "same-approver"
    assert api(people["reviewer"]).post(url, {"decision": "approve"}, format="json").json()["code"] == "mfa-required"
    one = _approve(api, mfa, people["reviewer"], url)
    assert one.json()["status"] == "requested" and one.json()["approval"]["approvals"] == 1
    assert _approve(api, mfa, people["reviewer"], url).json()["code"] == "same-approver"
    done = _approve(api, mfa, people["reviewer2"], url).json()
    assert done["status"] == "completed" and done["provider_refund_ref"].startswith("fake_rf_")
    assert done["credit_note"].startswith("CRN-GH-")
    assert FeePayment.objects.get(pk=p["id"]).status == "refunded"
    assert c.get(f"/v1/orders/{o['id']}").json()["status"] == "refunded"
    assert OutboxEvent.objects.filter(topic="refund.approved", aggregate_id=refund["id"]).exists()
    notes = c.get(f"/v1/payments/{p['id']}/receipt").json()["credit_notes"]
    assert len(notes) == 1 and "against receipt RCT-GH-" in notes[0]["description"]


def test_refund_cannot_name_a_destination(seeded, api, people, gh):
    """TC-PAY-008-02, TC-RUL-29-04: a card, wallet or account in the request is refused and audited."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"])
    for extra in ({"card_token": "tok_123"}, {"wallet_number": "+233240000000"},
                  {"bank_account": "1234567890123", "account_name": "Cousin"}):
        r = api(people["cm"]).post("/v1/refunds", {"payment_id": p["id"], "reason": "x", **extra}, format="json")
        assert r.status_code == 400
    assert not Refund.objects.filter(payment_id=p["id"]).exists()
    assert AuditEvent.objects.filter(action="refund.destination_refused").count() == 3


def test_refund_needs_a_reason_and_staff(seeded, api, people, gh):
    """TC-PAY-004-02: no reason, or an unauthorised role, is rejected."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"])
    r = api(people["cm"]).post("/v1/refunds", {"payment_id": p["id"], "reason": "  "}, format="json")
    assert r.status_code == 422
    assert api(people["runner"]).post("/v1/refunds", {"payment_id": p["id"], "reason": "x"},
                                      format="json").status_code == 403
    assert c.post("/v1/refunds", {"payment_id": p["id"], "reason": "x"}, format="json").status_code == 403


def test_partial_refunds_never_exceed_the_payment(seeded, api, people, gh, mfa):
    """FR-PAY-008: the amount is at most the payment less earlier refunds (service and database)."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"])
    cm = api(people["cm"])
    first = cm.post("/v1/refunds", {"payment_id": p["id"], "amount": "100.00", "reason": "Rush not delivered"},
                    format="json").json()
    for who in ("reviewer", "reviewer2"):
        _approve(api, mfa, people[who], f"/v1/refunds/{first['id']}/approvals")
    assert FeePayment.objects.get(pk=p["id"]).status == "partially_refunded"
    assert Order.objects.get(pk=o["id"]).status == "paid"
    r = cm.post("/v1/refunds", {"payment_id": p["id"], "amount": "300.00", "reason": "more"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "refund-too-large"
    with pytest.raises(IntegrityError), transaction.atomic():
        Refund.objects.create(country=gh, payment_id=p["id"], amount=Decimal("300.00"), currency="USD",
                              reason="direct insert", requested_by=people["cm"])


def test_refund_that_the_provider_cannot_pay_stays_open(seeded, api, people, gh, mfa):
    """TC-PAY-008-03: refund failed, listed for a case manager, no other route offered; retried later."""
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"], refundable=False)
    refund = api(people["cm"]).post("/v1/refunds", {"payment_id": p["id"], "reason": "Duplicate order"},
                                    format="json").json()
    for who in ("reviewer", "reviewer2"):
        out = _approve(api, mfa, people[who], f"/v1/refunds/{refund['id']}/approvals").json()
    assert out["status"] == "failed" and "can no longer receive" in out["failure_message"]
    issues = api(people["cm"]).get("/v1/reconciliation/issues?status=open&kind=refund_failed").json()["items"]
    assert [i["refund"] for i in issues] == [refund["id"]]
    assert api(people["cm"]).post(f"/v1/refunds/{refund['id']}/retry").json()["status"] == "failed"
    FakeProviderTransaction.objects.filter(reference=p["provider_ref"]).update(refundable=True)
    assert api(people["cm"]).post(f"/v1/refunds/{refund['id']}/retry").json()["status"] == "completed"
    assert ReconIssue.objects.get(kind="refund_failed", refund_id=refund["id"]).status == "resolved"


def test_rejected_refund_closes(seeded, api, people, gh, mfa):
    c = api(people["client"])
    o = _order(api, people, gh)
    p = pay(c, o["id"])
    refund = api(people["cm"]).post("/v1/refunds", {"payment_id": p["id"], "reason": "x"}, format="json").json()
    r = _approve(api, mfa, people["reviewer"], f"/v1/refunds/{refund['id']}/approvals", "reject")
    assert r.json()["status"] == "rejected"
    assert FeePayment.objects.get(pk=p["id"]).status == "confirmed"


# ---------------------------------------------------------------- offline payments (US-ORD-004)


def _offline(api, people, order_id, *, amount="350.00", currency="USD", proof=True):
    data = {"order_id": order_id, "amount": amount, "currency": currency, "reference": "GCB-TRF-889201",
            "received_on": "2026-11-12", "source_bank_name": "GCB Bank", "source_account_name": "Kofi Boateng",
            "source_account_number": "1021130045671"}
    if proof:
        data["proof"] = SimpleUploadedFile("advice.pdf", b"%PDF transfer advice", content_type="application/pdf")
    return api(people["cm"]).post("/v1/offline-payments", data, format="multipart")


def test_offline_payment_needs_proof(seeded, api, people, gh):
    """US-ORD-004 AC3, TC-ORD-004-03: without proof rejected; with proof the order is paid and audited."""
    o = _order(api, people, gh, who="client2")
    r = _offline(api, people, o["id"], proof=False)
    assert r.status_code == 422 and r.json()["code"] == "proof-required"
    assert Order.objects.get(pk=o["id"]).status == "awaiting_payment"
    assert _offline(api, people, o["id"], amount="300.00").json()["code"] == "amount-mismatch"
    r = _offline(api, people, o["id"])
    assert r.status_code == 201, r.content
    p = r.json()
    assert p["status"] == "confirmed" and p["source_account"]["number_last4"] == "5671"
    assert Order.objects.get(pk=o["id"]).status == "paid"
    assert OutboxEvent.objects.filter(topic="payment.offline_recorded", aggregate_id=p["id"]).exists()
    assert AuditEvent.objects.filter(action="payment.offline_recorded").exists()
    assert Receipt.objects.filter(payment_id=p["id"], kind="receipt").exists()
    assert api(people["client2"]).post("/v1/offline-payments", {}, format="json").status_code == 403


def test_offline_payment_over_threshold_needs_two_approvals(seeded, api, people, gh, mfa):
    """Two-person rule over the configured threshold (working assumption USD 500)."""
    o = _order(api, people, gh, who="client2", tier="premium")
    p = _offline(api, people, o["id"], amount="650.00").json()
    assert p["status"] == "pending_approval"
    order = api(people["client2"]).get(f"/v1/orders/{o['id']}").json()
    assert order["status"] == "awaiting_payment" and order["can_pay"] is False
    url = f"/v1/offline-payments/{p['id']}/approvals"
    assert _approve(api, mfa, people["cm"], url).json()["code"] == "same-approver"
    _approve(api, mfa, people["reviewer"], url)
    assert Order.objects.get(pk=o["id"]).status == "awaiting_payment"
    assert _approve(api, mfa, people["admin"], url).json()["status"] == "confirmed"
    assert Order.objects.get(pk=o["id"]).status == "paid"


def test_offline_refund_goes_back_to_the_source_account(seeded, api, people, gh, mfa):
    """FR-PAY-008, I-40: an offline fee is refunded to the account it came from, with the bank's proof."""
    o = _order(api, people, gh, who="client2")
    p = _offline(api, people, o["id"]).json()
    refund = api(people["cm"]).post("/v1/refunds", {"payment_id": p["id"], "reason": "Plot withdrawn"},
                                    format="json").json()
    assert "Kofi Boateng, GCB Bank" in refund["destination"]
    for who in ("reviewer", "reviewer2"):
        out = _approve(api, mfa, people[who], f"/v1/refunds/{refund['id']}/approvals").json()
    assert out["status"] == "processing"
    assert Message.objects.filter(person=people["cm"], template="offline_refund_due").exists()
    url = f"/v1/refunds/{refund['id']}/completion"
    cm = api(people["cm"])
    assert cm.post(url, {"bank_reference": "GCB-RF-1"}, format="multipart").json()["code"] == "proof-required"
    r = cm.post(url, {"bank_reference": "GCB-RF-1", "account_number": "999"}, format="multipart")
    assert r.status_code == 400
    proof = SimpleUploadedFile("refund.pdf", b"%PDF refund advice", content_type="application/pdf")
    done = cm.post(url, {"bank_reference": "GCB-RF-1", "proof": proof}, format="multipart").json()
    assert done["status"] == "completed" and done["provider_refund_ref"] == "GCB-RF-1"
    assert Order.objects.get(pk=o["id"]).status == "refunded"


# ---------------------------------------------------------------- reconciliation (US-PAY-006)


def _yesterday(*payments):
    """Settle the test's payments on a day the seed did not touch."""
    day = timezone.now() - timedelta(days=1)
    for p in payments:
        FeePayment.objects.filter(pk=p["id"]).update(confirmed_at=day)
        FakeProviderTransaction.objects.filter(reference=p["provider_ref"]).update(paid_at=day)
    return day.date()


def test_daily_settlement_matches_and_lists_mismatches(seeded, api, people, gh):
    """US-PAY-006, TC-PAY-006-01/02: lines matched; unmatched, wrong amounts, missing and duplicates listed."""
    c = api(people["client"])
    o1, o2 = _order(api, people, gh), _order(api, people, gh)
    p1, p2 = pay(c, o1["id"]), pay(c, o2["id"])
    day = _yesterday(p1, p2).isoformat()
    cm = api(people["cm"])
    r = cm.post("/v1/reconciliation/runs", {"country": "GH", "settlement_date": day}, format="json")
    assert r.status_code == 201 and r.json()["matched"] == 2 and r.json()["issues"] == 0
    csv_file = (f"provider_ref,amount,currency,fee\n{p1['provider_ref']},350.00,USD,6.83\n"
                f"fake_unknown,99.00,USD,1.00\n").encode()
    up = SimpleUploadedFile("settle.csv", csv_file, content_type="text/csv")
    r = cm.post("/v1/reconciliation/runs", {"country": "GH", "settlement_date": day, "file": up},
                format="multipart")
    assert r.status_code == 201 and r.json()["issues"] == 2
    run_id = r.json()["id"]
    kinds = sorted(i["kind"] for i in cm.get(f"/v1/reconciliation/issues?run={run_id}").json()["items"])
    assert kinds == ["duplicate_line", "unmatched_line"]
    assert len(cm.get(f"/v1/reconciliation/runs/{run_id}").json()["lines"]) == 2
    up = SimpleUploadedFile("settle.csv", csv_file, content_type="text/csv")
    r = cm.post("/v1/reconciliation/runs", {"country": "GH", "settlement_date": day, "file": up},
                format="multipart")
    assert r.status_code == 200 and r.json()["duplicate"] is True
    bad = SimpleUploadedFile("bad.csv", b"provider_ref,amount\nx,notanumber\n", content_type="text/csv")
    r = cm.post("/v1/reconciliation/runs", {"country": "GH", "settlement_date": day, "file": bad},
                format="multipart")
    assert r.status_code == 422 and r.json()["code"] == "settlement-file-invalid"
    issue = cm.get(f"/v1/reconciliation/issues?run={run_id}&kind=unmatched_line").json()["items"][0]
    r = cm.post(f"/v1/reconciliation/issues/{issue['id']}/resolution", {"resolution": "Provider test charge"},
                format="json")
    assert r.json()["status"] == "resolved"
    assert api(people["client"]).get("/v1/reconciliation/issues").status_code == 403


def test_missing_settlement_and_amount_mismatch(seeded, api, people, gh):
    c = api(people["client"])
    o1, o2 = _order(api, people, gh), _order(api, people, gh)
    p1, p2 = pay(c, o1["id"]), pay(c, o2["id"])
    day = _yesterday(p1, p2)
    run = services.import_settlement(people["cm"], country=gh, settlement_date=day, items=[
        adapters.SettlementItem(provider_ref=p1["provider_ref"], amount=Decimal("300.00"), currency="USD")])
    assert run.issues == 2
    found = {(i.kind, str(i.payment_id)) for i in ReconIssue.objects.filter(run=run)}
    assert found == {("amount_mismatch", p1["id"]), ("missing_settlement", p2["id"])}


# ---------------------------------------------------------------- seller invoices (US-PAY-007, checked plots)


def _seller_org(people, gh):
    org = Organisation.objects.get(name="Ato Estates Ltd")
    RoleGrant.objects.get_or_create(person=people["seller"], role="SE", organisation=org)
    return org


def test_checked_plot_is_invoiced_to_the_seller_and_paid(seeded, api, people, gh):
    """Checked plots: the seller pays a fixed fee per plot, by invoice; payment marks the order paid."""
    org = _seller_org(people, gh)
    s = api(people["seller"])
    o = place_order(s, people["seller"], gh, kind="listing_verification", organisation_id=str(org.pk))
    assert o["bill_to"] == "organisation" and o["price"]["amount"] == "200.00"
    inv = Invoice.objects.get(order_id=o["id"])
    assert inv.status == "issued" and inv.number.startswith("INV-GH-") and inv.purpose == "report_fee"
    assert s.post(f"/v1/orders/{o['id']}/payments", {"method": "card"}, format="json").status_code == 409
    listed = s.get("/v1/seller-invoices").json()["items"]
    assert inv.number in [i["number"] for i in listed]
    assert api(people["client"]).get(f"/v1/seller-invoices/{inv.pk}").status_code == 404
    started = s.post(f"/v1/seller-invoices/{inv.pk}/payments", {"method": "card"}, format="json")
    assert started.status_code == 201
    checkout(s, started.json()["payment"]["id"])
    inv.refresh_from_db()
    assert inv.status == "paid"
    assert Order.objects.get(pk=o["id"]).status == "paid"


def test_listing_fee_invoice_and_no_success_fee_by_default(seeded, people, gh):
    """FR-PAY-007, Q-31: listing fee invoiced on submission; success fees only if the country allows them."""
    org = _seller_org(people, gh)
    listing_id = uuid7()
    payload = {"listing_id": listing_id, "organisation_id": org.pk, "submitted_by": people["seller"].pk,
               "reference": "LST-GH-1"}
    publish("listing.submitted", listing_id, payload)
    publish("listing.submitted", listing_id, payload)
    assert Invoice.objects.filter(kind="listing_fee", subject_id=listing_id).count() == 1
    publish("listing.sold", listing_id, payload)
    assert not Invoice.objects.filter(kind="success_fee").exists()
    assert AuditEvent.objects.filter(action="seller_invoice.success_fee_not_charged").exists()
    cfg = gh.configs.get(status="published")
    cfg.data = {**cfg.data, "payments": {"success_fees": True}}
    cfg.save(update_fields=["data"])
    publish("listing.sold", listing_id, payload)
    assert Invoice.objects.get(kind="success_fee").amount == Decimal("250.00")


def test_staff_create_and_void_invoices(seeded, api, people, gh):
    org = _seller_org(people, gh)
    cm = api(people["cm"])
    r = cm.post("/v1/seller-invoices", {"organisation_id": str(org.pk), "kind": "api_fee",
                                        "description": "Plot status queries, October",
                                        "amount": {"amount": "80.00", "currency": "USD"},
                                        "bill_to_person": str(people["seller"].pk)}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "issued"
    assert api(people["seller"]).post("/v1/seller-invoices", {}, format="json").status_code in (400, 403)
    r = cm.post(f"/v1/seller-invoices/{r.json()['id']}/void", {"reason": "Raised in error"}, format="json")
    assert r.json()["status"] == "void"


def test_offline_payment_of_an_invoice(seeded, api, people, gh):
    org = _seller_org(people, gh)
    o = place_order(api(people["seller"]), people["seller"], gh, kind="listing_verification",
                    organisation_id=str(org.pk))
    inv = Invoice.objects.get(order_id=o["id"])
    ev = site_plan(people["cm"], gh, b"%PDF bank advice")
    r = api(people["cm"]).post("/v1/offline-payments", {
        "invoice_id": str(inv.pk), "amount": "200.00", "currency": "USD", "reference": "ECO-55",
        "received_on": "2026-11-12", "source_bank_name": "Ecobank", "source_account_name": "Ato Estates Ltd",
        "proof_evidence_id": str(ev.pk)}, format="json")
    assert r.status_code == 201, r.content
    assert Order.objects.get(pk=o["id"]).status == "paid"
