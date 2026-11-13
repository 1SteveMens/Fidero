"""Paying a stage on both routes (FR-BLD-005, FR-BLD-006, FR-BLD-012, FR-BLD-013, FR-PRJ-003; RUL-09, RUL-11,
RUL-21, RUL-22).

escrow route: one partial release instruction per payment through `escrow.services`. The client approves it
(RUL-11), two staff with release rights approve it (RUL-05) and the bank pays the verified payee. BLD follows
the instruction through the `release.*` events.

client_direct route (launch, decision 2026-11-12-two-front-doors): Tenmina never touches the money. Tenmina
confirms the stage and the invoice, the client approves, two staff confirm it may be paid, the client pays the
verified payee's own account from their own bank, and the payee (or a case manager, with the bank's receipt)
confirms it arrived.

Each subject registers what must be true before money moves (`register_subject`). The same checks run as the
escrow subject check (`escrow.registry`) and before every client_direct step.
"""
from decimal import Decimal

from django.db import transaction

from core import approvals, state
from core.errors import DomainError, Forbidden, Invalid, MfaRequired, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from .common import audit, fmt, log, notify, now, resolve, staff_in
from .models import Payment, Project

APPROVAL_SUBJECT = {"funds": "project_release"}  # every build type: milestone_release

# part -> {"blockers": fn(payment, stage) -> [reason], "on_status": fn(payment, to)}
_SUBJECTS: dict = {}


def register_subject(part, *, blockers, on_status):
    _SUBJECTS[part] = {"blockers": blockers, "on_status": on_status}


def _r(rule, code, message):
    return {"rule": rule, "code": code, "message": message}


def payee_reasons(payment) -> list[dict]:
    """RUL-22 on both routes: a verified payee whose bank account name matches, never the client, a relative or
    the client's representative. On the escrow route ESC checks this again."""
    from accounts.selectors import is_relative_or_representative

    p = payment.payee
    p.refresh_from_db()
    client = payment.project.client
    out = []
    if p.verification_status != "verified":
        out.append(_r("RUL-22", "payee-not-verified", f"{p.legal_name} is not a verified payee "
                                                      f"({p.verification_status})."))
    if p.name_match != "matched":
        out.append(_r("FR-ESC-015", "payee-not-verified", f"The bank's account name '{p.account_name}' does not "
                                                          f"match '{p.legal_name}'."))
    if p.person_id == client.pk or p.kind == "client_own_account":
        out.append(_r("RUL-22", "payee-not-verified", "A stage payment never goes to the client."))
    elif is_relative_or_representative(client, person=p.person if p.person_id else None, name=p.legal_name,
                                       phone=p.contact_phone):
        out.append(_r("RUL-22", "payee-not-verified", "The payee is a family member or representative of the "
                                                      "client. Money never goes to a relative."))
    return out


def blockers(payment, stage="prepare") -> list[dict]:
    """Every reason this payment cannot move on. `stage`: prepare, client, staff or send."""
    out = []
    project = payment.project
    if project.status not in ("active",):
        out.append(_r("FR-BLD-005", "project-not-active", f"The project is {project.status}."))
    entry = _SUBJECTS.get(payment.part)
    if entry is None:
        out.append(_r("RUL-09", "subject-unknown", "Tenmina does not know what this payment is for."))
    else:
        out.extend(entry["blockers"](payment, stage) or [])
    if payment.route == "client_direct":
        out.extend(payee_reasons(payment))
    return out


def raise_if_blocked(payment, stage, what="This payment"):
    reasons = blockers(payment, stage)
    if reasons:
        codes = {r["code"] for r in reasons}
        code = "payee-not-verified" if codes == {"payee-not-verified"} else "release-blocked"
        raise RuleBlocked(f"{what} is blocked: " + "; ".join(r["message"] for r in reasons[:3])
                          + (" ..." if len(reasons) > 3 else ""), code=code, blocking_reasons=reasons)


def escrow_subject_check(instruction) -> list[dict]:
    """Registered with escrow.registry for milestone, offplan_stage and project_invoice subjects (RUL-09,
    RUL-21). An escrow no BLD project runs is not BLD's to check."""
    p = Payment.objects.filter(instruction_id=instruction.pk).select_related("project").first()
    if p is None:
        p = Payment.objects.filter(subject_type=instruction.subject_type, subject_id=instruction.subject_id,
                                   status="preparing", route="escrow").select_related("project").first()
    if p is None:
        if Project.objects.filter(escrow_id=instruction.escrow_id).exists():
            return [_r("RUL-09", "milestone-unknown", "Prepare stage payments from the project, so the inspection, "
                                                      "re-price and evidence rules are checked.")]
        return []
    stage = "staff" if instruction.status == "pending_approval" else "send" if instruction.status == "approved" \
        else "client" if instruction.status == "awaiting_client" else "prepare"
    out = blockers(p, stage)
    if q(instruction.amount) != q(p.amount):
        out.append(_r("RUL-09", "amount-mismatch", f"The instruction must be {fmt(p.amount, p.currency)}."))
    if instruction.payee_id != p.payee_id:
        out.append(_r("RUL-21", "payee-not-verified", "The instruction must pay the stage's own payee."))
    return out


def label_for(subject_id) -> str:
    p = Payment.objects.filter(subject_id=subject_id).order_by("-created_at").first()
    return p.label if p else ""


# ----------------------------------------------------------------- preparing

@transaction.atomic
def prepare(project, *, part, subject_type, subject_id, payee, amount, by, milestone=None, holdback_amount=0,
            reprice=None, label="", evidence_ids=()) -> Payment:
    if payee is None:
        raise RuleBlocked("Every payment names one verified payee.", code="payee-not-verified",
                          blocking_reasons=[_r("RUL-22", "payee-not-verified", "No payee named.")])
    if not has_role(by, "CM", "RV", country=project.country):
        raise Forbidden("A case manager prepares payments.")
    amount = q(amount)
    if amount <= 0:
        raise RuleBlocked("There is nothing to pay for this stage.", code="release-blocked",
                          blocking_reasons=[_r("RUL-09", "nothing-to-pay", "The amount to pay is zero.")])
    if Payment.objects.filter(subject_type=subject_type, subject_id=subject_id, part=part,
                              status__in=Payment.LIVE).exists():
        raise StateConflict("There is already a live payment for this.", code="instruction-exists")
    if project.payment_route == "escrow" and project.escrow_id is None:
        raise StateConflict("Open the project's escrow first.", code="escrow-not-funded")
    pay = Payment.objects.create(country=project.country, project=project, milestone=milestone, part=part,
                                 subject_type=subject_type, subject_id=subject_id, label=label, payee=payee,
                                 amount=amount, currency=project.budget_currency, holdback_amount=q(holdback_amount),
                                 reprice=reprice, route=project.payment_route, prepared_by=by)
    if pay.route == "escrow":
        from escrow import services as esc

        ins = esc.request_release(project.escrow, payee=payee, amount=amount, subject_type=subject_type,
                                  subject_id=subject_id, requested_by=by, evidence_ids=evidence_ids,
                                  subject_label=label, holdback_amount=holdback_amount,
                                  reason=f"{label} ({project.title})")
        pay.instruction = ins
        state.transition(pay, "bld_payment", "awaiting_client", actor=by, extra_fields=["instruction"],
                         payload=_payload(pay))
    else:
        raise_if_blocked(pay, "prepare")
        state.transition(pay, "bld_payment", "awaiting_client", actor=by, payload=_payload(pay))
        notify(project.client, "approval_needed",
               f"Please approve {fmt(amount, pay.currency)} to {payee.legal_name} for {label}. Tenmina checked the "
               "stage. Nothing is paid until you approve.", subject="Your approval is needed", needs_action=True,
               obj=pay, link=f"/projects/{project.pk}/payments/{pay.pk}", category="approval")
    audit(by, "bld_payment.prepared", pay, {"amount": f"{amount:.2f}", "part": part, "route": pay.route})
    return pay


def _payload(p, **extra):
    return {"payment_id": p.pk, "project_id": p.project_id, "milestone_id": p.milestone_id, "part": p.part,
            "subject_type": p.subject_type, "subject_id": p.subject_id, "client_id": p.project.client_id,
            "amount": p.amount, "currency": p.currency, "route": p.route, "label": p.label,
            "link": f"/projects/{p.project_id}", **extra}


def _move(p, to, *, actor=None, reason="", extra_fields=None):
    if p.status == to:
        return p
    state.transition(p, "bld_payment", to, actor=actor, reason=reason, extra_fields=extra_fields,
                     payload=_payload(p))
    entry = _SUBJECTS.get(p.part)
    if entry is not None:
        entry["on_status"](p, to)
    return p


# ----------------------------------------------------------------- the client approves (RUL-11)

def _client_signed(client, mfa_at, code):
    from django.conf import settings
    from django.utils import timezone

    from accounts.services import mfa_verify

    if code:
        if not mfa_verify(client, code):
            raise MfaRequired("The code is not right. Try again.")
        return "totp_code"
    if mfa_at is None or timezone.now() - mfa_at > settings.TENMINA["MFA_FRESHNESS"]:
        raise MfaRequired()
    return "mfa_step_up"


@transaction.atomic
def client_approve(p: Payment, client, *, mfa_at=None, code=None, confirm_amount=None) -> Payment:
    p = Payment.objects.select_for_update().get(pk=p.pk)
    if p.project.client_id != client.pk:
        raise NotFound()
    if p.status != "awaiting_client":
        raise StateConflict("This payment is not waiting for your approval.")
    if confirm_amount is not None and q(confirm_amount) != p.amount:
        raise Invalid(f"The amount changed. Please check the new amount, {fmt(p.amount, p.currency)}.",
                      code="amount-mismatch")
    if p.reprice_id and p.reprice.changed and p.reprice.shown_to_client_at is None:
        p.reprice.shown_to_client_at = now()
        p.reprice.save(update_fields=["shown_to_client_at"])
    if p.route == "escrow":
        from escrow import services as esc

        esc.client_approve(p.instruction, client, mfa_at, code=code)  # release.client_approved moves us on
        p.refresh_from_db()
        return p
    _client_signed(client, mfa_at, code)
    raise_if_blocked(p, "client")
    p.client_approved_at = now()
    p.approval_request = approvals.request_approval(
        APPROVAL_SUBJECT.get(p.project.type, "milestone_release"), p.pk, p.prepared_by, required=2,
        country=p.country, summary=f"Confirm {fmt(p.amount, p.currency)} to {p.payee.legal_name} for {p.label}")
    _move(p, "client_approved", actor=client, extra_fields=["client_approved_at", "approval_request"])
    if p.reprice_id:
        p.reprice.client_approved_at = p.client_approved_at
        p.reprice.save(update_fields=["client_approved_at"])
    resolve(p)
    for s in staff_in(p.country, "RR"):
        if s.pk != p.prepared_by_id:
            notify(s, "release_approval_needed", f"{fmt(p.amount, p.currency)} to {p.payee.legal_name} for "
                                                 f"{p.label} waits for two confirmations.", needs_action=True,
                   obj=p, link=f"/back-office/project-payments/{p.pk}", category="approval")
    return p


@transaction.atomic
def client_decline(p: Payment, client, reason="") -> Payment:
    if p.project.client_id != client.pk:
        raise NotFound()
    if p.status != "awaiting_client":
        raise StateConflict("This payment is not waiting for your approval.")
    if p.route == "escrow":
        from escrow import services as esc

        esc.client_decline(p.instruction, client, reason)
        p.refresh_from_db()
        return p
    p.closed_reason = reason or "Declined by the client"
    _move(p, "rejected", actor=client, reason=p.closed_reason, extra_fields=["closed_reason"])
    return p


# ----------------------------------------------------------------- two staff approve (RUL-05, RUL-11)

def _allowed(p):
    def ok(a):
        if not has_role(a, "RR", country=p.country):
            return False
        if a.pk == p.project.client_id or (p.payee.person_id and p.payee.person_id == a.pk):
            return False
        return True

    return ok


def staff_decide(p: Payment, approver, *, mfa_at, decision="approve", note=""):
    if decision not in ("approve", "reject"):
        raise Invalid("Decision must be approve or reject.")
    if p.status == "awaiting_client":
        raise RuleBlocked("The client has not approved this payment. Silence is never approval.",
                          blocking_reasons=[{"rule": "RUL-11", "code": "client-approval-missing",
                                             "message": "The client approves first."}])
    if p.route == "escrow":
        from escrow import services as esc

        return esc.staff_approve(p.instruction, approver, mfa_at=mfa_at, decision=decision, note=note)
    if p.status != "client_approved" or p.approval_request is None:
        raise StateConflict(f"This payment is {p.status.replace('_', ' ')}.")
    if decision == "approve":
        raise_if_blocked(p, "staff")
    return approvals.decide(p.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=_allowed(p))


@transaction.atomic
def on_direct_approval(payment_id, approved: bool):
    p = Payment.objects.select_for_update().filter(pk=payment_id, route="client_direct").first()
    if p is None or p.status != "client_approved":
        return
    if not approved:
        p.closed_reason = "A staff member did not confirm it"
        _move(p, "rejected", reason=p.closed_reason, extra_fields=["closed_reason"])
        return
    p.release_approved_at = now()
    _move(p, "release_approved", extra_fields=["release_approved_at"])
    pe = p.payee
    notify(p.project.client, "pay_direct",
           f"Tenmina checked {p.label}. Please pay {fmt(p.amount, p.currency)} to {pe.account_name}, "
           f"{pe.bank_name}, account {pe.account_number}, from your own bank. Then tell us your payment reference.",
           subject="You can pay now", needs_action=True, obj=p, link=f"/projects/{p.project_id}/payments/{p.pk}",
           category="money")


# ----------------------------------------------------------------- client_direct: paid and received

@transaction.atomic
def record_client_payment(p: Payment, client, *, reference, evidence=None) -> Payment:
    p = Payment.objects.select_for_update().get(pk=p.pk)
    if p.project.client_id != client.pk:
        raise NotFound()
    if p.route != "client_direct":
        raise StateConflict("On the escrow route the bank pays. There is nothing for you to pay.")
    if p.status != "release_approved":
        raise StateConflict("Tenmina has not confirmed this payment yet. Please wait for the confirmation.")
    if not (reference or "").strip():
        raise Invalid("Enter your bank's payment reference.", code="validation-error")
    p.client_paid_at, p.client_paid_reference, p.client_paid_evidence = now(), reference.strip(), evidence
    p.save(update_fields=["client_paid_at", "client_paid_reference", "client_paid_evidence"])
    if evidence is not None:
        from evidence.services import link

        link(evidence, "bld_payment", p.pk, role="invoice", by=client)
    resolve(p)
    audit(client, "bld_payment.client_paid", p, {"reference": p.client_paid_reference})
    who = p.payee.person
    notify(who, "payment_to_confirm", f"{p.project.client.full_name} says they paid {fmt(p.amount, p.currency)} "
                                      f"for {p.label} (reference {p.client_paid_reference}). Please confirm when it "
                                      "reaches your account.", needs_action=True, obj=p,
           link=f"/project-payments/{p.pk}", category="money")
    return p


def _may_confirm_receipt(p, by):
    if has_role(by, "CM", "RV", country=p.country):
        return True
    pe = p.payee
    if pe.person_id and pe.person_id == by.pk:
        return True
    if pe.organisation_id:
        from accounts.selectors import is_member

        return is_member(by, pe.organisation_id)
    return False


@transaction.atomic
def confirm_receipt(p: Payment, by, *, evidence=None, note="") -> Payment:
    p = Payment.objects.select_for_update().get(pk=p.pk)
    if p.route != "client_direct":
        raise StateConflict("On the escrow route the bank confirms the payment.")
    if not _may_confirm_receipt(p, by):
        raise NotFound()
    if p.status != "release_approved" or p.client_paid_at is None:
        raise StateConflict("The client has not reported this payment yet.")
    staff = has_role(by, "CM", "RV", country=p.country)
    if staff and evidence is None:
        raise Invalid("Attach the bank's receipt or the payee's written confirmation.", code="validation-error")
    p.receipt_confirmed_by, p.receipt_evidence, p.paid_at = by, evidence, now()
    p.bank_reference = p.client_paid_reference
    if evidence is not None:
        from evidence.services import link

        link(evidence, "bld_payment", p.pk, role="invoice", by=by)
    _move(p, "paid", actor=by, reason=note, extra_fields=["receipt_confirmed_by", "receipt_evidence", "paid_at",
                                                          "bank_reference"])
    resolve(p)
    publish("project_payment.confirmed", p.pk, _payload(p, payee_id=p.payee_id))
    notify(p.project.client, "money_update", f"{p.payee.legal_name} confirmed {fmt(p.amount, p.currency)} for "
                                             f"{p.label} arrived. Thank you.", obj=p,
           link=f"/projects/{p.project_id}", category="money")
    return p


# ----------------------------------------------------------------- withdrawing

@transaction.atomic
def withdraw(p: Payment, by, *, reason, system=False) -> Payment:
    p.refresh_from_db()
    if p.status not in Payment.LIVE:
        return p
    if not system and not has_role(by, "CM", "RV", country=p.country):
        raise Forbidden("Only staff withdraw a payment.")
    if p.route == "escrow" and p.instruction_id:
        from escrow import services as esc

        ins = p.instruction
        ins.refresh_from_db()
        if ins.status in ("draft", "awaiting_client", "pending_approval", "approved"):
            esc.withdraw_instruction(ins, by, reason=reason, system=system)  # release.withdrawn moves us on
            p.refresh_from_db()
            if p.status not in Payment.LIVE:
                return p
        elif ins.status == "sent":
            raise StateConflict("The bank already has this instruction. It cannot be withdrawn here.")
    elif p.approval_request_id and p.approval_request.status == "open":
        approvals.withdraw(p.approval_request, by or p.prepared_by)
    p.closed_reason = reason
    _move(p, "withdrawn", actor=by, reason=reason, extra_fields=["closed_reason"])
    return p


# ----------------------------------------------------------------- following the escrow instruction

@transaction.atomic
def on_instruction_event(topic: str, payload: dict):
    iid = payload.get("instruction_id")
    if not iid:
        return
    p = Payment.objects.select_for_update().filter(instruction_id=iid).first()
    if p is None:
        return
    try:
        if topic == "release.client_approved" and p.status == "awaiting_client":
            p.client_approved_at = now()
            _move(p, "client_approved", extra_fields=["client_approved_at"])
            if p.reprice_id:
                p.reprice.client_approved_at = p.client_approved_at
                p.reprice.save(update_fields=["client_approved_at"])
        elif topic == "release.approved" and p.status == "client_approved":
            p.release_approved_at = now()
            _move(p, "release_approved", extra_fields=["release_approved_at"])
        elif topic == "release.confirmed" and p.status != "paid":
            if p.status == "client_approved":
                p.release_approved_at = p.release_approved_at or now()
                _move(p, "release_approved", extra_fields=["release_approved_at"])
            p.paid_at, p.bank_reference = now(), str(payload.get("bank_reference") or "")
            _move(p, "paid", extra_fields=["paid_at", "bank_reference"])
        elif topic in ("release.withdrawn", "release.rejected", "release.rejected_by_bank") \
                and p.status in Payment.LIVE:
            to = "withdrawn" if topic == "release.withdrawn" else "rejected"
            p.closed_reason = {"release.withdrawn": "The instruction was withdrawn",
                               "release.rejected": "The instruction was declined or rejected",
                               "release.rejected_by_bank": "The bank rejected the instruction"}[topic]
            _move(p, to, reason=p.closed_reason, extra_fields=["closed_reason"])
    except DomainError:
        log.exception("could not follow instruction %s on %s", iid, topic)
        raise


def paid_total(project, *, parts=None) -> Decimal:
    from django.db.models import Sum

    qs = Payment.objects.filter(project=project, status="paid")
    if parts:
        qs = qs.filter(part__in=parts)
    return qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
