"""The client's one Tenmina account per country (decision 2026-11-17;
FR-ESC-025 to FR-ESC-028, RUL-34).

The client sees one account at the licensed bank, with one set of pay-in
details and one balance per currency. Underneath, nothing changed in how the
money is kept apart:

- the account's **free balance** is its `held_funds` escrow in each currency.
  Every deposit lands there; school fees, care visits, errands and premiums
  are released from it to a verified payee (client first, then two staff);
- every other escrow is a **commitment** of the account: money set aside for
  one deal (a purchase, a build, an off-plan stage plan, a project fund, an
  event or a repair), with its own parties, conditions, locked payees, freezes
  and the bank's own sub-ledger for it. A release from a commitment can only
  use that commitment's own bank-confirmed money (RUL-34) and only pays a payee
  locked on it (RUL-28);
- moving free balance into a commitment is an instruction to the bank
  (`commitment_fund`). It pays nobody, so no staff approve it; the client
  approves it with their second factor, and the commitment counts as funded
  only when the bank confirms the move (`commitment_debit` on the free balance
  and `commitment_credit` on the commitment, from one bank confirmation);
- a cancelled commitment's money goes back to the source account of the
  client's deposits (RUL-29), unless the client chooses to keep it in the
  account (`commitment_return`, again with their second factor).

Balances are never stored: each line's figure is derived from bank-confirmed
events (ADR-18, ADR-26), and the account's figure is the sum of its lines.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from core import approvals, state  # noqa: F401 - approvals kept for symmetry with services
from core.errors import Forbidden, Invalid, NotFound, StateConflict
from core.ids import uuid7
from core.money import q
from core.permissions import has_role

from . import selectors
from .common import audit, fmt, local_date, notify, now, working_day_on_or_after
from .models import LIVE_INSTRUCTION, OPEN_STATUSES, BankEvent, ClientAccount, Escrow, \
    ReleaseInstruction

ZERO = Decimal("0.00")


# ----------------------------------------------------------------- the account

def _reference(country) -> str:
    import secrets

    from django.utils import timezone

    return f"ACC-{country.code}-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}"


def account_for(client, country) -> ClientAccount | None:
    code = getattr(country, "code", country)
    return ClientAccount.objects.filter(client=client, country__code=code).select_related("country").first()


def ensure_account(client, country, *, by, bank_partner) -> ClientAccount:
    """The client's account in this country, opened the first time money is
    held for them. One per client per country (FR-ESC-025)."""
    acc = account_for(client, country)
    if acc is not None:
        return acc
    acc, _ = ClientAccount.objects.get_or_create(
        client=client, country=country,
        defaults={"reference": _reference(country), "bank_partner": bank_partner, "created_by": by})
    audit(by, "account.opened", acc, {"client_id": str(client.pk)})
    return acc


def open_account(client, country, *, by, currency=None) -> ClientAccount:
    """POST /v1/account: the account and its free balance in the country's
    currency (or `currency`), so the bank's pay-in details can be shown."""
    from .services import open_held_funds

    if by.pk != client.pk and not has_role(by, "CM", "RV", country=country):
        raise Forbidden("A client opens their own account; otherwise a case manager does.")
    line = open_held_funds(client, country, currency or country.currency, by=by)
    return line.account


def free_line(acc: ClientAccount, currency) -> Escrow | None:
    return Escrow.objects.filter(account=acc, kind="held_funds", currency=str(currency).upper(),
                                 status__in=OPEN_STATUSES).first()


def free_lines(acc: ClientAccount):
    return Escrow.objects.filter(account=acc, kind="held_funds").exclude(status="cancelled").order_by("created_at")


def commitments(acc: ClientAccount, include_closed=True):
    qs = Escrow.objects.filter(account=acc).exclude(kind="held_funds").order_by("-created_at")
    return qs if include_closed else qs.filter(status__in=OPEN_STATUSES)


# ----------------------------------------------------------------- figures (derived, never stored)

def _sum(qs) -> Decimal:
    return qs.aggregate(s=Sum("amount"))["s"] or ZERO


def incoming(e: Escrow, currency=None, exclude=None) -> Decimal:
    """Money the client has asked the bank to move into this line, not yet confirmed."""
    qs = ReleaseInstruction.objects.filter(to_escrow=e, currency=(currency or e.currency).upper(),
                                           status__in=LIVE_INSTRUCTION)
    if exclude is not None:
        qs = qs.exclude(pk=getattr(exclude, "pk", exclude))
    return _sum(qs)


def set_aside(e: Escrow, currency=None) -> Decimal:
    """What the bank holds for this commitment now (held at the bank)."""
    return selectors.held_at_bank(e, currency)


def still_to_set_aside(e: Escrow, exclude=None) -> Decimal:
    """The agreed amount less what is held, already paid out, or on its way in."""
    if not e.is_commitment or e.status in ("cancelled", "released"):
        return ZERO
    paid = selectors.released_total(e)
    left = e.agreed_amount - selectors.held_at_bank(e) - paid - incoming(e, exclude=exclude)
    return max(left, ZERO)


def _money(amount, currency):
    return {"amount": f"{q(amount or 0):.2f}", "currency": currency}


def pay_in_details(acc: ClientAccount, currency=None) -> dict:
    """FR-ESC-003, RUL-01: one set of pay-in details for the whole account: the bank's programme account for each
    currency the account holds, and the client's one reference. Never a Tenmina account."""
    lines = []
    for line in free_lines(acc).select_related("programme_account", "programme_account__bank_partner"):
        if line.status == "proposed" or not line.virtual_account_ref or line.programme_account_id is None:
            continue
        pa = line.programme_account
        lines.append({"currency": line.currency, "account_name": pa.account_name, "account_number": pa.account_number,
                      "virtual_account_ref": line.virtual_account_ref, "line_id": str(line.pk)})
        for fx in line.fx_accounts.filter(closed_at__isnull=True).select_related("programme_account") \
                .order_by("currency"):
            lines.append({"currency": fx.currency, "account_name": fx.programme_account.account_name,
                          "account_number": fx.programme_account.account_number,
                          "virtual_account_ref": fx.virtual_account_ref, "line_id": str(line.pk)})
    if not lines:
        pending = free_lines(acc).filter(status="proposed").exists()
        return {"available": False, "account_reference": acc.reference, "lines": [], "foreign_currency_accounts": [],
                "message": "Accept the account terms to see the bank's pay-in details." if pending else
                "The bank's pay-in details appear once your account is open at the bank."}
    cur = (currency or acc.country.currency).upper()
    main = next((x for x in lines if x["currency"] == cur), lines[0])
    bank = acc.bank_partner
    return {"available": True, "bank_name": main_bank_name(acc),
            "account_name": main["account_name"], "account_number": main["account_number"],
            "virtual_account_ref": acc.virtual_account_ref or main["virtual_account_ref"],
            "reference": acc.virtual_account_ref or main["virtual_account_ref"], "account_reference": acc.reference,
            "currency": main["currency"], "lines": lines,
            "note": "Pay the bank, never Tenmina. Use your reference so the bank credits your Tenmina account. "
                    "Everything is paid from this one account.",
            "foreign_currency_accounts": [x for x in lines if x is not main]}


def main_bank_name(acc: ClientAccount) -> str:
    line = free_lines(acc).filter(programme_account__isnull=False).select_related("programme_account__bank_partner") \
        .first()
    bank = line.programme_account.bank_partner if line else acc.bank_partner
    return bank.bank_name or bank.name


def commitment_summary(e: Escrow) -> dict:
    """One commitment inside the account: what is set aside, paid out, still to set aside, and its state."""
    from .services import RELEASABLE

    held = selectors.held_at_bank(e)
    live_out = selectors.awaiting_bank(e)
    pos = selectors.latest_position(e, e.currency)
    payees = sorted({p.payee.legal_name for p in e.parties.filter(payee__isnull=False).select_related("payee")})
    waiting = ReleaseInstruction.objects.filter(escrow=e, status="awaiting_client").exists()
    return {
        "id": str(e.pk), "reference": e.reference, "kind": e.kind, "title": e.title, "status": e.status,
        "currency": e.currency, "agreed": _money(e.agreed_amount, e.currency),
        "set_aside": _money(held, e.currency), "paid_out": _money(selectors.released_total(e), e.currency),
        "on_its_way_in": _money(incoming(e), e.currency), "instructed_awaiting_bank": _money(live_out, e.currency),
        "still_to_set_aside": _money(still_to_set_aside(e), e.currency),
        "available_to_instruct": _money(selectors.available_to_instruct(e), e.currency),
        "payees": payees, "frozen": e.status == "frozen", "cancelling": bool(e.cancel_requested_at),
        "can_keep_in_account": bool(e.cancel_requested_at) and selectors.available_to_instruct(e) > 0,
        "can_fund": e.status in ("agreed", *RELEASABLE, "frozen") and not e.cancel_requested_at
        and still_to_set_aside(e) > 0,
        "needs_you": waiting, "bank_sub_ledger_ref": e.virtual_account_ref,
        "bank_position": None if pos is None else {"as_of": pos.as_of.isoformat(),
                                                   "reported": _money(pos.reported_held_amount, e.currency),
                                                   "status": pos.status},
        "link": f"/commitments/{e.pk}", "created_at": e.created_at.isoformat(),
    }


def balances(acc: ClientAccount) -> list[dict]:
    """One line per currency: everything held at the bank for the client, the free balance and what is set aside."""
    cur_map: dict[str, dict] = {}

    def row(cur):
        return cur_map.setdefault(cur, {"currency": cur, "held": ZERO, "free": ZERO, "free_held": ZERO,
                                        "set_aside": ZERO, "awaiting_bank": ZERO, "reported": ZERO,
                                        "reported_lines": 0, "lines": 0, "mismatch": False})

    for line in Escrow.objects.filter(account=acc).exclude(status__in=("proposed", "cancelled")):
        for cur, _ref in selectors.currencies(line):
            held = selectors.held_at_bank(line, cur)
            r = row(cur)
            r["held"] += held
            r["lines"] += 1
            if line.kind == "held_funds":
                r["free_held"] += held
                r["free"] += selectors.available_to_instruct(line, cur)
                r["awaiting_bank"] += selectors.awaiting_bank(line, cur)
            else:
                r["set_aside"] += held
            pos = selectors.latest_position(line, cur)
            if pos is not None:
                r["reported"] += pos.reported_held_amount
                r["reported_lines"] += 1
                r["mismatch"] = r["mismatch"] or pos.status == "mismatch"
    if not cur_map:
        row(acc.country.currency)
    out = []
    for cur, r in sorted(cur_map.items(), key=lambda x: (x[0] != acc.country.currency, x[0])):
        out.append({"currency": cur, "held_at_bank": _money(r["held"], cur), "free_balance": _money(r["free"], cur),
                    "set_aside": _money(r["set_aside"], cur), "instructed_awaiting_bank": _money(r["awaiting_bank"], cur),
                    "bank_position": {"reported": _money(r["reported"], cur), "lines_reported": r["reported_lines"],
                                      "lines": r["lines"], "complete": r["reported_lines"] == r["lines"] > 0,
                                      "mismatch": r["mismatch"]}})
    return out


def summary(acc: ClientAccount, *, include_closed=False) -> dict:
    lines = [{"id": str(x.pk), "reference": x.reference, "currency": x.currency, "status": x.status,
              "virtual_account_ref": x.virtual_account_ref, "held_at_bank": _money(selectors.held_at_bank(x), x.currency),
              "available_to_instruct": _money(selectors.available_to_instruct(x), x.currency)}
             for x in free_lines(acc)]
    return {"id": str(acc.pk), "reference": acc.reference, "country": acc.country.code, "status": acc.status,
            "client": str(acc.client_id), "client_name": acc.client.full_name, "bank_name": acc.bank_partner.name,
            "seal": "Held at the bank · Released on proof", "opened_at": acc.opened_at.isoformat(),
            "pay_in": pay_in_details(acc), "balances": balances(acc), "free_balance_lines": lines,
            "commitments": [commitment_summary(e) for e in commitments(acc, include_closed=True)
                            if include_closed or e.status not in ("cancelled", "released")
                            or selectors.held_at_bank(e) > 0],
            "closed_commitments": commitments(acc).filter(status__in=("cancelled", "released")).count()}


# ----------------------------------------------------------------- moving money inside the account (FR-ESC-027)

def _approve_transfer(ins: ReleaseInstruction, client, method, at):
    from .blockers import raise_if_blocked

    ins.client_approved_at, ins.client_approved_by, ins.client_approval_method = at, client, method
    ins.client_approved_amount = ins.amount
    raise_if_blocked(ins, "send", "This move")
    ins.last_approval_at = at
    ins.send_due_on = working_day_on_or_after(ins.country, local_date(ins.country, at))
    from .services import _client_payload

    state.transition(ins, "release_instruction", "approved", actor=client, event="release.approved",
                     extra_fields=["client_approved_at", "client_approved_by", "client_approval_method",
                                   "client_approved_amount", "last_approval_at", "send_due_on"],
                     payload=_client_payload(ins, transfer=True))
    return ins


def _new_transfer(kind, src: Escrow, dst: Escrow, *, amount, by, label) -> ReleaseInstruction:
    from .blockers import raise_if_blocked

    ins = ReleaseInstruction(id=uuid7(), country=src.country, escrow=src, to_escrow=dst, kind=kind, amount=q(amount),
                             currency=dst.currency if kind == "commitment_fund" else src.currency, prepared_by=by,
                             reason=label, subject_label=label, status="awaiting_client", clock_started_at=now())
    raise_if_blocked(ins, "prepare", "This move")
    ins.save(force_insert=True)
    return ins


@transaction.atomic
def fund_commitment(e: Escrow, client, *, amount=None, mfa_at=None, code=None) -> ReleaseInstruction:
    """FR-ESC-027: set money aside for a commitment from the account's free balance. The client approves with their
    second factor; no staff approve it because it pays nobody. The instruction goes to the bank at once; the
    commitment counts as funded only when the bank confirms the move."""
    from .payees import _client_signed
    from .services import _on

    _on(e.country)
    if e.client_id != client.pk:
        raise NotFound()
    if not e.is_commitment:
        raise Invalid("Choose a commitment to set money aside for.", code="validation-error")
    method = _client_signed(client, mfa_at, code)
    src = free_line(e.account, e.currency)
    if src is None:
        raise StateConflict(f"Your account holds no {e.currency} yet. Pay into your account first.",
                            code="free-balance-missing")
    amt = q(amount) if amount not in (None, "") else min(still_to_set_aside(e), selectors.available_to_instruct(src))
    if amt <= 0:
        raise Invalid("Enter the amount to set aside.", code="validation-error")
    ins = _new_transfer("commitment_fund", src, e, amount=amt, by=client, label=f"Set aside for {e.title}")
    _approve_transfer(ins, client, method, now())
    audit(client, "commitment.fund_requested", ins, {"commitment_id": str(e.pk), "amount": f"{amt:.2f}"})
    notify(client, "commitment_fund_requested",
           f"We asked the bank to set aside {fmt(amt, ins.currency)} for {e.title}. It counts once the bank "
           "confirms it.", obj=ins, link=f"/commitments/{e.pk}", category="money")
    return ins


@transaction.atomic
def keep_in_account(e: Escrow, client, *, mfa_at=None, code=None) -> ReleaseInstruction:
    """FR-ESC-028: a cancelled commitment's money goes back to the source account of the client's deposits
    (RUL-29) unless the client chooses to keep it in the account. Only the client can choose; refunds not yet
    sent are withdrawn and the money moves back to the free balance when the bank confirms it."""
    from .payees import _client_signed
    from .services import _on, withdraw_instruction

    _on(e.country)
    if e.client_id != client.pk:
        raise NotFound()
    if not e.is_commitment or not e.cancel_requested_at:
        raise StateConflict("Money set aside goes back to your free balance only when the commitment is cancelled.",
                            code="commitment-not-cancelled")
    method = _client_signed(client, mfa_at, code)
    dst = free_line(e.account, e.currency)
    if dst is None:
        raise StateConflict(f"Your account has no {e.currency} balance to keep it in.", code="free-balance-missing")
    for ins in ReleaseInstruction.objects.filter(escrow=e, kind="cancel_refund",
                                                 status__in=("awaiting_client", "pending_approval")):
        withdraw_instruction(ins, client, reason="The client chose to keep the money in their account", system=True)
    if ReleaseInstruction.objects.filter(escrow=e, kind="cancel_refund", status__in=("approved", "sent")).exists():
        raise StateConflict("A refund to your bank is already approved and on its way.", code="refund-in-progress")
    amt = selectors.available_to_instruct(e)
    if amt <= 0:
        raise StateConflict("Nothing set aside is left to keep.")
    ins = _new_transfer("commitment_return", e, dst, amount=amt, by=client,
                        label=f"Back to your free balance from {e.title}")
    _approve_transfer(ins, client, method, now())
    audit(client, "commitment.kept_in_account", ins, {"commitment_id": str(e.pk), "amount": f"{amt:.2f}"})
    return ins


def on_transfer_debit(ev: BankEvent):
    """The bank confirmed a move inside the account. One confirmation gives both legs: the debit on the line the
    money left (`ev`) and the credit on the line it reached, under that line's own sub-ledger (RUL-34)."""
    from .services import _close_if_empty, _escrow_payload, _parties_to_tell, dispatch, sync_status

    ins = ev.instruction
    dst = ins.to_escrow
    ref = dst.virtual_account_ref if ins.currency == dst.currency else \
        dst.fx_accounts.filter(currency=ins.currency).values_list("virtual_account_ref", flat=True).first()
    pa = dst.programme_account if ins.currency == dst.currency else \
        dst.fx_accounts.filter(currency=ins.currency).first().programme_account
    credit = BankEvent.objects.filter(escrow=dst, kind="commitment_credit", bank_reference=ev.bank_reference) \
        .exclude(status="rejected").first()
    if credit is None:
        credit = BankEvent.objects.create(
            country=dst.country, escrow=dst, kind="commitment_credit", amount=ev.amount, currency=ev.currency,
            occurred_at=ev.occurred_at, bank_reference=ev.bank_reference, programme_account=pa,
            virtual_account_ref=ref, source=ev.source, status="confirmed", proof_evidence=ev.proof_evidence,
            entered_by=ev.entered_by, checked_by=ev.checked_by, checked_at=ev.checked_at, instruction=ins,
            statement_line=ev.statement_line, note=f"Moved from {ins.escrow.reference}")
    ins.bank_confirmation_event = ev
    from .services import _client_payload

    state.transition(ins, "release_instruction", "confirmed", event="commitment.transfer_confirmed",
                     extra_fields=["bank_confirmation_event"],
                     payload=_client_payload(ins, bank_reference=ev.bank_reference, bank_event_id=ev.pk,
                                             to_escrow_id=dst.pk))
    audit(None, "commitment.transfer_confirmed", ins, {"debit": str(ev.pk), "credit": str(credit.pk)})
    dst.refresh_from_db()
    if dst.status == "agreed":
        dst.funded_at = now()
        dst.save(update_fields=["funded_at"])
        state.transition(dst, "escrow", "funded", event="escrow.funded", extra_fields=["funded_at"],
                         payload=_escrow_payload(dst, amount=ev.amount, currency=ev.currency, bank_event_id=credit.pk))
    if dst.is_commitment:
        for person in _parties_to_tell(dst):
            notify(person, "commitment_funded",
                   f"The bank confirmed {fmt(ev.amount, ev.currency)} set aside for {dst.title}. It is held for this "
                   "deal only and released only on proof.", obj=dst, link=f"/commitments/{dst.pk}",
                   category="money")
    else:
        from core.events import publish

        notify(dst.client, "commitment_returned",
               f"{fmt(ev.amount, ev.currency)} from {ins.escrow.title} is back in your account's free balance.",
               obj=dst, link="/tenmina-account", category="money")
        publish("held_funds.deposit_confirmed", dst.pk, _escrow_payload(
            dst, amount=ev.amount, currency=ev.currency, bank_event_id=credit.pk,
            label=f"Moved back from {ins.escrow.reference}"))
    for waiting in ReleaseInstruction.objects.filter(escrow=dst, status="approved", shortfall_since__isnull=False):
        dispatch(waiting)
    sync_status(dst)
    src = ins.escrow
    src.refresh_from_db()
    if src.is_commitment and src.cancel_requested_at:
        _close_if_empty(src, "cancelled")


def transfer_reasons(ins) -> list[dict]:
    """The rules for a move inside the account (FR-ESC-027, FR-ESC-028)."""
    def r(rule, code, message):
        return {"rule": rule, "code": code, "message": message}

    src, dst = ins.escrow, ins.to_escrow
    if dst is None or src.account_id != dst.account_id or src.client_id != dst.client_id:
        return [r("RUL-34", "transfer-other-account", "Money moves only between the lines of one client's account.")]
    out = []
    if ins.kind == "commitment_fund":
        if src.is_commitment or not dst.is_commitment:
            return [r("FR-ESC-027", "transfer-shape", "Money is set aside from the free balance into a commitment.")]
        if dst.status == "proposed":
            out.append(r("FR-ESC-027", "commitment-not-agreed", f"The terms of {dst.title} are not agreed yet."))
        elif dst.status in ("cancelled", "released") or dst.cancel_requested_at:
            out.append(r("FR-ESC-027", "commitment-closed", f"{dst.title} is closed or being cancelled."))
        if ins.currency != dst.currency:
            out.append(r("RUL-35", "transfer-currency", f"{dst.title} is in {dst.currency}."))
        left = still_to_set_aside(dst, exclude=ins)
        if dst.status not in ("proposed", "cancelled", "released") and ins.amount > left:
            out.append(r("FR-ESC-027", "commitment-overfunded",
                         f"Only {fmt(left, dst.currency)} is still to set aside for {dst.title}."))
    else:
        if not src.is_commitment or dst.is_commitment:
            return [r("FR-ESC-028", "transfer-shape", "Money goes back from a commitment to the free balance only.")]
        if not src.cancel_requested_at:
            out.append(r("FR-ESC-028", "commitment-not-cancelled",
                         "Money set aside goes back to the free balance only when the commitment is cancelled."))
        if dst.status in ("proposed", "cancelled", "released"):
            out.append(r("FR-ESC-028", "free-balance-closed", "Your account's free balance is not open."))
        if ins.currency != dst.currency:
            out.append(r("RUL-35", "transfer-currency", f"The free balance line is in {dst.currency}."))
    if dst.programme_account_id is None or not dst.virtual_account_ref:
        out.append(r("RUL-34", "virtual-account-missing", "The bank has not opened this line yet."))
    return out


def accounts_visible_to(user):
    from accounts.selectors import staff_country_codes

    codes = staff_country_codes(user)
    if codes is None:
        return ClientAccount.objects.all()
    if codes:
        return ClientAccount.objects.filter(country__code__in=codes)
    return ClientAccount.objects.filter(client=user)
