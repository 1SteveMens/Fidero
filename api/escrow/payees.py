"""Verified payee registry (ADR-17, RUL-22, FR-ESC-015), the payee lock and
payee changes with cooling-off (ADR-24, RUL-28, FR-ESC-016, sequence 5.12),
and the refund-destination exception (RUL-29, FR-ESC-017).

Called through escrow.services; not imported by other modules directly.
"""
import hashlib
import json
import secrets
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone

from accounts.normalise import normalise_name
from administration import flags
from core import approvals, state
from core.errors import (DomainError, Forbidden, Invalid, MfaRequired, NotFound, PayeeNotVerified, RuleBlocked,
                         StateConflict)
from core.events import publish
from core.permissions import has_role

from . import adapters, selectors
from .common import STAFF, alert_staff, audit, has_rr, is_staff, notify, now, setting
from .models import (OPEN_STATUSES, PAYEE_KINDS, RELEASABLE_KINDS, Escrow, EscrowPayee, Payee, PayeeChange,
                     ReleaseInstruction)

PAYEE_KINDS_CHANGES = ("new_payee", "add_payee")  # changes naming an already verified payee

BANK_FIELDS = ("bank_name", "account_number", "account_name", "account_name_source", "account_name_evidence")
NEVER_SOURCES = ("message", "email", "call", "whatsapp", "sms", "phone", "statement_line", "payee_word")


def _require_escrow_on(country):
    flags.require("escrow.enabled", country)
    flags.read_only_guard()


def _registry_on(country):
    """The verified payee registry works whether or not `escrow.enabled` is on: the launch `client_direct`
    routes (fees, construction, insurance) pay only verified payees too (ADR-17, RUL-22). Only escrows and
    releases need the flag."""
    flags.read_only_guard()


def _acct_bidx(number):
    from administration.services import account_bidx

    return account_bidx(number)


def _generated_evidence(country, by, name, payload: dict):
    from evidence.services import store

    data = json.dumps(payload, sort_keys=True, default=str, indent=1).encode()
    return store(data=data, country=country, uploaded_by=by, content_type="application/json", original_name=name,
                 source="generated", data_class="payee")


def check_account_name(*, country, by, bank_name, account_number, account_name, source, evidence, claimed_for):
    """FR-ESC-015, 9.2: the account name comes from the bank's name check or a
    bank letter. Anything else is refused. Returns (name, evidence, raw_sha256)."""
    if source in NEVER_SOURCES or source not in ("bank_name_check", "bank_letter"):
        raise Invalid("The account name must come from the bank's name check or a bank letter. A statement line, "
                      "message, email or call is never a source.", code="account-name-source",
                      blocking_reasons=[{"rule": "FR-ESC-015", "message": f"Source '{source}' is not accepted."}])
    if source == "bank_name_check":
        res = adapters.bank_name_check().lookup(bank_name=bank_name, account_number=account_number,
                                                claimed_name=claimed_for)
        if res.get("status") != "found":
            raise Invalid("The bank's name check does not cover this account. Use a bank letter checked by a second "
                          "staff member.", code="name-check-unavailable")
        ev = evidence or _generated_evidence(country, by, "bank-name-check.json", {
            "bank": bank_name, "account_last4": account_number[-4:], "name": res["name"],
            "raw_sha256": res["raw_sha256"], "at": timezone.now()})
        return res["name"], ev, res["raw_sha256"]
    if evidence is None:
        raise Invalid("Attach the bank letter that states the account name.", code="validation-error")
    if not account_name:
        raise Invalid("Enter the account name exactly as the bank letter prints it.", code="validation-error")
    return account_name.strip(), evidence, ""


def _payee_person_is_staff(person):
    return person is not None and person.has_tenmina_role("CM", "RV", "AD", "RN")


@transaction.atomic
def create_payee(by, *, country, kind, subject_type, subject_id, legal_name, legal_name_evidence, bank_name,
                 account_number, account_name="", account_name_source, account_name_evidence=None, person=None,
                 organisation=None, national_id_check=None, bank_partner_id=None, contact_email="",
                 contact_phone="") -> Payee:
    _registry_on(country)
    if not is_staff(by, country):
        raise Forbidden("Only Tenmina staff add payees.")
    if kind not in PAYEE_KINDS:
        raise Invalid(f"Unknown payee kind '{kind}'.", code="validation-error")
    if _payee_person_is_staff(person):
        raise RuleBlocked("Tenmina staff and runners are never payees of client money.",
                          code="payee-not-verified", blocking_reasons=[{"rule": "RUL-22",
                                                                        "message": "Staff or runner as payee"}])
    number = "".join((account_number or "").split())
    if len(number) < 6:
        raise Invalid("Enter the account number as the bank gives it.", code="validation-error")
    name, ev, raw = check_account_name(country=country, by=by, bank_name=bank_name, account_number=number,
                                       account_name=account_name, source=account_name_source,
                                       evidence=account_name_evidence, claimed_for=legal_name)
    if Payee.objects.filter(subject_type=subject_type, subject_id=subject_id, kind=kind).exists():
        raise StateConflict("This payee is already registered. Use a payee change to change its account.",
                            code="payee-exists")
    p = Payee.objects.create(
        country=country, kind=kind, subject_type=subject_type, subject_id=subject_id, person=person,
        organisation=organisation, legal_name=legal_name.strip(), legal_name_norm=normalise_name(legal_name),
        legal_name_evidence=legal_name_evidence, bank_partner_id=bank_partner_id, bank_name=bank_name.strip(),
        account_number=number, account_number_bidx=_acct_bidx(number), account_name=name,
        account_name_norm=normalise_name(name), account_name_source=account_name_source, account_name_evidence=ev,
        account_name_raw_sha256=raw, national_id_check=national_id_check, created_by=by,
        contact_email=contact_email or "", contact_phone=contact_phone or "")
    p.refresh_from_db()
    audit(by, "payee.created", p, {"kind": kind, "last4": p.last4, "name_match": p.name_match,
                                   "source": account_name_source})
    if p.name_match != "matched":
        alert_staff(country, ("RV",), "payee_name_mismatch",
                    f"The bank's account name for {p.legal_name} does not match. Nobody can override this; ask for "
                    "new evidence from the bank.", obj=p)
    return p


@transaction.atomic
def update_payee(p: Payee, by, data: dict) -> Payee:
    """Contact details change freely. Bank details change only through a
    payee change (RUL-28), except on a payee never verified nor locked."""
    _registry_on(p.country)
    if not is_staff(by, p.country):
        raise Forbidden("Only Tenmina staff edit payees.")
    bank_change = {k for k in BANK_FIELDS if k in data and data[k] not in (None, "")}
    if bank_change:
        locked = EscrowPayee.objects.filter(payee=p).exists()
        if p.verified_at is not None or locked:
            audit(by, "payee.direct_edit_refused", p, {"fields": sorted(bank_change)})
            alert_staff(p.country, ("RV",), "payee_edit_refused",
                        f"Someone tried to edit the bank details of {p.legal_name} directly. Only a payee change "
                        "request can change them.", obj=p)
            raise RuleBlocked("Bank details of a verified or agreed payee change only through a payee change request "
                              "with the client's approval, two staff, fresh checks and a cooling-off.",
                              code="payee-locked", blocking_reasons=[{"rule": "RUL-28",
                                                                      "message": "Direct edits are refused."}])
        name, ev, raw = check_account_name(
            country=p.country, by=by, bank_name=data.get("bank_name") or p.bank_name,
            account_number=data.get("account_number") or p.account_number,
            account_name=data.get("account_name") or p.account_name,
            source=data.get("account_name_source") or p.account_name_source,
            evidence=data.get("account_name_evidence") or p.account_name_evidence, claimed_for=p.legal_name)
        p.bank_name = data.get("bank_name") or p.bank_name
        p.account_number = "".join((data.get("account_number") or p.account_number).split())
        p.account_number_bidx = _acct_bidx(p.account_number)
        p.account_name, p.account_name_norm = name, normalise_name(name)
        p.account_name_source = data.get("account_name_source") or p.account_name_source
        p.account_name_evidence, p.account_name_raw_sha256 = ev, raw
    if data.get("legal_name"):
        if not data.get("legal_name_evidence"):
            raise Invalid("A new legal name needs its registration or identity document.", code="validation-error")
        p.legal_name, p.legal_name_norm = data["legal_name"].strip(), normalise_name(data["legal_name"])
        p.legal_name_evidence = data["legal_name_evidence"]
    for k in ("contact_email", "contact_phone", "national_id_check"):
        if k in data and data[k] is not None:
            setattr(p, k, data[k])
    p.save()
    if data.get("legal_name") and p.verification_status == "verified":
        _reset_verification(p, by, "The payee's legal name changed")
    audit(by, "payee.updated", p, {"fields": sorted(k for k in data if data[k] is not None)})
    p.refresh_from_db()
    return p


def _reset_verification(p, by, reason):
    p.verified_by = p.second_check_by = p.approval_request = None
    p.verified_at = None
    p.save(update_fields=["verified_by", "second_check_by", "approval_request", "verified_at"])
    state.transition(p, "payee", "pending", actor=by, reason=reason)
    _withdraw_live_instructions(p, by, reason)


def _withdraw_live_instructions(p, by, reason):
    from .services import withdraw_instruction

    for ins in selectors.live_instructions_to(p):
        withdraw_instruction(ins, by, reason=reason, system=True)


def payee_identity_reasons(p: Payee) -> list[dict]:
    from accounts.services import national_id_blockers

    if p.kind == "client_own_account":
        return []
    return national_id_blockers({f"Payee {p.legal_name}": p.national_id_check})


@transaction.atomic
def prepare_verification(p: Payee, by) -> Payee:
    """Step one: a staff member checks the evidence; two other staff approve
    (`payee_verification`). A mismatch can never be verified (FR-ESC-015)."""
    _registry_on(p.country)
    if not is_staff(by, p.country):
        raise Forbidden("Only Tenmina staff verify payees.")
    if p.person_id and p.person_id == by.pk:
        raise Forbidden("You cannot verify yourself as a payee.")
    p.refresh_from_db()
    if p.verification_status not in ("pending",):
        raise StateConflict(f"This payee is {p.verification_status}, not waiting for verification.")
    if p.name_match != "matched":
        raise PayeeNotVerified("The bank's account name does not match the payee's legal name. Nobody can override "
                               "this; only new evidence from the bank's name check or a bank letter clears it.",
                               blocking_reasons=[{"rule": "FR-ESC-015", "message":
                                                  f"'{p.account_name}' is not '{p.legal_name}'"}])
    reasons = payee_identity_reasons(p)
    if reasons:
        raise RuleBlocked("The payee's identity must match the national identity system first.",
                          code="national-id-check-required", blocking_reasons=reasons)
    if p.approval_request_id and p.approval_request.status == "open":
        raise StateConflict("This payee is already waiting for approval.")
    p.prepared_by = by
    p.approval_request = approvals.request_approval(
        "payee_verification", p.pk, by, required=2, country=p.country,
        summary=f"Verify payee {p.legal_name}, account ending {p.last4}")
    p.save(update_fields=["prepared_by", "approval_request"])
    return p


def verification_allowed(p):
    return lambda a: is_staff(a, p.country) and a.pk != p.person_id


def decide_verification(p: Payee, approver, *, decision, mfa_at, note=""):
    if p.approval_request is None or p.approval_request.status != "open":
        raise StateConflict("This payee has no open verification.")
    return approvals.decide(p.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=verification_allowed(p))


@transaction.atomic
def apply_verification(p: Payee, approved: bool):
    p.refresh_from_db()
    req = p.approval_request
    if p.verification_status != "pending" or req is None:
        return p
    if not approved:
        audit(None, "payee.verification_rejected", p)
        return p
    if p.name_match != "matched" or payee_identity_reasons(p):
        audit(None, "payee.verification_refused_at_apply", p)
        return p
    names = [a.approver_id for a in req.approvals.filter(decision="approve").order_by("approved_at")]
    p.verified_by_id, p.second_check_by_id = names[0], names[1]
    p.verified_at = now()
    p.valid_until = timezone.localdate() + timedelta(days=365)  # re-verify yearly (assumption)
    state.transition(p, "payee", "verified", event="payee.verified",
                     extra_fields=["verified_by", "second_check_by", "verified_at", "valid_until"],
                     payload={"payee_id": p.pk, "kind": p.kind, "subject_type": p.subject_type,
                              "subject_id": p.subject_id, "country": p.country.code})
    return p


@transaction.atomic
def suspend_payee(p: Payee, by, reason: str, *, system=False) -> Payee:
    if not system and not has_role(by, "RV", country=p.country):
        raise Forbidden("Only a reviewer suspends a payee.")
    if not reason:
        raise Invalid("Give the reason.", code="validation-error")
    p.refresh_from_db()
    if p.verification_status == "suspended":
        return p
    p.suspend_reason = reason
    p.save(update_fields=["suspend_reason"])
    state.transition(p, "payee", "suspended", actor=by, event="payee.suspended", reason=reason,
                     payload={"payee_id": p.pk, "kind": p.kind, "subject_type": p.subject_type,
                              "subject_id": p.subject_id})
    if p.approval_request_id and p.approval_request.status == "open":
        approvals.withdraw(p.approval_request, by)
    _withdraw_live_instructions(p, by, f"Payee suspended: {reason}")
    return p


@transaction.atomic
def reinstate_payee(p: Payee, by) -> Payee:
    """A suspended payee goes back to pending and is verified again by two people."""
    if not has_role(by, "RV", country=p.country):
        raise Forbidden("Only a reviewer reinstates a payee.")
    if p.verification_status != "suspended":
        raise StateConflict("This payee is not suspended.")
    p.verified_by = p.second_check_by = p.approval_request = None
    p.verified_at = None
    p.save(update_fields=["verified_by", "second_check_by", "approval_request", "verified_at"])
    return state.transition(p, "payee", "pending", actor=by, reason="Reinstated for re-verification")


# ----------------------------------------------------------------- the lock (RUL-28)

def lock_payee(e: Escrow, p: Payee, *, client_approved_at, source="client_approved_payment", change=None):
    if p.kind == "contracted_professional":
        raise RuleBlocked("A professional Tenmina contracts is paid from Tenmina's own account, never from client "
                          "money.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-27", "message": "Contracted professional on an escrow"}])
    row, _ = EscrowPayee.objects.get_or_create(
        escrow=e, payee=p, account_version=p.account_version,
        defaults={"source": source, "change": change, "client_approved_at": client_approved_at})
    return row


# ----------------------------------------------------------------- payee changes (5.12)

def _person_may_request_for(by, p: Payee) -> bool:
    if p.person_id and p.person_id == by.pk:
        return True
    if p.organisation_id:
        from accounts.selectors import membership

        m = membership(by, p.organisation_id)
        return m is not None
    return False


@transaction.atomic
def request_change(by, *, kind, reason, request_source, payee=None, escrow=None, replaces_payee=None,
                   deposit_event=None, bank_name="", account_number="", account_name="", account_name_source="",
                   account_name_evidence=None) -> PayeeChange:
    """FR-ESC-016: the only way to change where money goes. Never from a
    message, email or call (RUL-28)."""
    country = (payee or escrow).country
    if escrow is not None or kind != "new_account":
        _require_escrow_on(country)  # a change tied to an escrow
    else:
        _registry_on(country)
    if request_source not in PayeeChange.SOURCES:
        audit(by, "payee_change.source_refused", payee or escrow, {"source": request_source})
        raise RuleBlocked("Bank details are never taken from a message, email or call. The payee asks signed in, "
                          "or staff meet the payee.", code="payee-change-source",
                          blocking_reasons=[{"rule": "RUL-28", "message": f"Source '{request_source}' refused."}])
    if not reason:
        raise Invalid("Give the reason for the change.", code="validation-error")
    number = "".join((account_number or "").split())
    name, ev, raw = "", None, ""
    if kind == "new_account":
        if payee is None:
            raise Invalid("Name the payee.", code="validation-error")
        if request_source == "payee_signed_in" and not _person_may_request_for(by, payee):
            raise Forbidden("Only the payee, signed in, asks for its own new account.")
        if request_source == "staff_in_person" and not has_role(by, "CM", "RV", country=country):
            raise Forbidden("Only a case manager or reviewer who met the payee records this.")
        if request_source == "client_signed_in":
            raise Forbidden("A client cannot change a payee's account.")
        if payee.verification_status != "verified":
            raise StateConflict("Only a verified payee's account is changed this way; verify the payee first.")
        name, ev, raw = check_account_name(country=country, by=by, bank_name=bank_name, account_number=number,
                                           account_name=account_name, source=account_name_source,
                                           evidence=account_name_evidence, claimed_for=payee.legal_name)
        if normalise_name(name) != payee.legal_name_norm:
            raise PayeeNotVerified("The new account is not in the payee's own name.",
                                   blocking_reasons=[{"rule": "FR-ESC-015", "message": f"'{name}' is not "
                                                                                       f"'{payee.legal_name}'"}])
    elif kind == "new_payee":
        if not has_role(by, "CM", "RV", country=country):
            raise Forbidden("Only staff propose a new payee on an agreed escrow.")
        if escrow is None or escrow.status not in OPEN_STATUSES or escrow.status == "proposed":
            raise StateConflict("A new payee is proposed only on an agreed escrow.")
        if payee is None or replaces_payee is None:
            raise Invalid("Name the new payee and the payee it replaces.", code="validation-error")
        if payee.verification_status != "verified" or payee.name_match != "matched":
            raise PayeeNotVerified("The new payee must be verified first.",
                                   blocking_reasons=[{"rule": "RUL-22", "message": "New payee not verified"}])
        if not EscrowPayee.objects.filter(escrow=escrow, payee=replaces_payee, ended_at__isnull=True).exists():
            raise StateConflict("The payee to replace is not on this escrow.")
    elif kind == "add_payee":
        # An extra payee on an agreed escrow, e.g. an event vendor verified after the terms were agreed. Same
        # checks as a new payee: verified, name matched, a valid identity check, the client's approval first,
        # two staff and the cooling-off (RUL-22, RUL-28).
        if not has_role(by, "CM", "RV", country=country):
            raise Forbidden("Only staff add a payee to an agreed escrow.")
        if escrow is None or escrow.status not in OPEN_STATUSES or escrow.status == "proposed":
            raise StateConflict("A payee is added this way only to an agreed escrow. Before agreement, add it to "
                                "the terms.")
        if payee is None:
            raise Invalid("Name the payee to add.", code="validation-error")
        if payee.country_id != escrow.country_id:
            raise Invalid("The payee belongs to another country.", code="validation-error")
        if payee.kind not in RELEASABLE_KINDS:
            raise RuleBlocked("This kind of payee is never paid from client money.", code="payee-not-verified",
                              blocking_reasons=[{"rule": "RUL-27" if payee.kind == "contracted_professional"
                                                 else "RUL-22", "message": f"Payee kind {payee.kind}"}])
        if payee.verification_status != "verified" or payee.name_match != "matched":
            raise PayeeNotVerified("The payee must be verified first.",
                                   blocking_reasons=[{"rule": "RUL-22", "message": "Payee not verified"}])
        if EscrowPayee.objects.filter(escrow=escrow, payee=payee, ended_at__isnull=True).exists():
            raise StateConflict("This payee is already on this escrow.", code="payee-exists")
        if PayeeChange.objects.filter(escrow=escrow, payee=payee, kind="add_payee", status__in=[
                "requested", "checks_passed", "client_approved", "pending_approval"]).exists():
            raise StateConflict("This payee is already waiting to be added.", code="payee-exists")
    elif kind == "refund_destination":
        if escrow is None or deposit_event is None or deposit_event.escrow_id != escrow.pk \
                or deposit_event.kind != "deposit" or deposit_event.status != "confirmed":
            raise Invalid("Name a bank-confirmed deposit of this escrow.", code="validation-error")
        if not (has_role(by, "CM", "RV", country=country) or by.pk == escrow.client_id):
            raise Forbidden("Only the client or a case manager starts a refund exception.")
        if deposit_event.source_account_known and not deposit_event.source_cannot_receive:
            raise RuleBlocked("This deposit goes back to its source account. A refund exception is only for a "
                              "deposit with no source account, or one the source account cannot receive.",
                              code="refund-not-to-source",
                              blocking_reasons=[{"rule": "RUL-29", "message": "Source account can receive"}])
        name, ev, raw = check_account_name(country=country, by=by, bank_name=bank_name, account_number=number,
                                           account_name=account_name, source=account_name_source,
                                           evidence=account_name_evidence, claimed_for=escrow.client.full_name)
        if normalise_name(name) != normalise_name(escrow.client.full_name):
            raise PayeeNotVerified("A refund exception goes only to an account in the client's own name.",
                                   blocking_reasons=[{"rule": "RUL-29", "message": f"'{name}' is not the client"}])
    else:
        raise Invalid(f"Unknown change kind '{kind}'.", code="validation-error")
    ch = PayeeChange.objects.create(
        country=country, kind=kind, payee=payee, replaces_payee=replaces_payee, escrow=escrow,
        deposit_event=deposit_event, reason=reason, request_source=request_source, bank_name=bank_name or "",
        account_number=number, account_name=name, account_name_norm=normalise_name(name),
        account_name_source=account_name_source if kind not in PAYEE_KINDS_CHANGES else "", account_name_evidence=ev,
        account_name_raw_sha256=raw, requested_by=by)
    audit(by, "payee_change.requested", ch, {"kind": kind, "last4": number[-4:] if number else ""})
    publish("payee_change.requested", ch.pk, {"change_id": ch.pk, "kind": kind,
                                              "payee_id": payee.pk if payee else None,
                                              "escrow_id": escrow.pk if escrow else None})
    alert_staff(country, ("CM", "RV"), "payee_change_requested",
                f"A payee change ({kind.replace('_', ' ')}) was requested. Check the account evidence and run a fresh "
                "identity check.", obj=ch, link=f"/back-office/payee-changes/{ch.pk}")
    if kind in PAYEE_KINDS_CHANGES:
        ch.national_id_check = payee.national_id_check
        ch.save(update_fields=["national_id_check"])
    advance_change(ch)
    return ch


def _account_check_done(ch) -> bool:
    if ch.kind in PAYEE_KINDS_CHANGES:
        return True
    return ch.account_name_source == "bank_name_check" or ch.account_checked_by_id is not None


def _nid_done(ch) -> bool:
    chk = ch.national_id_check
    if chk is None or chk.result != "match":
        return False
    if ch.kind in PAYEE_KINDS_CHANGES:
        return True
    return chk.requested_at >= ch.requested_at  # fresh, made for this change (9.2, 5.12)


@transaction.atomic
def check_change_account(ch: PayeeChange, by) -> PayeeChange:
    """A second person checks a bank letter (FR-ESC-015)."""
    if not has_role(by, "CM", "RV", "AD", country=ch.country):
        raise Forbidden("Only staff check account evidence.")
    if by.pk == ch.requested_by_id:
        raise Forbidden("A second person must check the bank letter.")
    if ch.status != "requested" or ch.account_name_source != "bank_letter":
        raise StateConflict("Nothing to check on this change.")
    ch.account_checked_by = by
    ch.save(update_fields=["account_checked_by"])
    audit(by, "payee_change.account_checked", ch)
    return advance_change(ch)


@transaction.atomic
def change_identity_check(ch: PayeeChange, by, *, id_number="", subject_name="", national_id_check=None):
    """A fresh national identity check of the payee (or of the client for a
    refund exception), through IF-03 (RUL-31)."""
    from accounts.models import NationalIdCheck
    from accounts.services import request_national_id_check

    if ch.status != "requested":
        raise StateConflict("The checks on this change are already complete.")
    if national_id_check is not None:
        chk = national_id_check if isinstance(national_id_check, NationalIdCheck) else \
            NationalIdCheck.objects.filter(pk=national_id_check).first()
        if chk is None:
            raise NotFound("No such identity check.")
        if chk.requested_at < ch.requested_at:
            raise RuleBlocked("The identity check must be fresh, made for this change.", code="national-id-stale",
                              blocking_reasons=[{"rule": "RUL-28", "message": "Identity check older than the change"}])
    else:
        if ch.kind == "refund_destination":
            person, role = ch.escrow.client, "client"
            subject_name = subject_name or person.full_name
        else:
            person, role = ch.payee.person, "payee"
            subject_name = subject_name or (ch.payee.person.full_name if ch.payee.person_id else ch.payee.legal_name)
        chk = request_national_id_check(by=by, country=ch.country, subject_role=role, subject_name=subject_name,
                                        id_number=id_number, person=person, context_type="payee_change",
                                        context_id=ch.pk)
    ch.national_id_check = chk
    ch.save(update_fields=["national_id_check"])
    return advance_change(ch)


def advance_change(ch: PayeeChange) -> PayeeChange:
    ch.refresh_from_db()
    if ch.status != "requested" or not _account_check_done(ch) or not _nid_done(ch):
        if ch.status == "requested" and ch.national_id_check and ch.national_id_check.result not in (
                "pending", "unavailable", "match"):
            alert_staff(ch.country, ("RV",), "payee_change_identity_failed",
                        "The identity check for a payee change failed. The change cannot go ahead.", obj=ch)
        return ch
    state.transition(ch, "payee_change", "checks_passed", reason="Account name and identity checks passed")
    if ch.escrow_id:
        client = ch.escrow.client
        old = ch.replaces_payee if ch.kind == "new_payee" else ch.payee
        if ch.kind == "refund_destination":
            text = (f"A refund of your deposit {ch.deposit_event.bank_reference} needs to go to another account in "
                    f"your own name, ending {ch.account_number[-4:]}. Approve it only if you asked for this.")
        elif ch.kind == "new_payee":
            text = (f"Your escrow {ch.escrow.reference} would pay {ch.payee.legal_name} (account ending "
                    f"{ch.payee.last4}) instead of {old.legal_name}. Approve it only if you agree.")
        elif ch.kind == "add_payee":
            text = (f"Your escrow {ch.escrow.reference} would also be able to pay {ch.payee.legal_name} (account "
                    f"ending {ch.payee.last4}). Nothing is paid without your approval of each payment. Approve it "
                    "only if you agree.")
        else:
            text = (f"{old.legal_name} asked to be paid into a new account: '{ch.account_name}' ending "
                    f"{ch.account_number[-4:]} (now ending {old.last4}). Approve it only if you agree.")
        notify(client, "payee_change_approval", text, subject="Approve a change of account", needs_action=True,
               obj=ch, link=f"/escrows/{ch.escrow_id}/payee-changes/{ch.pk}", category="approval")
    else:
        _open_staff_approval(ch)
    return ch


def _open_staff_approval(ch):
    by = ch.requested_by
    ch.approval_request = approvals.request_approval(
        "payee_change", ch.pk, by, required=2, country=ch.country,
        summary=f"Payee change ({ch.kind.replace('_', ' ')}) {ch.pk}")
    ch.save(update_fields=["approval_request"])
    state.transition(ch, "payee_change", "pending_approval")


def _client_signed(client, mfa_at, code):
    from django.conf import settings

    from accounts.services import mfa_verify

    if code:
        if not mfa_verify(client, code):
            raise MfaRequired("The code is not right. Try again.")
        return "totp_code"
    if mfa_at is None or timezone.now() - mfa_at > settings.TENMINA["MFA_FRESHNESS"]:
        raise MfaRequired()
    return "mfa_step_up"


@transaction.atomic
def client_approve_change(ch: PayeeChange, client, *, mfa_at=None, code=None, approve=True) -> PayeeChange:
    """The client approves first (RUL-28, RUL-11). For a change to a payee
    shared by many clients, each client approves the new account for their
    own escrows after it is applied (I-42)."""
    _client_signed(client, mfa_at, code)
    if ch.escrow_id is None:
        if ch.status != "applied" or ch.kind != "new_account":
            raise StateConflict("This change is not waiting for your approval.")
        escrows = [e for e in selectors.escrows_paying(ch.payee) if e.client_id == client.pk]
        if not escrows:
            raise NotFound()
        from notifications.services import resolve_action

        resolve_action(ch, person=client)
        if not approve:
            for e in escrows:
                audit(client, "payee_change.client_declined_new_account", ch, {"escrow_id": str(e.pk)})
            return ch
        for e in escrows:
            lock_payee(e, ch.payee, client_approved_at=now(), source="payee_change", change=ch)
            audit(client, "payee_change.client_approved_new_account", ch, {"escrow_id": str(e.pk)})
        return ch
    if ch.escrow.client_id != client.pk:
        raise NotFound()
    if ch.status != "checks_passed":
        raise StateConflict("This change is not waiting for your approval.")
    from notifications.services import resolve_action

    resolve_action(ch, person=client)
    if not approve:
        state.transition(ch, "payee_change", "rejected", actor=client, reason="The client declined")
        return ch
    ch.client_approved_at, ch.client_approved_by = now(), client
    ch.save(update_fields=["client_approved_at", "client_approved_by"])
    state.transition(ch, "payee_change", "client_approved", actor=client)
    _open_staff_approval(ch)
    return ch


def change_allowed(ch):
    def ok(a):
        if not has_rr(a, ch.country):
            return False
        if a.pk in (ch.requested_by_id, ch.client_approved_by_id):
            return False
        if ch.payee_id and ch.payee.person_id == a.pk:
            return False
        return True

    return ok


def decide_change(ch: PayeeChange, approver, *, decision, mfa_at, note=""):
    if ch.status != "pending_approval" or ch.approval_request is None:
        raise StateConflict("This change is not waiting for staff approval. The client approves first.")
    return approvals.decide(ch.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=change_allowed(ch))


def _second_channels(client):
    chans = [c for c in ("sms", "email") if (c == "sms" and client.phone) or (c == "email" and client.email)]
    return tuple(chans) or ("email",)


@transaction.atomic
def apply_payee_change(ch: PayeeChange):
    """esc.apply_payee_change(): the only code that writes a payee's account
    columns. Raises account_version, starts the cooling-off, withdraws open
    approvals and sends the client a notice on a second channel."""
    ch.refresh_from_db()
    if ch.status != "pending_approval":
        return ch
    hours = int(setting("payee_cooling_off_hours", ch.country, 72))
    t = now()
    until = t + timedelta(hours=hours)
    token = secrets.token_urlsafe(24)
    ch.stop_token_hash = hashlib.sha256(token.encode()).hexdigest()
    if ch.kind == "new_account":
        p = Payee.objects.select_for_update().get(pk=ch.payee_id)
        ch.previous_bank_name, ch.previous_account_number, ch.previous_account_name = \
            p.bank_name, p.account_number, p.account_name
        with connection.cursor() as cur:
            cur.execute("SET LOCAL esc.apply_payee_change = 'on'")
        p.bank_name, p.account_number, p.account_name = ch.bank_name or p.bank_name, ch.account_number, ch.account_name
        p.account_number_bidx, p.account_name_norm = _acct_bidx(ch.account_number), ch.account_name_norm
        p.account_name_source, p.account_name_evidence = ch.account_name_source, ch.account_name_evidence
        p.account_name_raw_sha256 = ch.account_name_raw_sha256
        p.account_version += 1
        p.cooling_off_until = until
        p.save()
        with connection.cursor() as cur:
            cur.execute("SET LOCAL esc.apply_payee_change = 'off'")
        EscrowPayee.objects.filter(payee=p, ended_at__isnull=True).exclude(account_version=p.account_version) \
            .update(ended_at=t)
        if ch.escrow_id:
            lock_payee(ch.escrow, p, client_approved_at=ch.client_approved_at, source="payee_change", change=ch)
        _withdraw_live_instructions(p, None, "The payee's account changed (RUL-28)")
    elif ch.kind == "new_payee":
        EscrowPayee.objects.filter(escrow=ch.escrow, payee=ch.replaces_payee, ended_at__isnull=True).update(ended_at=t)
        lock_payee(ch.escrow, ch.payee, client_approved_at=ch.client_approved_at, source="payee_change", change=ch)
        for ins in ReleaseInstruction.objects.filter(escrow=ch.escrow, payee=ch.replaces_payee, status__in=[
                "awaiting_client", "pending_approval", "approved"]):
            from .services import withdraw_instruction

            withdraw_instruction(ins, None, reason="The payee was replaced (RUL-28)", system=True)
    elif ch.kind == "add_payee":
        lock_payee(ch.escrow, ch.payee, client_approved_at=ch.client_approved_at, source="payee_change", change=ch)
    elif ch.kind == "refund_destination":
        ins = ReleaseInstruction.objects.filter(refund_source_event=ch.deposit_event, status__in=[
            "awaiting_client", "pending_approval"]).first()
        if ins is not None:
            ins.refund_change = ch
            ins.save(update_fields=["refund_change"])
    ch.applied_at, ch.cooling_off_until = t, until
    clients = [ch.escrow.client] if ch.escrow_id else list({e.client for e in selectors.escrows_paying(ch.payee)})
    msg_id = None
    for client in clients:
        what = "the refund account" if ch.kind == "refund_destination" else \
            f"the account of {(ch.payee.legal_name if ch.payee_id else '')}"
        body = (f"Tenmina approved a change to {what}, now ending {ch.account_number[-4:] if ch.account_number else ''}"
                f". Nothing is paid to it before {timezone.localtime(until):%d %B %Y %H:%M %Z}. If you did not "
                f"expect this, stop it now: /payee-changes/{ch.pk}/stop?token={token}")
        msgs = notify(client, "payee_change_notice", body, subject="An account change on your money",
                      channels=_second_channels(client), category="safety", obj=ch, needs_action=False)
        if msgs and msg_id is None:
            msg_id = msgs[0].pk
        if ch.escrow_id is None:
            notify(client, "payee_change_approval",
                   f"{ch.payee.legal_name} has a new account. Approve it for your escrow before any payment to it.",
                   needs_action=True, obj=ch, link=f"/payee-changes/{ch.pk}", category="approval")
    if msg_id is None:
        import uuid

        msg_id = uuid.uuid4()  # no client to tell (a shared payee with no open escrow); recorded for the audit
    ch.second_channel_message_id = msg_id
    ch.save(update_fields=["previous_bank_name", "previous_account_number", "previous_account_name", "applied_at",
                           "cooling_off_until", "second_channel_message_id", "stop_token_hash"])
    state.transition(ch, "payee_change", "applied", event="payee_change.applied",
                     payload={"change_id": ch.pk, "kind": ch.kind, "payee_id": ch.payee_id,
                              "escrow_id": ch.escrow_id, "cooling_off_until": until})
    ch._stop_token = token  # for the caller (tests, seed); never stored in plain text
    return ch


@transaction.atomic
def stop_change(ch: PayeeChange, by, *, token="", mfa_at=None, code=None, reason="") -> PayeeChange:
    """During the cooling-off the client (single-use link with MFA) or a
    reviewer stops an applied change; the payee is suspended for review."""
    ch.refresh_from_db()
    if ch.status != "applied" or not ch.cooling_off_until or ch.cooling_off_until <= now():
        raise StateConflict("Only an applied change can be stopped, and only during its cooling-off.")
    is_rv = has_role(by, "RV", country=ch.country)
    if not is_rv:
        clients = {ch.escrow.client_id} if ch.escrow_id else {e.client_id for e in selectors.escrows_paying(ch.payee)}
        if by.pk not in clients:
            raise NotFound()
        if token and hashlib.sha256(token.encode()).hexdigest() != ch.stop_token_hash:
            raise Forbidden("This stop link is not valid.")
        _client_signed(by, mfa_at, code)
    ch.stopped_by, ch.stopped_at, ch.stop_reason = by, now(), reason or "Stopped during the cooling-off"
    ch.stop_token_hash = ""
    ch.save(update_fields=["stopped_by", "stopped_at", "stop_reason", "stop_token_hash"])
    state.transition(ch, "payee_change", "stopped", actor=by, event="payee_change.stopped",
                     payload={"change_id": ch.pk, "payee_id": ch.payee_id, "escrow_id": ch.escrow_id})
    if ch.payee_id:
        suspend_payee(ch.payee, by, f"Payee change stopped: {ch.stop_reason}", system=True)
    if ch.kind == "refund_destination":
        ReleaseInstruction.objects.filter(refund_change=ch, status__in=["awaiting_client", "pending_approval"]) \
            .update(refund_change=None)
    alert_staff(ch.country, ("RV",), "payee_change_stopped",
                "A payee change was stopped during its cooling-off. Nothing is paid to either account until a "
                "reviewer decides.", obj=ch, link=f"/back-office/payee-changes/{ch.pk}")
    return ch


def on_change_approval(ch: PayeeChange, approved: bool):
    if approved:
        return apply_payee_change(ch)
    if ch.status == "pending_approval":
        state.transition(ch, "payee_change", "rejected", reason="A staff member rejected the change")
    return ch


@transaction.atomic
def withdraw_change(ch: PayeeChange, by) -> PayeeChange:
    if by.pk != ch.requested_by_id and not has_role(by, "RV", country=ch.country):
        raise Forbidden("Only the requester or a reviewer withdraws a change.")
    if ch.status not in ("requested", "checks_passed", "client_approved", "pending_approval"):
        raise StateConflict("This change can no longer be withdrawn.")
    if ch.approval_request_id and ch.approval_request.status == "open":
        approvals.withdraw(ch.approval_request, by)
    return state.transition(ch, "payee_change", "withdrawn", actor=by)


def ensure_staff(by, country):
    if not has_role(by, *STAFF, country=country):
        raise Forbidden()


__all__ = ["create_payee", "update_payee", "prepare_verification", "decide_verification", "apply_verification",
           "suspend_payee", "reinstate_payee", "lock_payee", "request_change", "check_change_account",
           "change_identity_check", "client_approve_change", "decide_change", "apply_payee_change", "stop_change",
           "withdraw_change", "DomainError"]
