"""Disclosed exchange with no Tenmina margin (ADR-27, RUL-35, RUL-36,
FR-ESC-021 to FR-ESC-024). Rates are units of the `to` currency per one
unit of the `from` currency. A margin is (reference - rate) / reference as a
percentage. Every figure is synthetic in development and tests.
Called through escrow.services."""
import hashlib
import json
import math
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from django.db import transaction
from django.utils import timezone

from administration import flags
from core import approvals, state
from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.ids import uuid7
from core.money import q
from core.permissions import has_role

from . import adapters, selectors
from .common import alert_staff, audit, fmt, local_date, local_today, notify, now, setting
from .models import (BankEvent, Escrow, FxAccount, FxComparisonItem, FxComparisonRun, FxConversion, FxQuote,
                     FxRateObservation, ProgrammeAccount, ProgrammeRate, ReleaseInstruction)

R8 = Decimal("0.00000001")
P4 = Decimal("0.0001")
NO_MARGIN_LINE = "Tenmina takes no margin on the exchange."


def _on(country):
    flags.require("escrow.enabled", country)
    flags.read_only_guard()


def margin_of(reference, rate) -> Decimal:
    return ((Decimal(reference) - Decimal(rate)) / Decimal(reference) * 100).quantize(P4)


def _down(x) -> Decimal:
    return Decimal(x).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


# ----------------------------------------------------------------- reference rates (IF-14)

def _reference_source(country):
    from administration.models import Partner

    return Partner.objects.filter(country=country, kind="rate_source", status="active").order_by("created_at").first()


def _fresh(obs, country) -> bool:
    if obs is None or not obs.usable:
        return False
    stale_h = int(setting("fx_rate_stale_hours", country, 24))
    published = obs.source_published_at or obs.collected_at
    return (now() - published) <= timedelta(hours=stale_h) and local_date(country, published) == local_today(country)


def reference_observation(country, from_currency, to_currency, *, collect=True):
    """Today's usable reference rate, collected through IF-14 when missing.
    A stale rate never backs a quote (FR-ESC-023, I-45)."""
    obs = FxRateObservation.objects.filter(country=country, kind="reference", from_currency=from_currency,
                                           to_currency=to_currency).order_by("-collected_at").first()
    if _fresh(obs, country):
        return obs
    src = _reference_source(country)
    if not collect or src is None:
        return None
    try:
        r = adapters.rate_source().reference_rate(source=src, from_currency=from_currency, to_currency=to_currency)
    except Exception:  # noqa: BLE001
        return None
    obs = FxRateObservation.objects.create(country=country, source_partner=src, kind="reference",
                                           from_currency=from_currency, to_currency=to_currency, rate=r["rate"],
                                           source_published_at=r.get("published_at"), method="api",
                                           raw_sha256=r["raw_sha256"])
    return obs if _fresh(obs, country) else None


def programme_rate_for(country, bank_partner, from_currency, to_currency, amount=None):
    today = local_today(country)
    qs = ProgrammeRate.objects.filter(country=country, bank_partner=bank_partner, from_currency=from_currency,
                                      to_currency=to_currency, status="active", valid_from__lte=today) \
        .exclude(valid_to__lt=today)
    if amount is not None:
        qs = qs.filter(band_from__lte=amount).exclude(band_to__lte=amount)
    return qs.order_by("-valid_from", "band_from").first()


def _fees(schedule, from_currency, to_currency, rate):
    """Every fee by name, and their total in the `to` currency."""
    out, total = [], Decimal("0")
    for f in schedule or []:
        amt, cur = Decimal(str(f.get("amount", "0"))), str(f.get("currency", from_currency)).upper()
        to_amt = (amt * rate) if cur == from_currency else amt
        out.append({"name": f.get("name", "fee"), "charged_by": f.get("charged_by", ""), "amount": f"{amt:.2f}",
                    "currency": cur, "in_to_currency": f"{to_amt:.2f}"})
        total += to_amt
    return out, q(total)


def _limits(details, amount):
    lim = details.get("limit_per_transfer")
    if not lim:
        return "", 1, False
    lim = Decimal(str(lim))
    n = math.ceil(Decimal(amount) / lim)
    over = n > int(details.get("max_transfers_per_day", 99))
    text = f"Up to {lim:,.2f} per transfer" + (f"; this amount needs {n} transfers" if n > 1 else "")
    if over:
        text += ". Over this route's daily limit."
    return text, n, over


def _best_run(country, from_currency, to_currency, amount):
    run = FxComparisonRun.objects.filter(country=country, run_date=local_today(country), from_currency=from_currency,
                                         to_currency=to_currency, send_amount__lte=amount) \
        .order_by("-send_amount").first()
    return run


def _route_figures(e: Escrow, route, provider, from_currency, amount, ref, client_rate=None):
    """One route's figures, or None with a reason when it cannot be offered."""
    to_currency = e.currency
    amount = q(amount)
    details = provider.details or {}
    prate = None
    if route == "escrow_fx_account":
        prate = programme_rate_for(e.country, provider, from_currency, to_currency, amount)
        if prate is None:
            return None, "The bank has not given its programme rate in writing for this pair (Q-33)."
        rate = (ref.rate * (Decimal(100) - prate.margin_pct) / Decimal(100)).quantize(R8)
        fees, fees_to = _fees(prate.fee_schedule, from_currency, to_currency, rate)
        payment, estimate, lim = Decimal("0"), False, details.get("limits", {})
    elif route == "transfer_partner":
        if "margin_pct" not in details or "fee" not in details:
            return None, "This partner has not published its margin and fees."
        if "pays_tenmina" not in details:
            return None, "This partner has not answered whether it pays Tenmina anything."
        corridors = details.get("corridors") or []
        if f"{from_currency}/{to_currency}" not in corridors:
            return None, "This partner does not serve this corridor."
        rate = (ref.rate * (Decimal(100) - Decimal(str(details["margin_pct"]))) / Decimal(100)).quantize(R8)
        fees, fees_to = _fees([{"name": "Transfer fee", "amount": details["fee"], "currency": from_currency,
                                "charged_by": provider.name}], from_currency, to_currency, rate)
        payment, estimate, lim = Decimal(str(details.get("pays_tenmina") or 0)), False, details
    else:  # the client's own bank converts: Tenmina cannot see its rate
        rate = Decimal(str(client_rate)).quantize(R8) if client_rate else ref.rate
        fees, fees_to = [], Decimal("0.00")
        payment, estimate, lim = Decimal("0"), True, {}
    delivered = _down(amount * rate - fees_to)
    if delivered <= 0:
        return None, "The amount does not cover the fees."
    limits_text, transfers, over = _limits(lim if isinstance(lim, dict) else {}, amount)
    return {"route": route, "provider_partner_id": str(provider.pk), "provider": provider.name,
            "from_currency": from_currency, "from_amount": f"{amount:.2f}", "to_currency": to_currency,
            "reference_rate": str(ref.rate), "reference_source": ref.source_partner.name,
            "reference_published_at": (ref.source_published_at or ref.collected_at).isoformat(),
            "offered_rate": str(rate), "margin_pct": str(margin_of(ref.rate, rate)), "fees": fees,
            "fees_total_to": f"{fees_to:.2f}", "expected_to_amount": f"{delivered:.2f}",
            "limits_text": limits_text, "transfers_needed": transfers, "over_limit": over,
            "partner_payment_to_tenmina": f"{payment:.2f}", "tenmina_margin": "0.00", "is_estimate": estimate,
            "note": "Estimate from the reference rate, not checked by Tenmina." if estimate else "",
            "programme_rate_id": str(prate.pk) if prate else None}, ""


def deposit_routes(e: Escrow, viewer, *, currency, amount) -> dict:
    """FR-ESC-021: every way to pay in, with the reference rate and its source,
    the rate, the margin, every fee, the limits and the local amount delivered."""
    from administration.models import Partner

    flags.require("escrow.enabled", e.country)
    currency = currency.upper()
    out = {"escrow_id": str(e.pk), "currency": currency, "amount": f"{q(amount):.2f}", "to_currency": e.currency,
           "tenmina_margin_line": NO_MARGIN_LINE, "routes": [], "unavailable": [], "comparison": None}
    if currency == e.currency:
        out["routes"].append({"route": "escrow_local_account", "provider": e.bank_partner.name,
                              "from_currency": currency, "to_currency": e.currency, "expected_to_amount":
                              f"{q(amount):.2f}", "fees": [], "margin_pct": "0.0000", "tenmina_margin": "0.00",
                              "note": "Paid in the local currency: no exchange."})
        return out
    ref = reference_observation(e.country, currency, e.currency)
    if ref is None:
        out["unavailable"].append({"route": "all", "reason": "The reference rate is being updated. Routes appear "
                                                             "again once today's rate is collected."})
        return out
    candidates = [("escrow_fx_account", e.bank_partner), ("escrow_local_account", e.bank_partner)]
    candidates += [("transfer_partner", p) for p in Partner.objects.filter(country=e.country, kind="transfer_partner",
                                                                         status="active").order_by("name")]
    run = _best_run(e.country, currency, e.currency, q(amount))
    for route, provider in candidates:
        fig, why = _route_figures(e, route, provider, currency, amount, ref)
        if fig is None:
            out["unavailable"].append({"route": route, "provider": provider.name, "reason": why})
            continue
        fig["best_rate_claim"] = _best_claim(run, route, provider)
        out["routes"].append(fig)
    if run is not None:
        out["comparison"] = comparison_payload(run)
    return out


def _best_claim(run, route, provider) -> bool:
    """RUL-35: "best rate" only from a complete run of the same day, ranked by amount delivered."""
    if run is None or run.status != "complete" or run.best_observation is None:
        return False
    best = run.best_observation
    if route == "escrow_fx_account":
        return best.kind == "programme" and run.programme_rank == 1
    if route == "transfer_partner":
        return best.kind == "provider" and best.source_partner_id == provider.pk
    return False


# ----------------------------------------------------------------- quotes (FR-ESC-023)

@transaction.atomic
def issue_quote(e: Escrow, by, *, purpose, route, from_currency, from_amount, provider_partner=None,
                client_rate=None) -> FxQuote:
    _on(e.country)
    if by.pk != e.client_id and not has_role(by, "CM", "RV", country=e.country):
        raise NotFound()
    from_currency = from_currency.upper()
    if purpose not in FxQuote.PURPOSES or route not in FxQuote.ROUTES:
        raise Invalid("Unknown purpose or route.", code="validation-error")
    to_currency = e.currency if purpose in ("deposit", "release_conversion") else None
    if purpose == "refund_conversion":
        # a refund converts from the escrow's local currency back to the deposit's currency
        to_currency = from_currency
        from_currency = e.currency
    if from_currency == to_currency:
        raise Invalid("A quote is for two different currencies.", code="validation-error")
    provider = provider_partner or e.bank_partner
    pair_from, pair_to = from_currency, to_currency
    ref = reference_observation(e.country, pair_from, pair_to)
    if ref is None:
        raise RuleBlocked("The reference rate is being updated. A quote cannot be given on an old rate.",
                          code="fx-rate-stale", blocking_reasons=[{"rule": "RUL-35", "message":
                                                                   "No reference rate published today"}])
    if purpose == "refund_conversion":
        # figures for the reverse direction: the bank's programme rate for local -> foreign
        fake = Escrow(country=e.country, currency=to_currency, bank_partner=e.bank_partner)
        fig, why = _route_figures(fake, route, provider, pair_from, from_amount, ref, client_rate)
    else:
        fig, why = _route_figures(e, route, provider, pair_from, from_amount, ref, client_rate)
    if fig is None:
        raise RuleBlocked(f"This route cannot be offered: {why}", code="fx-route-unavailable",
                          blocking_reasons=[{"rule": "RUL-35", "message": why}])
    run = _best_run(e.country, pair_from, pair_to, q(from_amount))
    best = _best_claim(run, route, provider)
    minutes = int(setting("fx_quote_valid_minutes", e.country, 15))
    lines = [f"{fig['from_amount']} {pair_from} to {pair_to} by {fig['provider']} ({route.replace('_', ' ')})",
             f"Reference rate {fig['reference_rate']} from {fig['reference_source']} at "
             f"{fig['reference_published_at']}", f"Rate offered {fig['offered_rate']}",
             f"Margin {fig['margin_pct']}% of the reference rate"]
    lines += [f"Fee: {f['name']} {f['amount']} {f['currency']}" for f in fig["fees"]]
    lines += [f"Amount delivered: {fig['expected_to_amount']} {pair_to}", NO_MARGIN_LINE]
    if Decimal(fig["partner_payment_to_tenmina"]) > 0:
        lines.append(f"{fig['provider']} pays Tenmina {fig['partner_payment_to_tenmina']} {pair_from} for this "
                     "deposit.")
    if fig["is_estimate"]:
        lines.append(fig["note"])
    if best:
        lines.append("Best rate today among the providers compared.")
    text = "\n".join(lines)
    qt = FxQuote.objects.create(
        country=e.country, escrow=e, purpose=purpose, route=route, provider_partner=provider,
        from_currency=pair_from, from_amount=q(from_amount), to_currency=pair_to, reference_observation=ref,
        reference_rate=ref.rate, offered_rate=Decimal(fig["offered_rate"]), margin_pct=Decimal(fig["margin_pct"]),
        programme_rate_id=fig["programme_rate_id"], fees=fig["fees"], fees_total_to=Decimal(fig["fees_total_to"]),
        expected_to_amount=Decimal(fig["expected_to_amount"]), limits_text=fig["limits_text"],
        partner_payment_to_tenmina=Decimal(fig["partner_payment_to_tenmina"]),
        partner_payment_currency=pair_from if Decimal(fig["partner_payment_to_tenmina"]) > 0 else None,
        is_estimate=fig["is_estimate"], best_rate_claim=best, comparison_run=run if best else None, shown_text=text,
        shown_sha256=hashlib.sha256(text.encode()).hexdigest(), expires_at=now() + timedelta(minutes=minutes),
        created_by=by)
    audit(by, "fx_quote.issued", qt, {"route": route, "margin_pct": str(qt.margin_pct)})
    if route == "escrow_fx_account" and purpose == "deposit":
        _ensure_fx_account(e, pair_from)
    return qt


def _ensure_fx_account(e: Escrow, currency):
    fx = FxAccount.objects.filter(escrow=e, currency=currency).first()
    if fx is not None:
        return fx
    pa = ProgrammeAccount.objects.filter(country=e.country, currency=currency, kind="programme",
                                         status="active").first()
    if pa is None:
        return None
    ref = adapters.bank_instructions().open_virtual_account(escrow=e, programme_account=pa, currency=currency)
    if not ref:
        alert_staff(e.country, ("CM",), "fx_account_needed",
                    f"Ask the bank for {e.reference}'s {currency} virtual account and record it.", obj=e)
        return None
    return FxAccount.objects.create(country=e.country, escrow=e, programme_account=pa, currency=currency,
                                    virtual_account_ref=ref)


@transaction.atomic
def record_fx_account(e: Escrow, by, *, currency, virtual_account_ref) -> FxAccount:
    """The bank's foreign currency virtual account for the escrow (RUL-34, ADR-27)."""
    _on(e.country)
    if not has_role(by, "CM", "RV", country=e.country):
        raise Forbidden()
    currency = currency.upper()
    if currency == e.currency:
        raise Invalid("The escrow's own currency has its own virtual account.", code="validation-error")
    allowed = set((setting("fx_comparison_amounts", e.country, {}) or {}).keys())
    if allowed and not any(k.startswith(f"{currency}/") for k in allowed):
        raise Invalid("This currency is not a corridor in this country.", code="validation-error")
    pa = ProgrammeAccount.objects.filter(country=e.country, currency=currency, kind="programme",
                                         status="active").first()
    if pa is None:
        raise StateConflict(f"There is no active {currency} programme account.", code="programme-account-missing")
    if Escrow.objects.filter(virtual_account_ref=virtual_account_ref).exists() or \
            FxAccount.objects.filter(virtual_account_ref=virtual_account_ref).exists():
        raise StateConflict("This virtual account is already used.", code="virtual-account-duplicate")
    fx, _ = FxAccount.objects.update_or_create(escrow=e, currency=currency, defaults=dict(
        country=e.country, programme_account=pa, virtual_account_ref=virtual_account_ref))
    audit(by, "fx_account.recorded", fx, {"currency": currency})
    return fx


@transaction.atomic
def accept_quote(qt: FxQuote, client, *, mfa_at=None, code=None, shown_sha256=None) -> FxQuote:
    """The client accepts exactly what was shown, with MFA, before it expires."""
    from .payees import _client_signed

    e = qt.escrow
    _on(e.country)
    if e.client_id != client.pk:
        raise NotFound()
    qt.refresh_from_db()
    if qt.accepted_at:
        return qt
    _client_signed(client, mfa_at, code)
    if shown_sha256 and shown_sha256 != qt.shown_sha256:
        raise Invalid("The figures changed since you saw them. Ask for a new quote.", code="fx-quote-changed")
    if now() > qt.expires_at:
        raise RuleBlocked("This quote has expired. Ask for a new one.", code="fx-quote-expired",
                          blocking_reasons=[{"rule": "RUL-35", "message": "Quote expired"}])
    if not _fresh(qt.reference_observation, e.country):
        raise RuleBlocked("The reference rate is being updated. Ask for a new quote.", code="fx-rate-stale",
                          blocking_reasons=[{"rule": "RUL-35", "message": "Reference rate is stale"}])
    qt.accepted_by, qt.accepted_at = client, now()
    qt.save(update_fields=["accepted_by", "accepted_at"])
    publish("fx_quote.accepted", qt.pk, {"quote_id": qt.pk, "escrow_id": e.pk, "client_id": e.client_id,
                                         "purpose": qt.purpose, "route": qt.route})
    audit(client, "fx_quote.accepted", qt)
    for ins in ReleaseInstruction.objects.filter(fx_quote=qt, status="awaiting_client"):
        ins.client_approved_at, ins.client_approved_by = qt.accepted_at, client
        ins.client_approval_method, ins.client_approved_amount = "fx_quote", ins.amount
        state.transition(ins, "release_instruction", "pending_approval", actor=client,
                         event="release.client_approved",
                         extra_fields=["client_approved_at", "client_approved_by", "client_approval_method",
                                       "client_approved_amount"])
    return qt


@transaction.atomic
def set_conversion_choice(e: Escrow, client, *, choice, mfa_at=None, code=None) -> Escrow:
    """RUL-36: convert on deposit (the default) or at release with a buffer;
    changed only before the first foreign currency deposit."""
    from .payees import _client_signed

    _on(e.country)
    if e.client_id != client.pk:
        raise NotFound()
    _client_signed(client, mfa_at, code)
    if choice not in ("on_deposit", "at_release"):
        raise Invalid("Choose on_deposit or at_release.", code="validation-error")
    if BankEvent.objects.filter(escrow=e, kind="deposit", status="confirmed").exclude(currency=e.currency).exists():
        raise StateConflict("The choice is fixed once the bank confirms a foreign currency deposit. Convert early by "
                            "accepting a quote for a conversion.", code="conversion-choice-fixed")
    e.conversion_choice = choice
    e.fx_buffer_pct = Decimal(str(setting("fx_hold_buffer_pct", e.country, "5"))) if choice == "at_release" and \
        e.kind != "held_funds" else (Decimal("0") if choice == "at_release" else None)
    e.conversion_chosen_by, e.conversion_chosen_at = client, now()
    e.save(update_fields=["conversion_choice", "fx_buffer_pct", "conversion_chosen_by", "conversion_chosen_at"])
    audit(client, "escrow.conversion_choice", e, {"choice": choice, "buffer_pct": str(e.fx_buffer_pct)})
    return e


def buffer_amount(e: Escrow) -> Decimal:
    if e.conversion_choice != "at_release" or not e.fx_buffer_pct or e.kind == "held_funds":
        return Decimal("0")
    return q(e.agreed_amount * e.fx_buffer_pct / 100)


@transaction.atomic
def prepare_conversion(e: Escrow, by, *, quote: FxQuote) -> ReleaseInstruction:
    """A conversion between the escrow's own two virtual accounts, done by the
    bank (RUL-34, RUL-36). It pays no one; two staff approve it."""
    from .services import _alert_approvers, _client_payload, raise_if_blocked

    _on(e.country)
    if not has_role(by, "CM", "RV", country=e.country):
        raise Forbidden("A case manager prepares a conversion.")
    if quote.escrow_id != e.pk or quote.purpose not in ("deposit", "release_conversion"):
        raise Invalid("Name the client's quote for this escrow.", code="validation-error")
    iid = uuid7()
    ins = ReleaseInstruction(id=iid, country=e.country, escrow=e, kind="conversion", amount=quote.from_amount,
                             currency=quote.from_currency, to_currency=quote.to_currency, fx_quote=quote,
                             prepared_by=by, reason="Conversion between the escrow's own accounts",
                             clock_started_at=now(), subject_label=f"Convert {quote.from_currency} to "
                                                                   f"{quote.to_currency}")
    raise_if_blocked(ins, "prepare", "This conversion")
    ins.approval_request = approvals.request_approval(
        "escrow_release", iid, by, required=2, country=e.country,
        summary=f"Convert {fmt(quote.from_amount, quote.from_currency)} to {quote.to_currency} in {e.reference}")
    if quote.accepted_at:
        ins.status = "pending_approval"
        ins.client_approved_at, ins.client_approved_by = quote.accepted_at, quote.accepted_by
        ins.client_approval_method, ins.client_approved_amount = "fx_quote", ins.amount
    else:
        ins.status = "awaiting_client"
    ins.save(force_insert=True)
    publish("release.requested", ins.pk, _client_payload(ins))
    if ins.status == "pending_approval":
        _alert_approvers(ins)
    else:
        notify(e.client, "fx_quote_to_accept", "Please accept the quote for converting your money. Nothing converts "
                                               "until you accept.", needs_action=True, obj=quote, category="approval")
    return ins


def _staff_preparer(e):
    from .common import staff_in

    if has_role(e.created_by, "CM", "RV", country=e.country):
        return e.created_by
    return staff_in(e.country, "CM").first()


def on_deposit(ev: BankEvent):
    """FR-ESC-022, FR-ESC-023 on every confirmed deposit."""
    e = ev.escrow
    if ev.currency != e.currency:
        if e.conversion_choice != "on_deposit" or e.kind == "held_funds":
            return
        qt = FxQuote.objects.filter(escrow=e, purpose="deposit", route="escrow_fx_account",
                                    from_currency=ev.currency, accepted_at__isnull=False) \
            .exclude(pk__in=ReleaseInstruction.objects.filter(fx_quote__isnull=False).exclude(
                status__in=("withdrawn", "rejected", "rejected_by_bank")).values("fx_quote_id")) \
            .order_by("-accepted_at").first()
        prep = _staff_preparer(e)
        if qt is None or prep is None:
            alert_staff(e.country, ("CM",), "fx_quote_needed",
                        f"{fmt(ev.amount, ev.currency)} arrived on {e.reference} with no accepted quote. Issue a quote "
                        "for the client to accept before converting.", obj=e)
            return
        if qt.from_amount != ev.amount:
            qt = issue_quote(e, prep, purpose="release_conversion", route="escrow_fx_account",
                             from_currency=ev.currency, from_amount=ev.amount)
        prepare_conversion(e, prep, quote=qt)
        return
    qt = FxQuote.objects.filter(escrow=e, purpose="deposit", to_currency=ev.currency, accepted_at__isnull=False,
                                route__in=("transfer_partner", "escrow_local_account"), conversions__isnull=True) \
        .order_by("-accepted_at").first()
    if qt is None:
        return
    if ev.deposit_route == "transfer_partner" and qt.route == "transfer_partner":
        _record_conversion(e, qt, route="transfer_partner", credit=ev, debit=None, from_amount=qt.from_amount,
                           to_amount=ev.amount, applied_fees=qt.fees_total_to)
    elif qt.route == "escrow_local_account":
        _record_conversion(e, qt, route="client_bank", credit=ev, debit=None, from_amount=qt.from_amount,
                           to_amount=ev.amount, applied_fees=Decimal("0"))


def on_conversion_leg(ev: BankEvent):
    ins = ev.instruction
    if ins is None or ins.kind != "conversion":
        return
    debit = BankEvent.objects.filter(instruction=ins, kind="conversion_debit", status="confirmed").first()
    credit = BankEvent.objects.filter(instruction=ins, kind="conversion_credit", status="confirmed").first()
    if debit is None or credit is None or ins.status != "sent":
        return
    from .services import _client_payload

    ins.bank_confirmation_event = debit
    state.transition(ins, "release_instruction", "confirmed", event="release.confirmed",
                     extra_fields=["bank_confirmation_event"], payload=_client_payload(ins,
                                                                                      bank_reference=debit.bank_reference))
    qt = ins.fx_quote
    _record_conversion(ins.escrow, qt, route="bank_conversion", credit=credit, debit=debit,
                       from_amount=debit.amount, to_amount=credit.amount,
                       applied_fees=credit.applied_fees or Decimal("0"), instruction=ins,
                       applied_rate=credit.applied_rate or debit.applied_rate)
    from .services import dispatch

    for other in ReleaseInstruction.objects.filter(escrow=ins.escrow, status="approved"):
        dispatch(other)


def _record_conversion(e, qt: FxQuote, *, route, credit, debit, from_amount, to_amount, applied_fees,
                       instruction=None, applied_rate=None) -> FxConversion:
    """escrow.fx_conversion_check: the bank's or partner's result beside the quote."""
    if FxConversion.objects.filter(credit_event=credit).exists():
        return FxConversion.objects.get(credit_event=credit)
    rate = Decimal(applied_rate) if applied_rate else ((Decimal(to_amount) + Decimal(applied_fees)) /
                                                       Decimal(from_amount)).quantize(R8)
    ref = reference_observation(e.country, qt.from_currency, qt.to_currency, collect=True) or qt.reference_observation
    margin = margin_of(ref.rate, rate)
    expected = (qt.expected_to_amount * Decimal(from_amount) / qt.from_amount).quantize(Decimal("0.01"))
    short = q(expected - Decimal(to_amount))
    findings, status = [], "within"
    if route == "bank_conversion":
        pr = qt.programme_rate
        if pr is not None and margin > pr.margin_pct + pr.tolerance_pct:
            findings.append(f"Margin {margin}% is above the programme margin {pr.margin_pct}% "
                            f"(+{pr.tolerance_pct}% tolerance).")
        if Decimal(applied_fees) > qt.fees_total_to:
            findings.append(f"Fees {applied_fees} are above the quoted {qt.fees_total_to}.")
    elif route == "transfer_partner":
        tol = Decimal(str(setting("fx_delivery_tolerance", e.country, "1.00")))
        if short > tol:
            findings.append(f"The partner delivered {fmt(to_amount, qt.to_currency)}, short of the quoted "
                            f"{fmt(expected, qt.to_currency)} by {fmt(short, qt.to_currency)}.")
    else:
        status = "not_checked"
    if findings:
        status = "outside"
    conv = FxConversion.objects.create(
        country=e.country, escrow=e, quote=qt, route=route, instruction=instruction, debit_event=debit,
        credit_event=credit, from_amount=q(from_amount), to_amount=q(to_amount), applied_rate=rate,
        applied_fees=q(applied_fees), reference_observation=ref, reference_rate=ref.rate, margin_pct=margin,
        programme_rate=qt.programme_rate if route == "bank_conversion" else None, short_of_quote=short,
        status=status, findings=findings)
    payload = {"conversion_id": conv.pk, "escrow_id": e.pk, "client_id": e.client_id, "status": status,
               "quote_id": qt.pk, "findings": findings}
    publish("fx_conversion.confirmed", conv.pk, payload)
    if status == "outside":
        publish("fx_conversion.outside_margin", conv.pk, payload)
        alert_staff(e.country, ("CM", "RV"), "fx_outside_margin",
                    f"A conversion on {e.reference} differs from the client's quote: {' '.join(findings)} Claim the "
                    "difference (RB-48).", obj=conv)
        notify(e.client, "fx_outside_margin", "The exchange on your money differed from the quote you accepted: "
                                              + " ".join(findings) + " Tenmina is claiming the difference from the "
                                                                     "bank or partner.", obj=conv, category="money")
    return conv


@transaction.atomic
def resolve_conversion(conv: FxConversion, by, *, note, evidence, claim_amount=None, claim_reference=""):
    if not has_role(by, "RV", country=conv.country):
        raise Forbidden("Only a reviewer records the claim.")
    if conv.status != "outside":
        raise StateConflict("Only a conversion outside the quote is resolved.")
    if not note or evidence is None:
        raise Invalid("Record the outcome and attach the bank's or partner's answer.", code="validation-error")
    conv.resolved_by, conv.resolution_note, conv.resolution_evidence = by, note, evidence
    conv.claim_amount = q(claim_amount) if claim_amount is not None else conv.short_of_quote
    conv.claim_reference, conv.claimed_at = claim_reference or "", now()
    conv.save(update_fields=["resolved_by", "resolution_note", "resolution_evidence", "claim_amount",
                             "claim_reference", "claimed_at"])
    audit(by, "fx_conversion.claim_recorded", conv)
    return conv


@transaction.atomic
def check_conversion_resolution(conv: FxConversion, by):
    if not has_role(by, "CM", "RV", "AD", country=conv.country):
        raise Forbidden()
    if conv.status != "outside" or conv.resolved_by_id is None:
        raise StateConflict("No resolution waits for a check.")
    if by.pk == conv.resolved_by_id:
        raise Forbidden("A second staff member checks the resolution.", code="same-approver")
    conv.resolution_checked_by, conv.status = by, "resolved"
    conv.save(update_fields=["resolution_checked_by", "status"])
    audit(by, "fx_conversion.resolved", conv)
    return conv


# ----------------------------------------------------------------- programme rates (Q-33)

@transaction.atomic
def create_programme_rate(by, *, country, bank_partner, from_currency, to_currency, margin_pct, fee_schedule,
                          reference_source, valid_from, agreement_evidence, band_from=0, band_to=None,
                          tolerance_pct=0, valid_to=None) -> ProgrammeRate:
    _on(country)
    if not has_role(by, "AD", country=country):
        raise Forbidden("Only an administrator records the bank's programme rate.")
    if bank_partner.kind != "escrow_bank" or reference_source.kind != "rate_source":
        raise Invalid("Name the escrow bank and a reference rate source.", code="validation-error")
    if agreement_evidence is None:
        raise Invalid("Attach the bank's written agreement.", code="validation-error")
    if not isinstance(fee_schedule, list):
        raise Invalid("List every fee the bank may charge.", code="validation-error")
    pid = uuid7()
    req = approvals.request_approval("programme_rate", pid, by, required=1, country=country,
                                     summary=f"Programme rate {from_currency}/{to_currency} margin {margin_pct}%")
    pr = ProgrammeRate.objects.create(
        id=pid, country=country, bank_partner=bank_partner, from_currency=from_currency.upper(),
        to_currency=to_currency.upper(), band_from=q(band_from), band_to=q(band_to) if band_to else None,
        margin_pct=Decimal(str(margin_pct)), tolerance_pct=Decimal(str(tolerance_pct)), fee_schedule=fee_schedule,
        reference_source=reference_source, valid_from=valid_from, valid_to=valid_to,
        agreement_evidence=agreement_evidence, approval_request=req, created_by=by)
    audit(by, "programme_rate.proposed", pr, {"margin_pct": str(pr.margin_pct)})
    return pr


def decide_programme_rate(pr: ProgrammeRate, approver, *, decision, mfa_at, note=""):
    if pr.approval_request.status != "open":
        raise StateConflict("This rate is not waiting for approval.")
    return approvals.decide(pr.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=lambda a: has_role(a, "AD", country=pr.country))


def on_programme_rate_decided(pr: ProgrammeRate, approved: bool):
    pr.refresh_from_db()
    if pr.status != "pending":
        return pr
    if approved:
        ProgrammeRate.objects.filter(country=pr.country, bank_partner=pr.bank_partner, from_currency=pr.from_currency,
                                     to_currency=pr.to_currency, band_from=pr.band_from, status="active",
                                     valid_to__isnull=True).exclude(pk=pr.pk) \
            .update(valid_to=pr.valid_from - timedelta(days=1))
    pr.status = "active" if approved else "rejected"
    pr.save(update_fields=["status"])
    return pr


# ----------------------------------------------------------------- daily comparison (FR-ESC-024)

def _providers(country):
    from administration.models import Partner

    ids = setting("fx_comparison_providers", country, []) or []
    qs = Partner.objects.filter(country=country, status="active", kind__in=("transfer_partner", "rate_source"))
    out = []
    for i in ids:
        p = qs.filter(pk=i).first() if len(str(i)) == 36 else qs.filter(name=i).first()
        if p is not None:
            out.append(p)
    return out


@transaction.atomic
def collect_rates(country, *, by=None, day=None) -> list[FxComparisonRun]:
    """escrow.fx_collect_rates: the bank's programme rate and every provider in
    fx_comparison_providers, per corridor and band. Never edited afterwards."""
    flags.require("escrow.enabled", country)
    day = day or local_today(country)
    bands = setting("fx_comparison_amounts", country, {}) or {}
    providers = _providers(country)
    from administration.models import Partner

    bank = Partner.objects.filter(country=country, kind="escrow_bank", status="active").first()
    runs = []
    for pair, amounts in bands.items():
        frm, to = pair.split("/")
        ref = reference_observation(country, frm, to)
        for amt in amounts:
            amt = q(amt)
            items, fresh, expected = [], 0, len(providers) + (1 if bank else 0)
            if ref is not None and bank is not None:
                pr = programme_rate_for(country, bank, frm, to, amt)
                if pr is not None:
                    rate = (ref.rate * (100 - pr.margin_pct) / 100).quantize(R8)
                    fees, fees_to = _fees(pr.fee_schedule, frm, to, rate)
                    fees_from = sum((Decimal(f["amount"]) for f in fees if f["currency"] == frm), Decimal("0"))
                    obs = FxRateObservation.objects.create(
                        country=country, source_partner=bank, kind="programme", from_currency=frm, to_currency=to,
                        rate=rate, send_amount=amt, fees_total=q(fees_from), delivered_amount=_down(amt * rate - fees_to),
                        source_published_at=now(), method="api",
                        raw_sha256=hashlib.sha256(f"{pr.pk}|{rate}|{amt}".encode()).hexdigest())
                    items.append((bank, obs, False))
                    fresh += 1
                else:
                    items.append((bank, None, True))
            elif bank is not None:
                items.append((bank, None, True))
            for p in providers:
                try:
                    if ref is None:
                        raise ConnectionError("no reference")
                    r = adapters.rate_source().provider_quote(provider=p, from_currency=frm, to_currency=to,
                                                              send_amount=amt, reference_rate=ref.rate)
                    obs = FxRateObservation.objects.create(
                        country=country, source_partner=p, kind="provider", from_currency=frm, to_currency=to,
                        rate=r["rate"], send_amount=amt, fees_total=q(r["fees_total"]),
                        delivered_amount=q(r["delivered_amount"]), source_published_at=r.get("published_at"),
                        method="api", raw_sha256=r["raw_sha256"])
                    items.append((p, obs, False))
                    fresh += 1
                except Exception:  # noqa: BLE001 - a failed source is marked stale, never guessed
                    manual = FxRateObservation.objects.filter(
                        country=country, source_partner=p, kind="provider", from_currency=frm, to_currency=to,
                        send_amount=amt, method="manual", checked_by__isnull=False,
                        collected_at__date=day).order_by("-collected_at").first()
                    items.append((p, manual, manual is None))
                    fresh += 1 if manual else 0
            ranked = sorted([o for _, o, s in items if o is not None and not s], key=lambda o: -o.delivered_amount)
            status = "complete" if (fresh == expected and expected >= 1 and ref is not None) else \
                ("partial" if fresh else "failed")
            best = ranked[0] if ranked else None
            prog_rank = next((i + 1 for i, o in enumerate(ranked) if o.kind == "programme"), None)
            last_ok = FxComparisonRun.objects.filter(country=country, from_currency=frm, to_currency=to,
                                                     send_amount=amt, status="complete").order_by("-run_date").first()
            run, _ = FxComparisonRun.objects.update_or_create(
                country=country, run_date=day, from_currency=frm, to_currency=to, send_amount=amt,
                defaults=dict(reference_observation=ref, providers_expected=expected, providers_fresh=fresh,
                              status=status, best_observation=best,
                              programme_rank=prog_rank, published_at=now(),
                              last_success_at=now() if status == "complete" else (
                                  last_ok.published_at if last_ok else None)))
            for p, o, stale in items:
                rank = ranked.index(o) + 1 if o is not None and o in ranked else None
                FxComparisonItem.objects.update_or_create(run=run, provider=p, defaults=dict(
                    observation=o, stale=stale, rank=rank))
            payload = {"run_id": run.pk, "country": country.code, "pair": pair, "send_amount": amt,
                       "status": status, "run_date": day}
            if status == "complete":
                publish("fx_comparison.published", run.pk, payload)
            else:
                publish("fx.comparison_incomplete", run.pk, payload)
                alert_staff(country, ("CM", "AD"), "fx_comparison_incomplete",
                            f"Today's rate comparison for {pair} at {amt} is {status}. No screen says 'best rate' "
                            "until it is complete.", obj=run)
            runs.append(run)
    return runs


@transaction.atomic
def enter_observation(by, *, country, source_partner, kind, from_currency, to_currency, rate, proof_evidence,
                      send_amount=None, fees_total=None, delivered_amount=None, source_published_at=None):
    """A rate entered by hand when a source fails, with proof; it backs
    nothing until a second person checks it (FR-ESC-024, 6.17)."""
    if not has_role(by, "CM", "AD", country=country):
        raise Forbidden()
    if proof_evidence is None:
        raise Invalid("Attach a screenshot or the source's document.", code="validation-error")
    obs = FxRateObservation.objects.create(
        country=country, source_partner=source_partner, kind=kind, from_currency=from_currency.upper(),
        to_currency=to_currency.upper(), rate=Decimal(str(rate)), send_amount=send_amount, fees_total=fees_total,
        delivered_amount=delivered_amount, source_published_at=source_published_at or now(), method="manual",
        raw_sha256=proof_evidence.sha256, proof_evidence=proof_evidence, entered_by=by)
    audit(by, "fx_observation.entered", obs)
    return obs


@transaction.atomic
def check_observation(obs: FxRateObservation, by):
    if not has_role(by, "CM", "RV", "AD", country=obs.country):
        raise Forbidden()
    if obs.method != "manual" or obs.checked_by_id:
        raise StateConflict("Nothing to check.")
    if by.pk == obs.entered_by_id:
        raise Forbidden("A second person checks a rate entered by hand.", code="same-approver")
    obs.checked_by = by
    obs.save(update_fields=["checked_by"])
    audit(by, "fx_observation.checked", obs)
    return obs


def comparison_payload(run: FxComparisonRun) -> dict:
    items = []
    for it in run.items.select_related("observation", "provider").order_by("rank"):
        o = it.observation
        ref = run.reference_observation
        items.append({"provider": it.provider.name, "kind": o.kind if o else None, "stale": it.stale,
                      "rank": it.rank, "rate": str(o.rate) if o else None,
                      "margin_pct": str(margin_of(ref.rate, o.rate)) if (o and ref) else None,
                      "fees_total": f"{o.fees_total:.2f}" if o and o.fees_total is not None else None,
                      "delivered_amount": f"{o.delivered_amount:.2f}" if o and o.delivered_amount is not None else None,
                      "collected_at": o.collected_at.isoformat() if o else None,
                      "source_published_at": o.source_published_at.isoformat() if o and o.source_published_at else None,
                      "method": o.method if o else None})
    best = run.status == "complete" and run.programme_rank == 1
    return {"run_id": str(run.pk), "run_date": run.run_date.isoformat(), "pair": f"{run.from_currency}/"
            f"{run.to_currency}", "send_amount": f"{run.send_amount:.2f}", "status": run.status,
            "providers_expected": run.providers_expected, "providers_fresh": run.providers_fresh,
            "reference_rate": str(run.reference_observation.rate) if run.reference_observation else None,
            "last_success_at": run.last_success_at.isoformat() if run.last_success_at else None,
            "items": items, "bank_best_rate": best,
            "statement": "Best rate today among the providers compared." if best else
            ("" if run.status == "complete" else "Today's comparison is incomplete; no best rate is claimed.")}


def comparison_for(country, *, from_currency=None, amount=None, day=None) -> list[dict]:
    qs = FxComparisonRun.objects.filter(country=country, run_date=day or local_today(country))
    if from_currency:
        qs = qs.filter(from_currency=from_currency.upper())
    if amount:
        run = qs.filter(send_amount__lte=q(amount)).order_by("-send_amount").first()
        return [comparison_payload(run)] if run else []
    return [comparison_payload(r) for r in qs.order_by("from_currency", "send_amount")]


def quote_view(qt: FxQuote) -> dict:
    return json.loads(json.dumps({"id": str(qt.pk), "text": qt.shown_text, "sha256": qt.shown_sha256}))
