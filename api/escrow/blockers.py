"""esc.release_blockers() in Python (02 6.5). The database trigger in
dbsql.py checks the money rules a second time when an instruction is
approved or sent.

Every reason is {"rule", "code", "message"}. `stage` is one of:
- "prepare": the case manager prepares the instruction;
- "client":  the client approves;
- "staff":   a staff member with release rights approves;
- "send":    the dispatcher is about to send it to the bank.
"""
from decimal import Decimal

from django.utils import timezone

from . import registry, selectors
from .common import fmt, local_today, setting
from .models import (FRESH_SEARCH_KINDS, PAYEE_KIND_FOR_SUBJECT, BankEvent, Condition, Freeze, ReleaseInstruction,
                     StandingApproval)

RELEASE_KINDS = ("release", "partial_release")
CLIENT_APPROVAL_KINDS = ("release", "partial_release", "conversion")
STAFF_ROLES_EXCLUDED = ("CM", "RV", "AD", "RN")


def _r(rule, code, message, **extra):
    return {"rule": rule, "code": code, "message": message, **extra}


def fresh_search_reasons(e) -> list[dict]:
    """RUL-07: purchases only; counted from the registry result date and the site check date; day N counts."""
    if e.kind not in FRESH_SEARCH_KINDS:
        return []
    window = int(setting("fresh_search_window_days", e.country, 14))
    today = local_today(e.country)
    out = []
    if not e.fresh_search_case_id or e.fresh_search_result_date is None:
        out.append(_r("RUL-07", "fresh-search-missing", "No fresh official search is recorded for this purchase."))
    elif (today - e.fresh_search_result_date).days > window:
        out.append(_r("RUL-07", "fresh-search-stale",
                      f"The fresh search result dated {e.fresh_search_result_date:%d %B %Y} is outside the "
                      f"{window}-day window."))
    if e.site_check_date is None:
        out.append(_r("RUL-07", "site-check-missing", "No fresh site check is recorded for this purchase."))
    elif (today - e.site_check_date).days > window:
        out.append(_r("RUL-07", "site-check-stale",
                      f"The site check dated {e.site_check_date:%d %B %Y} is outside the {window}-day window."))
    return out


def open_condition_reasons(e, release_part="main") -> list[dict]:
    return [_r("RUL-06", "condition-open", f"Condition '{c.text}' is open", condition_id=str(c.pk))
            for c in Condition.objects.filter(escrow=e, status="open", release_part=release_part).order_by("created_at")]


def freeze_reasons(e) -> list[dict]:
    out = []
    for f in Freeze.objects.filter(escrow=e, lifted_at__isnull=True):
        rule = {"dispute": "RUL-15", "incident": "RUL-32", "reviewer_hold": "RUL-06"}[f.kind]
        label = {"dispute": "A dispute is open on this escrow",
                 "incident": "A failed re-check froze this escrow until the incident closes",
                 "reviewer_hold": "A reviewer has put this escrow on hold"}[f.kind]
        out.append(_r(rule, "escrow-frozen", f"{label}{': ' + f.reason if f.reason else ''}."))
    return out


def payee_reasons(ins, stage) -> list[dict]:
    """RUL-22, FR-ESC-015, RUL-28, RUL-31 for an instruction that pays a payee."""
    from accounts.selectors import is_relative_or_representative
    from accounts.services import national_id_blockers

    p, e = ins.payee, ins.escrow
    if p is None:
        return [_r("RUL-22", "payee-not-verified", "Every release names a verified payee.")]
    p.refresh_from_db()
    out = []
    if p.verification_status != "verified":
        out.append(_r("RUL-22", "payee-not-verified", f"The payee {p.legal_name} is not verified "
                                                      f"({p.verification_status})."))
    if p.name_match != "matched":
        out.append(_r("FR-ESC-015", "payee-not-verified",
                      f"The bank's account name '{p.account_name}' does not match the payee '{p.legal_name}'. "
                      "Nobody can override this; only new evidence clears it."))
    allowed = PAYEE_KIND_FOR_SUBJECT.get(ins.subject_type, set())
    if p.kind not in allowed:
        what = (ins.subject_type or "purchase release").replace("_", " ")
        out.append(_r("RUL-22", "payee-not-verified", f"A {p.kind.replace('_', ' ')} cannot be paid for a {what}."))
    client = e.client
    if p.person_id == client.pk or p.kind == "client_own_account":
        out.append(_r("RUL-22", "payee-not-verified", "A release never pays the client; refunds go to source."))
    elif is_relative_or_representative(client, person=p.person if p.person_id else None, name=p.legal_name,
                                       phone=p.contact_phone):
        out.append(_r("RUL-22", "payee-not-verified",
                      "The payee is a family member or representative of the client. Money never goes to a relative "
                      "or the client's representative."))
    if p.person_id and p.person.has_tenmina_role(*STAFF_ROLES_EXCLUDED):
        out.append(_r("RUL-22", "payee-not-verified", "Tenmina staff and runners are never paid from client money."))
    out.extend({**r, "code": "national-id-check-required"} for r in national_id_blockers(
        {f"Payee {p.legal_name}": p.national_id_check}))
    if ins.payee_account_version != p.account_version:
        out.append(_r("RUL-28", "payee-account-changed",
                      "The payee's account changed after this release was prepared. Prepare it again."))
    lock = selectors.live_lock(e, p)
    held_funds_first_payment = e.kind == "held_funds" and not e.locked_payees.filter(payee=p).exists()
    if lock is None and not (held_funds_first_payment and stage in ("prepare", "client")):
        if e.locked_payees.filter(payee=p).exists():
            msg = "The payee's account changed. The client has not approved the new account for this escrow."
        else:
            msg = "This payee is not one the client agreed for this escrow."
        out.append(_r("RUL-28", "payee-not-locked", msg))
    now = timezone.now()
    if p.cooling_off_until and p.cooling_off_until > now:
        out.append(_r("RUL-28", "payee-cooling-off",
                      f"The payee's account changed. Releases to it wait until "
                      f"{timezone.localtime(p.cooling_off_until):%d %B %Y %H:%M %Z}.",
                      ends_at=p.cooling_off_until.isoformat()))
    if lock is not None and lock.change_id and lock.change.kind == "new_payee" and lock.change.cooling_off_until \
            and lock.change.cooling_off_until > now:
        out.append(_r("RUL-28", "payee-cooling-off",
                      f"The new payee waits until "
                      f"{timezone.localtime(lock.change.cooling_off_until):%d %B %Y %H:%M %Z}.",
                      ends_at=lock.change.cooling_off_until.isoformat()))
    return out


def refund_reasons(ins) -> list[dict]:
    """RUL-29, FR-ESC-017: a refund goes to the source of the deposit it returns."""
    dep, e = ins.refund_source_event, ins.escrow
    out = []
    if dep is None or dep.escrow_id != e.pk or dep.kind != "deposit" or dep.status != "confirmed":
        return [_r("RUL-29", "refund-not-to-source", "A refund must name a bank-confirmed deposit of this escrow.")]
    if dep.misdirected:
        out.append(_r("RUL-34", "misdirected-deposit",
                      "This deposit was credited here by the bank's mistake. Only the bank's correcting entry moves "
                      "it; Tenmina never instructs a move between escrows."))
    others = ReleaseInstruction.objects.filter(refund_source_event=dep, status__in=[
        "awaiting_client", "pending_approval", "approved", "sent", "confirmed"]).exclude(pk=ins.pk)
    used = sum((i.amount for i in others), Decimal("0"))
    if ins.amount > dep.amount - used:
        out.append(_r("RUL-29", "refund-exceeds-deposit",
                      f"The refund is larger than what is left of the deposit ({fmt(dep.amount - used, dep.currency)})."))
    needs_exception = not dep.source_account_known or dep.source_cannot_receive
    if needs_exception:
        ch = ins.refund_change
        if ch is None or ch.status != "applied" or ch.deposit_event_id != dep.pk:
            why = "the bank gave no source account" if not dep.source_account_known else \
                "the source account cannot receive the refund"
            out.append(_r("RUL-29", "refund-exception-required",
                          f"This deposit cannot go back to source because {why}. The RUL-29 exception path "
                          "(an account in the client's own name, a fresh identity check, the client's approval, two "
                          "staff approvals and the cooling-off) must be completed first."))
        elif ch.cooling_off_until and ch.cooling_off_until > timezone.now():
            out.append(_r("RUL-28", "payee-cooling-off",
                          f"The refund account waits until {timezone.localtime(ch.cooling_off_until):%d %B %Y %H:%M}.",
                          ends_at=ch.cooling_off_until.isoformat()))
    elif ins.refund_change_id:
        out.append(_r("RUL-29", "refund-not-to-source",
                      "This deposit's source account can receive the refund; it goes there."))
    if ins.currency != dep.currency:
        q = ins.fx_quote
        if q is None or q.purpose != "refund_conversion" or q.accepted_at is None:
            out.append(_r("RUL-35", "fx-quote-required",
                          "A refund that converts needs a quote the client has accepted."))
    return out


def conversion_reasons(ins) -> list[dict]:
    q, e = ins.fx_quote, ins.escrow
    out = []
    if q is None or q.escrow_id != e.pk or q.from_currency != ins.currency or q.to_currency != ins.to_currency \
            or q.from_amount != ins.amount or q.purpose not in ("release_conversion", "deposit"):
        out.append(_r("RUL-35", "fx-quote-required", "The conversion must name the client's quote for this amount."))
    elif q.accepted_at is None:
        out.append(_r("RUL-35", "fx-quote-not-accepted", "The client has not accepted the quote."))
    if ins.to_currency not in {c for c, _ in selectors.currencies(e)}:
        out.append(_r("RUL-34", "fx-account-missing", "The escrow has no virtual account in the target currency."))
    return out


def funds_reasons(ins, stage) -> list[dict]:
    e = ins.escrow
    out = []
    if e.programme_account_id is None or not e.virtual_account_ref:
        out.append(_r("RUL-34", "virtual-account-missing", "The escrow has no virtual account at the bank yet."))
        return out
    avail = selectors.available_to_instruct(e, ins.currency, exclude=ins)
    if ins.amount > avail:
        short = ins.amount - max(avail, Decimal("0"))
        reason = _r("RUL-34", "held-funds-insufficient",
                    f"The bank has confirmed {fmt(max(avail, 0), ins.currency)} available for this escrow; this "
                    f"instruction needs {fmt(ins.amount, ins.currency)}. Short by {fmt(short, ins.currency)}.",
                    shortfall={"amount": f"{short:.2f}", "currency": ins.currency})
        foreign = [c for c, _ in selectors.currencies(e) if c != ins.currency and selectors.held_at_bank(e, c) > 0]
        if ins.kind in RELEASE_KINDS and foreign:
            reason["rule"] = "RUL-36"
            reason["message"] += " Money held in another currency must be converted first, or topped up."
        out.append(reason)
    for cur, _ref in selectors.currencies(e):
        pos = selectors.latest_position(e, cur)
        if pos is not None and pos.status == "mismatch":
            out.append(_r("RUL-34", "bank-position-mismatch",
                          f"The bank's figure for {cur} on {pos.as_of:%d %B %Y} differs from the confirmed events. "
                          "A reviewer must resolve it with the bank's written explanation."))
    return out


def standing_approval_covers(ins) -> StandingApproval | None:
    sa = ins.standing_approval
    if sa is None or sa.status != "active" or sa.escrow_id != ins.escrow_id or sa.currency != ins.currency:
        return None
    today = timezone.now()
    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    used = ReleaseInstruction.objects.filter(standing_approval=sa, created_at__gte=month_start, status__in=[
        "pending_approval", "approved", "sent", "confirmed"]).exclude(pk=ins.pk)
    total = sum((i.amount for i in used), Decimal("0")) + ins.amount
    return sa if total <= sa.monthly_max else None


def release_blockers(ins: ReleaseInstruction, stage: str = "send") -> list[dict]:
    from administration import flags

    e = ins.escrow
    e.refresh_from_db()
    out = []
    if flags.instructions_paused():
        out.append(_r("ADM-KILL", "instructions-paused",
                      "Release instructions are paused by an administrator. Nothing is sent until they resume."))
    if e.status in ("proposed", "agreed", "cancelled", "released"):
        out.append(_r("RUL-34", "escrow-not-funded" if e.status in ("proposed", "agreed") else "escrow-closed",
                      f"The escrow is {e.status.replace('_', ' ')}."))
    out.extend(freeze_reasons(e))
    if e.cancel_requested_at and ins.kind != "cancel_refund":
        out.append(_r("FR-ESC-013", "escrow-cancelling", "This escrow is being cancelled. Only refunds go out."))
    if ins.kind in RELEASE_KINDS:
        out.extend(open_condition_reasons(e, ins.release_part))
        if ins.release_part == "held_back" and not ReleaseInstruction.objects.filter(
                escrow=e, release_part="main", kind="release", status="confirmed").exists():
            out.append(_r("RUL-33", "main-release-first", "The held-back share follows the confirmed main release."))
        out.extend(fresh_search_reasons(e))
        out.extend(payee_reasons(ins, stage))
    if ins.kind == "cancel_refund":
        out.extend(refund_reasons(ins))
    if ins.kind == "conversion":
        out.extend(conversion_reasons(ins))
    out.extend(funds_reasons(ins, stage))
    if ins.subject_type:
        out.extend(registry.run_checks(ins))
    if stage in ("staff", "send") and ins.kind in CLIENT_APPROVAL_KINDS:
        if ins.client_approved_at is None and standing_approval_covers(ins) is None:
            out.append(_r("RUL-11", "client-approval-missing",
                          "The client has not approved this release. Silence is never approval."))
        elif ins.client_approved_at and ins.client_approved_amount is not None \
                and ins.client_approved_amount != ins.amount:
            out.append(_r("RUL-11", "client-approval-stale", "The amount changed after the client approved."))
    if stage == "send" and (ins.approval_request is None or ins.approval_request.status != "approved"):
        out.append(_r("RUL-05", "staff-approvals-missing", "Two staff with release rights have not both approved."))
    return out


def raise_if_blocked(ins, stage, what="This release"):
    from core.errors import RuleBlocked

    reasons = release_blockers(ins, stage)
    if not reasons:
        return
    codes = {r["code"] for r in reasons}
    code = "release-blocked"
    if codes == {"held-funds-insufficient"}:
        code = "held-funds-insufficient"
    elif codes == {"payee-not-verified"}:
        code = "payee-not-verified"
    raise RuleBlocked(f"{what} is blocked: " + "; ".join(r["message"] for r in reasons[:3])
                      + (" ..." if len(reasons) > 3 else ""), code=code, blocking_reasons=reasons)


def deposit_of(ev_id) -> BankEvent | None:
    return BankEvent.objects.filter(pk=ev_id, kind="deposit").first()
