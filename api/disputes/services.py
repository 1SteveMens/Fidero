"""DSP Disputes: the public interface other modules may call.

FR-DSP-001 a party to an escrow, milestone, project or listing opens a dispute with a reason and evidence
FR-DSP-002 every linked release is frozen (RUL-15): ESC freezes on dispute.opened and restores on
           dispute.resolved or dispute.withdrawn; LST suspends the listing
FR-DSP-003 deadlines in working days from configuration: response, evidence, decision (5, 10, 10 assumptions)
FR-DSP-004 the decision, reasons and decider are recorded after two staff approve it; every party is told
FR-DSP-005 a reviewer refers to mediation; the outcome is recorded and approved the same way

Events published (payload keys): dispute.opened, dispute.resolved, dispute.withdrawn with dispute_id,
reference, escrow_id or project_id (one event per escrow), milestone_id, listing_id, reason, country and,
for resolved, outcome ('refund' when the decision is a refund); dispute.closed with dispute_id, parties
[{person_id, organisation_id, side, role}], in_favour_of, raised_by_id, outcome, for RAT.
"""
import logging
import secrets

from django.db import transaction
from django.utils import timezone

from administration import flags
from audit.services import record
from core import approvals, state
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict
from core.events import publish
from core.permissions import has_role

from . import registry
from .models import IN_FAVOUR, OPEN_STATUSES, OUTCOMES, SUBJECT_TYPES, Decision, Dispute, Party, Statement, SubjectLink

log = logging.getLogger(__name__)

DEFAULT_DAYS = {"response_days": 5, "evidence_days": 10, "decision_days": 10}  # working days, assumptions
STATEMENT_STATES = ("open", "awaiting_response", "evidence")


# --------------------------------------------------------------------------- helpers

def _now():
    return timezone.now()


def _today(country):
    from escrow.common import local_today

    return local_today(country)


def _add_wd(country, d, n):
    from countries.selectors import add_working_days

    return add_working_days(country, d, int(n))


def deadline_days(country) -> dict:
    """FR-DSP-003: adm_setting dispute_deadlines, with the 01 defaults for any key it lacks."""
    from administration.selectors import setting

    v = setting("dispute_deadlines", country, {}) or {}
    return {k: int(v.get(k, d)) for k, d in DEFAULT_DAYS.items()}


def _notify(person, template, body, *, obj=None, needs_action=False, subject=""):
    if person is None:
        return
    from notifications.services import notify

    try:
        notify(person, template, body=body, subject=subject, subject_obj=obj, link=f"/disputes/{obj.pk}" if obj else "",
               needs_action=needs_action)
    except Exception:  # noqa: BLE001
        log.exception("notification %s failed", template)


def _people_of(party):
    if party.person_id:
        return [party.person]
    from accounts.models import Person

    return list(Person.objects.filter(memberships__organisation_id=party.organisation_id,
                                      memberships__status="active", is_active=True))


def _tell_parties(d, template, body, *, needs_action_sides=(), exclude=None):
    seen = set()
    for p in d.parties.select_related("person", "organisation"):
        for person in _people_of(p):
            if person.pk in seen or (exclude is not None and person.pk == exclude.pk):
                continue
            seen.add(person.pk)
            _notify(person, template, body, obj=d, needs_action=p.side in needs_action_sides,
                    subject=f"Dispute {d.reference}")
        if p.notified_at is None:
            Party.objects.filter(pk=p.pk).update(notified_at=_now())


def _alert_staff(country, roles, template, body, obj):
    from escrow.common import staff_in

    for p in staff_in(country, *roles):
        _notify(p, template, body, obj=obj, needs_action=True)


def _audit(actor, action, d, data=None):
    record(actor=actor, action=action, entity="dispute", entity_id=d.pk, data=data or {}, country=d.country)


def is_staff(person, country, *roles) -> bool:
    return has_role(person, *(roles or ("CM", "RV", "AD")), country=country)


def party_of(person, d) -> Party | None:
    """The person's own party row, directly or through an organisation they belong to."""
    if person is None or not person.is_authenticated:
        return None
    p = d.parties.filter(person=person).first()
    if p:
        return p
    from accounts.selectors import organisations_of

    orgs = list(organisations_of(person).values_list("pk", flat=True))
    return d.parties.filter(organisation_id__in=orgs).first() if orgs else None


def can_view(person, d) -> bool:
    return party_of(person, d) is not None or is_staff(person, d.country) or d.opened_by_id == getattr(person, "pk",
                                                                                                      None)


def _is_subject_party(person, subject) -> tuple:
    from accounts.selectors import is_member

    for who, org, role in subject.parties:
        if who is not None and who.pk == person.pk:
            return who, org, role
        if org is not None and is_member(person, org.pk):
            return None, org, role
    for e in subject.escrows:
        from accounts.selectors import is_representative

        if is_representative(person, "escrow", e.pk):
            return e.client, None, "buyer"
    return None


def dispute_payload(d, **extra) -> dict:
    return {"dispute_id": d.pk, "reference": d.reference, "country": d.country.code, "subject_type": d.subject_type,
            "subject_id": d.subject_id, "project_id": d.project_id, "milestone_id": d.milestone_id,
            "listing_id": d.listing_id, "reason": d.reason, **extra}


def _publish_each(topic, d, **extra):
    """One event per frozen escrow (ESC reads escrow_id), one for the project, one for a listing alone."""
    escrow_ids = list(d.links.filter(subject_type="escrow").values_list("subject_id", flat=True))
    sent = False
    if d.project_id:
        publish(topic, d.pk, dispute_payload(d, escrow_id=None, **extra))
        sent = True
    for eid in escrow_ids:
        if d.project_id:
            from escrow.models import Escrow

            if Escrow.objects.filter(pk=eid, project_id=d.project_id).exists():
                continue
        publish(topic, d.pk, dispute_payload(d, escrow_id=eid, **extra))
        sent = True
    if not sent:
        publish(topic, d.pk, dispute_payload(d, escrow_id=None, **extra))


# --------------------------------------------------------------------------- opening (FR-DSP-001, 002, 003)

def _evidence_list(ids, author, country):
    from evidence.models import Evidence

    ids = [str(i) for i in (ids or [])]
    found = list(Evidence.objects.filter(pk__in=ids))
    if len(found) != len(set(ids)):
        raise Invalid("Some evidence was not found. Upload it again.", code="evidence-rejected")
    for ev in found:
        if ev.country_id != country.pk:
            raise Forbidden("The evidence belongs to another country.")
        if ev.uploaded_by_id != author.pk and not is_staff(author, country):
            raise Forbidden("Attach only files you uploaded.")
    return found


def _link_evidence(found, d, author):
    from evidence.services import link

    for ev in found:
        link(ev, "dispute", d.pk, role="statement", by=author)


@transaction.atomic
def open_dispute(actor, *, subject_type, subject_id, reason, category="other", statement="", evidence_ids=(),
                 project_id=None) -> Dispute:
    flags.read_only_guard()
    if subject_type not in SUBJECT_TYPES:
        raise Invalid(f"A dispute is raised on one of: {', '.join(SUBJECT_TYPES)}.")
    if not (reason or "").strip():
        raise Invalid("Give the reason for the dispute.", extra={"errors": [{"pointer": "/reason",
                                                                              "message": "Required."}]})
    if category not in Dispute.CATEGORIES:
        raise Invalid(f"Category must be one of {', '.join(Dispute.CATEGORIES)}.")
    subject = registry.resolve(subject_type, subject_id, {"project_id": project_id})
    if subject is None:
        raise NotFound("There is nothing to dispute here.")
    country = subject.country
    if subject_type == "listing":
        flags.require("listings.enabled", country)
    mine = _is_subject_party(actor, subject)
    staff = is_staff(actor, country, "CM", "RV")
    if mine is None and not staff:
        raise NotFound("There is nothing to dispute here.")  # TC-DSP-001-02: a non-party learns nothing
    if Dispute.objects.filter(subject_type=subject_type, subject_id=subject_id, opened_by=actor,
                              status__in=OPEN_STATUSES).exists():
        raise StateConflict("You already have an open dispute on this.", code="dispute-exists")
    found = _evidence_list(evidence_ids, actor, country)
    d = Dispute.objects.create(
        country=country, reference=f"DSP-{country.code}-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}",
        opened_by=actor, opened_by_staff=mine is None, category=category, reason=reason.strip(),
        subject_type=subject_type, subject_id=subject_id, subject_label=subject.label,
        escrow=subject.escrows[0] if len(subject.escrows) == 1 else None, project_id=subject.project_id,
        milestone_id=subject.milestone_id, listing=subject.listing)
    raiser_key = None
    if mine is not None:
        who, org, role = mine
        raiser_key = (getattr(org, "pk", None), getattr(who, "pk", None) if org is None else None)
        Party.objects.create(dispute=d, person=who if org is None else None, organisation=org, side="raised_by",
                             role=role, name=org.name if org else who.full_name)
    else:
        Party.objects.create(dispute=d, person=actor, side="other", role="tenmina", name="Tenmina")
    seen = {raiser_key}
    for who, org, role in subject.parties:
        key = (getattr(org, "pk", None), getattr(who, "pk", None) if org is None else None)
        if key in seen or (who is None and org is None):
            continue
        seen.add(key)
        Party.objects.create(dispute=d, person=who if org is None else None, organisation=org, side="respondent",
                             role=role, name=org.name if org else who.full_name)
    for st, sid, prior in subject.links:
        SubjectLink.objects.get_or_create(dispute=d, subject_type=st, subject_id=sid, defaults={"prior_status": prior})
    text = (statement or "").strip() or reason.strip()
    Statement.objects.create(dispute=d, party=d.parties.filter(side__in=["raised_by", "other"]).first(), author=actor,
                             kind="statement" if mine is not None else "staff_note", text=text,
                             evidence_ids=[str(e.pk) for e in found])
    _link_evidence(found, d, actor)
    _audit(actor, "dispute.opened", d, {"subject_type": subject_type, "subject_id": str(subject_id),
                                        "links": [f"{a}:{b}" for a, b, _ in subject.links]})
    _publish_each("dispute.opened", d)
    # Open to Awaiting response once the other parties are told (01 C8), with every deadline set (FR-DSP-003).
    days = deadline_days(country)
    today = _today(country)
    d.response_due = _add_wd(country, today, days["response_days"])
    d.evidence_due = _add_wd(country, d.response_due, days["evidence_days"])
    d.decision_due = _add_wd(country, d.evidence_due, days["decision_days"])
    _tell_parties(d, "dispute_opened", f"A dispute was opened on {subject.label}: {d.reason} Payments linked to it "
                  f"are on hold. Respond by {d.response_due:%d %B %Y}.", needs_action_sides=("respondent",),
                  exclude=actor)
    state.transition(d, "dispute", "awaiting_response", actor=actor, event="dispute.awaiting_response",
                     payload=dispute_payload(d), extra_fields=["response_due", "evidence_due", "decision_due"])
    _alert_staff(country, ("CM", "RV"), "dispute_opened_staff", f"Dispute {d.reference} on {subject.label}: {d.reason}",
                 d)
    return d


# --------------------------------------------------------------------------- statements and stages

def _move(d, to, *, actor=None, reason="", extra=(), **payload):
    return state.transition(d, "dispute", to, actor=actor, reason=reason, payload=dispute_payload(d, **payload),
                            extra_fields=list(extra))


def _to_evidence(d, actor=None, why=""):
    days = deadline_days(d.country)
    today = _today(d.country)
    d.evidence_due = _add_wd(d.country, today, days["evidence_days"])
    d.decision_due = _add_wd(d.country, d.evidence_due, days["decision_days"])
    _move(d, "evidence", actor=actor, reason=why, extra=["evidence_due", "decision_due"])
    _tell_parties(d, "dispute_evidence", f"Dispute {d.reference} is in the evidence stage. Send your evidence by "
                  f"{d.evidence_due:%d %B %Y}.", needs_action_sides=("raised_by", "respondent"))


def _to_decision(d, actor=None, why=""):
    days = deadline_days(d.country)
    d.decision_due = _add_wd(d.country, _today(d.country), days["decision_days"])
    d.early_move_note = why if "confirmed" in why else d.early_move_note
    _move(d, "decision", actor=actor, reason=why, extra=["decision_due", "early_move_note"])
    _tell_parties(d, "dispute_decision_stage", f"Dispute {d.reference} is with Tenmina for a decision by "
                  f"{d.decision_due:%d %B %Y}.")
    _alert_staff(d.country, ("RV",), "dispute_decide", f"Dispute {d.reference} is ready for a decision.", d)


@transaction.atomic
def add_statement(d, author, *, text, evidence_ids=()) -> Statement:
    d = Dispute.objects.select_for_update().get(pk=d.pk)
    flags.read_only_guard()
    party = party_of(author, d)
    staff = is_staff(author, d.country, "CM", "RV")
    if party is None and not staff:
        raise NotFound()
    if not (text or "").strip():
        raise Invalid("Write your statement.")
    if party is not None and d.status not in STATEMENT_STATES:
        raise StateConflict("Statements are closed at this stage.", extra={"status": d.status})
    if party is None and d.status in ("closed", "withdrawn"):
        raise StateConflict("This dispute has ended.")
    found = _evidence_list(evidence_ids, author, d.country)
    kind = "staff_note" if party is None else ("response" if party.side == "respondent" and d.status ==
                                                "awaiting_response" else "evidence" if found else "statement")
    s = Statement.objects.create(dispute=d, party=party, author=author, kind=kind, text=text.strip(),
                                 evidence_ids=[str(e.pk) for e in found])
    _link_evidence(found, d, author)
    _audit(author, "dispute.statement", d, {"kind": kind, "evidence": len(found)})
    if party is not None and party.side == "respondent" and party.responded_at is None:
        party.responded_at = _now()
        party.save(update_fields=["responded_at"])
        if d.status == "awaiting_response" and not d.parties.filter(side="respondent",
                                                                    responded_at__isnull=True).exists():
            _to_evidence(d, author, "Response received")
    return s


@transaction.atomic
def confirm_evidence_complete(d, person) -> Dispute:
    """TC-STM-DSP-05, -11: every party confirming moves the dispute to Decision early; one is not enough."""
    d = Dispute.objects.select_for_update().get(pk=d.pk)
    party = party_of(person, d)
    if party is None:
        raise NotFound()
    if d.status != "evidence":
        raise StateConflict("You confirm your evidence during the evidence stage.")
    if party.evidence_complete_at is None:
        party.evidence_complete_at = _now()
        party.save(update_fields=["evidence_complete_at"])
        _audit(person, "dispute.evidence_complete", d, {"party_id": str(party.pk)})
    waiting = d.parties.filter(side__in=["raised_by", "respondent"], evidence_complete_at__isnull=True)
    if not waiting.exists():
        _to_decision(d, person, "All parties confirmed their evidence is complete: " + ", ".join(
            f"{p.name} at {timezone.localtime(p.evidence_complete_at):%d %b %H:%M}"
            for p in d.parties.filter(side__in=["raised_by", "respondent"])))
    d.refresh_from_db()
    return d


def deadline_tick(today=None) -> dict:
    """disputes.deadline_tick, hourly (US-DSP-003 AC2, TC-STM-DSP-03, -04, -07)."""
    out = {"to_evidence": 0, "to_decision": 0, "escalated": 0}
    for d in Dispute.objects.filter(status__in=["awaiting_response", "evidence", "decision"]).select_related(
            "country"):
        t = today or _today(d.country)
        with transaction.atomic():
            d = Dispute.objects.select_for_update().get(pk=d.pk)
            if d.status == "awaiting_response" and d.response_due and t > d.response_due:
                d.parties.filter(side="respondent", responded_at__isnull=True).update(missed_response=True)
                _audit(None, "dispute.response_missed", d, {"due": d.response_due.isoformat()})
                _to_evidence(d, None, "The response deadline passed without a response.")
                out["to_evidence"] += 1
            elif d.status == "evidence" and d.evidence_due and t > d.evidence_due:
                _to_decision(d, None, "The evidence deadline passed.")
                out["to_decision"] += 1
            elif d.status == "decision" and d.decision_due and t > d.decision_due and d.escalated_at is None:
                d.escalated_at = _now()
                d.save(update_fields=["escalated_at"])
                _audit(None, "dispute.escalated", d, {"decision_due": d.decision_due.isoformat()})
                publish("dispute.escalated", d.pk, dispute_payload(d))
                roles = tuple(_cfg_list(d.country, "disputes.escalate_to_roles", ["AD"]))
                _alert_staff(d.country, roles, "dispute_escalated", f"Dispute {d.reference} passed its decision "
                             f"deadline of {d.decision_due:%d %B %Y}. It needs a decision now.", d)
                _tell_parties(d, "dispute_escalated", f"The decision on dispute {d.reference} is late. It has been "
                              "escalated within Tenmina.")
                out["escalated"] += 1
    return out


def _cfg_list(country, key, default):
    from countries.selectors import config

    try:
        v = config(country, key, default)
    except Exception:  # noqa: BLE001
        return default
    return v or default


# --------------------------------------------------------------------------- decisions (FR-DSP-004, 005)

def conflicted(person, d) -> list[str]:
    """TC-DSP-004-02: a party, or someone who prepared or approved a disputed release, may not decide."""
    out = []
    if party_of(person, d) is not None or d.opened_by_id == person.pk:
        out.append("You are a party to this dispute.")
    ids = list(d.links.filter(subject_type="release_instruction").values_list("subject_id", flat=True))
    escrow_ids = list(d.links.filter(subject_type="escrow").values_list("subject_id", flat=True))
    from core.models import Approval
    from escrow.models import ReleaseInstruction

    ins = ReleaseInstruction.objects.filter(escrow_id__in=escrow_ids).values_list("pk", flat=True)
    all_ids = set(ids) | set(ins)
    if all_ids:
        if Approval.objects.filter(request__subject_type="escrow_release", request__subject_id__in=all_ids,
                                   approver=person).exists():
            out.append("You approved a release this dispute is about.")
        if ReleaseInstruction.objects.filter(pk__in=all_ids, prepared_by=person).exists():
            out.append("You prepared a release this dispute is about.")
    return out


def _decider(person, d, roles):
    if not is_staff(person, d.country, *roles):
        raise Forbidden("Only Tenmina staff decide a dispute.")
    why = conflicted(person, d)
    if why:
        raise DomainError(" ".join(why), code="conflict-of-interest", status=409,
                          blocking_reasons=[{"rule": "FR-DSP-004", "message": m} for m in why])


@transaction.atomic
def propose_decision(d, actor, *, outcome, in_favour_of, reasons, details=None, mediation_reference="") -> Decision:
    """Record the decision (or the mediation outcome) for two staff to approve. Reasons are required."""
    d = Dispute.objects.select_for_update().get(pk=d.pk)
    flags.read_only_guard()
    _decider(actor, d, ("CM", "RV"))
    kind = "mediation_outcome" if d.status == "referred" else "decision"
    if d.status not in ("decision", "referred"):
        raise StateConflict("A decision is recorded only in the decision stage (or after mediation).",
                            extra={"status": d.status})
    if outcome not in OUTCOMES:
        raise Invalid(f"Outcome must be one of {', '.join(OUTCOMES)}.")
    if in_favour_of not in IN_FAVOUR:
        raise Invalid(f"In favour of must be one of {', '.join(IN_FAVOUR)}.")
    if not (reasons or "").strip():
        raise Invalid("Give the reasons for the decision.", extra={"errors": [{"pointer": "/reasons",
                                                                                "message": "Required."}]})
    if kind == "mediation_outcome" and not (mediation_reference or d.mediation_reference):
        raise Invalid("Give the mediator's reference for the outcome.")
    if d.decisions.filter(status="pending").exists():
        raise StateConflict("A decision is already waiting for approval.")
    dec = Decision.objects.create(dispute=d, kind=kind, outcome=outcome, in_favour_of=in_favour_of,
                                  reasons=reasons.strip(), details=details or {}, prepared_by=actor)
    dec.approval_request = approvals.request_approval(
        "dispute_decision", dec.pk, actor, required=2, country=d.country,
        summary=f"{kind.replace('_', ' ').capitalize()} on dispute {d.reference}: {outcome}")
    dec.save(update_fields=["approval_request"])
    if mediation_reference:
        d.mediation_reference = mediation_reference
        d.save(update_fields=["mediation_reference"])
    _audit(actor, "dispute.decision_proposed", d, {"decision_id": str(dec.pk), "outcome": outcome, "kind": kind})
    _alert_staff(d.country, ("RV",), "dispute_decision_approval", f"A decision on dispute {d.reference} needs two "
                 "approvals.", d)
    return dec


def approve_decision(d, approver, *, decision="approve", mfa_at=None, note="") -> Decision:
    dec = d.decisions.filter(status="pending").select_related("approval_request").first()
    if dec is None:
        raise StateConflict("There is no decision waiting for approval.")
    _decider(approver, d, ("RV", "AD"))
    if decision == "reject" and not (note or "").strip():
        raise Invalid("Say why you reject the decision.")
    approvals.decide(dec.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                     allowed=lambda a: is_staff(a, d.country, "RV", "AD") and not conflicted(a, d))
    dec.refresh_from_db()
    return dec


@transaction.atomic
def on_approval(subject_id, approved: bool):
    dec = Decision.objects.select_for_update().filter(pk=subject_id).first()
    if dec is None or dec.status != "pending":
        return
    d = Dispute.objects.select_for_update().get(pk=dec.dispute_id)
    dec.decided_at = _now()
    if not approved:
        state.transition(dec, "dispute_decision", "rejected", extra_fields=["decided_at"],
                         payload={"dispute_id": d.pk})
        _notify(dec.prepared_by, "dispute_decision_rejected", f"The decision on dispute {d.reference} was not "
                "approved. Record a new one.", obj=d, needs_action=True)
        return
    state.transition(dec, "dispute_decision", "approved", extra_fields=["decided_at"], payload={"dispute_id": d.pk})
    d.decision, d.decision_outcome, d.in_favour_of = dec.reasons, dec.outcome, dec.in_favour_of
    d.decided_by, d.decided_at, d.closed_at = dec.prepared_by, _now(), _now()
    _move(d, "closed", actor=dec.prepared_by, extra=["decision", "decision_outcome", "in_favour_of",
                                                                  "decided_by", "decided_at", "closed_at"],
          outcome=dec.outcome)
    _close_effects(d, dec)


def _close_effects(d, dec):
    """Lift or apply the outcome on every frozen subject, tell everyone, and tell RAT."""
    words = {"continue": "Payments continue under the normal checks.",
             "refund": "The escrow is cancelled and the money goes back to where it came from.",
             "partial_refund": "Tenmina will prepare the partial refund under the escrow rules.",
             "other": "Tenmina will contact you about the next steps."}[dec.outcome]
    _publish_each("dispute.resolved", d, outcome="refund" if dec.outcome == "refund" else dec.outcome,
                  in_favour_of=dec.in_favour_of)
    if dec.outcome == "partial_refund":
        _alert_staff(d.country, ("CM",), "dispute_partial_refund", f"Dispute {d.reference} was decided for a partial "
                     f"refund: {dec.details}. Prepare it under the escrow rules.", d)
    _tell_parties(d, "dispute_decided", f"Dispute {d.reference} is decided: {d.decision} {words}")
    publish("dispute.closed", d.pk, {
        "dispute_id": d.pk, "reference": d.reference, "country": d.country.code, "outcome": dec.outcome,
        "in_favour_of": dec.in_favour_of, "raised_by_id": d.opened_by_id if not d.opened_by_staff else None,
        "kind": dec.kind, "subject_type": d.subject_type, "subject_id": d.subject_id,
        "parties": [{"person_id": p.person_id, "organisation_id": p.organisation_id, "side": p.side,
                     "role": p.role} for p in d.parties.all()]})


@transaction.atomic
def refer(d, actor, *, mediator, reason) -> Dispute:
    d = Dispute.objects.select_for_update().get(pk=d.pk)
    _decider(actor, d, ("RV",))
    if d.status not in ("open", "awaiting_response", "evidence", "decision"):
        raise StateConflict("This dispute cannot be referred now.", extra={"status": d.status})
    if not (mediator or "").strip() or not (reason or "").strip():
        raise Invalid("Name the mediator and give the reason.")
    if d.decisions.filter(status="pending").exists():
        raise StateConflict("A decision is waiting for approval. Reject it before referring.")
    d.referred_at, d.referred_by = _now(), actor
    d.mediator, d.referral_reason = mediator.strip(), reason.strip()
    _move(d, "referred", actor=actor, reason=reason.strip(),
          extra=["referred_at", "referred_by", "mediator", "referral_reason"])
    _tell_parties(d, "dispute_referred", f"Dispute {d.reference} was referred to mediation with {d.mediator}. "
                  "Payments stay on hold until the outcome is recorded.")
    return d


@transaction.atomic
def withdraw(d, actor, reason="") -> Dispute:
    """Only the party who raised it, and only before the decision stage (TC-STM-DSP-15 to -17)."""
    d = Dispute.objects.select_for_update().get(pk=d.pk)
    if actor.pk != d.opened_by_id:
        if can_view(actor, d):
            raise Forbidden("Only the person who raised the dispute can withdraw it.")
        raise NotFound()
    if d.status not in ("open", "awaiting_response", "evidence"):
        raise StateConflict("A dispute can be withdrawn only before the decision stage. A new dispute is needed "
                            "to reopen one.", extra={"status": d.status})
    d.withdrawn_at, d.withdraw_reason = _now(), (reason or "").strip()
    _move(d, "withdrawn", actor=actor, reason=d.withdraw_reason, extra=["withdrawn_at", "withdraw_reason"])
    _publish_each("dispute.withdrawn", d)
    _tell_parties(d, "dispute_withdrawn", f"Dispute {d.reference} was withdrawn. Payments that were on hold return "
                  "to where they were, with the normal checks.")
    return d


def visible(user):
    from django.db.models import Q

    from accounts.selectors import organisations_of, staff_country_codes

    q = Q(parties__person=user) | Q(opened_by=user) | Q(
        parties__organisation_id__in=list(organisations_of(user).values_list("pk", flat=True)))
    if has_role(user, "CM", "RV", "AD"):
        codes = staff_country_codes(user)
        if codes is None:
            return Dispute.objects.all()
        q |= Q(country__code__in=list(codes))
    return Dispute.objects.filter(q).distinct()


def open_disputes_for_subject(subject_type, subject_id):
    return Dispute.objects.filter(status__in=OPEN_STATUSES).filter(
        links__subject_type=subject_type, links__subject_id=subject_id).distinct()
