"""Programme escrow accounts (RUL-34), the bank's daily figure per escrow
(FR-ESC-019, document 06 RB-47) and statement import (FR-ESC-011).
Called through escrow.services."""
import hashlib
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from administration import flags
from core import approvals, state
from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.permissions import has_role

from . import adapters, selectors
from .common import alert_staff, audit, fmt, now
from .models import BankEvent, BankPosition, Escrow, FxAccount, ProgrammeAccount, ReleaseInstruction, StatementFile, \
    StatementLine


def _on(country):
    flags.require("escrow.enabled", country)
    flags.read_only_guard()


# ----------------------------------------------------------------- programme accounts (6.16)

@transaction.atomic
def create_programme_account(by, *, country, bank_partner, currency, account_number, account_name,
                             agreement_evidence, kind="programme") -> ProgrammeAccount:
    """An administrator records the bank's escrow account; a second
    administrator approves (FR-ADM-003). Never a Tenmina account (RUL-01, RUL-27)."""
    from administration.models import Partner
    from administration.services import account_bidx

    _on(country)
    if not has_role(by, "AD", country=country):
        raise Forbidden("Only an administrator records a programme escrow account.")
    if bank_partner.kind != "escrow_bank" or bank_partner.country_id != country.pk:
        raise Invalid("The account must be held by this country's escrow bank partner.", code="validation-error")
    if kind not in ProgrammeAccount.KINDS:
        raise Invalid("Kind is programme or single_escrow.", code="validation-error")
    if agreement_evidence is None:
        raise Invalid("Attach the agreement with the bank (Q-28, Q-29).", code="validation-error")
    number = "".join((account_number or "").split())
    bidx = account_bidx(number)
    if Partner.objects.filter(kind__in=("operating_bank", "operating_mobile_money"), account_number_bidx=bidx) \
            .exists():
        raise RuleBlocked("A Tenmina operating account can never be an escrow account.", code="tenmina-account-refused",
                          blocking_reasons=[{"rule": "RUL-27", "message": "Operating and escrow accounts differ."}])
    import uuid

    pid = uuid.uuid4()
    req = approvals.request_approval("programme_account", pid, by, required=1, country=country,
                                     summary=f"{bank_partner.name} {currency} escrow account ending {number[-4:]}")
    pa = ProgrammeAccount.objects.create(id=pid, country=country, bank_partner=bank_partner, currency=currency.upper(),
                                         kind=kind, account_number=number, account_number_bidx=bidx,
                                         account_name=account_name.strip(), agreement_evidence=agreement_evidence,
                                         approval_request=req, created_by=by)
    audit(by, "programme_account.proposed", pa, {"currency": pa.currency, "last4": pa.last4, "kind": kind})
    return pa


def decide_programme_account(pa: ProgrammeAccount, approver, *, decision, mfa_at, note=""):
    if pa.approval_request.status != "open":
        raise StateConflict("This account is not waiting for approval.")
    return approvals.decide(pa.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=lambda a: has_role(a, "AD", country=pa.country))


@transaction.atomic
def on_programme_account_decided(pa: ProgrammeAccount, approved: bool):
    pa.refresh_from_db()
    if pa.status != "pending":
        return pa
    if not approved:
        pa.closed_on = timezone.localdate()
        return state.transition(pa, "programme_account", "closed", extra_fields=["closed_on"], reason="Not approved")
    if pa.kind == "programme":
        old = ProgrammeAccount.objects.filter(country=pa.country, currency=pa.currency, kind="programme",
                                              status="active").exclude(pk=pa.pk).first()
        if old is not None:
            old.closed_on = timezone.localdate()
            state.transition(old, "programme_account", "closed", extra_fields=["closed_on"],
                             reason="Replaced by a new programme account")
    pa.opened_on = timezone.localdate()
    return state.transition(pa, "programme_account", "active", extra_fields=["opened_on"],
                            event="programme_account.active", payload={"programme_account_id": pa.pk,
                                                                       "currency": pa.currency})


# ----------------------------------------------------------------- daily bank figure (FR-ESC-019, RB-47)

def _compare(pos: BankPosition):
    pos.derived_held_at_bank = selectors.held_at_bank(pos.escrow, pos.currency)
    target = "matched" if pos.reported_held_amount == pos.derived_held_at_bank else "mismatch"
    pos.save(update_fields=["derived_held_at_bank", "checked_by"])
    state.transition(pos, "bank_position", target, event="bank_position.mismatch" if target == "mismatch" else None,
                     payload={"position_id": pos.pk, "escrow_id": pos.escrow_id, "currency": pos.currency,
                              "reported": pos.reported_held_amount, "derived": pos.derived_held_at_bank})
    if target == "mismatch":
        alert_staff(pos.country, ("RV", "CM"), "bank_position_mismatch",
                    f"The bank's figure for {pos.escrow.reference} on {pos.as_of:%d %B %Y} "
                    f"({fmt(pos.reported_held_amount, pos.currency)}) differs from the confirmed events "
                    f"({fmt(pos.derived_held_at_bank, pos.currency)}). Releases on it are blocked.", obj=pos)
    return pos


@transaction.atomic
def record_bank_position(e: Escrow, *, as_of, reported_held_amount, currency=None, source="manual", by=None,
                         proof_evidence=None, statement_file=None, virtual_account_ref=None) -> BankPosition:
    _on(e.country)
    if source == "manual":
        if by is None or not has_role(by, "CM", "RV", country=e.country):
            raise Forbidden("Only staff enter the bank's figure.")
        if proof_evidence is None:
            raise Invalid("Attach the bank's report.", code="bank-confirmation-required")
    cur = (currency or e.currency).upper()
    ref = virtual_account_ref
    if ref is None:
        ref = e.virtual_account_ref if cur == e.currency else \
            getattr(FxAccount.objects.filter(escrow=e, currency=cur).first(), "virtual_account_ref", None)
    if not ref:
        raise Invalid("This escrow has no virtual account in that currency.", code="validation-error")
    try:
        with transaction.atomic():
            pos = BankPosition.objects.create(country=e.country, escrow=e, virtual_account_ref=ref, as_of=as_of,
                                              reported_held_amount=Decimal(str(reported_held_amount)), currency=cur,
                                              source=source, proof_evidence=proof_evidence, entered_by=by,
                                              statement_file=statement_file)
    except IntegrityError as exc:
        raise StateConflict("The bank's figure for that day is already recorded.") from exc
    audit(by, "bank_position.recorded", pos, {"as_of": str(as_of), "source": source})
    if source != "manual":
        _compare(pos)
    return pos


@transaction.atomic
def check_bank_position(pos: BankPosition, by) -> BankPosition:
    if not has_role(by, "CM", "RV", country=pos.country):
        raise Forbidden()
    pos.refresh_from_db()
    if pos.status != "pending_check":
        raise StateConflict("This figure is not waiting for a check.")
    if by.pk == pos.entered_by_id:
        raise Forbidden("A second person checks the figure.", code="same-approver")
    pos.checked_by = by
    return _compare(pos)


@transaction.atomic
def resolve_position(pos: BankPosition, by, *, note, evidence) -> BankPosition:
    """A reviewer records the bank's written explanation; a second staff member
    checks it. Resolving never edits a bank event."""
    if not has_role(by, "RV", country=pos.country):
        raise Forbidden("Only a reviewer resolves a mismatch.")
    if pos.status != "mismatch":
        raise StateConflict("This figure is not a mismatch.")
    if not note or evidence is None:
        raise Invalid("Record the bank's written explanation and attach it.", code="validation-error")
    pos.resolved_by, pos.resolution_note, pos.resolution_evidence = by, note, evidence
    pos.save(update_fields=["resolved_by", "resolution_note", "resolution_evidence"])
    audit(by, "bank_position.resolution_proposed", pos)
    return pos


@transaction.atomic
def check_resolution(pos: BankPosition, by) -> BankPosition:
    if not has_role(by, "CM", "RV", "AD", country=pos.country):
        raise Forbidden()
    if pos.status != "mismatch" or pos.resolved_by_id is None:
        raise StateConflict("No resolution waits for a check.")
    if by.pk == pos.resolved_by_id:
        raise Forbidden("A second staff member checks the resolution.", code="same-approver")
    pos.resolution_checked_by, pos.resolved_at = by, now()
    state.transition(pos, "bank_position", "resolved", actor=by, event="bank_position.resolved",
                     extra_fields=["resolution_checked_by", "resolved_at"],
                     payload={"position_id": pos.pk, "escrow_id": pos.escrow_id})
    from .services import dispatch, sync_status

    sync_status(pos.escrow)
    for ins in ReleaseInstruction.objects.filter(escrow=pos.escrow, status="approved"):
        dispatch(ins)
    return pos


# ----------------------------------------------------------------- statement import (FR-ESC-011)

def _escrow_by_ref(ref, country):
    e = Escrow.objects.filter(virtual_account_ref=ref, country=country).first()
    if e is not None:
        return e
    fx = FxAccount.objects.filter(virtual_account_ref=ref, country=country).select_related("escrow").first()
    return fx.escrow if fx else None


@transaction.atomic
def import_statement(by, *, country, data: bytes, original_name="statement.csv", account_kind="escrow",
                     programme_account=None) -> StatementFile:
    """Matched credits confirm deposits; debits naming a sent instruction
    confirm it; position lines record the bank's figure. The same file, or the
    same bank reference, is never applied twice."""
    from evidence.services import store

    _on(country)
    if by is not None and not has_role(by, "CM", "RV", country=country):
        raise Forbidden("Only staff import statements.")
    if not flags.enabled("escrow.bank_statement_import", country):
        raise Invalid("Statement import is not switched on in this country.", code="feature-off", status=404)
    digest = hashlib.sha256(data).hexdigest()
    if StatementFile.objects.filter(sha256=digest).exists():
        raise StateConflict("This statement file was already imported. No line is applied twice.",
                            code="statement-duplicate")
    try:
        rows = adapters.bank_statement().parse(data)
    except (ValueError, KeyError) as exc:
        raise Invalid(f"The statement file could not be read: {exc}", code="validation-error") from exc
    ev = store(data=data, country=country, uploaded_by=by, content_type="text/csv", original_name=original_name,
               source="provider", data_class="escrow_payment")
    sf = StatementFile.objects.create(country=country, programme_account=programme_account, account_kind=account_kind,
                                      sha256=digest, original_name=original_name, evidence=ev, uploaded_by=by,
                                      line_count=len(rows))
    matched = unmatched = 0
    for r in rows:
        line = StatementLine.objects.create(file=sf, **r)
        status = _apply_line(sf, line, by)
        line.match_status = status
        line.save(update_fields=["match_status", "escrow", "bank_event", "bank_position", "note"])
        if status == "matched":
            matched += 1
        elif status == "unmatched":
            unmatched += 1
        if account_kind == "owner_rent":
            publish("statement.line_imported", line.pk, {"line_id": line.pk, "file_id": sf.pk,
                                                         "virtual_account_ref": line.virtual_account_ref,
                                                         "amount": line.amount, "currency": line.currency,
                                                         "booked_on": line.booked_on, "kind": line.kind,
                                                         "narrative": line.narrative,
                                                         "counterparty_name": line.counterparty_name})
    sf.matched_count, sf.unmatched_count = matched, unmatched
    sf.save(update_fields=["matched_count", "unmatched_count"])
    audit(by, "statement.imported", sf, {"lines": len(rows), "matched": matched, "unmatched": unmatched})
    if unmatched:
        alert_staff(country, ("CM",), "statement_unmatched",
                    f"{unmatched} line(s) in {original_name} matched no escrow. Review the unmatched queue.", obj=sf,
                    link=f"/back-office/bank-statements/{sf.pk}/unmatched")
    return sf


def _apply_line(sf, line: StatementLine, by) -> str:
    from datetime import datetime, time

    from .services import record_bank_event

    if sf.account_kind == "owner_rent":
        return "ignored"
    e = _escrow_by_ref(line.virtual_account_ref, sf.country) if line.virtual_account_ref else None
    occurred = timezone.make_aware(datetime.combine(line.booked_on, time(12, 0)))
    if line.kind == "position":
        if e is None:
            line.note = "No escrow has this virtual account."
            return "unmatched"
        try:
            pos = record_bank_position(e, as_of=line.booked_on, reported_held_amount=line.amount,
                                       currency=line.currency, source="statement", statement_file=sf,
                                       virtual_account_ref=line.virtual_account_ref)
        except StateConflict:
            line.note = "A figure for that day is already recorded."
            return "duplicate"
        line.escrow, line.bank_position = e, pos
        return "matched"
    if line.kind == "credit":
        if e is None or e.status == "proposed":
            line.note = "No agreed escrow has this virtual account. It counts nowhere until matched (RUL-34)."
            return "unmatched"
        if BankEvent.objects.filter(escrow=e, kind="deposit", bank_reference=line.bank_reference) \
                .exclude(status="rejected").exists():
            line.escrow = e
            line.note = "Already recorded; counted once."
            return "duplicate"
        known = bool(line.counterparty_account and line.counterparty_name)
        ev = record_bank_event(e, kind="deposit", amount=line.amount, currency=line.currency,
                               bank_reference=line.bank_reference or f"{sf.sha256[:8]}-{line.line_no}",
                               occurred_at=occurred, virtual_account_ref=line.virtual_account_ref,
                               source="statement", by=by, source_bank_name=line.counterparty_bank,
                               source_account_number=line.counterparty_account,
                               source_account_name=line.counterparty_name, source_account_known=known,
                               statement_line=line, note=line.narrative)
        line.escrow, line.bank_event = e, ev
        return "matched"
    # debit: the narrative or reference names the instruction
    ins = None
    for token in (line.narrative + " " + line.bank_reference).replace(",", " ").split():
        try:
            ins = ReleaseInstruction.objects.filter(pk=token.strip(), status="sent").first()
        except Exception:  # noqa: BLE001 - not a uuid
            ins = None
        if ins is None:
            ins = ReleaseInstruction.objects.filter(sent_reference=token.strip(), status="sent").first() \
                if token.strip() else None
        if ins is not None:
            break
    if ins is None or (e is not None and ins.escrow_id != e.pk) or ins.amount != line.amount:
        line.note = "No sent instruction of this amount matches this line."
        return "unmatched"
    kind = {"cancel_refund": "refund_confirmed", "conversion": "conversion_debit"}.get(ins.kind, "release_confirmed")
    ev = record_bank_event(ins.escrow, kind=kind, amount=line.amount, currency=line.currency,
                           bank_reference=line.bank_reference or f"{sf.sha256[:8]}-{line.line_no}",
                           occurred_at=occurred, virtual_account_ref=line.virtual_account_ref or None,
                           source="statement", by=by, instruction=ins, statement_line=line)
    line.escrow, line.bank_event = ins.escrow, ev
    return "matched"


def unmatched_lines(sf: StatementFile):
    if sf is None:
        raise NotFound()
    return sf.lines.filter(match_status="unmatched").order_by("line_no")
