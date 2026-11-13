"""Exchange: RUL-35, RUL-36, FR-ESC-021 to 024 (ADR-27). All rates are synthetic test fixtures."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from core.errors import Invalid, RuleBlocked, StateConflict
from core.models import OutboxEvent
from escrow import adapters, services
from escrow.models import Escrow, FxConversion, FxQuote, ReleaseInstruction


@pytest.fixture
def fx_escrow(b):
    e = b.agree(b.purchase(price="150000.00"))
    services.record_fx_account(e, b.cm, currency="USD", virtual_account_ref=f"VA-USD-{e.reference}")
    return Escrow.objects.get(pk=e.pk)


@pytest.fixture(autouse=True)
def _reset_fake():
    adapters.FakeRateSource.fails = set()
    adapters.FakeRateSource.stale_reference = False
    yield
    adapters.FakeRateSource.fails = set()
    adapters.FakeRateSource.stale_reference = False


def test_deposit_routes_show_every_part(b, fx_escrow):
    """FR-ESC-021 AC1, AC4, AC6: rate, source, margin, fees, limits, amount delivered; own bank is an estimate."""
    out = services.deposit_routes(fx_escrow, b.client, currency="USD", amount="18000.00")
    assert out["tenmina_margin_line"] == "Tenmina takes no margin on the exchange."
    routes = {(r["route"], r["provider"]): r for r in out["routes"]}
    bank = next(r for (k, _), r in routes.items() if k == "escrow_fx_account")
    assert Decimal(bank["margin_pct"]) == Decimal("0.5000")
    assert bank["fees"] and bank["reference_source"] and bank["tenmina_margin"] == "0.00"
    assert Decimal(bank["expected_to_amount"]) == Decimal("18000") * Decimal("14.925") - Decimal("149.25")
    own = next(r for (k, _), r in routes.items() if k == "escrow_local_account")
    assert own["is_estimate"] and "not checked by Tenmina" in own["note"]
    remit = routes[("transfer_partner", "Remit Bridge [demo]")]
    assert remit["transfers_needed"] == 4 and remit["over_limit"]
    diaspora = routes[("transfer_partner", "DiasporaPay [demo]")]
    assert diaspora["partner_payment_to_tenmina"] == "1.50"
    for r in out["routes"]:
        assert "margin_pct" in r and "fees" in r


def test_route_without_published_margin_not_offered(b, fx_escrow):
    """FR-ESC-021 AC2, AC5: no published margin and fees, or no answer on payments to Tenmina: not offered."""
    from administration import services as adm

    adm.create_partner(country=b.gh, kind="transfer_partner", name="Hidden Margin Co", by=b.p["admin"],
                       details={"corridors": ["USD/GHS"], "pays_tenmina": "0"})
    adm.create_partner(country=b.gh, kind="transfer_partner", name="Silent Co", by=b.p["admin"],
                       details={"corridors": ["USD/GHS"], "margin_pct": "1", "fee": "1"})
    out = services.deposit_routes(fx_escrow, b.client, currency="USD", amount="1000.00")
    offered = {r["provider"] for r in out["routes"]}
    assert "Hidden Margin Co" not in offered and "Silent Co" not in offered
    assert {u["provider"] for u in out["unavailable"] if "provider" in u} >= {"Hidden Margin Co", "Silent Co"}


def test_stale_reference_rate_refuses_quotes(b, fx_escrow):
    """FR-ESC-021 AC3, FR-ESC-023: a quote is never built on an old rate."""
    adapters.FakeRateSource.stale_reference = True
    with pytest.raises(RuleBlocked) as ei:
        services.issue_quote(fx_escrow, b.client, purpose="deposit", route="escrow_local_account",
                             from_currency="EUR", from_amount="100.00")
    assert ei.value.code == "fx-rate-stale"


def test_quote_acceptance_rules(b, fx_escrow):
    """FR-ESC-023 AC1, TC-ESC-021-04: exactly as shown, before it expires, and never edited."""
    qt = services.issue_quote(fx_escrow, b.client, purpose="deposit", route="escrow_fx_account",
                              from_currency="USD", from_amount="1000.00")
    assert qt.tenmina_margin == 0 and qt.programme_rate_id and "no margin" in qt.shown_text
    with pytest.raises(Invalid):
        services.accept_quote(qt, b.client, mfa_at=timezone.now(), shown_sha256="0" * 64)
    services.accept_quote(qt, b.client, mfa_at=timezone.now(), shown_sha256=qt.shown_sha256)
    assert OutboxEvent.objects.filter(topic="fx_quote.accepted", aggregate_id=qt.pk).exists()
    with pytest.raises(DatabaseError), transaction.atomic():
        FxQuote.objects.filter(pk=qt.pk).update(offered_rate="20.0")


def test_expired_quote_refused(b, fx_escrow):
    """FR-ESC-023: a quote holds for fx_quote_valid_minutes only."""
    qt = services.issue_quote(fx_escrow, b.client, purpose="deposit", route="escrow_fx_account",
                              from_currency="USD", from_amount="1000.00")
    import escrow.fx as fxmod

    real_now = fxmod.now
    try:
        fxmod.now = lambda: real_now() + timedelta(hours=2)
        with pytest.raises(RuleBlocked) as ei:
            services.accept_quote(qt, b.client, mfa_at=timezone.now(), shown_sha256=qt.shown_sha256)
    finally:
        fxmod.now = real_now
    assert ei.value.code == "fx-quote-expired"


def test_conversion_choice_and_buffer(b, fx_escrow):
    """RUL-36, FR-ESC-022 AC1, AC2: at release copies the buffer; fixed after a foreign currency deposit."""
    e = services.set_conversion_choice(fx_escrow, b.client, choice="at_release", mfa_at=timezone.now())
    assert e.fx_buffer_pct is not None and e.fx_buffer_pct > 0
    b.deposit(e, "1000.00", currency="USD", va=e.fx_accounts.get(currency="USD").virtual_account_ref)
    with pytest.raises(StateConflict):
        services.set_conversion_choice(Escrow.objects.get(pk=e.pk), b.client, choice="on_deposit",
                                       mfa_at=timezone.now())


def _convert(b, e, credit_amount=None, fees="149.25"):
    qt = services.issue_quote(e, b.client, purpose="deposit", route="escrow_fx_account", from_currency="USD",
                              from_amount="1000.00")
    services.accept_quote(qt, b.client, mfa_at=timezone.now(), shown_sha256=qt.shown_sha256)
    usd_va = e.fx_accounts.get(currency="USD").virtual_account_ref
    b.deposit(e, "1000.00", currency="USD", va=usd_va)
    ins = ReleaseInstruction.objects.get(escrow=e, kind="conversion")
    assert ins.status == "pending_approval" and ins.client_approval_method == "fx_quote"
    ins = b.approve_all(ins, client=False)
    assert ins.status == "sent", ins.last_send_error
    b.confirm(ins)
    amount = credit_amount or qt.expected_to_amount
    ev = services.record_bank_event(e, kind="conversion_credit", amount=amount, bank_reference=f"CONV-{ins.pk}",
                                    by=b.cm, proof_evidence=b.ev("fx-advice"), instruction=ins,
                                    applied_fees=Decimal(fees))
    services.check_bank_event(ev, b.rv)
    return qt, ReleaseInstruction.objects.get(pk=ins.pk)


def test_convert_on_deposit_checked_against_quote(b, fx_escrow):
    """FR-ESC-022, FR-ESC-023 AC2: the bank converts between the escrow's own accounts; checked against the quote."""
    qt, ins = _convert(b, fx_escrow)
    assert ins.status == "confirmed"
    conv = FxConversion.objects.get(quote=qt)
    assert conv.status == "within"
    assert services.selectors.held_at_bank(fx_escrow, "GHS") == qt.expected_to_amount
    assert services.selectors.held_at_bank(fx_escrow, "USD") == 0


def test_conversion_outside_margin_alerts(b, fx_escrow):
    """FR-ESC-023 AC3: a margin above the programme margin raises an alert and is claimed by two people."""
    qt, ins = _convert(b, fx_escrow, credit_amount=Decimal("14500.00"))
    conv = FxConversion.objects.get(quote=qt)
    assert conv.status == "outside" and conv.findings
    assert OutboxEvent.objects.filter(topic="fx_conversion.outside_margin", aggregate_id=conv.pk).exists()
    services.resolve_conversion(conv, b.rv, note="Bank refunded the difference", evidence=b.ev("bank-answer"))
    from core.errors import Forbidden

    with pytest.raises(Forbidden):
        services.check_conversion_resolution(conv, b.rv)
    assert services.check_conversion_resolution(conv, b.rv2).status == "resolved"


def test_partner_delivery_short_of_quote(b, fx_escrow):
    """FR-ESC-023 AC5, IF-15: a partner delivering less than quoted raises the alert."""
    from administration.models import Partner

    partner = Partner.objects.get(name="SendHome Transfers [demo]")
    qt = services.issue_quote(fx_escrow, b.client, purpose="deposit", route="transfer_partner",
                              from_currency="USD", from_amount="1000.00", provider_partner=partner)
    services.accept_quote(qt, b.client, mfa_at=timezone.now(), shown_sha256=qt.shown_sha256)
    b.deposit(fx_escrow, qt.expected_to_amount - Decimal("50.00"), known=False, route="transfer_partner",
              partner=partner)
    conv = FxConversion.objects.get(quote=qt)
    assert conv.status == "outside" and conv.short_of_quote == Decimal("50.00")


def test_release_short_after_conversion_blocked(b, codes):
    """RUL-36, FR-ESC-022 AC3: a release short in local currency is blocked with the shortfall named."""
    e = b.agree(b.purchase(price="20000.00"))
    services.record_fx_account(e, b.cm, currency="USD", virtual_account_ref=f"VA-USD-{e.reference}")
    services.set_conversion_choice(Escrow.objects.get(pk=e.pk), b.client, choice="at_release",
                                   mfa_at=timezone.now())
    b.deposit(e, "2000.00", currency="USD", va=f"VA-USD-{e.reference}")
    e = Escrow.objects.get(pk=e.pk)
    b.close_all(e)
    b.fresh(e)
    with pytest.raises(RuleBlocked) as ei:
        services.request_release(Escrow.objects.get(pk=e.pk), requested_by=b.cm)
    reason = next(r for r in ei.value.blocking_reasons if r["code"] == "held-funds-insufficient")
    assert reason["rule"] == "RUL-36" and reason["shortfall"]["amount"] == "20000.00"


def test_daily_comparison_and_best_rate(b, fx_escrow):
    """FR-ESC-024, RUL-35: ranked by amount delivered; "best rate" only on a complete day where the bank wins."""
    runs = {r.send_amount: r for r in services.collect_rates(b.gh) if r.from_currency == "USD"}
    small, large = runs[Decimal("1000.00")], runs[Decimal("10000.00")]
    assert small.status == "complete" and large.status == "complete"
    assert small.programme_rank != 1 and large.programme_rank == 1
    qt = services.issue_quote(fx_escrow, b.client, purpose="deposit", route="escrow_fx_account",
                              from_currency="USD", from_amount="10000.00")
    assert qt.best_rate_claim and "Best rate" in qt.shown_text
    qt_small = services.issue_quote(fx_escrow, b.client, purpose="deposit", route="escrow_fx_account",
                                    from_currency="USD", from_amount="1000.00")
    assert not qt_small.best_rate_claim and "Best rate" not in qt_small.shown_text
    adapters.FakeRateSource.fails = {"SendHome Transfers [demo]"}
    runs = {r.send_amount: r for r in services.collect_rates(b.gh) if r.from_currency == "USD"}
    assert runs[Decimal("10000.00")].status == "partial"
    assert OutboxEvent.objects.filter(topic="fx.comparison_incomplete").exists()
    qt2 = services.issue_quote(fx_escrow, b.client, purpose="deposit", route="escrow_fx_account",
                               from_currency="USD", from_amount="10000.00")
    assert not qt2.best_rate_claim
    payload = services.comparison_for(b.gh, from_currency="USD", amount="10000.00")[0]
    assert payload["status"] == "partial" and not payload["bank_best_rate"]
    assert any(i["stale"] for i in payload["items"])


def test_manual_rate_needs_a_second_person(b):
    """FR-ESC-024, 6.17: a rate entered by hand backs nothing until checked by another person."""
    from administration.models import Partner
    from core.errors import Forbidden

    src = Partner.objects.get(name="Remit Bridge [demo]")
    obs = services.enter_observation(b.cm, country=b.gh, source_partner=src, kind="provider", from_currency="USD",
                                     to_currency="GHS", rate="14.80", send_amount="1000.00", fees_total="5.00",
                                     delivered_amount="14726.00", proof_evidence=b.ev("screenshot"))
    assert not obs.usable
    with pytest.raises(Forbidden):
        services.check_observation(obs, b.cm)
    assert services.check_observation(obs, b.rv).usable


def test_programme_rate_needs_second_admin(b):
    """Q-33, FR-ADM-003: a programme rate is active only after a second administrator approves."""
    from administration.models import Partner

    bank = Partner.objects.filter(country=b.gh, kind="escrow_bank").first()
    src = Partner.objects.filter(country=b.gh, kind="rate_source").first()
    pr = services.create_programme_rate(b.p["admin"], country=b.gh, bank_partner=bank, from_currency="EUR",
                                        to_currency="GHS", margin_pct="0.60", fee_schedule=[], reference_source=src,
                                        valid_from=timezone.localdate(), agreement_evidence=b.ev("agreement"))
    assert pr.status == "pending"
    services.decide_programme_rate(pr, b.p["admin2"], decision="approve", mfa_at=timezone.now())
    pr.refresh_from_db()
    assert pr.status == "active"
