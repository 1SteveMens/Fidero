"""The panel of vetted contractors, inspectors, quantity surveyors and developers (FR-BLD-003), conflict links
(FR-BLD-004, RUL-10) and contractor removal (FR-BLD-010)."""
from django.db import transaction
from django.db.models import Q

from core import state
from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.permissions import has_role

from .common import BUILD_FLAG, alert_staff, audit, evidence_objects, link_all, log, notify, now, require_staff
from .models import ConflictLink, Milestone, PanelMember, Payment, Project

CHECK_TEMPLATE = {"contractor": "contractor_check", "developer": "offplan_check"}
LICENCE_ROLE = {"inspector": "IN", "quantity_surveyor": "QS"}
DOCUMENT_KINDS = ["registration_certificate", "tax_clearance", "insurance", "licence", "company_profile",
                  "reference_letter", "permit", "other"]


def _require_flag(country):
    from administration import flags

    flags.require(BUILD_FLAG, country)
    flags.read_only_guard()


@transaction.atomic
def create_member(by, *, country, kind, name, person=None, organisation=None, registration_number="",
                  contact_phone="", contact_email="", specialities=()) -> PanelMember:
    _require_flag(country)
    require_staff(by, country, "CM", "AD", message="Only a case manager or administrator adds to the panel.")
    if kind not in PanelMember.KINDS:
        raise Invalid(f"Kind must be one of {', '.join(PanelMember.KINDS)}.", code="validation-error")
    if person is None and organisation is None:
        raise Invalid("Name the person or the company.", code="validation-error")
    if not (name or "").strip():
        raise Invalid("Enter the name.", code="validation-error")
    role = PanelMember.ROLE_FOR_KIND[kind]
    if person is not None and not person.has_tenmina_role(role):
        raise Invalid(f"{person.full_name} does not hold the {kind.replace('_', ' ')} role.", code="validation-error")
    if person is not None and person.has_tenmina_role("CM", "RV", "AD", "RR", "PY"):
        raise RuleBlocked("Tenmina staff cannot be on the panel.", code="separation-of-duties",
                          blocking_reasons=[{"rule": "RUL-10", "message": "Staff are never panel members."}])
    dup = PanelMember.objects.filter(country=country, kind=kind).exclude(status="removed")
    dup = dup.filter(person=person) if person is not None else dup.filter(organisation=organisation)
    if dup.exists():
        raise StateConflict("This person or company is already on the panel.", code="panel-member-exists")
    m = PanelMember.objects.create(country=country, kind=kind, name=name.strip(), person=person,
                                   organisation=organisation, registration_number=registration_number or "",
                                   contact_phone=contact_phone or "", contact_email=contact_email or "",
                                   specialities=list(specialities or []), created_by=by)
    audit(by, "panel_member.created", m, {"kind": kind})
    publish("panel_member.created", m.pk, {"panel_member_id": m.pk, "kind": kind, "country": country.code})
    return m


@transaction.atomic
def add_documents(m: PanelMember, by, *, evidence_ids, kind) -> PanelMember:
    _require_flag(m.country)
    require_staff(by, m.country, "CM", "AD", "RV")
    if kind not in DOCUMENT_KINDS:
        raise Invalid(f"Document kind must be one of {', '.join(DOCUMENT_KINDS)}.", code="validation-error")
    link_all(evidence_objects(evidence_ids, by, m.country, what="document"), "panel_member", m.pk, kind, by)
    audit(by, "panel_member.document_added", m, {"kind": kind})
    return m


def documents(m: PanelMember):
    from evidence.models import EvidenceLink

    return EvidenceLink.objects.filter(subject_type="panel_member", subject_id=m.pk).select_related("evidence")


@transaction.atomic
def start_check(m: PanelMember, by):
    """Contractors and developers are checked through a case (FR-BLD-003, FR-BLD-011); inspectors and quantity
    surveyors through their verified licence (RUL-20)."""
    from cases.services import open_case

    _require_flag(m.country)
    require_staff(by, m.country, "CM")
    template = CHECK_TEMPLATE.get(m.kind)
    if template is None:
        raise StateConflict("Inspectors and quantity surveyors are checked through their licence. Approve them "
                            "once the licence is verified.")
    case = open_case(template, m.country, "panel_member", m.pk, actor=by, case_manager=by,
                     title=f"{template.replace('_', ' ').capitalize()}: {m.name}")
    m.check_case_id = case.pk
    m.save(update_fields=["check_case_id"])
    audit(by, "panel_member.check_started", m, {"case_id": str(case.pk)})
    return case


def vetting_reasons(m: PanelMember) -> list[dict]:
    """Why a panel member cannot become active yet."""
    from accounts.selectors import valid_licence

    out = []
    if m.kind in CHECK_TEMPLATE and m.check_outcome != "verified":
        out.append({"rule": "FR-BLD-003", "message": "The company check is not verified."})
    role = LICENCE_ROLE.get(m.kind)
    if role and (m.person is None or valid_licence(m.person, role) is None):
        out.append({"rule": "RUL-20", "message": "There is no verified, in-date licence on file."})
    if not documents(m).exists():
        out.append({"rule": "FR-BLD-003", "message": "No documents are on file."})
    return out


def on_check_case(payload: dict):
    """case.status_changed for a contractor or developer check (subject panel_member)."""
    if payload.get("subject_type") != "panel_member" or payload.get("status") != "completed":
        return
    m = PanelMember.objects.filter(pk=payload.get("subject_id")).first()
    if m is None:
        return
    outcome = payload.get("outcome") or ""
    m.check_outcome = outcome
    m.check_case_id = m.check_case_id or payload.get("case_id")
    m.save(update_fields=["check_outcome", "check_case_id"])
    if outcome == "verified" and m.status == "pending":
        state.transition(m, "panel_member", "vetted", reason="Company check verified",
                         payload={"panel_member_id": m.pk, "kind": m.kind})
        alert_staff(m.country, ("AD",), "panel_ready", f"{m.name} passed the company check. Approve them to go on "
                                                       "the panel.", obj=m, link=f"/back-office/panel/{m.pk}")
    elif outcome == "not_verified":
        alert_staff(m.country, ("CM",), "panel_check_failed", f"{m.name} did not pass the company check.", obj=m)


@transaction.atomic
def approve(m: PanelMember, by) -> PanelMember:
    """US-BLD-003 AC1: a member with every document checked becomes active when an administrator approves."""
    _require_flag(m.country)
    require_staff(by, m.country, "AD", message="Only an administrator approves panel members.")
    if m.status not in ("pending", "vetted"):
        raise StateConflict(f"This panel member is {m.status}.")
    reasons = vetting_reasons(m)
    if reasons:
        raise RuleBlocked("This panel member cannot be approved yet.", code="panel-not-vetted",
                          blocking_reasons=reasons)
    if m.status == "pending":
        state.transition(m, "panel_member", "vetted", actor=by, payload={"panel_member_id": m.pk, "kind": m.kind})
    m.approved_by, m.approved_at = by, now()
    state.transition(m, "panel_member", "active", actor=by, extra_fields=["approved_by", "approved_at"],
                     payload={"panel_member_id": m.pk, "kind": m.kind})
    notify(m.person, "panel_approved", "You are on the Tenmina panel. Work will reach you in Tenmina Field.",
           obj=m, channels=("in_app", "email"))
    return m


@transaction.atomic
def suspend(m: PanelMember, by, *, reason) -> PanelMember:
    require_staff(by, m.country, "AD", "RV", message="Only an administrator or reviewer suspends panel members.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    m.status_reason = reason.strip()
    state.transition(m, "panel_member", "suspended", actor=by, reason=reason, extra_fields=["status_reason"],
                     payload={"panel_member_id": m.pk, "kind": m.kind})
    return m


@transaction.atomic
def reinstate(m: PanelMember, by) -> PanelMember:
    require_staff(by, m.country, "AD", message="Only an administrator reinstates panel members.")
    if m.status != "suspended":
        raise StateConflict("Only a suspended member is reinstated.")
    reasons = vetting_reasons(m)
    if reasons:
        raise RuleBlocked("This panel member's checks are no longer in order.", code="panel-not-vetted",
                          blocking_reasons=reasons)
    m.status_reason = ""
    state.transition(m, "panel_member", "active", actor=by, extra_fields=["status_reason"],
                     payload={"panel_member_id": m.pk, "kind": m.kind})
    return m


@transaction.atomic
def remove(m: PanelMember, by, *, finding, flag_id=None, mfa_at=None) -> PanelMember:
    """FR-BLD-010, US-BLD-010: after a reviewer confirms a finding (evidence for work not done), the contractor
    leaves the panel and every pending release on their projects is frozen. Clients are told."""
    from escrow import services as esc

    from . import payments

    _require_flag(m.country)
    if not has_role(by, "RV", country=m.country):
        raise Forbidden("Only a reviewer removes a panel member, after confirming the finding.")
    if not (finding or "").strip():
        raise Invalid("Record the confirmed finding.", code="validation-error")
    if flag_id:
        from mobile.models import FraudFlag

        f = FraudFlag.objects.filter(pk=flag_id).first()
        if f is None or f.status != "upheld":
            raise RuleBlocked("The flag has not been upheld by a reviewer.", code="finding-not-confirmed",
                              blocking_reasons=[{"rule": "FR-BLD-010", "message": "Uphold the flag first."}])
    if m.status == "removed":
        raise StateConflict("This panel member was already removed.")
    m.removed_by, m.removed_at, m.removal_finding = by, now(), finding.strip()
    m.status_reason = finding.strip()
    state.transition(m, "panel_member", "removed", actor=by, reason=finding,
                     extra_fields=["removed_by", "removed_at", "removal_finding", "status_reason"],
                     payload={"panel_member_id": m.pk, "kind": m.kind})
    frozen = []
    projects = Project.objects.filter(Q(contractor=m) | Q(inspector=m), status__in=["setup", "active", "paused"])
    for p in projects:
        if p.inspector_id == m.pk:
            p.inspector = None
            p.save(update_fields=["inspector"])
            continue
        from .milestones import freeze_milestone

        for ms in p.milestones.exclude(status__in=["paid", "frozen"]):
            freeze_milestone(ms, kind="contractor_removed", source_id=m.pk, by=by,
                             reason="The contractor was removed from the panel")
        for pay in Payment.objects.filter(project=p, status__in=Payment.LIVE):
            try:
                payments.withdraw(pay, by, reason="The contractor was removed from the panel", system=True)
            except Exception:  # noqa: BLE001 - a sent instruction stays with the bank; the hold below stops more
                log.exception("could not withdraw payment %s", pay.pk)
        if p.escrow_id and p.escrow.status not in ("released", "cancelled", "frozen", "proposed"):
            try:
                esc.place_hold(p.escrow, by, reason=f"Contractor {m.name} removed: {finding.strip()}")
            except Exception:  # noqa: BLE001
                log.exception("could not hold escrow %s", p.escrow_id)
        if p.status == "active":
            p.prior_status, p.status_reason = "active", "The contractor was removed from the panel"
            state.transition(p, "project", "paused", actor=by, reason=p.status_reason,
                             extra_fields=["prior_status", "status_reason"], payload={"project_id": p.pk})
        notify(p.client, "contractor_removed",
               f"We removed {m.name} from our panel after a reviewer confirmed they claimed work that was not done. "
               f"Payments on {p.title} are on hold. Your case manager will call you about a new contractor.",
               subject="Your builder was removed", obj=p, link=f"/projects/{p.pk}", category="safety",
               channels=("in_app", "email"))
        frozen.append(str(p.pk))
    publish("contractor.removed", m.pk, {"panel_member_id": m.pk, "kind": m.kind, "person_id": m.person_id,
                                         "organisation_id": m.organisation_id, "finding": m.removal_finding,
                                         "project_ids": frozen, "country": m.country.code})
    audit(by, "panel_member.removed", m, {"projects": frozen})
    return m


# ----------------------------------------------------------------- conflicts (RUL-10)

@transaction.atomic
def add_conflict(by, *, inspector, contractor, reason, note="") -> ConflictLink:
    require_staff(by, inspector.country, "CM", "RV", "AD")
    if inspector.kind != "inspector" or contractor.kind not in ("contractor", "developer"):
        raise Invalid("A conflict links an inspector and a contractor or developer.", code="validation-error")
    if reason not in ConflictLink.REASONS:
        raise Invalid(f"Reason must be one of {', '.join(ConflictLink.REASONS)}.", code="validation-error")
    link, created = ConflictLink.objects.get_or_create(inspector=inspector, contractor=contractor, defaults=dict(
        reason=reason, note=note or "", recorded_by=by))
    if created:
        audit(by, "conflict_link.recorded", link, {"inspector": str(inspector.pk), "contractor": str(contractor.pk),
                                                  "reason": reason})
        _unassign_conflicted(inspector, contractor, by)
    return link


def _unassign_conflicted(inspector, contractor, by):
    """A link recorded after assignment removes the inspector from that contractor's work at once."""
    from .models import Inspection

    for p in Project.objects.filter(contractor=contractor, inspector=inspector):
        p.inspector = None
        p.save(update_fields=["inspector"])
        alert_staff(p.country, ("CM",), "inspector_conflict", f"{inspector.name} has a recorded link to "
                                                              f"{contractor.name}. Assign another inspector to "
                                                              f"{p.title}.", obj=p)
    for i in Inspection.objects.filter(project__contractor=contractor, inspector=inspector, status="scheduled"):
        from .milestones import cancel_inspection

        cancel_inspection(i, by, reason="The inspector has a recorded link to the contractor (RUL-10).")


def conflict_reasons(inspector: PanelMember, contractor: PanelMember | None) -> list[dict]:
    """RUL-10: any recorded link, a shared organisation, or the same person."""
    if contractor is None:
        return []
    out = []
    link = ConflictLink.objects.filter(inspector=inspector, contractor=contractor).first()
    if link:
        out.append({"rule": "RUL-10", "code": "inspector-conflicted",
                    "message": f"{inspector.name} has a recorded link to {contractor.name} "
                               f"({link.reason.replace('_', ' ')})."})
    if inspector.person_id and inspector.person_id == contractor.person_id:
        out.append({"rule": "RUL-10", "code": "inspector-conflicted", "message": "The inspector is the contractor."})
    if inspector.organisation_id and inspector.organisation_id == contractor.organisation_id:
        out.append({"rule": "RUL-10", "code": "inspector-conflicted",
                    "message": "The inspector and the contractor are the same company."})
    if inspector.person_id:
        from accounts.models import Membership

        theirs = set(Membership.objects.filter(person=inspector.person, status="active")
                     .values_list("organisation_id", flat=True))
        other = set()
        if contractor.organisation_id:
            other.add(contractor.organisation_id)
        if contractor.person_id:
            other |= set(Membership.objects.filter(person=contractor.person, status="active")
                         .values_list("organisation_id", flat=True))
        if theirs & other:
            out.append({"rule": "RUL-10", "code": "inspector-conflicted",
                        "message": "The inspector works for the contractor's company."})
    return out


def require_assignable_inspector(inspector: PanelMember, contractor: PanelMember | None, country):
    from accounts.services import require_valid_licence

    if inspector.kind != "inspector" or inspector.country_id != country.pk:
        raise Invalid("Choose an inspector from this country's panel.", code="validation-error")
    if inspector.status != "active":
        raise RuleBlocked(f"{inspector.name} is not active on the panel.", code="panel-not-active",
                          blocking_reasons=[{"rule": "FR-BLD-003", "message": f"Status: {inspector.status}"}])
    reasons = conflict_reasons(inspector, contractor)
    if reasons:
        raise RuleBlocked("This inspector has a link to the contractor and cannot be assigned.",
                          code="inspector-conflicted", blocking_reasons=reasons)
    if inspector.person is None:
        raise Invalid("An inspector on the panel must be a person with Tenmina Field.", code="validation-error")
    require_valid_licence(inspector.person, "IN")


def track_record(m: PanelMember) -> dict:
    """FR-BLD-003, FR-RAT-003: what the panel member has done with Tenmina."""
    from .models import Defect, Inspection

    if m.kind in ("contractor", "developer"):
        ps = Project.objects.filter(contractor=m)
        ms = Milestone.objects.filter(project__contractor=m)
        insp = Inspection.objects.filter(project__contractor=m, status="recorded", kind="milestone")
    else:
        ps = Project.objects.filter(Q(inspector=m) | Q(quantity_surveyor=m))
        ms = Milestone.objects.none()
        insp = Inspection.objects.filter(inspector=m, status="recorded")
    passed = insp.filter(outcome__in=["pass", "pass_with_defects"]).count()
    return {"projects": ps.count(), "projects_completed": ps.filter(status="completed").count(),
            "milestones_paid": ms.filter(status="paid").count(), "inspections": insp.count(),
            "inspections_passed": passed, "inspections_failed": insp.filter(outcome="fail").count(),
            "defects_recorded": Defect.objects.filter(inspection__in=insp).count(),
            "removed": m.status == "removed", "removal_finding": m.removal_finding}


@transaction.atomic
def link_payee(m: PanelMember, by, *, payee=None, details=None):
    """The verified payee a contractor or developer is paid to (ADR-17). Either an existing payee, or a new one
    created in the payee registry; two staff verify it there."""
    from escrow import services as esc

    require_staff(by, m.country, "CM", "RV")
    if m.kind not in ("contractor", "developer"):
        raise StateConflict("Inspectors and quantity surveyors are paid by Tenmina, never from client money.")
    if payee is None:
        d = dict(details or {})
        kind = "developer" if m.kind == "developer" else "contractor"
        payee = esc.create_payee(by, country=m.country, kind=kind, subject_type="panel_member", subject_id=m.pk,
                                 person=m.person, organisation=m.organisation, **d)
        if payee.name_match == "matched":
            esc.prepare_verification(payee, by)
    elif payee.country_id != m.country_id or payee.kind not in ("contractor", "developer", "supplier"):
        raise Invalid("That payee cannot be paid for building work in this country.", code="validation-error")
    m.payee = payee
    m.save(update_fields=["payee"])
    audit(by, "panel_member.payee_linked", m, {"payee_id": str(payee.pk)})
    return m


def member_for(person, kind=None):
    qs = PanelMember.objects.filter(person=person).exclude(status="removed")
    if kind:
        qs = qs.filter(kind=kind)
    return qs.first()


def get(pk) -> PanelMember:
    m = PanelMember.objects.filter(pk=pk).first()
    if m is None:
        raise NotFound("Panel member not found.")
    return m
