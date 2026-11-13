"""FEE Payments to institutions: the public interface other modules may call.

Everything here is behind the `lines.fee` flag (06 2.6). Tenmina never holds
the money: on the `client_direct` route the client pays the institution's
verified account directly; on the `held_funds` route the partner bank pays the
institution's verified payee record after the client and two staff approve
(RUL-05, RUL-11, RUL-22). There is no cash route (FR-FEE-006).

Institutions (FR-FEE-001, FR-FEE-006)
    register_institution(by, *, country, type, legal_name, ...) -> (Institution, created)
    add_contact(inst, by, *, full_name, ...) / remove_contact(contact, by, reason)
    create_payee(inst, by, *, bank_name, account_number, ...) -> esc Payee (kind institution)
    prepare_payee_verification(inst, by)            # two other staff approve on /v1/payees/{id}
    try_verify(inst) -> list of what is still missing
    propose_not_eligible(inst, by, reason) / decide_not_eligible(inst, by, confirm=True)
    review_look_alike(inst, by, decision, note) / reopen(inst, by, reason)
    add_beneficiary(client, inst, family_member, institution_account_ref="") -> Beneficiary
Invoices (FR-FEE-002, FR-FEE-003)
    submit_invoice(by, *, institution, family_member=None, tenmina_reference="", ...) -> Invoice
    attach_document(invoice, by, evidence, ...)     # a draft from a schedule, or a corrected bill
    contact_confirm(invoice, by) / check_invoice(invoice, by, *, outcome, ...)
    set_route(invoice, by, route, reason)
    client_approve(invoice, client, *, mfa_at, code, confirm_amount, confirm_payee_account_name) -> dict
    client_decline(invoice, client, reason) / cancel_invoice(invoice, by, reason)
    prepare_instruction(invoice, by) -> Payment     # held_funds route only
Payments and receipts (FR-FEE-003, FR-FEE-004)
    report_client_payment(payment, client, *, paid_on, reference, evidence)
    confirm_received(payment, by, *, method, amount, ...)
    add_receipt(payment, by, *, receipt_evidence, confirmation_evidence=None)
Schedules, runners and statements (FR-FEE-005 to FR-FEE-007)
    create_schedule / update_schedule / set_schedule_status
    create_runner_task / complete_runner_task / cancel_runner_task
    statement(client, family_member) -> dict / statement_pdf(client, family_member) -> Statement
Jobs (02 7.12): schedule_due(), receipt_overdue(), institution_reverify()

Events published: institution.verified, invoice.submitted, invoice.client_approved, fee_payment.receipted,
fee_schedule.due (plus <entity>.status_changed from each state change).
Events consumed: case.status_changed, release.confirmed, release.withdrawn, release.rejected,
release.rejected_by_bank, held_funds.deposit_confirmed, payee.verified, payee.suspended, payee.status_changed,
payee_change.applied, submission.received.
"""
from datetime import datetime, time
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.utils import timezone

from administration import flags
from core import state
from core.errors import DomainError, Forbidden, Invalid, MfaRequired, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from .common import (STAFF, add_period, alert_staff, audit, cfg, days, fmt, is_staff, log, new_reference, notify,
                     now, resolve_action, setting, staff_in, today)
from .models import (INSTITUTION_TYPES, ROUTES, Beneficiary, ClientInstitution, Institution, InstitutionContact,
                     Invoice, Payment, RunnerTask, Schedule, Statement)

NOT_ELIGIBLE_TEXT = ("This institution cannot receive a bank transfer, so Tenmina cannot pay it. "
                     "We never pay in cash.")
LIVE_PAYMENT = ("awaiting_client_payment", "client_reported", "instructed", "paid", "receipted", "receipt_overdue")


# ----------------------------------------------------------------- helpers

def _on(country):
    flags.require("lines.fee", country)
    flags.read_only_guard()


def _staff(by, country, roles=STAFF, msg="Only Tenmina staff can do this."):
    if not is_staff(by, country, roles):
        raise Forbidden(msg)


def institution_types(country) -> list[str]:
    return list(cfg(country, "fees.institution_types", INSTITUTION_TYPES) or INSTITUTION_TYPES)


def default_route(country) -> str:
    """The country's payment route (`fees.payment_route`, default `client_direct`: verify and confirm)."""
    route = cfg(country, "fees.payment_route", "client_direct")
    return route if route in ROUTES else "client_direct"


def receipt_target_days(country) -> int:
    return int(setting("receipt_target_days", country, 10) or 10)


def _norm(name):
    from accounts.normalise import normalise_name

    return normalise_name(name)


def _bidx(value):
    from accounts.normalise import bidx

    return bidx(value)


def _reg_norm(number):
    return "".join(ch for ch in (number or "").upper() if ch.isalnum())


def _person_label(p):
    return getattr(p, "full_name", "") or "Tenmina"


def _evidence_ok(evidence, by, country):
    """The caller may use this evidence: they uploaded it, or they may view it."""
    from evidence import access

    if evidence is None:
        return None
    if evidence.country_id != country.pk:
        raise Invalid("This file belongs to another country.", code="validation-error")
    if evidence.uploaded_by_id != by.pk and not access.can_view(by, evidence):
        raise Invalid("That file was not found.", code="validation-error")
    return evidence


def _link(evidence, subject_type, subject_id, role, by):
    from evidence.services import link

    return link(evidence, subject_type, subject_id, role=role, by=by)


def _clients_of(inst):
    from accounts.models import Person

    return Person.objects.filter(pk__in=ClientInstitution.objects.filter(institution=inst).values("client"))


def active_contacts(inst, *, confirm=None, receipts=None):
    qs = InstitutionContact.objects.filter(institution=inst, status="active")
    if confirm:
        qs = qs.filter(may_confirm_invoices=True)
    if receipts:
        qs = qs.filter(may_send_receipts=True)
    return qs


def contact_for(person, inst) -> InstitutionContact | None:
    if person is None or not getattr(person, "is_authenticated", False):
        return None
    return InstitutionContact.objects.filter(institution=inst, person=person, status="active").first()


def _payee_ok(inst) -> bool:
    p = inst.payee
    return p is not None and p.verification_status == "verified" and p.name_match == "matched"


def eligibility_reasons(inst) -> list[dict]:
    """Why an invoice for this institution cannot be checked, approved or paid now (FR-FEE-001, FR-FEE-006)."""
    inst.refresh_from_db()
    if inst.status == "not_eligible":
        return [{"rule": "FR-FEE-006", "code": "institution-not-eligible", "message": NOT_ELIGIBLE_TEXT}]
    if inst.status != "verified":
        return [{"rule": "FR-FEE-001", "code": "institution-not-verified",
                 "message": f"{inst.legal_name} is not verified yet ({inst.status.replace('_', ' ')})."}]
    if not _payee_ok(inst):
        return [{"rule": "RUL-22", "code": "payee-not-verified",
                 "message": f"The bank account of {inst.legal_name} is not verified."}]
    return []


def _require_eligible(inst, what):
    reasons = eligibility_reasons(inst)
    if reasons:
        code = reasons[0]["code"]
        raise RuleBlocked(f"{what}: {reasons[0]['message']}", code=code, blocking_reasons=reasons)


# ----------------------------------------------------------------- institutions (FR-FEE-001)

def _similar(a: str, b: str) -> bool:
    """A look-alike: a name one or two letters different (TC-SEC-33)."""
    from difflib import SequenceMatcher

    if not a or not b or a == b:
        return False
    if abs(len(a) - len(b)) > 3:
        return False
    return SequenceMatcher(None, a, b).ratio() >= 0.88


def _link_client(client, inst):
    if client is not None and client.has_tenmina_role("CL"):
        ClientInstitution.objects.get_or_create(client=client, institution=inst)


@transaction.atomic
def register_institution(by, *, country, type, legal_name, registration_number="", address="", phone="", email="",
                         returns_confirmation=False, invoice_channel="manual_upload", proposed_bank_name="",
                         proposed_account_number="", proposed_account_name="", registration_evidence=None,
                         organisation=None, client=None) -> tuple[Institution, bool]:
    """US-FEE-001 AC1: saved Unverified; no payment can be made until Tenmina verifies its registration, its
    account in its own name and a named contact. A duplicate links to the existing record; a look-alike name is
    flagged for a reviewer (TC-FEE-001-04, TC-SEC-33)."""
    from cases.services import open_case

    _on(country)
    staff = is_staff(by, country, ("CM", "RV"))
    if not staff and not by.has_tenmina_role("CL"):
        raise Forbidden("A client or a case manager registers an institution.")
    client = client if staff else by
    if type not in institution_types(country):
        raise Invalid(f"'{type}' is not an institution type in {country.name}. Choose one of: "
                      f"{', '.join(institution_types(country))}.", code="validation-error")
    if not (legal_name or "").strip():
        raise Invalid("Enter the institution's registered name.", code="validation-error")
    norm, reg = _norm(legal_name), _reg_norm(registration_number)
    existing = None
    if reg:
        existing = Institution.objects.filter(country=country, registration_number_norm=reg).first()
    existing = existing or Institution.objects.filter(country=country, legal_name_bidx=_bidx(norm)).first()
    if existing is not None:
        _link_client(client, existing)
        audit(by, "institution.duplicate_linked", existing, {"registration_number": reg})
        return existing, False
    if registration_evidence is not None:
        _evidence_ok(registration_evidence, by, country)
    inst = Institution.objects.create(
        country=country, type=type, legal_name=legal_name.strip(), legal_name_norm=norm, legal_name_bidx=_bidx(norm),
        registration_number=(registration_number or "").strip(), registration_number_norm=reg,
        registration_evidence=registration_evidence, address=address or "", phone=phone or "", email=email or "",
        organisation=organisation, returns_confirmation=bool(returns_confirmation),
        invoice_channel=invoice_channel or "manual_upload", proposed_bank_name=proposed_bank_name or "",
        proposed_account_number="".join((proposed_account_number or "").split()),
        proposed_account_name=proposed_account_name or "", added_by_client=client if client else None,
        created_by=by)
    _link_client(client, inst)
    if registration_evidence is not None:
        _link(registration_evidence, "institution", inst.pk, "registration_certificate", by)
    for other in Institution.objects.filter(country=country).exclude(pk=inst.pk).only("pk", "legal_name_norm",
                                                                                    "legal_name"):
        if _similar(norm, other.legal_name_norm):
            inst.look_alike_of, inst.look_alike_status = other, "open"
            inst.save(update_fields=["look_alike_of", "look_alike_status"])
            audit(by, "institution.look_alike_flagged", inst, {"similar_to": str(other.pk)})
            alert_staff(country, ("RV",), "institution_look_alike",
                        f"'{inst.legal_name}' looks like '{other.legal_name}', which is already registered. Check "
                        "it is not an impersonation before it can be verified.", obj=inst,
                        link=f"/back-office/institutions/{inst.pk}")
            break
    case = open_case("institution_verification", country, subject_type="institution", subject_id=inst.pk,
                     client=client, actor=by, title=f"Institution verification: {inst.legal_name}")
    inst.verification_case = case
    inst.save(update_fields=["verification_case"])
    audit(by, "institution.registered", inst, {"type": type, "case_id": str(case.pk)})
    publish("institution.registered", inst.pk, {"institution_id": inst.pk, "country": country.code,
                                                "case_id": case.pk, "client_id": getattr(client, "pk", None)})
    if client is not None:
        notify(client, "institution_registered",
               f"We are checking {inst.legal_name}: its registration, its bank account in its own name and a named "
               "contact. You can upload bills now; nothing is paid until it is verified.", obj=inst,
               link=f"/institutions/{inst.pk}", channels=("in_app",))
    return inst, True


def _is_runner_or_staff(person):
    return person is not None and person.has_tenmina_role("CM", "RV", "AD", "RN")


@transaction.atomic
def add_contact(inst: Institution, by, *, full_name, phone="", email="", role_title="", person=None,
                may_confirm_invoices=True, may_send_receipts=True, evidence=None) -> InstitutionContact:
    """FR-FEE-001: a named contact at the institution who confirms invoices and sends receipts. Never a
    relative or representative of a client who pays this institution, never Tenmina staff (RUL-22, TC-RUL-22-03)."""
    from accounts.selectors import is_relative_or_representative

    _on(inst.country)
    _staff(by, inst.country, ("CM", "RV"), "Only a case manager names the institution's contact.")
    if not (full_name or "").strip():
        raise Invalid("Enter the contact's name.", code="validation-error")
    if _is_runner_or_staff(person):
        raise RuleBlocked("Tenmina staff and runners cannot be an institution's contact.", code="contact-refused",
                          blocking_reasons=[{"rule": "RUL-22", "message": "Staff or runner as contact"}])
    for client in _clients_of(inst):
        if is_relative_or_representative(client, person=person, name=full_name, phone=phone):
            audit(by, "institution.contact_refused", inst, {"reason": "relative_or_representative"})
            alert_staff(inst.country, ("RV",), "institution_contact_refused",
                        f"A contact named for {inst.legal_name} matches a family member or representative of a "
                        "client who pays it. It was refused.", obj=inst)
            raise RuleBlocked("This contact matches a family member or representative of a client who pays this "
                              "institution. The named contact must be the institution's own staff.",
                              code="contact-refused",
                              blocking_reasons=[{"rule": "RUL-22", "message": "Contact is a relative or "
                                                                              "representative of a client"}])
    if evidence is not None:
        _evidence_ok(evidence, by, inst.country)
    c = InstitutionContact.objects.create(
        institution=inst, person=person, full_name=full_name.strip(), phone=phone or "", email=email or "",
        role_title=role_title or "", may_confirm_invoices=bool(may_confirm_invoices),
        may_send_receipts=bool(may_send_receipts), confirmation_evidence=evidence, added_by=by)
    if evidence is not None:
        _link(evidence, "institution", inst.pk, "contact_confirmation", by)
    if person is not None and not person.has_tenmina_role("IC"):
        from accounts.services import grant_role

        try:
            grant_role(person, "IC", country=inst.country, organisation=inst.organisation, granted_by=by)
        except DomainError as exc:
            raise RuleBlocked(f"This person cannot be an institution contact: {exc.detail}",
                              code="contact-refused") from None
    audit(by, "institution.contact_added", inst, {"contact_id": str(c.pk), "has_account": person is not None})
    try_verify(inst)
    return c


@transaction.atomic
def remove_contact(c: InstitutionContact, by, reason="") -> InstitutionContact:
    _staff(by, c.institution.country, ("CM", "RV"))
    if c.status != "active":
        return c
    c.status, c.removed_at, c.removed_reason = "removed", now(), reason or ""
    c.save(update_fields=["status", "removed_at", "removed_reason"])
    audit(by, "institution.contact_removed", c.institution, {"contact_id": str(c.pk), "reason": reason})
    return c


@transaction.atomic
def create_payee(inst: Institution, by, *, bank_name, account_number, account_name="", account_name_source,
                 account_name_evidence=None, legal_name_evidence=None, signatory_name="", signatory_id_number="",
                 national_id_check=None, contact_email="", contact_phone="", signatory=None):
    """The institution's account in its own name, as the bank states it (FR-FEE-001, FR-ESC-015). The payee
    record lives in the escrow payee registry (ADR-17); two other staff verify it there."""
    from accounts.services import request_national_id_check
    from escrow import services as esc

    _on(inst.country)
    _staff(by, inst.country, ("CM", "RV"), "Only a case manager records the institution's bank account.")
    if inst.payee_id:
        raise StateConflict("This institution already has a bank account on record. A change goes through a payee "
                            "change request (RUL-28).", code="payee-exists")
    if inst.status == "not_eligible":
        raise StateConflict("This institution is marked not eligible. Reopen it first.")
    ev = legal_name_evidence or inst.registration_evidence
    if ev is None:
        raise Invalid("Attach the registration certificate that shows the institution's legal name.",
                      code="validation-error")
    _evidence_ok(ev, by, inst.country)
    if account_name_evidence is not None:
        _evidence_ok(account_name_evidence, by, inst.country)
    if national_id_check is None and signatory_id_number:
        national_id_check = request_national_id_check(
            by=by, country=inst.country, subject_role="signatory", subject_name=signatory_name or inst.legal_name,
            id_number=signatory_id_number, person=signatory, context_type="institution", context_id=inst.pk)
    payee = esc.create_payee(by, country=inst.country, kind="institution", subject_type="institution",
                             subject_id=inst.pk, legal_name=inst.legal_name, legal_name_evidence=ev,
                             bank_name=bank_name, account_number=account_number, account_name=account_name,
                             account_name_source=account_name_source, account_name_evidence=account_name_evidence,
                             person=signatory, organisation=inst.organisation, national_id_check=national_id_check,
                             contact_email=contact_email or inst.email, contact_phone=contact_phone or inst.phone)
    inst.payee = payee
    inst.save(update_fields=["payee"])
    if payee.account_name_evidence_id:
        _link(payee.account_name_evidence, "institution", inst.pk, "bank_letter", by)
    audit(by, "institution.payee_recorded", inst, {"payee_id": str(payee.pk), "name_match": payee.name_match})
    if payee.name_match != "matched":
        for client in _clients_of(inst):
            notify(client, "institution_account_mismatch",
                   f"The bank says the account given for {inst.legal_name} is in another name. We cannot pay it. "
                   "We have asked the institution for an account in its own name.", obj=inst,
                   link=f"/institutions/{inst.pk}", channels=("in_app",))
    return payee


def prepare_payee_verification(inst: Institution, by):
    from escrow import services as esc

    _on(inst.country)
    if inst.payee is None:
        raise StateConflict("Record the institution's bank account first.")
    return esc.prepare_verification(inst.payee, by)


def verification_checklist(inst: Institution) -> list[dict]:
    """What is done and what is missing before the institution is verified (TC-FEE-001-01, -03)."""
    case = inst.verification_case
    payee = inst.payee
    contact = active_contacts(inst, confirm=True).first()
    items = [
        {"key": "registration", "label": "Registration checked with the regulator",
         "done": bool(case and case.status == "completed" and case.outcome == "verified"),
         "detail": (case.outcome_note if case and case.outcome == "not_verified" else "")},
        {"key": "bank_account", "label": "Bank account in the institution's own name",
         "done": bool(payee and payee.verification_status == "verified" and payee.name_match == "matched"),
         "detail": ("The bank's account name does not match the institution." if payee and
                    payee.name_match != "matched" else (payee.verification_status if payee else "not recorded"))},
        {"key": "named_contact", "label": "A named contact who confirms invoices", "done": contact is not None,
         "detail": contact.full_name if contact else ""},
        {"key": "look_alike", "label": "Not a look-alike of another institution",
         "done": inst.look_alike_status in ("", "cleared"), "detail": inst.look_alike_status},
    ]
    return items


@transaction.atomic
def try_verify(inst: Institution, actor=None) -> list[dict]:
    """Verified only when all three checks pass, each by its own evidence, and two staff verified the account
    (RUL-22, FR-FEE-001). Returns what is still missing."""
    inst = Institution.objects.select_for_update().get(pk=inst.pk)
    missing = [i for i in verification_checklist(inst) if not i["done"]]
    if missing or inst.status not in ("pending", "suspended"):
        return missing
    inst.verified_at, inst.status_reason = now(), ""
    state.transition(inst, "fee_institution", "verified", actor=actor, event="institution.verified",
                     extra_fields=["verified_at", "status_reason"],
                     payload={"institution_id": inst.pk, "payee_id": inst.payee_id, "country": inst.country.code})
    for client in _clients_of(inst):
        notify(client, "institution_verified",
               f"{inst.legal_name} is verified: its registration, its bank account in its own name and a named "
               "contact. Bills from it can now be checked and paid to that account only.", obj=inst,
               link=f"/institutions/{inst.pk}", channels=("in_app", "email"))
    return []


def _open_new_case(inst, actor, reason):
    from cases.services import open_case

    client = inst.added_by_client
    case = open_case("institution_verification", inst.country, subject_type="institution", subject_id=inst.pk,
                     client=client, actor=actor, title=f"Institution re-verification: {inst.legal_name}")
    inst.verification_case = case
    inst.save(update_fields=["verification_case"])
    audit(actor, "institution.reverification_opened", inst, {"case_id": str(case.pk), "reason": reason})
    return case


@transaction.atomic
def on_case_status_changed(payload: dict):
    """The verification case finished: verified or not verified (CASE decide_verification)."""
    if payload.get("product_line") != "institution_verification" or payload.get("subject_type") != "institution":
        return
    if payload.get("to") != "completed":
        return
    inst = Institution.objects.filter(pk=payload.get("subject_id")).first()
    if inst is None or (inst.verification_case_id and str(inst.verification_case_id) != str(payload.get("case_id"))):
        return
    if payload.get("outcome") == "verified":
        try_verify(inst)
        return
    if inst.status in ("pending", "suspended", "verified"):
        from cases.models import Case

        case = Case.objects.filter(pk=payload.get("case_id")).first()
        inst.status_reason = (case.outcome_note if case else "") or "The checks did not pass."
        if inst.status == "verified":
            state.transition(inst, "fee_institution", "pending", reason="Re-verification failed",
                             extra_fields=["status_reason"])
        state.transition(inst, "fee_institution", "not_verified", reason=inst.status_reason,
                         extra_fields=["status_reason"])
        for client in _clients_of(inst):
            notify(client, "institution_not_verified",
                   f"We could not verify {inst.legal_name}: {inst.status_reason} Tenmina cannot pay it.",
                   obj=inst, link=f"/institutions/{inst.pk}", channels=("in_app", "email"))


def _withdraw_live_instructions(inst, reason):
    from escrow import services as esc

    for p in Payment.objects.filter(invoice__institution=inst, route="held_funds", status="instructed") \
            .select_related("release_instruction"):
        ins = p.release_instruction
        if ins and ins.status in ("draft", "awaiting_client", "pending_approval", "approved"):
            esc.withdraw_instruction(ins, None, reason=reason, system=True)


@transaction.atomic
def on_payee_status(payee_id, to, reason=""):
    """RUL-22, US-FEE-001 AC3: when the account is suspended or reset, the institution is not payable
    until it is checked again."""
    inst = Institution.objects.filter(payee_id=payee_id).first()
    if inst is None:
        return
    if to == "verified":
        try_verify(inst)
        return
    if inst.status != "verified":
        return
    target = "suspended" if to in ("suspended", "revoked") else "pending"
    inst.status_reason = reason or ("The institution's bank account is suspended." if target == "suspended" else
                                    "The institution's bank account is being checked again.")
    state.transition(inst, "fee_institution", target, reason=inst.status_reason, extra_fields=["status_reason"])
    for client in _clients_of(inst):
        notify(client, "institution_paused",
               f"Payments to {inst.legal_name} are paused: {inst.status_reason}", obj=inst,
               link=f"/institutions/{inst.pk}", channels=("in_app",))


@transaction.atomic
def on_payee_account_changed(payee_id):
    """US-FEE-001 AC3, TC-RUL-22-04: a verified institution whose bank account changed returns to Unverified
    until a new verification case passes."""
    inst = Institution.objects.filter(payee_id=payee_id).first()
    if inst is None or inst.status not in ("verified", "suspended"):
        return
    inst.status_reason = "The institution's bank account changed. We are checking it again."
    state.transition(inst, "fee_institution", "pending", reason=inst.status_reason, extra_fields=["status_reason"])
    _open_new_case(inst, None, "bank account changed")
    for client in _clients_of(inst):
        notify(client, "institution_paused", f"Payments to {inst.legal_name} are paused: {inst.status_reason}",
               obj=inst, link=f"/institutions/{inst.pk}", channels=("in_app",))


@transaction.atomic
def propose_not_eligible(inst: Institution, by, reason) -> Institution:
    """FR-FEE-006 step one: a case manager records that the institution cannot receive a bank transfer into an
    account in its own name. A reviewer checks it."""
    _on(inst.country)
    _staff(by, inst.country, ("CM",), "A case manager records this; a reviewer checks it.")
    if not (reason or "").strip():
        raise Invalid("Say why the institution cannot receive a bank transfer.", code="validation-error")
    if inst.status == "not_eligible":
        raise StateConflict("This institution is already marked not eligible.")
    inst.eligibility_proposed_by, inst.eligibility_proposed_at = by, now()
    inst.eligibility_proposed_reason = reason.strip()
    inst.save(update_fields=["eligibility_proposed_by", "eligibility_proposed_at", "eligibility_proposed_reason"])
    audit(by, "institution.not_eligible_proposed", inst, {"reason": reason})
    alert_staff(inst.country, ("RV",), "institution_eligibility_check",
                f"{inst.legal_name} is proposed as not eligible for direct payment: {reason}. Please check.",
                obj=inst, exclude=(by.pk,))
    return inst


@transaction.atomic
def decide_not_eligible(inst: Institution, by, *, confirm=True, note="") -> Institution:
    """FR-FEE-006 step two: a reviewer, not the case manager who proposed it, confirms or sends it back."""
    _on(inst.country)
    _staff(by, inst.country, ("RV",), "Only a reviewer checks this.")
    inst.refresh_from_db()
    if not inst.eligibility_proposed_at:
        raise StateConflict("Nothing is waiting for a check.")
    if inst.eligibility_proposed_by_id == by.pk:
        from core.errors import SameApprover

        raise SameApprover("The person who proposed this cannot check it.")
    if not confirm:
        audit(by, "institution.not_eligible_declined", inst, {"note": note})
        inst.eligibility_proposed_by = None
        inst.eligibility_proposed_at = None
        inst.eligibility_proposed_reason = ""
        inst.save(update_fields=["eligibility_proposed_by", "eligibility_proposed_at", "eligibility_proposed_reason"])
        return inst
    inst.not_eligible_reason = inst.eligibility_proposed_reason
    inst.eligibility_checked_by = by
    inst.status_reason = NOT_ELIGIBLE_TEXT
    state.transition(inst, "fee_institution", "not_eligible", actor=by, reason=inst.not_eligible_reason,
                     extra_fields=["not_eligible_reason", "eligibility_checked_by", "status_reason"],
                     payload={"institution_id": inst.pk})
    _withdraw_live_instructions(inst, "The institution is not eligible for direct payment.")
    for client in _clients_of(inst):
        notify(client, "institution_not_eligible", f"{inst.legal_name}: {NOT_ELIGIBLE_TEXT}", obj=inst,
               link=f"/institutions/{inst.pk}", channels=("in_app", "email"))
    return inst


@transaction.atomic
def review_look_alike(inst: Institution, by, *, decision, note) -> Institution:
    """TC-SEC-33: a reviewer clears a look-alike name, or confirms an impersonation (not verified)."""
    _staff(by, inst.country, ("RV",), "Only a reviewer decides on a look-alike.")
    if inst.look_alike_status != "open":
        raise StateConflict("No look-alike review is open for this institution.")
    if decision not in ("cleared", "confirmed") or not (note or "").strip():
        raise Invalid("Decide cleared or confirmed, and say why.", code="validation-error")
    inst.look_alike_status, inst.look_alike_reviewed_by = decision, by
    inst.save(update_fields=["look_alike_status", "look_alike_reviewed_by"])
    audit(by, "institution.look_alike_" + decision, inst, {"note": note})
    if decision == "confirmed" and inst.status == "pending":
        inst.status_reason = "This looks like an impersonation of another institution. Tenmina will not pay it."
        state.transition(inst, "fee_institution", "not_verified", actor=by, reason=note,
                         extra_fields=["status_reason"])
    else:
        try_verify(inst, by)
    return inst


@transaction.atomic
def reopen(inst: Institution, by, reason) -> Institution:
    """A not-eligible or not-verified institution starts a new verification (e.g. it opened an account in its
    own name)."""
    _on(inst.country)
    _staff(by, inst.country, ("CM", "RV"))
    if inst.status not in ("not_eligible", "not_verified", "suspended"):
        raise StateConflict("Only a not eligible, not verified or suspended institution is reopened.")
    if not (reason or "").strip():
        raise Invalid("Say why it is checked again.", code="validation-error")
    inst.status_reason = "We are checking this institution again."
    inst.eligibility_proposed_by = None
    inst.eligibility_proposed_at = None
    inst.eligibility_proposed_reason = ""
    state.transition(inst, "fee_institution", "pending", actor=by, reason=reason,
                     extra_fields=["status_reason", "eligibility_proposed_by", "eligibility_proposed_at",
                                   "eligibility_proposed_reason"])
    _open_new_case(inst, by, reason)
    return inst


@transaction.atomic
def add_beneficiary(client, inst: Institution, family_member, *, institution_account_ref="") -> Beneficiary:
    """The pupil or patient: a registered family member of the client, never the payee."""
    from accounts.selectors import active_family_member

    _on(inst.country)
    fm = active_family_member(client, getattr(family_member, "pk", family_member))
    b = Beneficiary.objects.filter(family_member=fm, institution=inst, status="active").first()
    if b is not None:
        if institution_account_ref and b.institution_account_ref != institution_account_ref:
            b.institution_account_ref = institution_account_ref
            b.save(update_fields=["institution_account_ref"])
        return b
    _link_client(client, inst)
    for _ in range(5):
        ref = new_reference("TMF", inst.country)
        if not Beneficiary.objects.filter(tenmina_reference=ref).exists():
            break
    b = Beneficiary.objects.create(country=inst.country, client=client, family_member=fm, institution=inst,
                                   institution_account_ref=institution_account_ref or "", tenmina_reference=ref)
    audit(client, "fee.beneficiary_added", inst, {"family_member_id": str(fm.pk), "reference": ref})
    return b


# ----------------------------------------------------------------- invoices (FR-FEE-002)

def _invoice_currencies(country):
    return {country.currency, *(cfg(country, "fees.invoice_currencies", []) or [])}


def compute_flags(inv: Invoice) -> list[dict]:
    """What the document says against the records (TC-FEE-002-03, TC-SEC-34). An account other than the verified
    one can never be resolved by staff: the institution must reissue the bill (US-FEE-002 AC3)."""
    out = []
    fm, inst = inv.family_member, inv.institution
    if inv.name_on_invoice and _norm(inv.name_on_invoice) != _norm(fm.full_name):
        b = Beneficiary.objects.filter(family_member=fm, institution=inst, status="active").first()
        if not (b and b.institution_account_ref and _norm(inv.name_on_invoice) == _norm(b.institution_account_ref)):
            out.append({"code": "names-another-person", "resolvable": True,
                        "message": f"The bill names '{inv.name_on_invoice}', not {fm.full_name}."})
    if inv.institution_name_on_invoice and _norm(inv.institution_name_on_invoice) != inst.legal_name_norm:
        out.append({"code": "institution-name-differs", "resolvable": True,
                    "message": f"The bill is headed '{inv.institution_name_on_invoice}', not {inst.legal_name}."})
    stated = "".join(ch for ch in (inv.account_number_on_invoice or "") if ch.isalnum())
    if stated and inst.payee_id and stated != inst.payee.account_number and not (
            len(stated) <= 4 and inst.payee.account_number.endswith(stated)):
        out.append({"code": "account-not-verified", "resolvable": False,
                    "message": "The bill names a bank account other than the institution's verified account. "
                               "It cannot be paid; ask the institution to reissue it."})
    return out


def _resolve_submitter(by, inst, client):
    if client is not None and by.pk == client.pk:
        return "client"
    if contact_for(by, inst) is not None:
        return "institution_contact"
    if is_staff(by, inst.country, ("CM", "RV")):
        return "case_manager"
    if by.has_tenmina_role("RN") and RunnerTask.objects.filter(runner=by, institution=inst, kind="collect_invoice",
                                                               status="open").exists():
        return "runner"
    return None


@transaction.atomic
def submit_invoice(by, *, institution, institution_reference, amount, currency=None, family_member=None,
                   tenmina_reference="", due_on=None, description="", name_on_invoice="",
                   institution_name_on_invoice="", account_number_on_invoice="", evidence=None,
                   _runner_task=None) -> Invoice:
    """US-FEE-002: a bill with its reference, checked against the institution and the family member. The client,
    the institution's named contact (quoting Tenmina's reference), a case manager or a runner submits it."""
    from accounts.selectors import active_family_member

    inst = institution
    _on(inst.country)
    if inst.status == "not_eligible":
        raise RuleBlocked(NOT_ELIGIBLE_TEXT, code="institution-not-eligible",
                          blocking_reasons=[{"rule": "FR-FEE-006", "message": inst.not_eligible_reason}])
    client = None
    if tenmina_reference:
        b = Beneficiary.objects.filter(tenmina_reference=tenmina_reference.strip().upper(), institution=inst,
                                       status="active").select_related("family_member", "client").first()
        if b is None:
            raise Invalid("We do not know that Tenmina reference for this institution.", code="unknown-reference")
        family_member, client = b.family_member, b.client
    elif family_member is not None:
        client = family_member.client
    else:
        raise Invalid("Name the family member, or quote the Tenmina reference the client gave you.",
                      code="validation-error")
    submitter = _runner_task and "runner" or _resolve_submitter(by, inst, client)
    if submitter is None:
        raise NotFound()
    if submitter == "institution_contact" and not tenmina_reference:
        raise Invalid("Quote the Tenmina reference the client gave you.", code="validation-error")
    fm = active_family_member(client, family_member.pk)
    currency = (currency or inst.country.currency).upper()
    if currency not in _invoice_currencies(inst.country):
        raise Invalid(f"Bills in {inst.country.name} are paid in {inst.country.currency}.", code="validation-error")
    amount = q(amount)
    if amount <= 0:
        raise Invalid("Enter the amount on the bill.", code="validation-error")
    if not (institution_reference or "").strip():
        raise Invalid("Enter the invoice, student or patient reference on the bill.", code="validation-error")
    if evidence is None:
        raise Invalid("Upload the bill or fee note.", code="validation-error")
    _evidence_ok(evidence, by, inst.country)
    ref = institution_reference.strip()
    if Invoice.objects.filter(institution=inst, institution_reference=ref).exclude(
            status__in=["rejected", "cancelled"]).exists():
        audit(by, "invoice.reference_reused", inst, {"reference": ref})
        raise StateConflict("A bill with this reference is already on record for this institution. It cannot be "
                            "paid twice.", code="invoice-reference-used")
    if submitter == "client":
        _link_client(client, inst)
    inv = Invoice(country=inst.country, client=client, family_member=fm, institution=inst,
                  institution_reference=ref, description=description or "", amount=amount, currency=currency,
                  due_on=due_on, name_on_invoice=name_on_invoice or "",
                  institution_name_on_invoice=institution_name_on_invoice or "",
                  account_number_on_invoice=account_number_on_invoice or "", submitted_by=submitter,
                  submitted_by_person=by, evidence=evidence, evidence_sha256=evidence.sha256,
                  route=default_route(inst.country), status="submitted")
    if submitter == "institution_contact":
        inv.contact_confirmed_by, inv.contact_confirmed_at = contact_for(by, inst), now()
    inv.check_flags = compute_flags(inv)
    inv.check_status = "flagged" if inv.check_flags else "pending"
    try:
        with transaction.atomic():
            inv.save(force_insert=True)
    except IntegrityError as exc:
        raise StateConflict("A bill with this reference is already on record for this institution.",
                            code="invoice-reference-used") from exc
    _link(evidence, "fee_invoice", inv.pk, "invoice", by)
    if not Beneficiary.objects.filter(family_member=fm, institution=inst, status="active").exists():
        add_beneficiary(client, inst, fm)
    audit(by, "invoice.submitted", inv, {"submitted_by": submitter, "sha256": evidence.sha256,
                                         "flags": [f["code"] for f in inv.check_flags]})
    publish("invoice.submitted", inv.pk, {"invoice_id": inv.pk, "client_id": client.pk, "institution_id": inst.pk,
                                          "family_member_id": fm.pk, "amount": amount, "currency": currency,
                                          "submitted_by": submitter, "country": inst.country.code})
    if submitter != "client":
        notify(client, "invoice_received",
               f"A bill from {inst.legal_name} for {fm.full_name} arrived ({fmt(amount, currency)}). We check it "
               "with the institution before you approve it.", obj=inv, link=f"/invoices/{inv.pk}",
               channels=("in_app", "email"), category="money")
    msg = (f"A bill from {inst.legal_name} ({fmt(amount, currency)}) needs checking with the institution's named "
           "contact.")
    if inv.check_flags:
        msg += " It is flagged: " + "; ".join(f["message"] for f in inv.check_flags)
    alert_staff(inst.country, ("CM",), "invoice_to_check", msg, obj=inv, link=f"/back-office/invoices/{inv.pk}")
    return inv


def _reset_for_new_version(inv, by, why):
    inv.check_status, inv.checked_by, inv.checked_at, inv.check_note = "pending", None, None, ""
    inv.client_approved_at, inv.client_approval_method = None, ""
    if inv.status in ("checked", "client_approved"):
        state.transition(inv, "fee_invoice", "submitted", actor=by, reason=why,
                         extra_fields=["check_status", "checked_by", "checked_at", "check_note", "client_approved_at",
                                       "client_approval_method"])


@transaction.atomic
def attach_document(inv: Invoice, by, evidence, *, institution_reference=None, amount=None, due_on=None,
                    name_on_invoice=None, institution_name_on_invoice=None, account_number_on_invoice=None) -> Invoice:
    """A draft from a schedule gets its real bill; a corrected bill is a new version that needs a new check and
    a new approval (TC-SEC-34). The first document's hash stays on record."""
    _on(inv.country)
    inv = Invoice.objects.select_for_update().get(pk=inv.pk)
    who = _resolve_submitter(by, inv.institution, inv.client)
    if who is None:
        raise NotFound()
    if inv.status not in ("draft", "submitted", "checked", "client_approved"):
        raise StateConflict("This bill is already being paid. A new bill needs a new invoice.")
    if Payment.objects.filter(invoice=inv, status__in=LIVE_PAYMENT).exists():
        raise StateConflict("A payment is under way for this bill. Withdraw it first.")
    if evidence is None:
        raise Invalid("Upload the bill.", code="validation-error")
    _evidence_ok(evidence, by, inv.country)
    previous = inv.evidence
    if institution_reference:
        ref = institution_reference.strip()
        if Invoice.objects.filter(institution=inv.institution, institution_reference=ref).exclude(
                pk=inv.pk).exclude(status__in=["rejected", "cancelled"]).exists():
            raise StateConflict("A bill with this reference is already on record.", code="invoice-reference-used")
        inv.institution_reference = ref
    if amount is not None:
        inv.amount = q(amount)
    if due_on is not None:
        inv.due_on = due_on
    for f, v in (("name_on_invoice", name_on_invoice), ("institution_name_on_invoice", institution_name_on_invoice),
                 ("account_number_on_invoice", account_number_on_invoice)):
        if v is not None:
            setattr(inv, f, v)
    inv.evidence, inv.evidence_sha256 = evidence, evidence.sha256
    if who == "institution_contact":
        inv.contact_confirmed_by, inv.contact_confirmed_at = contact_for(by, inv.institution), now()
    else:
        inv.contact_confirmed_by, inv.contact_confirmed_at = None, None
    was = inv.status
    inv.check_flags = compute_flags(inv)
    inv.save()
    if previous is not None:
        _link(previous, "fee_invoice", inv.pk, "superseded_invoice", by)
    _link(evidence, "fee_invoice", inv.pk, "invoice", by)
    if was == "draft":
        inv.check_status = "flagged" if inv.check_flags else "pending"
        state.transition(inv, "fee_invoice", "submitted", actor=by, extra_fields=["check_status"])
    else:
        _reset_for_new_version(inv, by, "A new version of the bill was uploaded")
        inv.check_status = "flagged" if inv.check_flags else "pending"
        inv.save(update_fields=["check_status"])
    audit(by, "invoice.document_attached", inv, {"sha256": evidence.sha256, "previous": getattr(previous, "sha256", None),
                                                 "was": was})
    alert_staff(inv.country, ("CM",), "invoice_to_check",
                f"A {'new version of a ' if was != 'draft' else ''}bill from {inv.institution.legal_name} needs "
                "checking.", obj=inv)
    return inv


@transaction.atomic
def contact_confirm(inv: Invoice, by, note="") -> Invoice:
    """The institution's named contact confirms the bill is theirs and correct (FR-FEE-001, IF-10)."""
    _on(inv.country)
    c = contact_for(by, inv.institution)
    if c is None:
        raise NotFound()
    if not c.may_confirm_invoices:
        raise Forbidden("You are not named to confirm invoices for this institution.")
    if inv.status not in ("submitted", "checked"):
        raise StateConflict("This bill is not waiting for confirmation.")
    inv.contact_confirmed_by, inv.contact_confirmed_at = c, now()
    inv.save(update_fields=["contact_confirmed_by", "contact_confirmed_at"])
    audit(by, "invoice.contact_confirmed", inv, {"contact_id": str(c.pk), "note": note})
    return inv


@transaction.atomic
def check_invoice(inv: Invoice, by, *, outcome, contact=None, note="", resolve_flags=False) -> Invoice:
    """US-FEE-002 AC2: the case manager confirms the bill with the institution's named contact; the invoice then
    shows Checked with the checker's name. Not for an institution that is not verified or not eligible."""
    _on(inv.country)
    _staff(by, inv.country, ("CM", "RV"), "Only a case manager checks invoices.")
    inv = Invoice.objects.select_for_update().get(pk=inv.pk)
    if inv.status != "submitted":
        raise StateConflict(f"This bill is {inv.status.replace('_', ' ')}, not waiting for a check.")
    if outcome == "rejected":
        if not (note or "").strip():
            raise Invalid("Say why the bill is rejected; the client sees it.", code="validation-error")
        inv.check_status, inv.checked_by, inv.checked_at, inv.check_note = "rejected", by, now(), note
        inv.status_reason = note
        state.transition(inv, "fee_invoice", "rejected", actor=by, reason=note,
                         extra_fields=["check_status", "checked_by", "checked_at", "check_note", "status_reason"])
        notify(inv.client, "invoice_rejected",
               f"We could not accept the bill from {inv.institution.legal_name}: {note}", obj=inv,
               link=f"/invoices/{inv.pk}", channels=("in_app", "email"))
        return inv
    if outcome != "checked":
        raise Invalid("Outcome must be checked or rejected.", code="validation-error")
    _require_eligible(inv.institution, "This bill cannot be checked")
    inv.check_flags = compute_flags(inv)
    hard = [f for f in inv.check_flags if not f.get("resolvable")]
    if hard:
        inv.check_status = "flagged"
        inv.save(update_fields=["check_flags", "check_status"])
        audit(by, "invoice.check_refused", inv, {"flags": [f["code"] for f in hard]})
        alert_staff(inv.country, ("RV",), "invoice_account_mismatch",
                    f"A bill from {inv.institution.legal_name} names an account other than the verified one.",
                    obj=inv)
        raise RuleBlocked("This bill names a bank account other than the institution's verified account. It "
                          "cannot be approved for payment; reject it and ask for a new bill.",
                          code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "code": f["code"], "message": f["message"]}
                                            for f in hard])
    if inv.check_flags and not (resolve_flags and (note or "").strip()):
        raise RuleBlocked("This bill is flagged. Resolve each flag with the institution and record why.",
                          code="invoice-flagged",
                          blocking_reasons=[{"rule": "FR-FEE-002", "code": f["code"], "message": f["message"]}
                                            for f in inv.check_flags])
    if contact is not None:
        if contact.institution_id != inv.institution_id or contact.status != "active" \
                or not contact.may_confirm_invoices:
            raise Invalid("That person is not a named contact who confirms invoices here.", code="validation-error")
        inv.contact_confirmed_by, inv.contact_confirmed_at = contact, now()
    if inv.contact_confirmed_by_id is None:
        raise RuleBlocked("Confirm the bill with the institution's named contact first.",
                          code="contact-confirmation-missing",
                          blocking_reasons=[{"rule": "FR-FEE-001", "message": "No confirmation from the named "
                                                                              "contact"}])
    inv.check_status, inv.checked_by, inv.checked_at, inv.check_note = "checked", by, now(), note or ""
    state.transition(inv, "fee_invoice", "checked", actor=by,
                     extra_fields=["check_status", "check_flags", "checked_by", "checked_at", "check_note",
                                   "contact_confirmed_by", "contact_confirmed_at"],
                     payload={"invoice_id": inv.pk, "checked_by": by.full_name})
    notify(inv.client, "invoice_checked",
           f"The bill from {inv.institution.legal_name} for {inv.family_member.full_name} "
           f"({fmt(inv.amount, inv.currency)}) is checked. Please approve it. Nothing is paid until you do.",
           obj=inv, needs_action=True, link=f"/invoices/{inv.pk}", channels=("in_app", "email"),
           category="approval")
    return inv


@transaction.atomic
def set_route(inv: Invoice, by, route, reason="") -> Invoice:
    """A case manager chooses the route for one payment before the client approves (two front doors decision)."""
    _on(inv.country)
    _staff(by, inv.country, ("CM", "RV"), "Only a case manager changes how a bill is paid.")
    if route not in ROUTES:
        raise Invalid(f"Route must be one of {', '.join(ROUTES)}.", code="validation-error")
    if inv.status not in ("draft", "submitted", "checked"):
        raise StateConflict("The route is chosen before the client approves.")
    if route == "held_funds":
        flags.require("escrow.enabled", inv.country)
    inv.route, inv.route_overridden_by = route, by
    inv.save(update_fields=["route", "route_overridden_by"])
    audit(by, "invoice.route_set", inv, {"route": route, "reason": reason})
    return inv


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


def held_funds_figures(client, country, currency) -> dict | None:
    from escrow import selectors as esel

    if not flags.enabled("escrow.enabled", country):
        return None
    e = esel.held_funds_for(client, country, currency)
    if e is None:
        return None
    return {"escrow_id": str(e.pk), "escrow_reference": e.reference,
            "held_at_bank": {"amount": f"{esel.held_at_bank(e, currency):.2f}", "currency": currency},
            "instructed_awaiting_bank": {"amount": f"{esel.awaiting_bank(e, currency):.2f}", "currency": currency},
            "available_to_instruct": {"amount": f"{esel.available_to_instruct(e, currency):.2f}",
                                      "currency": currency}}


def approval_preview(inv: Invoice) -> dict:
    """What the client sees before approving: the payee name as the bank states it (7.9)."""
    p = inv.institution.payee
    out = {"invoice_id": str(inv.pk), "route": inv.route,
           "institution": {"id": str(inv.institution_id), "name": inv.institution.legal_name,
                           "payee_status": p.verification_status if p else None,
                           "name_match": p.name_match if p else None,
                           "account_name": p.account_name if p else None,
                           "account_last4": p.last4 if p else None},
           "family_member": {"id": str(inv.family_member_id), "relationship": inv.family_member.relationship},
           "amount": {"amount": f"{inv.amount:.2f}", "currency": inv.currency}}
    if inv.route == "held_funds":
        out["held_funds"] = held_funds_figures(inv.client, inv.country, inv.currency)
    return out


def pay_to(inv: Invoice) -> dict:
    """client_direct: the institution's verified account, shown only after the client approves. Never a
    Tenmina account (RUL-01)."""
    p = inv.institution.payee
    b = Beneficiary.objects.filter(family_member=inv.family_member, institution=inv.institution,
                                   status="active").first()
    return {"account_holder": p.legal_name, "bank_name": p.bank_name, "account_name": p.account_name,
            "account_number": p.account_number, "currency": inv.currency,
            "amount": {"amount": f"{inv.amount:.2f}", "currency": inv.currency},
            "reference": inv.institution_reference + (f" / {b.tenmina_reference}" if b else ""),
            "note": f"Pay {inv.institution.legal_name} directly from your own bank or transfer service. Never pay "
                    "Tenmina or a relative. Use the reference so the institution can match your payment."}


def _family_plan_covers(inv) -> bool:
    from orders.models import Order

    month = timezone.localdate().strftime("%Y-%m")
    return Order.objects.filter(client=inv.client, country=inv.country, kind="family_plan",
                                details__period_month=month,
                                status__in=["draft", "awaiting_payment", "paid"]).exists()


def _service_order(inv: Invoice):
    """Tenmina's own fee for this payment, through PAY (amount [TO VERIFY]); none when a monthly plan covers it."""
    from orders.services import create_line_order

    if cfg(inv.country, "fees.service_fee", "per_payment") == "none" or inv.service_order_id or _family_plan_covers(inv):
        return None
    try:
        with transaction.atomic():
            order = create_line_order(client=inv.client, kind="family_payment_fee", country=inv.country,
                                      subject_type="fee_invoice", subject_id=inv.pk,
                                      details={"institution": inv.institution.legal_name,
                                               "invoice_reference": inv.institution_reference})
    except DomainError as exc:  # Tenmina's fee never holds up a family payment
        log.warning("fee order for invoice %s not created: %s", inv.pk, exc.detail)
        return None
    inv.service_order = order
    inv.save(update_fields=["service_order"])
    return order


def subscribe_plan(client, country, period_month):
    """The monthly plan covers every payment in that month (decision 2026-11-12; price [TO VERIFY])."""
    from orders.services import create_line_order

    _on(country)
    if not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client buys a plan.")
    try:
        datetime.strptime(period_month, "%Y-%m")
    except (TypeError, ValueError):
        raise Invalid("Give the month as YYYY-MM.", code="validation-error") from None
    return create_line_order(client=client, kind="family_plan", country=country,
                             details={"period_month": period_month})


def _system_preparer(inv):
    """The staff member who prepares an instruction the system starts: the checker, else a case manager."""
    if inv.checked_by_id and has_role(inv.checked_by, "CM", "RV", country=inv.country):
        return inv.checked_by
    return staff_in(inv.country, "CM").first()


def _instruct(inv: Invoice, by, *, client_mfa_at=None, client_code=None) -> Payment:
    """held_funds: prepare the release to the institution's verified payee record (RUL-22). When the client has
    just approved with a fresh step-up, their approval is applied to the instruction too (RUL-11)."""
    from escrow import selectors as esel
    from escrow import services as esc

    flags.require("escrow.enabled", inv.country)
    e = esel.held_funds_for(inv.client, inv.country, inv.currency)
    if e is None:
        raise StateConflict("There is no amount held at the bank for this client yet.", code="held-funds-missing")
    inst = inv.institution
    ins = esc.request_release(
        e, payee=inst.payee, amount=inv.amount, subject_type="fee_invoice", subject_id=inv.pk, requested_by=by,
        evidence_ids=[inv.evidence_id] if inv.evidence_id else [], reason=f"Invoice {inv.institution_reference}",
        subject_label=f"{inv.description or 'Bill'} {inv.institution_reference}, {inst.legal_name}",
        family_member_id=inv.family_member_id, currency=inv.currency)
    pay = Payment.objects.create(country=inv.country, invoice=inv, route="held_funds", amount=inv.amount,
                                 currency=inv.currency, escrow=e, release_instruction=ins, status="instructed")
    state.transition(inv, "fee_invoice", "instructed", actor=by, payload={"instruction_id": ins.pk})
    if client_mfa_at is not None or client_code:
        esc.client_approve(ins, inv.client, client_mfa_at, code=client_code)
    audit(by, "invoice.instructed", inv, {"instruction_id": str(ins.pk), "payment_id": str(pay.pk)})
    return pay


@transaction.atomic
def client_approve(inv: Invoice, client, *, mfa_at=None, code=None, confirm_amount=None,
                   confirm_payee_account_name="", note="") -> dict:
    """US-FEE-003, 7.9: the client approves a checked bill, with a fresh step-up, confirming the amount and the
    payee's account name as the bank states it. Silence is never approval (RUL-11)."""
    _on(inv.country)
    inv = Invoice.objects.select_for_update().get(pk=inv.pk)
    if inv.client_id != client.pk:
        raise NotFound()
    if inv.status != "checked" or inv.check_status != "checked":
        raise StateConflict("This bill is not waiting for your approval." if inv.status != "submitted" else
                            "This bill has not been checked with the institution yet.")
    _require_eligible(inv.institution, "This bill cannot be approved")
    method = _client_signed(client, mfa_at, code)
    amt = confirm_amount.get("amount") if isinstance(confirm_amount, dict) else confirm_amount
    cur = (confirm_amount.get("currency") if isinstance(confirm_amount, dict) else None) or inv.currency
    if amt is None or q(amt) != inv.amount or str(cur).upper() != inv.currency:
        raise Invalid("The amount you confirmed is not the bill's amount.", code="amount-mismatch")
    payee = inv.institution.payee
    if _norm(confirm_payee_account_name or "") != _norm(payee.account_name):
        raise Invalid("The account name you confirmed is not the one the bank states.", code="payee-name-mismatch")
    inv.client_approved_at, inv.client_approval_method = now(), method
    state.transition(inv, "fee_invoice", "client_approved", actor=client, event="invoice.client_approved",
                     extra_fields=["client_approved_at", "client_approval_method"],
                     payload={"invoice_id": inv.pk, "client_id": client.pk, "route": inv.route,
                              "amount": inv.amount, "currency": inv.currency, "note": note})
    resolve_action(inv)
    _service_order(inv)
    out = approval_preview(inv)
    out["status"] = "client_approved"
    if inv.route == "client_direct":
        Payment.objects.create(country=inv.country, invoice=inv, route="client_direct", amount=inv.amount,
                               currency=inv.currency, status="awaiting_client_payment")
        out["pay_to"] = pay_to(inv)
        out["next"] = (f"Pay {inv.institution.legal_name} from your own bank using these details, then tell us. "
                       "The institution confirms it received the money and we send you the receipt.")
        return out
    return _held_funds_after_approval(inv, client, mfa_at=mfa_at if method == "mfa_step_up" else None,
                                      code=code if method == "totp_code" else None, out=out)


def _held_funds_after_approval(inv, client, *, mfa_at, code, out):
    from escrow import selectors as esel
    from escrow import services as esc

    flags.require("escrow.enabled", inv.country)
    e = esel.held_funds_for(client, inv.country, inv.currency)
    if e is None:
        try:
            e = esc.open_held_funds(client, inv.country, inv.currency, by=client)
        except DomainError as exc:
            out["held_funds"] = None
            out["next"] = f"Open an amount held at the bank first: {exc.detail}"
            return out
    avail = esel.available_to_instruct(e, inv.currency)
    preparer = _system_preparer(inv)
    if avail >= inv.amount and preparer is not None and e.virtual_account_ref:
        _instruct(inv, preparer, client_mfa_at=mfa_at, client_code=code)
        out["status"] = "instructed"
        out["held_funds"] = held_funds_figures(client, inv.country, inv.currency)
        out["next"] = (f"Two Tenmina staff now approve. The bank pays {inv.institution.legal_name}. You will see the "
                       "receipt here.")
        return out
    short = max(inv.amount - avail, Decimal("0.00"))
    out["held_funds"] = held_funds_figures(client, inv.country, inv.currency)
    out["top_up"] = {"short_by": {"amount": f"{short:.2f}", "currency": inv.currency},
                     "payment_instructions": esc.payment_instructions(e)}
    out["next"] = ("Add money to the amount held at the bank using the bank's details. When the bank confirms it, "
                   "we prepare the payment and ask you to approve it.")
    notify(client, "fee_top_up_needed",
           f"To pay {inv.institution.legal_name}, add {fmt(short, inv.currency)} to the amount held at the bank. Pay "
           "the bank, never Tenmina.", obj=inv, needs_action=True, link=f"/invoices/{inv.pk}", category="money")
    return out


@transaction.atomic
def client_decline(inv: Invoice, client, reason="") -> Invoice:
    inv = Invoice.objects.select_for_update().get(pk=inv.pk)
    if inv.client_id != client.pk:
        raise NotFound()
    if inv.status != "checked":
        raise StateConflict("This bill is not waiting for your approval.")
    inv.client_declined_at, inv.status_reason = now(), reason or "Declined by the client"
    state.transition(inv, "fee_invoice", "cancelled", actor=client, reason=inv.status_reason,
                     extra_fields=["client_declined_at", "status_reason"])
    resolve_action(inv)
    alert_staff(inv.country, ("CM",), "invoice_declined",
                f"The client declined the bill from {inv.institution.legal_name}: {inv.status_reason}", obj=inv)
    return inv


@transaction.atomic
def cancel_invoice(inv: Invoice, by, reason) -> Invoice:
    inv = Invoice.objects.select_for_update().get(pk=inv.pk)
    if by.pk != inv.client_id and not is_staff(by, inv.country, ("CM", "RV")):
        raise NotFound()
    if inv.status not in ("draft", "submitted", "checked", "client_approved"):
        raise StateConflict("A bill being paid cannot be cancelled. Withdraw the payment first.")
    live = Payment.objects.filter(invoice=inv, status__in=LIVE_PAYMENT).first()
    if live is not None:
        if live.status in ("awaiting_client_payment", "client_reported"):
            if live.status == "client_reported":
                raise StateConflict("You told us you paid this bill. We are confirming it with the institution.")
            live.withdrawn_reason = reason or "Cancelled"
            state.transition(live, "fee_payment", "withdrawn", actor=by, extra_fields=["withdrawn_reason"])
        else:
            raise StateConflict("A payment is under way for this bill.")
    inv.status_reason = reason or "Cancelled"
    state.transition(inv, "fee_invoice", "cancelled", actor=by, reason=inv.status_reason,
                     extra_fields=["status_reason"])
    resolve_action(inv)
    return inv


@transaction.atomic
def prepare_instruction(inv: Invoice, by) -> Payment:
    """POST /v1/invoices/{id}/instructions (US-FEE-003 AC2): a case manager prepares the release to the
    institution's verified account. Two staff approve it after the client (RUL-05)."""
    _on(inv.country)
    _staff(by, inv.country, ("CM", "RV"), "Only a case manager prepares a payment instruction.")
    inv = Invoice.objects.select_for_update().get(pk=inv.pk)
    if inv.route != "held_funds":
        raise StateConflict("This bill is paid by the client directly to the institution. Tenmina sends no "
                            "instruction for it.", code="route-client-direct")
    if inv.status != "client_approved" or inv.client_approved_at is None:
        raise RuleBlocked("The client has not approved this bill. Silence is never approval.",
                          code="client-approval-missing",
                          blocking_reasons=[{"rule": "RUL-11", "message": "The client approves first."}])
    if Payment.objects.filter(invoice=inv, status__in=LIVE_PAYMENT).exists():
        raise StateConflict("A payment is already under way for this bill.", code="instruction-exists")
    _require_eligible(inv.institution, "This bill cannot be paid")
    return _instruct(inv, by)


@transaction.atomic
def on_deposit_confirmed(payload: dict):
    """US-FEE-003 AC2: when the bank confirms the client's deposit, approved bills waiting for money get their
    instruction prepared; the client then approves the payment itself (RUL-11)."""
    from escrow import selectors as esel

    e = esel.escrow(payload.get("escrow_id"))
    if e is None or e.kind != "held_funds":
        return
    waiting = Invoice.objects.filter(client_id=e.client_id, country=e.country, route="held_funds",
                                     status="client_approved").order_by("due_on", "created_at")
    for inv in waiting:
        if Payment.objects.filter(invoice=inv, status__in=LIVE_PAYMENT).exists():
            continue
        if esel.available_to_instruct(e, inv.currency) < inv.amount or eligibility_reasons(inv.institution):
            continue
        preparer = _system_preparer(inv)
        if preparer is None:
            continue
        try:
            with transaction.atomic():
                _instruct(inv, preparer)
        except DomainError as exc:
            log.warning("instruction for invoice %s not prepared: %s", inv.pk, exc.detail)


def _mark_paid(pay: Payment, *, actor=None, bank_reference="", at=None):
    t = at or now()
    pay.paid_at, pay.bank_reference = t, bank_reference or pay.bank_reference
    pay.receipt_due_at = t + days(receipt_target_days(pay.country))
    state.transition(pay, "fee_payment", "paid", actor=actor, extra_fields=["paid_at", "bank_reference",
                                                                            "receipt_due_at",
                                                                            "institution_confirmed_at",
                                                                            "institution_confirmed_by",
                                                                            "institution_confirmed_contact",
                                                                            "confirmation_method",
                                                                            "confirmation_note"],
                     payload={"payment_id": pay.pk, "invoice_id": pay.invoice_id})
    inv = pay.invoice
    state.transition(inv, "fee_invoice", "paid", actor=actor, payload={"payment_id": pay.pk})
    inst = inv.institution
    notify(inv.client, "fee_paid",
           f"{inst.legal_name} has been paid {fmt(pay.amount, pay.currency)} for {inv.family_member.full_name}. "
           "We are getting the receipt for you.", obj=pay, link=f"/fee-payments/{pay.pk}",
           channels=("in_app", "email"), category="money")
    for c in active_contacts(inst, receipts=True).filter(person__isnull=False):
        notify(c.person, "fee_receipt_requested",
               f"Payment received for reference {inv.institution_reference}. Please upload the official receipt.",
               obj=pay, needs_action=True, link=f"/fee-payments/{pay.pk}", channels=("in_app", "email"))
    return pay


@transaction.atomic
def on_release_confirmed(payload: dict):
    """The bank confirmed it paid the institution (held_funds route)."""
    if payload.get("subject_type") != "fee_invoice":
        return
    pay = Payment.objects.filter(release_instruction_id=payload.get("instruction_id"),
                                 status="instructed").select_related("invoice").first()
    if pay is None:
        return
    pay.confirmation_method = "bank_confirmation"
    _mark_paid(pay, bank_reference=payload.get("bank_reference") or "")


@transaction.atomic
def on_release_closed(payload: dict, why: str):
    """The instruction was withdrawn, rejected or refused by the bank: the bill goes back to approved-and-waiting."""
    if payload.get("subject_type") != "fee_invoice":
        return
    pay = Payment.objects.filter(release_instruction_id=payload.get("instruction_id"),
                                 status="instructed").select_related("invoice").first()
    if pay is None:
        return
    pay.withdrawn_reason = why
    state.transition(pay, "fee_payment", "withdrawn", reason=why, extra_fields=["withdrawn_reason"])
    inv = pay.invoice
    inv.status_reason = why
    state.transition(inv, "fee_invoice", "client_approved", reason=why, extra_fields=["status_reason"])
    notify(inv.client, "fee_payment_stopped",
           f"The payment to {inv.institution.legal_name} did not go ahead: {why}. Your case manager will be in "
           "touch.", obj=inv, link=f"/invoices/{inv.pk}", channels=("in_app", "email"), category="money")
    alert_staff(inv.country, ("CM",), "fee_payment_stopped",
                f"The payment for bill {inv.institution_reference} did not go ahead: {why}.", obj=inv)


# ----------------------------------------------------------------- client_direct: verify and confirm

@transaction.atomic
def report_client_payment(pay: Payment, client, *, paid_on=None, reference="", evidence=None) -> Payment:
    """The client tells us they paid the institution's verified account from their own bank."""
    _on(pay.country)
    pay = Payment.objects.select_for_update().select_related("invoice").get(pk=pay.pk)
    if pay.invoice.client_id != client.pk:
        raise NotFound()
    if pay.route != "client_direct" or pay.status != "awaiting_client_payment":
        raise StateConflict("This payment is not waiting for your transfer.")
    if evidence is None and not (reference or "").strip():
        raise Invalid("Give your transfer reference or upload the transfer confirmation.", code="validation-error")
    if evidence is not None:
        _evidence_ok(evidence, client, pay.country)
    pay.client_paid_on = paid_on or today()
    pay.client_transfer_reference = reference or ""
    pay.client_transfer_evidence = evidence
    pay.client_reported_at = now()
    state.transition(pay, "fee_payment", "client_reported", actor=client,
                     extra_fields=["client_paid_on", "client_transfer_reference", "client_transfer_evidence",
                                   "client_reported_at"])
    if evidence is not None:
        _link(evidence, "fee_payment", pay.pk, "client_transfer", client)
    inv = pay.invoice
    for c in active_contacts(inv.institution, confirm=True).filter(person__isnull=False):
        notify(c.person, "fee_confirm_receipt",
               f"A payment of {fmt(pay.amount, pay.currency)} for reference {inv.institution_reference} was sent to "
               "your account. Please confirm when you receive it.", obj=pay, needs_action=True,
               link=f"/fee-payments/{pay.pk}", channels=("in_app", "email"))
    alert_staff(pay.country, ("CM",), "fee_confirm_with_institution",
                f"The client says they paid {inv.institution.legal_name} for bill {inv.institution_reference}. "
                "Confirm receipt with the named contact.", obj=pay)
    return pay


@transaction.atomic
def confirm_received(pay: Payment, by, *, amount=None, currency=None, method="", contact=None, note="",
                     evidence=None, received=True) -> Payment:
    """The institution confirms it received the client's payment: its named contact in the portal, or a case
    manager recording the named contact's call (client_direct route)."""
    _on(pay.country)
    pay = Payment.objects.select_for_update().select_related("invoice", "invoice__institution").get(pk=pay.pk)
    inv, inst = pay.invoice, pay.invoice.institution
    own = contact_for(by, inst)
    staff = is_staff(by, pay.country, ("CM", "RV"))
    if own is None and not staff:
        raise NotFound()
    if own is not None and not own.may_confirm_invoices:
        raise Forbidden("You are not named to confirm payments for this institution.")
    if pay.route != "client_direct" or pay.status not in ("awaiting_client_payment", "client_reported"):
        raise StateConflict("This payment is not waiting for the institution's confirmation.")
    if not received:
        if not (note or "").strip():
            raise Invalid("Say what the institution reported.", code="validation-error")
        pay.confirmation_note = note
        if pay.status == "client_reported":
            state.transition(pay, "fee_payment", "awaiting_client_payment", actor=by, reason=note,
                             extra_fields=["confirmation_note"])
        notify(inv.client, "fee_not_received",
               f"{inst.legal_name} says it has not received your payment yet: {note}", obj=pay,
               link=f"/fee-payments/{pay.pk}", channels=("in_app", "email"), category="money")
        return pay
    if amount is not None and (q(amount) != pay.amount or (currency or pay.currency).upper() != pay.currency):
        audit(by, "fee_payment.amount_differs", pay, {"reported": str(amount)})
        raise Invalid("The amount received is not the bill's amount. Record what was received in the note and "
                      "ask the client to pay the difference.", code="amount-mismatch")
    if own is not None:
        pay.institution_confirmed_contact, pay.confirmation_method = own, "contact_portal"
    else:
        if method not in ("contact_call", "receipt"):
            raise Invalid("Record how the institution confirmed: contact_call or receipt.", code="validation-error")
        if method == "contact_call":
            if contact is None or contact.institution_id != inst.pk or contact.status != "active":
                raise Invalid("Name the institution's contact who confirmed.", code="validation-error")
            if not (note or "").strip():
                raise Invalid("Record what the contact said.", code="validation-error")
        if method == "receipt" and evidence is None:
            raise Invalid("Attach the institution's receipt.", code="validation-error")
        pay.institution_confirmed_contact, pay.confirmation_method = contact, method
    pay.institution_confirmed_at, pay.institution_confirmed_by, pay.confirmation_note = now(), by, note or ""
    _mark_paid(pay, actor=by)
    if evidence is not None:
        _evidence_ok(evidence, by, pay.country)
        add_receipt(pay, by, receipt_evidence=evidence)
    return pay


# ----------------------------------------------------------------- receipts (FR-FEE-004)

@transaction.atomic
def add_receipt(pay: Payment, by, *, receipt_evidence, confirmation_evidence=None) -> Payment:
    """US-FEE-004: the institution's receipt, and where the institution agrees, a confirmation of enrolment or
    treatment, linked to the payment and shown on the client's dashboard. Never in SMS or WhatsApp text."""
    _on(pay.country)
    pay = Payment.objects.select_for_update().select_related("invoice", "invoice__institution").get(pk=pay.pk)
    inv, inst = pay.invoice, pay.invoice.institution
    own = contact_for(by, inst)
    if own is None and not is_staff(by, pay.country, ("CM", "RV")):
        raise NotFound()
    if own is not None and not own.may_send_receipts:
        raise Forbidden("You are not named to send receipts for this institution.")
    if pay.status not in ("paid", "receipt_overdue"):
        raise StateConflict("A receipt is added once the institution has been paid.")
    if receipt_evidence is None:
        raise Invalid("Upload the receipt.", code="validation-error")
    _evidence_ok(receipt_evidence, by, pay.country)
    if confirmation_evidence is not None:
        if not inst.returns_confirmation:
            raise Invalid("This institution has not agreed to share confirmations. Only the receipt is kept.",
                          code="confirmation-not-agreed")
        _evidence_ok(confirmation_evidence, by, pay.country)
    pay.receipt_evidence, pay.confirmation_evidence, pay.receipt_received_at = (receipt_evidence,
                                                                                 confirmation_evidence, now())
    state.transition(pay, "fee_payment", "receipted", actor=by, event="fee_payment.receipted",
                     extra_fields=["receipt_evidence", "confirmation_evidence", "receipt_received_at"],
                     payload={"payment_id": pay.pk, "invoice_id": inv.pk, "client_id": inv.client_id,
                              "family_member_id": inv.family_member_id, "receipt_sha256": receipt_evidence.sha256})
    _link(receipt_evidence, "fee_payment", pay.pk, "receipt", by)
    if confirmation_evidence is not None:
        _link(confirmation_evidence, "fee_payment", pay.pk, "confirmation", by)
    state.transition(inv, "fee_invoice", "receipted", actor=by)
    resolve_action(pay)
    notify(inv.client, "fee_receipt_returned",
           f"The receipt from {inst.legal_name} for {inv.family_member.full_name} is on your dashboard.", obj=pay,
           link=f"/fee-payments/{pay.pk}", channels=("in_app", "email"), category="money")
    return pay


def receipt_overdue(at=None) -> int:
    """fees.receipt_overdue (daily): no receipt after `receipt_target_days`: chase the institution, tell the
    client and give the case manager a task (US-FEE-004 AC2)."""
    t = at or now()
    n = 0
    for pay in Payment.objects.filter(status="paid", receipt_due_at__lt=t).select_related("invoice",
                                                                                          "invoice__institution"):
        with transaction.atomic():
            pay.receipt_chased_at = t
            state.transition(pay, "fee_payment", "receipt_overdue", extra_fields=["receipt_chased_at"])
            inv, inst = pay.invoice, pay.invoice.institution
            for c in active_contacts(inst, receipts=True).filter(person__isnull=False):
                notify(c.person, "fee_receipt_overdue", f"The receipt for reference {inv.institution_reference} "
                       "is overdue. Please upload it.", obj=pay, needs_action=True, channels=("in_app", "email"))
            alert_staff(pay.country, ("CM",), "fee_receipt_overdue",
                        f"No receipt from {inst.legal_name} for bill {inv.institution_reference}. Chase the named "
                        "contact, or send a runner to collect it.", obj=pay)
            notify(inv.client, "fee_receipt_overdue_client",
                   f"{inst.legal_name} has not sent the receipt yet. We are chasing it.", obj=pay,
                   channels=("in_app",))
            n += 1
    return n


# ----------------------------------------------------------------- schedules (FR-FEE-005)

@transaction.atomic
def create_schedule(by, *, institution, family_member, period, expected_amount, currency=None, next_due_on,
                    reminder_lead_days=14, label="") -> Schedule:
    from accounts.selectors import active_family_member

    inst = institution
    _on(inst.country)
    client = family_member.client
    if by.pk != client.pk and not is_staff(by, inst.country, ("CM",)):
        raise NotFound()
    fm = active_family_member(client, family_member.pk)
    if inst.status in ("not_eligible", "not_verified"):
        raise RuleBlocked(NOT_ELIGIBLE_TEXT if inst.status == "not_eligible" else
                          f"{inst.legal_name} is not verified. Tenmina cannot pay it.",
                          code="institution-not-eligible")
    if period not in Schedule.PERIODS:
        raise Invalid(f"Period must be one of {', '.join(Schedule.PERIODS)}.", code="validation-error")
    currency = (currency or inst.country.currency).upper()
    if currency not in _invoice_currencies(inst.country):
        raise Invalid(f"Bills in {inst.country.name} are paid in {inst.country.currency}.", code="validation-error")
    if q(expected_amount) <= 0:
        raise Invalid("Enter the expected amount.", code="validation-error")
    if int(reminder_lead_days) < 1 or int(reminder_lead_days) > 60:
        raise Invalid("Remind between 1 and 60 days before.", code="validation-error")
    add_beneficiary(client, inst, fm)
    s = Schedule.objects.create(country=inst.country, client=client, family_member=fm, institution=inst,
                                label=label or f"{inst.legal_name} {period} fees", period=period,
                                expected_amount=q(expected_amount), expected_currency=currency,
                                next_due_on=next_due_on, reminder_lead_days=int(reminder_lead_days), created_by=by)
    audit(by, "fee_schedule.created", s, {"period": period})
    return s


@transaction.atomic
def update_schedule(s: Schedule, by, data: dict) -> Schedule:
    _on(s.country)
    if by.pk != s.client_id and not is_staff(by, s.country, ("CM",)):
        raise NotFound()
    if s.status == "ended":
        raise StateConflict("This schedule has ended.")
    if "expected_amount" in data and data["expected_amount"] is not None:
        if q(data["expected_amount"]) <= 0:
            raise Invalid("Enter the expected amount.", code="validation-error")
        s.expected_amount = q(data["expected_amount"])
    for f in ("next_due_on", "label"):
        if data.get(f) is not None:
            setattr(s, f, data[f])
    if data.get("reminder_lead_days") is not None:
        if int(data["reminder_lead_days"]) < 1 or int(data["reminder_lead_days"]) > 60:
            raise Invalid("Remind between 1 and 60 days before.", code="validation-error")
        s.reminder_lead_days = int(data["reminder_lead_days"])
    s.save()
    audit(by, "fee_schedule.updated", s, {"fields": sorted(k for k, v in data.items() if v is not None)})
    return s


@transaction.atomic
def set_schedule_status(s: Schedule, by, to) -> Schedule:
    if by.pk != s.client_id and not is_staff(by, s.country, ("CM",)):
        raise NotFound()
    return state.transition(s, "fee_schedule", to, actor=by)


def _generate(s: Schedule, t):
    """The draft bill for this period, and a request to the institution for the real one."""
    b = add_beneficiary(s.client, s.institution, s.family_member)
    inv = Invoice.objects.create(
        country=s.country, client=s.client, family_member=s.family_member, institution=s.institution, schedule=s,
        institution_reference=f"{b.tenmina_reference}-{s.next_due_on:%Y%m%d}", description=s.label,
        amount=s.expected_amount, currency=s.expected_currency, due_on=s.next_due_on, submitted_by="schedule",
        route=default_route(s.country), status="draft")
    due = s.next_due_on
    s.last_generated_due_on = due
    s.next_due_on = add_period(due, s.period, s.country)
    s.save(update_fields=["last_generated_due_on", "next_due_on"])
    publish("fee_schedule.due", s.pk, {"schedule_id": s.pk, "invoice_id": inv.pk, "client_id": s.client_id,
                                       "due_on": due, "institution_id": s.institution_id})
    for c in active_contacts(s.institution, confirm=True).filter(person__isnull=False):
        notify(c.person, "fee_invoice_request",
               f"Please send the bill for Tenmina reference {b.tenmina_reference}, due {due:%d %B %Y}.", obj=inv,
               needs_action=True, link=f"/invoices/{inv.pk}", channels=("in_app", "email"))
    notify(s.client, "fee_schedule_reminder",
           f"{s.label} for {s.family_member.full_name} is due on {due:%d %B %Y} (about "
           f"{fmt(s.expected_amount, s.expected_currency)}). We have asked {s.institution.legal_name} for the bill. "
           "Nothing is paid until you approve it.", obj=inv, link=f"/invoices/{inv.pk}", channels=("in_app", "email"),
           category="reminder")
    return inv


def schedule_due(on=None) -> dict:
    """fees.schedule_due (daily): draft bills from schedules within their reminder lead time; reminders for bills
    waiting for the client's approval. Nothing is ever approved for the client (RUL-11)."""
    t = on or today()
    made, reminded = 0, 0
    for s in Schedule.objects.filter(status="active").select_related("institution", "family_member", "client"):
        if not flags.enabled("lines.fee", s.country) or s.institution.status in ("not_eligible", "not_verified"):
            continue
        if s.next_due_on - days(s.reminder_lead_days) <= t and s.last_generated_due_on != s.next_due_on:
            with transaction.atomic():
                _generate(s, t)
                made += 1
    for inv in Invoice.objects.filter(status__in=["checked", "draft"], due_on__isnull=False).select_related(
            "institution", "family_member", "client"):
        lead = inv.schedule.reminder_lead_days if inv.schedule_id else 7
        if inv.due_on - days(lead) > t:
            continue
        if inv.client_reminded_at and timezone.localdate(inv.client_reminded_at) >= t:
            continue
        if inv.status == "checked":
            late = inv.due_on < t
            notify(inv.client, "fee_approval_reminder",
                   (f"The bill from {inv.institution.legal_name} was due on {inv.due_on:%d %B %Y} and is not paid. "
                    if late else f"The bill from {inv.institution.legal_name} is due on {inv.due_on:%d %B %Y}. ")
                   + "Nothing is paid until you approve it.", obj=inv, needs_action=True,
                   link=f"/invoices/{inv.pk}", channels=("in_app", "email"), category="reminder")
        inv.client_reminded_at = now()
        inv.save(update_fields=["client_reminded_at"])
        reminded += 1
    return {"drafts": made, "reminders": reminded}


def institution_reverify(on=None) -> int:
    """fees.institution_reverify (monthly): a verified institution whose payee is past its valid-until date goes
    back to pending with a new verification case (RUL-22)."""
    t = on or today()
    n = 0
    for inst in Institution.objects.filter(status="verified", payee__valid_until__lt=t).select_related("payee"):
        with transaction.atomic():
            inst.status_reason = "The yearly re-check of this institution is due."
            state.transition(inst, "fee_institution", "pending", reason=inst.status_reason,
                             extra_fields=["status_reason"])
            _open_new_case(inst, None, "yearly re-verification")
            n += 1
    return n


# ----------------------------------------------------------------- runner tasks (FR-FEE-006)

@transaction.atomic
def create_runner_task(inst: Institution, by, *, kind, runner, due_at, invoice=None, family_member=None,
                       deliver_to_family_member=None, instructions="") -> RunnerTask:
    """A runner collects an invoice or delivers a receipt in person. It carries paper, never money: the task has
    no amount and no instruction, and a runner is never a payee (RUL-22)."""
    _on(inst.country)
    _staff(by, inst.country, ("CM",), "Only a case manager asks a runner.")
    if kind not in RunnerTask.KINDS:
        raise Invalid("Kind must be collect_invoice or deliver_receipt.", code="validation-error")
    if runner is None or not runner.has_tenmina_role("RN"):
        raise Invalid("Choose a runner.", code="validation-error")
    if inst.payee_id and inst.payee.person_id == runner.pk:
        raise RuleBlocked("A runner is never a payee.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "message": "Runner is the institution's payee"}])
    client = None
    if kind == "deliver_receipt":
        if invoice is None or invoice.institution_id != inst.pk:
            raise Invalid("Name the bill whose receipt is delivered.", code="validation-error")
        if invoice.status not in ("paid", "receipted"):
            raise StateConflict("A receipt is delivered once the bill is paid.")
        client = invoice.client
        deliver_to_family_member = deliver_to_family_member or invoice.family_member
        if deliver_to_family_member.client_id != client.pk:
            raise Invalid("Deliver only to the client's own family member.", code="validation-error")
    else:
        if family_member is None:
            raise Invalid("Name the family member whose bill is collected.", code="validation-error")
        client = family_member.client
        if inst.status in ("not_eligible", "not_verified"):
            raise RuleBlocked(NOT_ELIGIBLE_TEXT, code="institution-not-eligible")
    t = RunnerTask.objects.create(country=inst.country, institution=inst, client=client, family_member=family_member
                                  or (invoice.family_member if invoice else None), invoice=invoice, kind=kind,
                                  runner=runner, deliver_to_family_member=deliver_to_family_member,
                                  instructions=instructions or "", due_at=due_at, created_by=by)
    audit(by, "fee_runner_task.created", t, {"kind": kind, "runner_id": str(runner.pk)})
    notify(runner, "fee_runner_task",
           f"{'Collect a bill from' if kind == 'collect_invoice' else 'Deliver a receipt from'} {inst.legal_name} "
           f"by {timezone.localtime(due_at):%d %B %Y}. You carry paper only, never money.", obj=t, needs_action=True,
           link=f"/field/fee-runner-tasks/{t.pk}", channels=("in_app",), category="task")
    return t


@transaction.atomic
def complete_runner_task(t: RunnerTask, by, *, evidence, note="", invoice_data=None) -> RunnerTask:
    """The runner uploads the bill photo, or the handover record. A collected bill goes through the normal checks
    (US-FEE-006 AC3)."""
    _on(t.country)
    t = RunnerTask.objects.select_for_update().get(pk=t.pk)
    if t.runner_id != by.pk and not is_staff(by, t.country, ("CM",)):
        raise NotFound()
    if t.status != "open":
        raise StateConflict("This task is not open.")
    if evidence is None:
        raise Invalid("Attach the photo of the bill or the handover record.", code="validation-error")
    _evidence_ok(evidence, by, t.country)
    t.evidence, t.note, t.done_at = evidence, note or "", now()
    if t.kind == "collect_invoice" and invoice_data:
        b = Beneficiary.objects.filter(family_member=t.family_member, institution=t.institution,
                                       status="active").first() or add_beneficiary(t.client, t.institution,
                                                                                    t.family_member)
        inv = submit_invoice(by, institution=t.institution, institution_reference=invoice_data.get("reference", ""),
                             amount=invoice_data.get("amount"), currency=invoice_data.get("currency"),
                             tenmina_reference=b.tenmina_reference, due_on=invoice_data.get("due_on"),
                             description=invoice_data.get("description", ""),
                             name_on_invoice=invoice_data.get("name_on_invoice", ""), evidence=evidence,
                             _runner_task=t)
        t.invoice = inv
    state.transition(t, "fee_runner_task", "done", actor=by, extra_fields=["evidence", "note", "done_at", "invoice"])
    _link(evidence, "fee_runner_task", t.pk, "collected_invoice" if t.kind == "collect_invoice" else "handover", by)
    resolve_action(t)
    if t.kind == "collect_invoice" and t.invoice_id is None:
        alert_staff(t.country, ("CM",), "fee_runner_invoice_collected",
                    f"A runner collected a bill from {t.institution.legal_name}. Enter it for checking.", obj=t)
    if t.kind == "deliver_receipt":
        notify(t.client, "fee_receipt_delivered",
               f"The receipt from {t.institution.legal_name} was delivered to "
               f"{t.deliver_to_family_member.full_name}.", obj=t, channels=("in_app",))
    return t


@transaction.atomic
def cancel_runner_task(t: RunnerTask, by, reason) -> RunnerTask:
    _staff(by, t.country, ("CM",))
    t.cancel_reason = reason or ""
    return state.transition(t, "fee_runner_task", "cancelled", actor=by, reason=reason,
                            extra_fields=["cancel_reason"])


def on_submission(payload: dict):
    """A runner sent the task's evidence from Tenmina Field."""
    if payload.get("subject_type") != "fee_runner_task":
        return
    from accounts.models import Person
    from evidence.models import Evidence

    t = RunnerTask.objects.filter(pk=payload.get("subject_id"), status="open").first()
    person = Person.objects.filter(pk=payload.get("person_id")).first()
    if t is None or person is None or payload.get("flagged"):
        return
    items = payload.get("items") or []
    ev_id = next((i.get("evidence_id") for i in items if i.get("evidence_id")), None)
    ev = Evidence.objects.filter(pk=ev_id).first() if ev_id else None
    form = {i.get("requirement_key"): i.get("value") for i in items if i.get("value") is not None}
    data = None
    if t.kind == "collect_invoice" and form.get("reference") and form.get("amount"):
        data = {"reference": form["reference"], "amount": form["amount"], "due_on": form.get("due_on"),
                "name_on_invoice": form.get("name_on_invoice", "")}
    if ev is not None:
        try:
            complete_runner_task(t, person, evidence=ev, note=payload.get("note") or "", invoice_data=data)
        except DomainError as exc:
            log.warning("runner task %s not completed from submission: %s", t.pk, exc.detail)


# ----------------------------------------------------------------- statements (FR-FEE-007)

def statement(client, family_member) -> dict:
    """Invoices, payments, receipts and the amount held at the bank for one family member, in date order."""
    from escrow import selectors as esel

    if family_member.client_id != client.pk:
        raise NotFound()
    lines = []
    totals = {}
    for inv in Invoice.objects.filter(client=client, family_member=family_member).exclude(status="draft") \
            .select_related("institution").order_by("created_at"):
        t = totals.setdefault(inv.currency, {"invoiced": Decimal("0"), "paid": Decimal("0"),
                                             "awaiting": Decimal("0")})
        if inv.status not in ("rejected", "cancelled"):
            t["invoiced"] += inv.amount
        lines.append({"at": inv.created_at, "type": "invoice", "id": str(inv.pk), "institution": inv.institution.legal_name,
                      "reference": inv.institution_reference, "description": inv.description,
                      "amount": {"amount": f"{inv.amount:.2f}", "currency": inv.currency}, "status": inv.status})
        for pay in inv.payments.exclude(status="withdrawn"):
            if pay.paid_at:
                t["paid"] += pay.amount
                lines.append({"at": pay.paid_at, "type": "payment", "id": str(pay.pk),
                              "institution": inv.institution.legal_name, "reference": inv.institution_reference,
                              "description": "Paid by the bank" if pay.route == "held_funds" else
                              "Paid by you, confirmed by the institution",
                              "amount": {"amount": f"{pay.amount:.2f}", "currency": pay.currency},
                              "status": pay.status, "route": pay.route})
            else:
                t["awaiting"] += pay.amount
            if pay.receipt_received_at:
                lines.append({"at": pay.receipt_received_at, "type": "receipt", "id": str(pay.pk),
                              "institution": inv.institution.legal_name, "reference": inv.institution_reference,
                              "description": "Receipt returned" + (" with confirmation" if
                                                                   pay.confirmation_evidence_id else ""),
                              "amount": None, "status": "receipted",
                              "evidence_id": str(pay.receipt_evidence_id)})
    lines.sort(key=lambda r: r["at"])
    held = []
    if flags.enabled("escrow.enabled", family_member.country):
        from escrow.models import Escrow

        for e in Escrow.objects.filter(client=client, country=family_member.country, kind="held_funds"):
            for cur, _ref in esel.currencies(e):
                held.append({"escrow_id": str(e.pk), "escrow_reference": e.reference,
                             "held_at_bank": {"amount": f"{esel.held_at_bank(e, cur):.2f}", "currency": cur},
                             "awaiting_bank": {"amount": f"{esel.awaiting_bank(e, cur):.2f}", "currency": cur},
                             "available_to_instruct": {"amount": f"{esel.available_to_instruct(e, cur):.2f}",
                                                       "currency": cur}})
    return {"family_member": {"id": str(family_member.pk), "full_name": family_member.full_name,
                              "relationship": family_member.relationship},
            "lines": [dict(r, at=r["at"].isoformat()) for r in lines],
            "totals": [{"currency": c, "invoiced": f"{v['invoiced']:.2f}", "paid": f"{v['paid']:.2f}",
                        "awaiting_payment": f"{v['awaiting']:.2f}"} for c, v in sorted(totals.items())],
            "held_at_bank": held,
            "note": "Amounts held are what the bank has confirmed. Tenmina never holds your money."}


@transaction.atomic
def statement_pdf(client, family_member) -> Statement:
    """US-FEE-007 AC2: a PDF of the statement with its hash stored, like a report (US-RPT-007)."""
    from evidence.services import register_issued, store

    from .pdf import render_statement

    data = statement(client, family_member)
    raw = render_statement(data, client_name=client.full_name)
    ev = store(data=raw, country=family_member.country, uploaded_by=client, content_type="application/pdf",
               original_name=f"statement-{family_member.pk}.pdf", source="generated",
               description=f"Family statement for {family_member.full_name}", owner_type="fee_statement",
               owner_id=family_member.pk, data_class="family_payment")
    st = Statement.objects.create(country=family_member.country, client=client, family_member=family_member,
                                  evidence=ev, sha256=ev.sha256)
    _link(ev, "fee_statement", family_member.pk, "statement_pdf", client)
    register_issued(ev, "fee_statement", family_member.pk, kind="fee_statement", by=client)
    audit(client, "fee.statement_issued", st, {"sha256": ev.sha256})
    return st


# ----------------------------------------------------------------- escrow subject check (RUL-22, FR-FEE-003)

def release_check(instruction) -> list[dict]:
    """registry.subject_check("fee_invoice"): runs when the release is prepared, approved and sent."""
    inv = Invoice.objects.filter(pk=instruction.subject_id).select_related("institution").first()
    if inv is None:
        # An instruction escrow created without a FEE bill (seed or a manual entry) is checked by escrow's own
        # payee rules only; FEE has nothing to add.
        log.warning("fee_invoice instruction %s names no FEE invoice", instruction.pk)
        return []
    out = []

    def r(rule, code, msg):
        out.append({"rule": rule, "code": code, "message": msg})

    if inv.route != "held_funds":
        r("FR-FEE-003", "route-client-direct", "This bill is paid by the client directly; Tenmina sends no "
                                               "instruction for it.")
    if inv.check_status != "checked":
        r("FR-FEE-002", "invoice-not-checked", "The bill has not been checked with the institution.")
    if inv.client_approved_at is None:
        r("RUL-11", "client-approval-missing", "The client has not approved this bill.")
    if inv.status in ("rejected", "cancelled"):
        r("FR-FEE-002", "invoice-closed", f"The bill is {inv.status}.")
    for reason in eligibility_reasons(inv.institution):
        r(reason["rule"], reason["code"], reason["message"])
    if instruction.payee_id != inv.institution.payee_id:
        r("RUL-22", "payee-not-institution", "The payee is not the institution's verified account.")
    if q(instruction.amount) != inv.amount or instruction.currency != inv.currency:
        r("FR-FEE-003", "amount-mismatch", f"The instruction is not the bill's amount "
                                           f"({fmt(inv.amount, inv.currency)}).")
    if instruction.escrow.client_id != inv.client_id:
        r("RUL-22", "escrow-not-client", "The money held belongs to another client.")
    if instruction.family_member_id and str(instruction.family_member_id) != str(inv.family_member_id):
        r("FR-FEE-007", "family-member-mismatch", "The instruction names another family member.")
    return out


def label(subject_id) -> str:
    inv = Invoice.objects.filter(pk=subject_id).select_related("institution").first()
    if inv is None:
        return ""
    return f"{inv.description or 'Bill'} {inv.institution_reference}, {inv.institution.legal_name}"


def on_time(d):
    return timezone.make_aware(datetime.combine(d, time(17, 0))) if d else None
