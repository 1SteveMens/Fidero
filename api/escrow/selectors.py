"""ESC read-only queries other modules may use.

Held funds are DERIVED, never stored (ADR-03, ADR-18, ADR-26): "held at the
bank" is bank-confirmed money in less bank-confirmed money out, per escrow
and currency, from `esc_bank_event` rows matched by virtual account. The SQL
twin is the view `esc_confirmed_funds` (dbsql.py), which the database
triggers use.

- held_funds_for(client, country, currency)  the client's open held amount, or None
- confirmed_funds(escrow)                    [{currency, virtual_account_ref, held_at_bank, ...}]
- held_at_bank(escrow, currency)             Decimal
- available_to_instruct(escrow, currency)    held_at_bank less live instructions and money awaiting correction
- statement(escrow, family_member_id=None)   the running statement (FR-ESC-014, FR-FEE-007)
- instruction(pk), escrow(pk)
- escrows_paying(payee)                      open escrows locked on a payee
"""
from decimal import Decimal

from django.db.models import Q, Sum

from .models import (LIVE_INSTRUCTION, OPEN_STATUSES, BankEvent, BankPosition, Escrow, EscrowPayee, FxAccount,
                     ReleaseInstruction)

ZERO = Decimal("0.00")
IN_KINDS = ("deposit", "conversion_credit")
OUT_KINDS = ("release_confirmed", "refund_confirmed", "conversion_debit", "correction_debit")


def escrow(pk) -> Escrow | None:
    return Escrow.objects.filter(pk=pk).first()


def instruction(pk) -> ReleaseInstruction | None:
    return ReleaseInstruction.objects.filter(pk=pk).first()


def held_funds_for(client, country, currency) -> Escrow | None:
    code = getattr(country, "code", country)
    return Escrow.objects.filter(kind="held_funds", client=client, country__code=code, currency=currency.upper(),
                                 status__in=OPEN_STATUSES).first()


def currencies(e: Escrow) -> list[tuple[str, str | None]]:
    """(currency, virtual_account_ref) for the escrow's own account and its foreign currency ones."""
    out = [(e.currency, e.virtual_account_ref)]
    for fx in FxAccount.objects.filter(escrow=e).order_by("currency"):
        out.append((fx.currency, fx.virtual_account_ref))
    return out


def _sum(qs) -> Decimal:
    return qs.aggregate(s=Sum("amount"))["s"] or ZERO


def held_at_bank(e: Escrow, currency: str | None = None) -> Decimal:
    cur = (currency or e.currency).upper()
    qs = BankEvent.objects.filter(escrow=e, currency=cur, status="confirmed")
    return _sum(qs.filter(kind__in=IN_KINDS)) - _sum(qs.filter(kind__in=OUT_KINDS))


def awaiting_bank(e: Escrow, currency: str | None = None, exclude=None) -> Decimal:
    cur = (currency or e.currency).upper()
    qs = ReleaseInstruction.objects.filter(escrow=e, currency=cur, status__in=LIVE_INSTRUCTION)
    if exclude is not None:
        qs = qs.exclude(pk=getattr(exclude, "pk", exclude))
    return _sum(qs)


def awaiting_correction(e: Escrow, currency: str | None = None) -> Decimal:
    """RUL-34, I-43: a deposit the bank credited here by mistake cannot be
    released; only the bank's correcting entry changes it."""
    cur = (currency or e.currency).upper()
    corrected = _sum(BankEvent.objects.filter(escrow=e, currency=cur, status="confirmed", kind="correction_debit"))
    flagged = _sum(BankEvent.objects.filter(escrow=e, currency=cur, status="confirmed", kind="deposit",
                                            misdirected=True))
    return max(flagged - corrected, ZERO)


def available_to_instruct(e: Escrow, currency: str | None = None, exclude=None) -> Decimal:
    return held_at_bank(e, currency) - awaiting_bank(e, currency, exclude) - awaiting_correction(e, currency)


def latest_position(e: Escrow, currency: str):
    return BankPosition.objects.filter(escrow=e, currency=currency).exclude(status="pending_check") \
        .order_by("-as_of", "-created_at").first()


def confirmed_funds(e: Escrow) -> list[dict]:
    out = []
    for cur, ref in currencies(e):
        pos = latest_position(e, cur)
        last = BankEvent.objects.filter(escrow=e, currency=cur, status="confirmed").order_by("-occurred_at").first()
        out.append({
            "currency": cur, "virtual_account_ref": ref,
            "programme_account_id": str(e.programme_account_id) if e.programme_account_id else None,
            "held_at_bank": held_at_bank(e, cur), "instructed_awaiting_bank": awaiting_bank(e, cur),
            "awaiting_correction": awaiting_correction(e, cur), "available_to_instruct": available_to_instruct(e, cur),
            "last_bank_event_at": last.occurred_at if last else None,
            "latest_bank_figure": None if pos is None else {
                "as_of": pos.as_of, "reported_held_amount": pos.reported_held_amount, "status": pos.status},
        })
    return out


def statement(e: Escrow, family_member_id=None) -> dict:
    """The running statement: bank events and instructions in time order.
    Only bank-confirmed events change "held at the bank" (FR-ESC-014)."""
    rows = []
    for ev in BankEvent.objects.filter(escrow=e).exclude(status="rejected").select_related("instruction") \
            .order_by("occurred_at", "created_at"):
        ins = ev.instruction
        if family_member_id and (ins is None or str(ins.family_member_id) != str(family_member_id)):
            if ev.kind != "deposit":
                continue
        sign = 1 if ev.kind in IN_KINDS else -1
        rows.append({"at": ev.occurred_at, "type": "bank_event", "kind": ev.kind, "id": str(ev.pk),
                     "amount": ev.amount * sign, "currency": ev.currency, "bank_reference": ev.bank_reference,
                     "status": ev.status, "counts": ev.status == "confirmed",
                     "subject_type": ins.subject_type if ins else None,
                     "subject_id": str(ins.subject_id) if ins and ins.subject_id else None,
                     "subject_label": ins.subject_label if ins else "",
                     "family_member_id": str(ins.family_member_id) if ins and ins.family_member_id else None,
                     "payee": ins.payee.legal_name if ins and ins.payee_id else None})
    for ins in ReleaseInstruction.objects.filter(escrow=e, status__in=LIVE_INSTRUCTION).select_related("payee"):
        if family_member_id and str(ins.family_member_id) != str(family_member_id):
            continue
        rows.append({"at": ins.created_at, "type": "instruction", "kind": ins.kind, "id": str(ins.pk),
                     "amount": -ins.amount, "currency": ins.currency, "bank_reference": "", "status": ins.status,
                     "counts": False, "subject_type": ins.subject_type,
                     "subject_id": str(ins.subject_id) if ins.subject_id else None,
                     "subject_label": ins.subject_label,
                     "family_member_id": str(ins.family_member_id) if ins.family_member_id else None,
                     "payee": ins.payee.legal_name if ins.payee_id else None})
    rows.sort(key=lambda r: r["at"])
    return {"escrow_id": str(e.pk), "reference": e.reference, "lines": rows, "funds": confirmed_funds(e)}


def escrows_paying(payee) -> list[Escrow]:
    ids = EscrowPayee.objects.filter(payee=payee).values_list("escrow_id", flat=True)
    return list(Escrow.objects.filter(pk__in=ids, status__in=OPEN_STATUSES))


def live_lock(e: Escrow, payee):
    return EscrowPayee.objects.filter(escrow=e, payee=payee, account_version=payee.account_version,
                                      ended_at__isnull=True).select_related("change").first()


def open_escrows_of(person):
    return Escrow.objects.filter(client=person, status__in=OPEN_STATUSES)


def released_total(e: Escrow, currency=None) -> Decimal:
    cur = (currency or e.currency).upper()
    return _sum(BankEvent.objects.filter(escrow=e, currency=cur, status="confirmed", kind="release_confirmed"))


def instructions_needing_client(person):
    return ReleaseInstruction.objects.filter(escrow__client=person, status="awaiting_client")


def live_instructions_to(payee):
    return ReleaseInstruction.objects.filter(payee=payee, status__in=["awaiting_client", "pending_approval",
                                                                      "approved"])


def q_visible_to_client(person):
    return Q(client=person) | Q(parties__person=person)
