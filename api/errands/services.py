"""TSK Paperwork and errands: the public interface other modules may call.

Catalogue (FR-TSK-001): errands.catalogue.items(country), item(country, code)
Orders (FR-TSK-002)
    create_errand(client, *, country, code, for_family_member_id=None, notes="") -> Errand
    upload_document(errand, by, key, *, evidence) -> ErrandDocument
    submit_errand(errand, client, *, terms_version, scope_version) -> Errand   # every checklist item named
    review_document(doc, by, *, accept, reason="") -> ErrandDocument
    funding_blockers(errand) -> [reason]; check_funded(errand) -> Errand
Agents and steps (FR-TSK-003, RUL-22, RUL-23, RUL-27)
    add_agent(by, *, person, vetting=None, agency_org=None, pro_agreement_id=None) -> Agent
    agent_blockers(agent) -> [reason]
    assign(errand, by, *, agent, agency_payee) -> Errand
    approve_agency(errand, client, *, mfa_at) -> Errand    # the client agrees the agency payee (RUL-28)
    start_step / record_step_proof(step, person, *, kind, evidence_id) / complete_step(step, person)
    prepare_step_fee(step, by) -> ReleaseInstruction        # payee = the agency, never the agent
    step_payable_blockers(step, payee=None, amount=None)     # registered with escrow.registry
Completion and handover (FR-TSK-004, FR-TSK-005)
    upload_result(errand, person, *, evidence_id) -> Errand
    check_result(errand, by, *, accept, note="") -> Errand   # completes; publishes work.accepted for PRO
    record_handover(errand, by, *, method, ...) -> Handover
    confirm_handover(errand, person) -> Handover
Jobs: target_watch(now=None) (errands.target_watch)

Events published: errand.ordered, errand.submitted, errand.funded, errand.assigned, errand_step.receipted,
errand.result_uploaded, errand.completed, errand.handed_over, work.accepted.
Events consumed: order.paid, held_funds.deposit_confirmed, release.confirmed, release.withdrawn,
release.rejected, release.rejected_by_bank, checkin.recorded, vetting.expired, vetting.revoked,
family_confirmation.confirmed.
"""
import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from administration import flags
from audit.services import record, security_event
from core import state
from core.errors import DomainError, Forbidden, Invalid, MfaRequired, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.permissions import has_role

from . import catalogue
from .models import Agent, Errand, ErrandDocument, ErrandStep, Handover

ZERO = Decimal("0.00")


# --------------------------------------------------------------------------- helpers

def _now():
    return timezone.now()


def _uuid(value):
    """An event payload's id, or None when it is not one of ours (other modules publish test ids)."""
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _on(country):
    flags.require("lines.tsk", country)
    flags.read_only_guard()


def _staff(by, country, *roles):
    if by is None or not has_role(by, *(roles or ("CM", "RV", "AD")), country=country):
        raise Forbidden("Only Tenmina staff can do this.")


def _reference(country):
    return f"TSK-{country.code}-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}"


def _notify(person, template, body, *, obj=None, needs_action=False, link="", channels=("in_app",), category=None,
            to_address="", country=None, subject=""):
    from notifications.services import notify

    return notify(person, template, body=body, subject=subject, subject_obj=obj, needs_action=needs_action,
                  link=link, channels=channels, category=category, to_address=to_address, country=country)


def _staff_in(country, *roles):
    from accounts.models import Person

    return list(Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                      role_grants__role__in=roles, role_grants__revoked_at__isnull=True,
                                      is_active=True).distinct().order_by("created_at"))


def _alert_cms(errand, template, body, needs_action=True):
    for p in _staff_in(errand.country, "CM"):
        _notify(p, template, body, obj=errand, needs_action=needs_action, link=f"/back-office/errands/{errand.pk}")


def _audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=obj._meta.db_table, entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None) or getattr(getattr(obj, "errand", None), "country", None))


def _fmt(amount, currency):
    return f"{currency} {Decimal(amount):,.2f}"


def _require_fresh_mfa(mfa_at):
    from django.conf import settings

    if mfa_at is None or _now() - mfa_at > settings.TENMINA["MFA_FRESHNESS"]:
        raise MfaRequired()


# --------------------------------------------------------------------------- orders (FR-TSK-001, FR-TSK-002)

@transaction.atomic
def create_errand(client, *, country, code, for_family_member_id=None, notes="", by=None) -> Errand:
    """US-TSK-001 AC1: clients order only their own country's errands, at the fees then published."""
    from countries.selectors import current_config

    _on(country)
    by = by or client
    if by.pk != client.pk:
        _staff(by, country, "CM")
    if not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client orders an errand.")
    it = catalogue.item(country, code)
    fm = None
    if for_family_member_id:
        from accounts.selectors import active_family_member

        fm = active_family_member(client, for_family_member_id)
    cfg = current_config(country)
    if cfg is None:
        raise StateConflict("This country has no published configuration.")
    e = Errand.objects.create(
        country=country, reference=_reference(country), client=client, for_family_member=fm, catalogue_version=cfg,
        catalogue_key=code, item=it, official_fees_amount=Decimal(it["official_fees"]["amount"]),
        official_fees_currency=it["official_fees"]["currency"],
        tenmina_charge_amount=Decimal(it["tenmina_charge"]["amount"]),
        tenmina_charge_currency=it["tenmina_charge"]["currency"], target_days=it["target_days"], notes=notes or "")
    for c in it["checklist"]:
        ErrandDocument.objects.create(errand=e, key=c["key"], label=c["label"], required=c["required"])
    for s in it["steps"]:
        ErrandStep.objects.create(errand=e, seq=s["seq"], key=s["key"], description=s["description"],
                                  official_fee_amount=Decimal(s["official_fee"]),
                                  official_fee_currency=e.official_fees_currency, needs_documents=s["documents"])
    _audit(by, "errand.ordered", e, {"code": code, "catalogue_version": str(cfg.pk)})
    publish("errand.ordered", e.pk, {"errand_id": e.pk, "client_id": client.pk, "code": code,
                                     "country": country.code})
    return e


def _client_or_cm(errand, by):
    if by.pk == errand.client_id:
        return
    _staff(by, errand.country, "CM")


@transaction.atomic
def upload_document(errand: Errand, by, key, *, evidence) -> ErrandDocument:
    """US-TSK-002: each checklist document, hashed and linked; restricted to the client, staff and the agent
    for the step that needs it (TC-TSK-002-03)."""
    from evidence.services import link

    _on(errand.country)
    _client_or_cm(errand, by)
    if errand.status not in ("ordered", "documents_pending", "funded"):
        raise StateConflict("Documents are uploaded before the agent starts.")
    doc = errand.documents.filter(key=key).first()
    if doc is None:
        raise NotFound("This document is not on the errand's checklist.")
    if doc.status == "accepted":
        raise StateConflict("Tenmina already accepted this document.")
    link(evidence, "errand_document", doc.pk, role=f"checklist:{key}", by=by)
    doc.evidence, doc.status, doc.uploaded_at, doc.reject_reason = evidence, "uploaded", _now(), ""
    doc.save()
    _audit(by, "errand.document_uploaded", errand, {"key": key, "evidence_id": str(evidence.pk)})
    if errand.status == "documents_pending" and not errand.documents.filter(status="rejected").exists():
        state.transition(errand, "tsk_errand", "ordered", actor=by)
    if errand.submitted_at:
        _alert_cms(errand, "errand_document_check", f"{errand.reference}: '{doc.label}' was uploaded. Check it.")
    return doc


def missing_documents(errand) -> list[ErrandDocument]:
    return list(errand.documents.filter(required=True).exclude(status__in=["uploaded", "accepted"]))


@transaction.atomic
def submit_errand(errand: Errand, client, *, terms_version, scope_version) -> Errand:
    """US-TSK-002 AC1, AC2: refused while a checklist item is missing, naming it. Tenmina's charge goes through
    the payment provider (an order); the official fees go into held funds at the partner bank. They are shown
    separately, each with its own receipt (RUL-01)."""
    from escrow import services as esc
    from orders.services import create_line_order

    _on(errand.country)
    if errand.client_id != client.pk:
        raise NotFound()
    if errand.submitted_at:
        raise StateConflict("This errand was already submitted.")
    missing = missing_documents(errand)
    if missing:
        names = ", ".join(d.label for d in missing)
        raise Invalid(f"Upload the missing documents first: {names}.", code="checklist-incomplete",
                      extra={"missing": [d.key for d in missing],
                             "errors": [{"pointer": f"/documents/{d.key}", "message": f"{d.label} is missing."}
                                        for d in missing]})
    order = create_line_order(client=client, kind="errand", country=errand.country, subject_type="errand",
                              subject_id=errand.pk, details={"errand_code": errand.catalogue_key,
                                                             "errand_reference": errand.reference},
                              accepted_terms=(terms_version, scope_version))
    errand.fee_order_id = order.pk
    if errand.official_fees_amount > 0:
        errand.escrow = esc.open_held_funds(client, errand.country, errand.official_fees_currency, by=client)
    errand.submitted_at = _now()
    errand.due_on = timezone.localdate() + timedelta(days=errand.target_days)
    errand.save(update_fields=["fee_order_id", "escrow", "submitted_at", "due_on"])
    _audit(client, "errand.submitted", errand, {"order_id": str(order.pk)})
    publish("errand.submitted", errand.pk, {"errand_id": errand.pk, "client_id": client.pk,
                                            "order_id": order.pk})
    _alert_cms(errand, "errand_document_check", f"{errand.reference}: check the client's documents.")
    return errand


def payment_routes(errand: Errand) -> dict:
    """The two payments, each by its own route (TC-TSK-002-04)."""
    from escrow import services as esc

    out = {"tenmina_charge": {"amount": f"{errand.tenmina_charge_amount:.2f}",
                              "currency": errand.tenmina_charge_currency, "route": "payment_provider",
                              "order_id": str(errand.fee_order_id) if errand.fee_order_id else None,
                              "paid": errand.fee_paid_at is not None,
                              "note": "Paid by card or mobile money to Tenmina. Never into the partner bank."},
           "official_fees": {"amount": f"{errand.official_fees_amount:.2f}",
                             "currency": errand.official_fees_currency, "route": "partner_bank_held_funds",
                             "note": "Paid into your held funds at the partner bank. Tenmina never holds it.",
                             "bank": None}}
    if errand.escrow_id:
        try:
            out["official_fees"]["bank"] = esc.payment_instructions(errand.escrow)
        except DomainError:
            out["official_fees"]["bank"] = None
    return out


@transaction.atomic
def review_document(doc: ErrandDocument, by, *, accept, reason="") -> ErrandDocument:
    errand = doc.errand
    _on(errand.country)
    _staff(by, errand.country, "CM", "RV")
    if doc.status != "uploaded":
        raise StateConflict("Only an uploaded document is checked.")
    if not accept and not (reason or "").strip():
        raise Invalid("Say what is wrong with the document.")
    doc.status = "accepted" if accept else "rejected"
    doc.reject_reason = "" if accept else reason.strip()
    doc.reviewed_by, doc.reviewed_at = by, _now()
    doc.save()
    _audit(by, f"errand.document_{doc.status}", errand, {"key": doc.key})
    if not accept:
        if errand.status in ("ordered", "funded"):
            state.transition(errand, "tsk_errand", "documents_pending", actor=by, reason=reason)
        _notify(errand.client, "errand_document_rejected", f"Please upload '{doc.label}' again for "
                f"{errand.reference}: {reason}", obj=errand, needs_action=True, link=f"/errands/{errand.pk}")
    else:
        check_funded(errand)
    return doc


def funding_blockers(errand: Errand) -> list[dict]:
    """What stops an agent being assigned (TC-TSK-002-02); shown to the client in plain words."""
    from escrow.selectors import available_to_instruct

    out = []
    if not errand.submitted_at:
        out.append({"rule": "FR-TSK-002", "code": "not-submitted", "message": "The order is not submitted yet."})
    for d in errand.documents.filter(required=True).exclude(status="accepted"):
        msg = {"missing": f"'{d.label}' is missing.", "uploaded": f"Tenmina is checking '{d.label}'.",
               "rejected": f"'{d.label}' needs uploading again: {d.reject_reason}"}.get(d.status, d.label)
        out.append({"rule": "FR-TSK-002", "code": f"document-{d.status}", "message": msg, "key": d.key})
    if errand.fee_paid_at is None:
        out.append({"rule": "FR-TSK-002", "code": "charge-unpaid",
                    "message": "Tenmina's charge is not paid yet (card or mobile money)."})
    need = remaining_fees(errand)
    if need > 0:
        have = available_to_instruct(errand.escrow, errand.official_fees_currency) if errand.escrow_id else ZERO
        if have < need:
            out.append({"rule": "FR-TSK-002", "code": "official-fees-short",
                        "message": f"The partner bank holds {_fmt(max(have, ZERO), errand.official_fees_currency)} "
                                   f"for you; the official fees need {_fmt(need, errand.official_fees_currency)}."})
    return out


def remaining_fees(errand) -> Decimal:
    return sum((s.official_fee_amount for s in errand.steps.filter(status__in=["pending", "in_progress", "blocked"])),
               ZERO)


@transaction.atomic
def check_funded(errand: Errand) -> Errand:
    errand = Errand.objects.select_for_update().get(pk=errand.pk)
    if errand.status != "ordered" or funding_blockers(errand):
        return errand
    state.transition(errand, "tsk_errand", "funded", event="errand.funded",
                     payload={"errand_id": errand.pk, "client_id": errand.client_id})
    _alert_cms(errand, "errand_assign", f"{errand.reference} is ready: assign a vetted agent and the agency.")
    _notify(errand.client, "errand_funded", f"Everything for {errand.item.get('name')} is in place. Tenmina is "
            "assigning a vetted agent.", obj=errand, link=f"/errands/{errand.pk}")
    return errand


@transaction.atomic
def cancel_errand(errand: Errand, by, *, reason) -> Errand:
    _client_or_cm(errand, by)
    if errand.status not in ("ordered", "documents_pending", "funded", "assigned"):
        raise StateConflict("An errand the agent has started cannot be cancelled here. Ask Tenmina.")
    if errand.steps.filter(status__in=["fee_instructed", "fee_paid"]).exists():
        raise StateConflict("An official fee is being paid. It cannot be cancelled now.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.")
    errand.cancel_reason = reason.strip()
    from escrow.services import standing_approval_for, withdraw_standing_approval

    sa = standing_approval_for("errand", errand.pk)
    if sa is not None:
        withdraw_standing_approval(sa, errand.client)
    return state.transition(errand, "tsk_errand", "cancelled", actor=by, reason=reason,
                            extra_fields=["cancel_reason"])


@transaction.atomic
def give_standing_approval(errand: Errand, client, *, monthly_max, mfa_at=None, code=None):
    """RUL-11: step fees up to a monthly amount without approving each; each still needs its receipt and two
    staff approvals."""
    from escrow import services as esc

    _on(errand.country)
    if errand.client_id != client.pk:
        raise NotFound()
    if errand.escrow is None:
        errand.escrow = esc.open_held_funds(client, errand.country, errand.official_fees_currency, by=client)
        errand.save(update_fields=["escrow"])
    return esc.create_standing_approval(errand.escrow, client, subject_kind="errand", subject_id=errand.pk,
                                        monthly_max=monthly_max, mfa_at=mfa_at, code=code)


@transaction.atomic
def withdraw_standing_approval(errand: Errand, client):
    from escrow import services as esc

    if errand.client_id != client.pk:
        raise NotFound()
    sa = esc.standing_approval_for("errand", errand.pk)
    if sa is None:
        raise NotFound("There is no standing approval on this errand.")
    return esc.withdraw_standing_approval(sa, client)


# --------------------------------------------------------------------------- agents (FR-TSK-003)

def _agreement_ok(agent: Agent) -> bool:
    """FR-PRO-001: an active agreement with role errand_agent. PRO answers when it is installed; until then the
    agreement id recorded on the panel stands for it."""
    try:
        from profpay import selectors as pro

        fn = getattr(pro, "active_agreement", None)
    except ImportError:
        fn = None
    if fn is not None:
        try:
            return fn(agent.person, "errand_agent") is not None
        except Exception:  # noqa: BLE001
            return False
    return agent.pro_agreement_id is not None


def agent_blockers(agent: Agent) -> list[dict]:
    out = []
    if agent.status != "active":
        out.append({"rule": "FR-TSK-003", "code": "agent-not-active", "message": f"The agent is {agent.status}."})
    v = agent.vetting
    v.refresh_from_db()
    if v.status != "vetted" or v.valid_until is None or v.valid_until < timezone.localdate():
        out.append({"rule": "FR-TSK-003", "code": "agent-not-vetted",
                    "message": f"{agent.person.full_name}'s vetting is not current ({v.status})."})
    if not _agreement_ok(agent):
        out.append({"rule": "FR-PRO-001", "code": "agent-no-agreement",
                    "message": "The agent has no active agreement with Tenmina, so Tenmina cannot pay them."})
    return out


@transaction.atomic
def add_agent(by, *, person, vetting=None, agency_org=None, pro_agreement_id=None) -> Agent:
    from accounts.selectors import live_vetting

    vetting = vetting or live_vetting(person, "errand_agent")
    if vetting is None or vetting.kind != "errand_agent" or vetting.person_id != person.pk:
        raise RuleBlocked("This person has no completed errand agent vetting.", code="agent-not-vetted",
                          blocking_reasons=[{"rule": "FR-TSK-003", "message": "Vetting is needed first."}])
    country = vetting.country
    _on(country)
    _staff(by, country, "CM", "RV")
    if vetting.status != "vetted" or vetting.valid_until is None or vetting.valid_until < timezone.localdate():
        raise RuleBlocked("The agent's vetting is not complete or has expired.", code="agent-not-vetted",
                          blocking_reasons=[{"rule": "FR-TSK-003", "message": f"Vetting is {vetting.status}."}])
    if person.has_tenmina_role("CM", "RV", "AD"):
        raise RuleBlocked("Tenmina staff are not errand agents.", code="separation-of-duties",
                          blocking_reasons=[{"rule": "FR-TSK-003", "message": "Staff"}])
    if Agent.objects.filter(person=person).exists():
        raise StateConflict("This person is already on the agent panel.")
    if not person.has_tenmina_role("CE"):
        from accounts.services import grant_role

        grant_role(person, "CE", country=country, granted_by=by)
    a = Agent.objects.create(country=country, person=person, vetting=vetting, agency_org=agency_org,
                             pro_agreement_id=pro_agreement_id, added_by=by)
    _audit(by, "errand_agent.added", a, {"vetting_id": str(vetting.pk)})
    return a


@transaction.atomic
def update_agent(agent: Agent, by, *, pro_agreement_id=None, agency_org=None) -> Agent:
    _staff(by, agent.country, "CM", "RV")
    if pro_agreement_id is not None:
        agent.pro_agreement_id = pro_agreement_id
    if agency_org is not None:
        agent.agency_org = agency_org
    agent.save()
    _audit(by, "errand_agent.updated", agent)
    return agent


@transaction.atomic
def set_agent_status(agent: Agent, by, *, to, reason="", system=False) -> Agent:
    if not system:
        _staff(by, agent.country, "CM", "RV")
    if to in ("suspended", "removed") and not (reason or "").strip():
        raise Invalid("Give the reason.")
    agent.status_reason = reason or ""
    state.transition(agent, "tsk_agent", to, actor=by, reason=reason, extra_fields=["status_reason"])
    if to != "active":
        for e in agent.errands.filter(status__in=["assigned", "in_progress"]):
            _alert_cms(e, "errand_agent_unavailable", f"The agent on {e.reference} is {to}. Assign another agent.")
    return agent


def _check_agency_payee(errand, agent, payee):
    """RUL-22, RUL-27: the official fee goes to the agency's verified account, never to the agent or their
    employer, and never to a contracted professional."""
    reasons = []
    if payee is None:
        reasons.append({"rule": "RUL-22", "message": "Name the agency's verified account."})
    else:
        if payee.kind not in ("agency", "institution"):
            reasons.append({"rule": "RUL-22", "message": f"A {payee.kind} cannot receive an official fee."})
        if payee.verification_status != "verified" or payee.name_match != "matched":
            reasons.append({"rule": "RUL-22", "message": f"{payee.legal_name} is not verified."})
        if payee.country_id != errand.country_id:
            reasons.append({"rule": "RUL-22", "message": "The agency is in another country."})
        if agent is not None and (payee.person_id == agent.person_id or (
                agent.agency_org_id and payee.organisation_id == agent.agency_org_id)):
            reasons.append({"rule": "RUL-22", "message": "The agent is never the payee of an official fee."})
    if reasons:
        raise RuleBlocked("The official fees can only go to the agency's verified account.",
                          code="payee-not-verified", blocking_reasons=reasons)


@transaction.atomic
def assign(errand: Errand, by, *, agent: Agent, agency_payee) -> Errand:
    """US-TSK-003 AC1, TC-TSK-003-03, TC-TSK-003-07: only a vetted agent with an agreement, and the agency as a
    verified payee."""
    _on(errand.country)
    _staff(by, errand.country, "CM")
    errand = Errand.objects.select_for_update().get(pk=errand.pk)
    if errand.status != "funded":
        reasons = funding_blockers(errand)
        raise StateConflict("This errand cannot be assigned yet." + (" " + reasons[0]["message"] if reasons else ""),
                            extra={"blocking_reasons": reasons})
    if agent.country_id != errand.country_id:
        raise Invalid("The agent works in another country.")
    reasons = agent_blockers(agent)
    if reasons:
        raise RuleBlocked("This agent cannot be assigned: " + "; ".join(r["message"] for r in reasons),
                          code="agent-not-vetted", blocking_reasons=reasons)
    if errand.official_fees_amount > 0 or agency_payee is not None:
        _check_agency_payee(errand, agent, agency_payee)
    errand.agent, errand.agency_payee, errand.assigned_at = agent, agency_payee, _now()
    errand.agency_approved_at = None
    state.transition(errand, "tsk_errand", "assigned", actor=by, event="errand.assigned",
                     extra_fields=["agent", "agency_payee", "assigned_at", "agency_approved_at"],
                     payload={"errand_id": errand.pk, "agent_id": agent.pk, "agent_person_id": agent.person_id,
                              "person_id": agent.person_id, "client_id": errand.client_id})
    _notify(errand.client, "errand_assigned",
            f"{agent.person.full_name}, a vetted agent, is handling {errand.item.get('name')}. Official fees go only "
            f"to {agency_payee.legal_name if agency_payee else 'the agency'}'s account.", obj=errand,
            link=f"/errands/{errand.pk}", needs_action=_needs_agency_approval(errand))
    return errand


def _needs_agency_approval(errand) -> bool:
    from escrow.services import standing_approval_for

    return bool(errand.agency_payee_id and errand.agency_approved_at is None
                and standing_approval_for("errand", errand.pk) is not None)


@transaction.atomic
def approve_agency(errand: Errand, client, *, mfa_at=None) -> Errand:
    """RUL-28: with a standing approval, the client agrees the agency as payee once, with a fresh step-up.
    Without one, the client's approval of the first fee does it."""
    from escrow import services as esc

    _on(errand.country)
    if errand.client_id != client.pk:
        raise NotFound()
    if errand.agency_payee is None or errand.escrow is None:
        raise StateConflict("No agency is named yet.")
    _require_fresh_mfa(mfa_at)
    now = _now()
    esc.lock_payee(errand.escrow, errand.agency_payee, client_approved_at=now, source="client_approved_payment")
    errand.agency_approved_at = now
    errand.save(update_fields=["agency_approved_at"])
    _audit(client, "errand.agency_approved", errand, {"payee_id": str(errand.agency_payee_id)})
    from notifications.services import resolve_action

    resolve_action(errand)
    return errand


# --------------------------------------------------------------------------- steps (FR-TSK-003, RUL-23)

def _agent_step(step: ErrandStep, person):
    e = Errand.objects.select_related("agent").get(pk=step.errand_id)
    step.errand = e
    if e.agent is None or e.agent.person_id != person.pk:
        raise NotFound("This errand is not assigned to you.")
    if e.agent.status != "active":
        raise Forbidden("You are not active on the agent panel.")
    if e.status not in ("assigned", "in_progress", "result_uploaded"):
        raise StateConflict("This errand is not open for steps.")
    return e


def _start(step: ErrandStep, actor):
    e = step.errand
    if e.status == "assigned":
        state.transition(e, "tsk_errand", "in_progress", actor=actor)
    if step.status in ("pending", "blocked"):
        step.started_at = step.started_at or _now()
        state.transition(step, "tsk_errand_step", "in_progress", actor=actor, extra_fields=["started_at"])


@transaction.atomic
def start_step(step: ErrandStep, person) -> ErrandStep:
    _on(step.errand.country)
    _agent_step(step, person)
    _start(step, person)
    return step


def _field_evidence(person, step, evidence_id, what):
    """RUL-08: taken in Tenmina Field for this step (or this errand)."""
    from evidence.models import Evidence
    from mobile.models import SignedManifest

    ev = Evidence.objects.filter(pk=evidence_id).first()
    if ev is None or ev.uploaded_by_id != person.pk:
        raise Invalid(f"The {what} was not found.")
    if not ev.is_release_grade:
        raise Invalid(f"The {what} must be photographed in Tenmina Field.", code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-08", "message": "Not app-captured."}],
                      extra={"reason": "not_app_captured"})
    m = SignedManifest.objects.filter(evidence=ev).first()
    ok = m is not None and ((m.subject_type == "errand_step" and str(m.subject_id) == str(step.pk)) or (
        m.subject_type == "errand" and str(m.subject_id) == str(step.errand_id)))
    if not ok:
        raise Invalid(f"The {what} was taken for different work.")
    return ev


@transaction.atomic
def record_step_proof(step: ErrandStep, person, *, kind, evidence_id) -> ErrandStep:
    """POST /v1/mobile/errands/{id}/steps/{seq}/receipts: the acknowledgement of lodging or the official receipt
    (FR-TSK-003)."""
    from evidence.services import link

    _on(step.errand.country)
    e = _agent_step(step, person)
    if kind not in ("acknowledgement", "receipt"):
        raise Invalid("kind must be acknowledgement or receipt.")
    step = ErrandStep.objects.select_for_update().get(pk=step.pk)
    if step.status == "done":
        raise StateConflict("This step is done.")
    ev = _field_evidence(person, step, evidence_id, kind)
    link(ev, "errand_step", step.pk, role=kind, by=person)
    _start(step, person)
    step.refresh_from_db()
    if kind == "acknowledgement":
        step.acknowledgement_evidence = ev
        step.save(update_fields=["acknowledgement_evidence"])
    else:
        step.receipt_evidence = ev
        step.save(update_fields=["receipt_evidence"])
        if step.status == "fee_paid":
            state.transition(step, "tsk_errand_step", "receipted", actor=person, event="errand_step.receipted",
                             payload={"errand_id": e.pk, "step_id": step.pk, "seq": step.seq,
                                      "evidence_id": ev.pk, "client_id": e.client_id})
        else:
            publish("errand_step.receipted", step.pk, {"errand_id": e.pk, "step_id": step.pk, "seq": step.seq,
                                                       "evidence_id": ev.pk, "client_id": e.client_id})
    _audit(person, f"errand_step.{kind}", e, {"seq": step.seq, "evidence_id": str(ev.pk)})
    _notify(e.client, "errand_progress", f"{e.item.get('name')}: step {step.seq} ({step.description}) has its "
            f"{kind}.", obj=e, link=f"/errands/{e.pk}")
    if kind != "acknowledgement" or step.official_fee_amount > 0:
        _alert_cms(e, "errand_step_proof", f"{e.reference} step {step.seq}: {kind} uploaded.", needs_action=False)
    return step


@transaction.atomic
def complete_step(step: ErrandStep, person) -> ErrandStep:
    """TC-TSK-003-04: a step is done only with its receipt or acknowledgement; a step with a fee only with the
    receipt after the agency was paid."""
    _on(step.errand.country)
    e = _agent_step(step, person)
    step = ErrandStep.objects.select_for_update().get(pk=step.pk)
    if step.official_fee_amount > 0:
        if step.status != "receipted" or step.receipt_evidence_id is None:
            raise RuleBlocked("This step has an official fee: it is done only when the agency has been paid and its "
                              "receipt is uploaded.", code="visit-not-confirmed",
                              blocking_reasons=[{"rule": "RUL-23", "message": "Receipt missing."}])
    elif step.acknowledgement_evidence_id is None and step.receipt_evidence_id is None:
        raise RuleBlocked("Upload the receipt or acknowledgement before marking the step done.",
                          code="visit-not-confirmed",
                          blocking_reasons=[{"rule": "RUL-23", "message": "No receipt or acknowledgement."}])
    if step.status == "pending":
        _start(step, person)
        step.refresh_from_db()
    step.done_at = _now()
    state.transition(step, "tsk_errand_step", "done", actor=person, event="errand_step.done",
                     extra_fields=["done_at"], payload={"errand_id": e.pk, "step_id": step.pk, "seq": step.seq})
    _notify(e.client, "errand_progress", f"{e.item.get('name')}: step {step.seq} is done ({step.description}).",
            obj=e, link=f"/errands/{e.pk}")
    return step


def step_payable_blockers(step: ErrandStep, payee=None, amount=None) -> list[dict]:
    """RUL-22, RUL-23 for the escrow subject check."""
    e = step.errand
    out = []
    if step.acknowledgement_evidence_id is None and step.receipt_evidence_id is None:
        out.append({"rule": "RUL-23", "code": "visit-not-confirmed",
                    "message": f"Step {step.seq} has no receipt or acknowledgement from the agency yet."})
    if step.status not in ("in_progress", "fee_instructed", "fee_paid", "receipted", "done"):
        out.append({"rule": "RUL-23", "code": "visit-not-confirmed", "message": f"Step {step.seq} has not started."})
    if step.official_fee_amount <= 0:
        out.append({"rule": "RUL-22", "code": "step-has-no-fee", "message": "This step has no official fee."})
    if payee is not None:
        if e.agency_payee_id is None or payee.pk != e.agency_payee_id:
            out.append({"rule": "RUL-22", "code": "payee-not-verified",
                        "message": "An official fee is paid only to the errand's agency."})
        if e.agent_id and payee.person_id == e.agent.person_id:
            out.append({"rule": "RUL-27", "code": "payee-not-verified",
                        "message": "The agent is paid by Tenmina, never from the client's money."})
    if amount is not None and Decimal(amount) != step.official_fee_amount:
        out.append({"rule": "RUL-22", "code": "step-amount",
                    "message": f"The fee for step {step.seq} is {_fmt(step.official_fee_amount, step.official_fee_currency)}."})
    return out


@transaction.atomic
def prepare_step_fee(step: ErrandStep, by):
    """US-TSK-003 AC2, AC4, TC-TSK-003-05: the official fee to the agency's verified account, against the step's
    receipt or acknowledgement. A standing approval within its month replaces the client's approval; the
    evidence and two staff approvals are always required."""
    from escrow import services as esc
    from mobile.services import evidence_blockers

    e = Errand.objects.select_related("agent", "agency_payee", "escrow").get(pk=step.errand_id)
    step.errand = e
    _on(e.country)
    _staff(by, e.country, "CM", "RV")
    flags.require("escrow.enabled", e.country)
    step = ErrandStep.objects.select_for_update().get(pk=step.pk)
    if step.release_instruction_id and step.status == "fee_instructed":
        raise StateConflict("This step's fee already has an instruction.")
    if e.status not in ("assigned", "in_progress"):
        raise StateConflict("Fees are paid while the errand is in progress.")
    reasons = step_payable_blockers(step, payee=e.agency_payee)
    if step.status != "in_progress" and not any(r["code"] == "visit-not-confirmed" for r in reasons):
        raise StateConflict(f"Step {step.seq} is {step.status.replace('_', ' ')}.")
    if reasons:
        raise RuleBlocked(reasons[0]["message"], code=reasons[0]["code"] if reasons[0]["code"] in (
            "visit-not-confirmed", "payee-not-verified") else "release-blocked", blocking_reasons=reasons)
    ids = [x for x in (step.acknowledgement_evidence_id, step.receipt_evidence_id) if x]
    ev_reasons = evidence_blockers(ids)
    if ev_reasons:
        raise RuleBlocked("The step's evidence is not cleared.", code="release-blocked", blocking_reasons=ev_reasons)
    sa = esc.standing_approval_for("errand", e.pk)
    if sa is not None and sa.escrow_id != e.escrow_id:
        sa = None
    ins = esc.request_release(
        e.escrow, payee=e.agency_payee, amount=step.official_fee_amount, currency=step.official_fee_currency,
        subject_type="errand_step", subject_id=step.pk, requested_by=by, evidence_ids=ids,
        reason=f"Official fee, step {step.seq}", subject_label=step_label(step),
        family_member_id=e.for_family_member_id, standing_approval=sa)
    step.release_instruction_id = ins.pk
    state.transition(step, "tsk_errand_step", "fee_instructed", actor=by, extra_fields=["release_instruction_id"],
                     payload={"instruction_id": ins.pk, "errand_id": e.pk})
    return ins


def step_label(step) -> str:
    e = step.errand
    return f"{e.item.get('name')} ({e.reference}), step {step.seq}: {step.description}"


@transaction.atomic
def on_release(payload: dict, topic: str):
    if payload.get("subject_type") != "errand_step":
        return None
    step = ErrandStep.objects.select_for_update().filter(pk=_uuid(payload.get("subject_id"))).first()
    if step is None or str(step.release_instruction_id) != str(payload.get("instruction_id")):
        return None
    if topic == "release.confirmed" and step.status == "fee_instructed":
        step.paid_at = _now()
        state.transition(step, "tsk_errand_step", "fee_paid", event="errand_step.fee_paid", extra_fields=["paid_at"],
                         payload={"errand_id": step.errand_id, "step_id": step.pk})
        e = step.errand
        if e.agent:
            _notify(e.agent.person, "errand_fee_paid", f"The bank paid the official fee for {e.reference} step "
                    f"{step.seq}. Upload the agency's receipt in Tenmina Field.", obj=e, channels=("in_app", "push"),
                    needs_action=True)
        _notify(e.client, "errand_progress", f"The bank paid the official fee for step {step.seq} to "
                f"{e.agency_payee.legal_name if e.agency_payee_id else 'the agency'}.", obj=e,
                link=f"/errands/{e.pk}", category="money")
        if step.receipt_evidence_id:
            state.transition(step, "tsk_errand_step", "receipted", event="errand_step.receipted",
                             payload={"errand_id": e.pk, "step_id": step.pk, "seq": step.seq,
                                      "evidence_id": step.receipt_evidence_id, "client_id": e.client_id})
    elif topic in ("release.withdrawn", "release.rejected", "release.rejected_by_bank") \
            and step.status == "fee_instructed":
        step.release_instruction_id = None
        state.transition(step, "tsk_errand_step", "in_progress", extra_fields=["release_instruction_id"],
                         reason=f"Instruction {topic.split('.')[-1].replace('_', ' ')}")
    return step


@transaction.atomic
def on_checkin(payload: dict):
    if payload.get("subject_type") != "errand_step" or payload.get("kind", "checkin") != "checkin":
        return None
    from mobile.models import CheckIn

    step = ErrandStep.objects.filter(pk=_uuid(payload.get("subject_id"))).first()
    ci = CheckIn.objects.filter(pk=_uuid(payload.get("checkin_id"))).first()
    if step is None or ci is None or step.checkin_id or step.errand.agent is None \
            or step.errand.agent.person_id != ci.person_id:
        return None
    step.checkin = ci
    step.save(update_fields=["checkin"])
    if step.errand.status in ("assigned", "in_progress"):
        _start(step, ci.person)
    return step


# --------------------------------------------------------------------------- result and completion (FR-TSK-004)

def _duplicate_result(errand, ev) -> Errand | None:
    return Errand.objects.filter(result_evidence__sha256=ev.sha256).exclude(pk=errand.pk).first()


@transaction.atomic
def upload_result(errand: Errand, person, *, evidence_id) -> Errand:
    """US-TSK-004 AC1: the resulting document or official confirmation, photographed in the app."""
    from evidence.services import link

    _on(errand.country)
    errand = Errand.objects.select_for_update().get(pk=errand.pk)
    if errand.agent is None or errand.agent.person_id != person.pk:
        raise NotFound("This errand is not assigned to you.")
    if errand.status not in ("assigned", "in_progress"):
        raise StateConflict("The result is uploaded while the errand is in progress.")
    open_steps = errand.steps.exclude(status="done")
    if open_steps.exists():
        raise StateConflict("Finish every step, with its receipt, before uploading the result.",
                            extra={"open_steps": [s.seq for s in open_steps]})
    from evidence.models import Evidence
    from mobile.models import SignedManifest

    ev = Evidence.objects.filter(pk=evidence_id, uploaded_by=person).first()
    if ev is None:
        raise Invalid("The result photo was not found.")
    if not ev.is_release_grade:
        raise Invalid("Photograph the resulting document in Tenmina Field.", code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-08", "message": "Not app-captured."}])
    m = SignedManifest.objects.filter(evidence=ev).first()
    step_ids = {str(s) for s in errand.steps.values_list("pk", flat=True)}
    if m is None or not ((m.subject_type == "errand" and str(m.subject_id) == str(errand.pk))
                         or (m.subject_type == "errand_step" and str(m.subject_id) in step_ids)):
        raise Invalid("The result photo was taken for different work.")
    link(ev, "errand", errand.pk, role="result", by=person)
    if errand.status == "assigned":
        state.transition(errand, "tsk_errand", "in_progress", actor=person)
    errand.result_evidence, errand.result_uploaded_at, errand.result_note = ev, _now(), ""
    state.transition(errand, "tsk_errand", "result_uploaded", actor=person, event="errand.result_uploaded",
                     extra_fields=["result_evidence", "result_uploaded_at", "result_note"],
                     payload={"errand_id": errand.pk, "evidence_id": ev.pk})
    dup = _duplicate_result(errand, ev)
    if dup is not None:
        security_event("errand.result_reused", actor=person, entity="tsk_errand", entity_id=str(errand.pk),
                       country=errand.country, data={"other_errand": str(dup.pk)},
                       summary="A result document already used on another errand was uploaded")
    _alert_cms(errand, "errand_result_check", f"{errand.reference}: check the resulting document.")
    return errand


def result_blockers(errand: Errand) -> list[dict]:
    """TC-RUL-23-06, TC-TSK-004-03: a reused or flagged document is not confirmed."""
    from mobile.services import evidence_blockers

    out = []
    if errand.result_evidence_id is None:
        out.append({"rule": "RUL-23", "code": "result-missing", "message": "No resulting document is uploaded."})
        return out
    if _duplicate_result(errand, errand.result_evidence) is not None:
        out.append({"rule": "RUL-23", "code": "result-reused",
                    "message": "This document image was already used on another errand."})
    out.extend(evidence_blockers([errand.result_evidence_id]))
    if errand.steps.exclude(status="done").exists():
        out.append({"rule": "FR-TSK-003", "code": "steps-open", "message": "Not every step is done."})
    return out


@transaction.atomic
def check_result(errand: Errand, by, *, accept, note="") -> Errand:
    """US-TSK-004 AC2, TC-TSK-004-01, TC-TSK-004-02: completed only when Tenmina checks the document; the agent's
    payable follows through work.accepted (FR-PRO-002), paid from Tenmina's own account (RUL-27)."""
    _on(errand.country)
    _staff(by, errand.country, "CM", "RV")
    errand = Errand.objects.select_for_update().get(pk=errand.pk)
    if errand.status != "result_uploaded":
        raise StateConflict("There is no uploaded result to check.")
    if errand.agent and by.pk == errand.agent.person_id:
        raise Forbidden("The agent cannot check their own result.")
    if not accept:
        if not (note or "").strip():
            raise Invalid("Say what is wrong with the result.")
        errand.result_note = note.strip()
        state.transition(errand, "tsk_errand", "in_progress", actor=by, reason=note, extra_fields=["result_note"])
        _notify(errand.agent.person, "errand_result_rejected", f"{errand.reference}: the result was not accepted. "
                f"{note}", obj=errand, channels=("in_app", "push"), needs_action=True)
        return errand
    reasons = result_blockers(errand)
    if reasons:
        raise RuleBlocked("The result cannot be accepted: " + reasons[0]["message"], code="result-not-accepted",
                          blocking_reasons=reasons)
    now = _now()
    errand.result_checked_by, errand.result_checked_at, errand.completed_at = by, now, now
    errand.result_note = (note or "").strip()
    state.transition(errand, "tsk_errand", "completed", actor=by, event="errand.completed",
                     extra_fields=["result_checked_by", "result_checked_at", "completed_at", "result_note"],
                     payload={"errand_id": errand.pk, "client_id": errand.client_id,
                              "agent_person_id": errand.agent.person_id})
    errand.work_accepted_at = now
    errand.save(update_fields=["work_accepted_at"])
    publish("work.accepted", errand.pk, {
        "work_kind": "errand", "work_type": "errand", "work_ref": errand.pk, "subject_type": "errand",
        "subject_id": errand.pk, "person_id": errand.agent.person_id, "role": "CE",
        "errand_code": errand.catalogue_key, "assigned_at": errand.assigned_at, "accepted_at": now, "quantity": 1,
        "country": errand.country.code})
    _notify(errand.client, "errand_completed", f"{errand.item.get('name')} is done. Tenmina checked the "
            "document. We will tell you when it is handed over.", obj=errand, link=f"/errands/{errand.pk}")
    return errand


# --------------------------------------------------------------------------- handover (FR-TSK-005)

@transaction.atomic
def record_handover(errand: Errand, by, *, method, proof_kind, evidence, receiver_person=None,
                    family_member=None, courier_name="", tracking_reference="", receiver_name="") -> Handover:
    """US-TSK-005, TC-TSK-005-01, TC-TSK-005-02: to the client, their named representative, a family member or a
    courier with a tracking reference; with a signature or photo. Anyone else is refused."""
    from accounts.selectors import is_representative
    from evidence.services import link

    _on(errand.country)
    errand = Errand.objects.select_for_update().get(pk=errand.pk)
    is_agent = errand.agent is not None and errand.agent.person_id == by.pk
    if not is_agent:
        _staff(by, errand.country, "CM")
    if errand.status != "completed":
        raise StateConflict("Only a completed errand is handed over.")
    if method not in Handover.METHODS:
        raise Invalid("Hand over to the client, a representative, a family member or a courier.")
    if proof_kind not in Handover.PROOFS:
        raise Invalid("Record a signature or a photo.")
    if evidence is None:
        raise Invalid("Attach the signature or photo.")
    if is_agent and not evidence.is_release_grade:
        raise Invalid("Take the signature or photo in Tenmina Field.", code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-08", "message": "Not app-captured."}])
    name = (receiver_name or "").strip()
    if method == "client":
        receiver_person, name = errand.client, errand.client.full_name
    elif method == "representative":
        if receiver_person is None or not (is_representative(receiver_person, "errand", errand.pk)
                                           or is_representative(receiver_person, "errand", str(errand.pk))):
            raise Invalid("The receiver is not a representative the client named for this errand.",
                          code="receiver-not-named")
        name = receiver_person.full_name
    elif method == "family_member":
        if family_member is None or family_member.client_id != errand.client_id or family_member.status != "active":
            raise Invalid("The receiver is not one of the client's family members.", code="receiver-not-named")
        name = family_member.full_name
    else:
        if not courier_name.strip() or not tracking_reference.strip():
            raise Invalid("A courier handover needs the courier's name and the tracking reference.",
                          code="receiver-not-named")
        name = name or courier_name.strip()
    link(evidence, "errand", errand.pk, role=f"handover_{proof_kind}", by=by)
    h = Handover.objects.create(errand=errand, method=method, receiver_person=receiver_person,
                                receiver_family_member=family_member if method == "family_member" else None,
                                receiver_name=name, courier_name=courier_name.strip(),
                                tracking_reference=tracking_reference.strip(), proof_kind=proof_kind,
                                evidence=evidence, recorded_by=by, handed_at=_now())
    errand.handed_over_at = h.handed_at
    state.transition(errand, "tsk_errand", "handed_over", actor=by, event="errand.handed_over",
                     extra_fields=["handed_over_at"],
                     payload={"errand_id": errand.pk, "client_id": errand.client_id, "method": method,
                              "tracking_reference": h.tracking_reference})
    text = f"{errand.item.get('name')} was handed to {name}"
    if method == "courier":
        text += f" ({courier_name}, tracking {tracking_reference})"
    _notify(errand.client, "errand_handed_over", text + ". Tell us if anything is wrong.", obj=errand,
            link=f"/errands/{errand.pk}")
    if method == "family_member" and family_member.phone:
        from notifications.services import send_confirmation_code

        conf = send_confirmation_code(subject_type="errand_handover", subject_id=h.pk, country=errand.country,
                                      purpose="errand_handover", to_address=family_member.phone, channel="sms",
                                      recipient_name=family_member.full_name, recipient_person=family_member.person,
                                      summary=f"You received {errand.item.get('name')} from Tenmina", created_by=by)
        h.confirmation_id = conf.pk
        h.save(update_fields=["confirmation_id"])
    return h


@transaction.atomic
def confirm_handover(errand: Errand, person) -> Handover:
    """The client (or the representative who received it) confirms receipt."""
    h = getattr(errand, "handover", None)
    if h is None:
        raise NotFound("Nothing was handed over yet.")
    if person.pk not in (errand.client_id, h.receiver_person_id):
        raise NotFound()
    if h.confirmed_at is None:
        h.confirmed_at, h.confirmed_via = _now(), "client" if person.pk == errand.client_id else "receiver"
        h.save(update_fields=["confirmed_at", "confirmed_via"])
        _audit(person, "errand.handover_confirmed", errand, {"via": h.confirmed_via})
    return h


@transaction.atomic
def on_family_confirmed(payload: dict):
    if payload.get("subject_type") != "errand_handover":
        return None
    h = Handover.objects.filter(pk=_uuid(payload.get("subject_id")), confirmed_at__isnull=True).first()
    if h is None:
        return None
    h.confirmed_at, h.confirmed_via = _now(), payload.get("via") or "code"
    h.save(update_fields=["confirmed_at", "confirmed_via"])
    return h


# --------------------------------------------------------------------------- events and jobs

@transaction.atomic
def on_order_paid(payload: dict):
    if payload.get("kind") != "errand" or not payload.get("subject_id"):
        return None
    e = Errand.objects.filter(pk=_uuid(payload["subject_id"])).first()
    if e is None or e.fee_paid_at:
        return e
    e.fee_paid_at = _now()
    e.save(update_fields=["fee_paid_at"])
    return check_funded(e)


def on_deposit(payload: dict):
    for e in Errand.objects.filter(escrow_id=payload.get("escrow_id"), status="ordered"):
        check_funded(e)


@transaction.atomic
def on_vetting_lapsed(payload: dict):
    if payload.get("kind") != "errand_agent":
        return
    for a in Agent.objects.filter(person_id=payload.get("person_id"), status="active"):
        set_agent_status(a, None, to="suspended", reason="The agent's vetting expired or was revoked.", system=True)


def target_watch(now=None) -> dict:
    """Job errands.target_watch: warn when an errand nears or passes its target time (FR-TSK-001)."""
    now = now or _now()
    today = timezone.localdate(now)
    out = {"near": 0, "overdue": 0}
    open_states = ["ordered", "documents_pending", "funded", "assigned", "in_progress", "result_uploaded"]
    for e in Errand.objects.filter(status__in=open_states, due_on__isnull=False):
        with transaction.atomic():
            if e.due_on < today and e.overdue_warned_at is None:
                e.overdue_warned_at = now
                e.save(update_fields=["overdue_warned_at"])
                _notify(e.client, "errand_overdue", f"{e.item.get('name')} has passed its target date "
                        f"({e.due_on:%d %B}). Tenmina is chasing it.", obj=e, link=f"/errands/{e.pk}")
                _alert_cms(e, "errand_overdue", f"{e.reference} is past its target date.")
                out["overdue"] += 1
            elif today <= e.due_on <= today + timedelta(days=2) and e.near_warned_at is None:
                e.near_warned_at = now
                e.save(update_fields=["near_warned_at"])
                _alert_cms(e, "errand_near_target", f"{e.reference} is due on {e.due_on:%d %B}.", needs_action=False)
                out["near"] += 1
    return out


def status_text(e: Errand) -> str:
    """Each step in plain language for the client (J-12 step 3)."""
    if e.status == "ordered" and not e.submitted_at:
        missing = missing_documents(e)
        return (f"Upload {len(missing)} document(s) to start." if missing else
                "Accept the terms and submit to pay.")
    if e.status in ("ordered", "documents_pending"):
        reasons = funding_blockers(e)
        return reasons[0]["message"] if reasons else "Ready for an agent."
    if e.status == "funded":
        return "Tenmina is assigning a vetted agent."
    if e.status in ("assigned", "in_progress"):
        step = e.steps.exclude(status="done").order_by("seq").first()
        if step is None:
            return "All steps are done. Waiting for the resulting document."
        return f"Step {step.seq}: {step.description} ({step.status.replace('_', ' ')})"
    return {"result_uploaded": "Tenmina is checking the resulting document.",
            "completed": "Done. Waiting for handover.", "handed_over": "Handed over.",
            "cancelled": f"Cancelled: {e.cancel_reason}"}.get(e.status, e.status)
