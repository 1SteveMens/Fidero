"""RPT Reports: the public interface other modules may call.

Report builder (FR-RPT-001 to 011, sequence 5.2) and the monthly random re-check (FR-RPT-012, RUL-32).

Rules: RUL-02 verdict rule (problem `verdict-rule`), RUL-04 locked scope text, RUL-20 licences
(`licence-invalid`), RUL-03 release by the signing lawyer and a different Tenmina reviewer
(`same-approver`), RUL-31 parties checked, RUL-30 usable official searches, ADR-15 deterministic PDF
with its SHA-256, RUL-32 re-checks by an unlinked licensed professional.
"""
import hashlib
import json
import logging
import math
import secrets
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from administration import flags
from audit.services import record
from core import approvals, state
from core.errors import DomainError, Forbidden, Invalid, NotFound, RuleBlocked, SameApprover, StateConflict
from core.events import publish
from core.permissions import has_role

from . import templates
from .models import (AnonymisedCopy, Condition, HashCheck, Incident, Recheck, RecheckCandidate, RecheckDraw, Report,
                     Section, Signature)

log = logging.getLogger(__name__)
REPORT_LINES = ("land", "building")
DEFAULT_RECHECK_DUE_DAYS = 20  # [TO VERIFY] days a re-checker has
SLOT_LAWYER, SLOT_REVIEWER = "signing_lawyer", "reviewer"


def _now():
    return timezone.now()


def _cases():
    from cases import services as cs

    return cs


def verdict_error(msg, allowed):
    return DomainError(msg, code="verdict-rule", status=409, title="The verdict rule would be broken",
                       blocking_reasons=[{"rule": "RUL-02", "message": msg}], extra={"allowed_verdicts": allowed})


# --------------------------------------------------------------------------- building (FR-RPT-001, FR-RPT-004)

def template_for(line, country):
    from administration.selectors import current_config

    cv = current_config("report_template", country, line)
    if cv is None:
        raise DomainError(f"No report template is published for '{line}' in {country.name}.",
                          code="report-template-missing", status=409)
    try:
        templates.layout(cv.content)
    except Invalid as exc:
        raise DomainError(f"The published report template for '{line}' (version {cv.version}) cannot be used: "
                          f"{exc.detail}", code="report-template-invalid", status=409) from None
    return cv


def scope_text(country):
    from administration.selectors import current_locked_text

    lt = current_locked_text("scope_statement", country)
    if lt is None:
        raise DomainError(f"No scope and limitation statement is published for {country.name} (RUL-04).",
                          code="scope-text-missing", status=409)
    return lt


def _scope_findings(lt):
    return {"text": lt.text, "version": lt.version, "locked_text_version_id": str(lt.pk), "sha256": lt.text_sha256}


def _cover(case):
    a = case.asset
    return {"text": f"Report for case {case.reference}.",
            "client": case.client.full_name if case.client else "",
            "plot": ", ".join(x for x in (a.locality if a else "", f"plot {a.plot_number}" if a and a.plot_number else "",
                                          f"site plan {a.site_plan_ref}" if a and a.site_plan_ref else "") if x)}


def _apply_geo(report, actor=None):
    """Section 7 proposed verdict from the overlay checks; section 4 satellite image (FR-GEO-003, 006)."""
    case = report.case
    if not case.asset_id:
        return
    from geo.selectors import section7

    try:
        s7 = section7(case.asset_id)
        Section.objects.filter(report=report, key="overlays").update(
            proposed_verdict=s7.get("proposed_verdict"),
            proposed_reasons=[{k: str(v) for k, v in r.items()} for r in s7.get("reasons", [])])
    except Exception:  # noqa: BLE001 - GEO problems never stop a report being built
        log.exception("section 7 proposal failed for %s", report.reference)


@transaction.atomic
def create_report(case, actor=None) -> Report:
    """US-RPT-001 AC1: sections 1 to 14 from the current template version, with the locked scope text."""
    existing = Report.objects.filter(case=case).order_by("-version").first()
    if existing:
        return existing
    if case.product_line not in REPORT_LINES:
        raise StateConflict("This case has no report.")
    cv = template_for(case.product_line, case.country)
    lt = scope_text(case.country)
    report = Report.objects.create(case=case, country=case.country, version=1, reference=f"{case.reference}-R1",
                                   template_version=cv, scope_text_version=lt)
    _build_sections(report, cv, lt, case)
    _apply_geo(report, actor)
    record(actor=actor, action="report.created", entity="report", entity_id=report.pk, country=case.country,
           data={"case_id": str(case.pk), "template_version": cv.version, "scope_version": lt.version})
    publish("report.created", report.pk, {"report_id": report.pk, "case_id": case.pk, "version": 1})
    return report


def _build_sections(report, cv, lt, case, copy_from=None):
    old = {s.number: s for s in copy_from.sections.all()} if copy_from else {}
    for s in templates.layout(cv.content):
        prev = old.get(s["number"])
        findings = prev.findings if prev else {}
        if s["key"] == "cover" and not prev:
            findings = _cover(case)
        if s["number"] == 12:
            findings = _scope_findings(lt)
        if s["number"] == 9 and not prev:
            findings = _records_chain(case) or findings
        Section.objects.create(report=report, number=s["number"], position=s["position"], label=s["label"],
                               key=s["key"], title=s["title"], owner_role=s["owner"], locked=s["locked"],
                               in_verdict_rule=s["in_verdict_rule"], needs_signature=s["needs_signature"],
                               findings=findings, verdict=prev.verdict if prev else None,
                               proposed_verdict=prev.proposed_verdict if prev else None,
                               proposed_reasons=prev.proposed_reasons if prev else [])


def _records_chain(case) -> dict:
    """FR-REC-002, TC-REC-002-01: when the lawyer already confirmed an exact records match for the case, a report
    drafted afterwards starts section 9 from that chain, marked as from the records. The lawyer still signs it."""
    from records.selectors import confirmed_chain

    try:
        chain = confirmed_chain(case.pk)
    except Exception:  # noqa: BLE001 - the records module never stops a report being built
        log.exception("records chain for case %s could not be read", case.pk)
        return {}
    if not chain:
        return {}
    return {"chain_from_records": chain,
            "records_note": "Chain of ownership from the family or stool register, confirmed by the lawyer."}


def refresh_geo(asset_id):
    """overlay.completed: update section 7's proposal on every draft report for the plot."""
    for r in Report.objects.filter(case__asset_id=asset_id, status="draft"):
        _apply_geo(r)


# --------------------------------------------------------------------------- permissions

def _assigned_roles(user, case) -> set:
    if not user or not user.is_authenticated:
        return set()
    return set(case.tasks.filter(Q(assignee=user) | Q(second_assignee=user)).values_list("owner_role", flat=True))


def is_report_staff(user, report) -> bool:
    return has_role(user, "CM", "RV", country=report.country)


def can_view(user, report) -> bool:
    cs = _cases()
    case = report.case
    if is_report_staff(user, report) or cs.is_assigned(user, case):
        return True
    if report.status in ("released", "superseded"):
        return cs.is_client(user, case) or cs.is_representative(user, case)
    return False


def can_edit_section(user, report, section) -> bool:
    if section.locked:
        return False
    if section.owner_role == "CM":
        return has_role(user, "CM", "RV", country=report.country)
    return section.owner_role in _assigned_roles(user, report.case) and \
        user.has_tenmina_role(section.owner_role, country=report.country)


def _require_draft(report):
    if report.status in ("released", "superseded"):
        raise StateConflict("A released report never changes. Issue a correction instead (FR-RPT-010).",
                            code="report-released")
    if report.status != "draft":
        raise StateConflict("The report is in review. It must be returned before anyone edits it.")


def _section(report, number) -> Section:
    s = report.sections.filter(number=number).first()
    if s is None:
        raise NotFound(f"Section {number} not found.")
    return s


# --------------------------------------------------------------------------- sections and verdicts (002, 003)

def _content_hash(section) -> str:
    body = {"number": section.number, "title": section.title, "findings": section.findings,
            "verdict": section.verdict}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def allowed_verdicts(report) -> tuple[list, list]:
    """RUL-02: green is not allowed if any section 4 to 10 (or a building check) is red. A party whose
    national identity check failed is a red finding (RUL-31, I-45): then only red is allowed."""
    reasons = []
    reds = [s for s in report.sections.all() if s.in_verdict_rule and s.verdict == "red"]
    allowed = ["red", "amber", "green"]
    if reds:
        allowed = ["red", "amber"]
        reasons += [{"rule": "RUL-02", "message": f"Section {s.label} ({s.title}) is red."} for s in reds]
    failed = _cases().failed_parties(report.case)
    if failed:
        allowed = ["red"]
        reasons += [{"rule": "RUL-31", "message": f"{p.role.replace('_', ' ').capitalize()} {p.name}: identity not "
                                                  "verified in the national identity system."} for p in failed]
    return allowed, reasons


@transaction.atomic
def update_section(report, number, actor, *, findings=None, verdict=..., evidence_ids=()) -> Section:
    flags.read_only_guard()
    report = Report.objects.select_for_update().get(pk=report.pk)
    section = _section(report, number)
    if section.locked:
        raise DomainError("This section is locked. The scope statement comes only from the approved text "
                          "(RUL-04).", code="locked-text", status=409,
                          blocking_reasons=[{"rule": "RUL-04", "message": "Section 12 cannot be edited."}])
    _require_draft(report)
    if not can_edit_section(actor, report, section):
        raise Forbidden("Only the owner of this section can change it.")
    before = _content_hash(section)
    if findings is not None:
        if not isinstance(findings, dict):
            raise Invalid("Findings must be an object, for example {\"text\": \"...\"}.")
        section.findings = findings
    if verdict is not ...:
        if verdict not in (None, "red", "amber", "green"):
            raise Invalid("A section verdict is red, amber or green.")
        section.verdict = verdict
        if verdict == "red" and section.in_verdict_rule and report.overall_verdict == "green":
            report.overall_verdict = None  # TC-RUL-02-04: reset before the section goes red
            report.save(update_fields=["overall_verdict"])
    section.updated_by, section.edited_at = actor, _now()
    section.save()
    from evidence.models import Evidence
    from evidence.services import link

    for eid in evidence_ids or []:
        ev = Evidence.objects.filter(pk=eid).first()
        if ev is None or (ev.uploaded_by_id != actor.pk and not is_report_staff(actor, report)):
            raise Invalid("That evidence was not found.")
        link(ev, "report", report.pk, role=f"section_{section.number}", by=actor)
    changed = _content_hash(section) != before
    if changed:
        Signature.objects.filter(section=section, invalidated_at__isnull=True).update(
            invalidated_at=_now(), invalidated_reason="The section changed after signing.")
    # TC-RUL-02-04: a section turned red resets a green overall verdict.
    allowed, _ = allowed_verdicts(report)
    if report.overall_verdict and report.overall_verdict not in allowed:
        report.overall_verdict = None
        report.save(update_fields=["overall_verdict"])
    record(actor=actor, action="report.section_saved", entity="report", entity_id=report.pk, country=report.country,
           data={"section": section.number, "verdict": section.verdict, "changed": changed})
    return section


@transaction.atomic
def set_overall_verdict(report, actor, verdict) -> Report:
    """US-RPT-003: refused by screen or API when it would break RUL-02."""
    report = Report.objects.select_for_update().get(pk=report.pk)
    _require_draft(report)
    s11 = report.sections.filter(number=11).first()
    if not (has_role(actor, "CM", "RV", country=report.country)
            or (s11 is not None and can_edit_section(actor, report, s11))):
        raise Forbidden("Only the lawyer who owns section 11 or Tenmina staff set the overall verdict.")
    if verdict not in ("red", "amber", "green"):
        raise Invalid("The overall verdict is red, amber or green.")
    allowed, reasons = allowed_verdicts(report)
    if verdict not in allowed:
        raise verdict_error(f"The overall verdict cannot be {verdict}. Allowed: {', '.join(allowed)}. "
                            + " ".join(r["message"] for r in reasons), allowed)
    report.overall_verdict, report.verdict_set_by = verdict, actor
    report.save(update_fields=["overall_verdict", "verdict_set_by"])
    record(actor=actor, action="report.verdict_set", entity="report", entity_id=report.pk, country=report.country,
           data={"verdict": verdict})
    return report


# --------------------------------------------------------------------------- conditions (FR-RPT-009)

@transaction.atomic
def add_condition(report, actor, *, text, responsible, closing_evidence, key="", release_part="main") -> Condition:
    _require_draft(report)
    s11 = _section(report, 11)
    if not can_edit_section(actor, report, s11):
        raise Forbidden("Only the owner of section 11 records release conditions.")
    if not (text or "").strip() or not (closing_evidence or "").strip():
        raise Invalid("Each condition needs its text, the party responsible and the evidence that closes it.")
    if responsible not in Condition.RESPONSIBLE:
        raise Invalid(f"Responsible party must be one of {', '.join(Condition.RESPONSIBLE)}.")
    pos = (report.conditions.order_by("-position").values_list("position", flat=True).first() or 0) + 1
    c = Condition.objects.create(report=report, position=pos, key=key or "", text=text.strip(),
                                 responsible=responsible, closing_evidence=closing_evidence.strip(),
                                 release_part=release_part, created_by=actor)
    Signature.objects.filter(section=s11, invalidated_at__isnull=True).update(
        invalidated_at=_now(), invalidated_reason="Conditions changed after signing.")
    record(actor=actor, action="report.condition_added", entity="report", entity_id=report.pk, country=report.country,
           data={"condition_id": str(c.pk)})
    return c


@transaction.atomic
def remove_condition(condition: Condition, actor):
    report = condition.report
    _require_draft(report)
    if not can_edit_section(actor, report, _section(report, 11)):
        raise Forbidden("Only the owner of section 11 removes release conditions.")
    record(actor=actor, action="report.condition_removed", entity="report", entity_id=report.pk,
           country=report.country, data={"condition_id": str(condition.pk), "text": condition.text})
    Signature.objects.filter(section__report=report, section__number=11, invalidated_at__isnull=True).update(
        invalidated_at=_now(), invalidated_reason="Conditions changed after signing.")
    condition.delete()


# --------------------------------------------------------------------------- signatures (FR-RPT-005, RUL-20)

@transaction.atomic
def sign_section(report, number, actor) -> Signature:
    from accounts.services import require_valid_licence

    report = Report.objects.select_for_update().get(pk=report.pk)
    section = _section(report, number)
    _require_draft(report)
    if not section.needs_signature:
        raise Invalid("This section is not signed by a professional.")
    if not actor.has_tenmina_role(section.owner_role, country=report.country) or \
            section.owner_role not in _assigned_roles(actor, report.case):
        raise Forbidden(f"Only the {section.owner_role} assigned to this case signs this section.")
    if section.in_verdict_rule and not section.verdict:
        raise Invalid("Choose the section verdict before signing.")
    lic = require_valid_licence(actor, section.owner_role)  # RUL-20, raises licence-invalid
    Signature.objects.filter(section=section, signer=actor, invalidated_at__isnull=True).update(
        invalidated_at=_now(), invalidated_reason="Signed again.")
    sig = Signature.objects.create(report=report, section=section, signer=actor, role=section.owner_role, licence=lic,
                                   signer_name=actor.full_name, licence_number=lic.number, licence_body=lic.body,
                                   signed_at=_now(), content_sha256=_content_hash(section))
    record(actor=actor, action="report.section_signed", entity="report", entity_id=report.pk, country=report.country,
           data={"section": section.number, "licence": lic.number, "content_sha256": sig.content_sha256})
    return sig


def sign_sections(report, actor) -> list[Signature]:
    """Sign every section the actor owns on this report, in one step."""
    roles = _assigned_roles(actor, report.case)
    out = []
    for s in report.sections.filter(needs_signature=True, owner_role__in=list(roles)).order_by("position"):
        out.append(sign_section(report, s.number, actor))
    if not out:
        raise Forbidden("You have no section to sign on this report.")
    return out


def valid_signature(section) -> Signature | None:
    sig = section.signatures.filter(invalidated_at__isnull=True).order_by("-signed_at").first()
    if sig is None or sig.content_sha256 != _content_hash(section):
        return None
    # TC-RUL-20-04: valid if the licence was in date when signed.
    if sig.licence.status not in ("verified", "expired") or sig.licence.expires_on < sig.signed_at.date():
        return None
    return sig


def signing_lawyers(report) -> set:
    ids = set()
    for s in report.sections.filter(needs_signature=True, owner_role="LW"):
        sig = valid_signature(s)
        if sig:
            ids.add(sig.signer_id)
    return ids


def signers(report) -> set:
    return {sig.signer_id for s in report.sections.filter(needs_signature=True) if (sig := valid_signature(s))}


# --------------------------------------------------------------------------- review and release (5.2)

def review_blockers(report) -> list[dict]:
    out = []
    for s in report.sections.all().order_by("position"):
        if s.locked:
            continue
        if s.in_verdict_rule and not s.verdict:
            out.append({"rule": "FR-RPT-002", "message": f"Section {s.label} ({s.title}) has no verdict."})
        if not s.findings:
            out.append({"rule": "FR-RPT-002", "message": f"Section {s.label} ({s.title}) has no findings."})
        if s.needs_signature and valid_signature(s) is None:
            out.append({"rule": "RUL-20", "message": f"Section {s.label} ({s.title}) is not signed by its "
                                                     f"{s.owner_role}."})
    if not signing_lawyers(report):
        out.append({"rule": "RUL-03", "message": "No lawyer has signed the legal sections."})
    allowed, _ = allowed_verdicts(report)
    if not report.overall_verdict:
        out.append({"rule": "RUL-02", "message": "Set the overall verdict."})
    elif report.overall_verdict not in allowed:
        out.append({"rule": "RUL-02", "message": f"The overall verdict must be one of {', '.join(allowed)}."})
    if report.overall_verdict in ("amber", "green") and not report.conditions.exists():
        out.append({"rule": "FR-RPT-009", "message": "Record the release conditions in section 11."})
    return out


def release_blockers(report) -> list[dict]:
    """5.2: the client's identity, every party's national identity check, and usable official searches."""
    from accounts.selectors import client_identity_passed

    cs = _cases()
    case = report.case
    out = []
    if case.client and not client_identity_passed(case.client):
        out.append({"rule": "FR-ACC-004", "message": "The client's identity check has not passed."})
    out += cs.party_blockers(case)
    from cases.selectors import search_blockers

    out += search_blockers(case)
    return out


@transaction.atomic
def submit_review(report, actor) -> Report:
    """Compute the allowed verdict, insert the current scope text and open the two-person approval."""
    flags.read_only_guard()
    report = Report.objects.select_for_update().select_related("case").get(pk=report.pk)
    if not has_role(actor, "CM", country=report.country):
        raise Forbidden("Only a case manager sends a report to review.")
    _require_draft(report)
    case = report.case
    if report.supersedes_id is None and case.status != "in_progress":
        raise StateConflict(f"Case {case.reference} is {case.status.replace('_', ' ')}.")
    blockers = review_blockers(report)
    if any(b["rule"] == "RUL-02" for b in blockers) and report.overall_verdict:
        allowed, _ = allowed_verdicts(report)
        raise verdict_error("The overall verdict breaks the verdict rule.", allowed)
    blockers += release_blockers(report)
    if blockers:
        raise RuleBlocked("The report is not ready for review.", code="review-blocked", blocking_reasons=blockers)
    lt = scope_text(report.country)  # RUL-04: the version in force now
    if lt.pk != report.scope_text_version_id:
        report.scope_text_version = lt
        Section.objects.filter(report=report, number=12).update(findings=_scope_findings(lt))
    if report.supersedes_id is None:
        _cases().mark_in_review(case, actor)
    req = approvals.request_approval("report_release", report.pk, actor, required=2, country=report.country,
                                     summary=f"Release report {report.reference} ({report.overall_verdict})")
    report.approval_request, report.submitted_by, report.submitted_at = req, actor, _now()
    state.transition(report, "report", "in_review", actor=actor, event="report.submitted",
                     payload={"report_id": report.pk, "case_id": case.pk, "version": report.version},
                     extra_fields=["approval_request", "submitted_by", "submitted_at", "scope_text_version"])
    from cases.services import _notify, _staff_people

    for pid in signing_lawyers(report):
        from accounts.models import Person

        _notify(Person.objects.get(pk=pid), "approval_needed", subject=f"Approve report {report.reference}",
                body=f"Report {report.reference} is ready for your approval as the signing lawyer.", obj=report,
                link=f"/reports/{report.pk}")
    for p in _staff_people(report.country, "RV"):
        if p.pk != actor.pk:
            _notify(p, "approval_needed", subject=f"Review report {report.reference}",
                    body=f"Report {report.reference} needs a second review.", obj=report, link=f"/reports/{report.pk}")
    return report


def _slot_for(report, approver, req):
    taken = dict(req.approvals.values_list("slot", "approver_id"))
    lawyers = signing_lawyers(report)
    if approver.pk in lawyers:
        if SLOT_LAWYER in taken:
            raise SameApprover("The signing lawyer has already approved. A Tenmina reviewer gives the other approval.")
        return SLOT_LAWYER
    if approver.has_tenmina_role("LW", country=report.country) and not approver.has_tenmina_role(
            "RV", country=report.country):
        raise Forbidden("Only the lawyer who signed the legal section can give the lawyer's approval (RUL-03).")
    if not approver.has_tenmina_role("RV", country=report.country):
        raise Forbidden("Only the signing lawyer and a Tenmina reviewer approve a report.")
    if approver.pk in signers(report):
        raise SameApprover("A person who signed the report cannot also be its reviewer. Two different people are "
                           "required.")
    if SLOT_REVIEWER in taken:
        raise SameApprover("A reviewer has already approved. The signing lawyer must give the other approval; two "
                           "different people are required (RUL-03).")
    return SLOT_REVIEWER


@transaction.atomic
def approve(report, actor, *, decision="approve", note="", mfa_at=None) -> Report:
    """POST /v1/reports/{id}/approvals: the signing lawyer and a different reviewer (RUL-03), or return."""
    report = Report.objects.select_for_update().get(pk=report.pk)
    if report.status != "in_review" or report.approval_request is None:
        raise StateConflict("This report is not waiting for approval.")
    req = report.approval_request
    if decision not in ("approve", "return"):
        raise Invalid("Decision is approve or return.")
    if decision == "return":
        if not (note or "").strip():
            raise Invalid("Say what must change.")
        if not (actor.pk in signing_lawyers(report) or actor.has_tenmina_role("RV", country=report.country)):
            raise Forbidden("Only the signing lawyer or a reviewer returns a report.")
        approvals.decide(req, actor, decision="reject", mfa_at=mfa_at, note=note, slot="returned")
        report.refresh_from_db()
        return report
    slot = _slot_for(report, actor, req)
    if req.approvals.filter(decision="approve").exists():  # this is the closing approval
        blockers = release_blockers(report) + [b for b in review_blockers(report) if b["rule"] != "FR-RPT-009"]
        if blockers:
            raise RuleBlocked("The report cannot be released yet.", code="release-blocked", blocking_reasons=blockers)
    approvals.decide(req, actor, decision="approve", mfa_at=mfa_at, note=note, slot=slot,
                     allowed=lambda person: True)
    report.refresh_from_db()
    return report


@transaction.atomic
def on_approval_closed(report_id, approved: bool):
    report = Report.objects.select_for_update().filter(pk=report_id).first()
    if report is None or report.status != "in_review":
        return report
    req = report.approval_request
    if not approved:
        note = req.approvals.filter(decision="reject").values_list("note", flat=True).first() or ""
        report.approval_request = None
        state.transition(report, "report", "draft", reason=note, event="report.returned",
                         payload={"report_id": report.pk, "case_id": report.case_id}, extra_fields=["approval_request"])
        if report.supersedes_id is None:
            _cases().return_to_progress(report.case, None, note)
        if report.submitted_by:
            from cases.services import _notify

            _notify(report.submitted_by, "generic", subject=f"Report {report.reference} returned", obj=report,
                    body=f"Report {report.reference} was returned: {note}", link=f"/reports/{report.pk}")
        return report
    slots = set(req.approvals.filter(decision="approve").values_list("slot", flat=True))
    if slots != {SLOT_LAWYER, SLOT_REVIEWER}:
        # Approved through a path that skipped the slot rule: never release (RUL-03).
        report.release_error = "Approvals did not come from the signing lawyer and a different reviewer."
        report.save(update_fields=["release_error"])
        record(action="report.release_refused", entity="report", entity_id=report.pk, country=report.country,
               data={"slots": sorted(slots)})
        return report
    state.transition(report, "report", "approved", event="report.approved",
                     payload={"report_id": report.pk, "case_id": report.case_id})
    try:
        with transaction.atomic():
            release(report)
    except DomainError as exc:
        report.refresh_from_db()
        report.release_error = exc.detail
        report.save(update_fields=["release_error"])
    return report


def _doc(report, *, anonymise=False):
    from accounts.models import Person

    case = report.case
    req = report.approval_request
    when = report.released_at or _now()
    sections = []
    for s in report.sections.all().order_by("position"):
        lines = []
        if s.number == 12:
            lines = [s.findings.get("text", ""), f"Scope statement version {s.findings.get('version')}."]
        elif s.number == 13:
            for sec in report.sections.filter(needs_signature=True).order_by("position"):
                sig = valid_signature(sec)
                if sig:
                    lines.append(f"Section {sec.label}: {sig.signer_name}, {sig.role}, licence {sig.licence_number} "
                                 f"({sig.licence_body}), signed {sig.signed_at:%d %B %Y %H:%M} UTC")
            if req is not None:
                for a in req.approvals.filter(decision="approve").order_by("approved_at"):
                    who = Person.objects.get(pk=a.approver_id)
                    lines.append(f"Approved ({a.slot.replace('_', ' ')}): {who.full_name}, "
                                 f"{a.approved_at:%d %B %Y %H:%M} UTC")
        else:
            from .pdf import findings_text

            lines = findings_text(s.findings)
            if s.number == 11:
                for c in report.conditions.all():
                    lines.append(f"Condition {c.position}: {c.text} Responsible: {c.responsible}. Closed by: "
                                 f"{c.closing_evidence}.")
        sections.append({"label": s.label, "title": s.title, "verdict": s.verdict, "lines": lines})
    header = [f"Report {report.reference}, version {report.version}", f"Case {case.reference}",
              f"Released {when:%d %B %Y}"]
    if report.supersedes_id:
        header.append(f"This version corrects {report.supersedes.reference}: {report.correction_reason}")
    doc = {"title": "Tenmina verification report", "header": header, "verdict": report.overall_verdict,
           "sections": sections, "rendered_at": when.replace(microsecond=0),
           "footer": ["Check this file's fingerprint (SHA-256) on Tenmina's public check page with the report "
                      "reference."]}
    if anonymise:
        from .pdf import redact

        names = _sensitive_strings(report)
        doc["header"] = [redact(h, names) for h in doc["header"]]
        for s in doc["sections"]:
            s["lines"] = [redact(x, names) for x in s["lines"]]
        doc["title"] = "Tenmina verification report (anonymised case study)"
    return doc


def _sensitive_strings(report) -> list[str]:
    case = report.case
    out = [case.reference, report.reference]
    if case.client:
        out += [case.client.full_name, case.client.email or "", case.client.phone or ""]
    a = case.asset
    if a:
        out += [a.plot_number, a.site_plan_ref, a.ghana_post_gps, a.address, a.name]
    if case.order:
        o = case.order
        out += [o.seller_name, o.seller_phone, o.seller_email, o.plot_number, o.site_plan_ref, o.ghana_post_gps]
    out += list(case.parties.values_list("name", flat=True))
    out += [s.signer_name for s in Signature.objects.filter(report=report)]
    out += [s.licence_number for s in Signature.objects.filter(report=report)]
    from accounts.models import Person

    if report.approval_request:
        out += list(Person.objects.filter(pk__in=report.approval_request.approvals.values("approver_id"))
                    .values_list("full_name", flat=True))
    return [x for x in out if x]


@transaction.atomic
def release(report, actor=None) -> Report:
    """FR-RPT-007: render the PDF once, store the bytes write-once with their SHA-256, register the hash for the
    public check, release, and tell the client without report contents."""
    from evidence.services import link, register_issued, store

    report = Report.objects.select_for_update().select_related("case", "country").get(pk=report.pk)
    if report.status != "approved":
        raise StateConflict("Only an approved report is released.")
    blockers = release_blockers(report)
    if blockers:
        raise RuleBlocked("The report cannot be released yet.", code="release-blocked", blocking_reasons=blockers)
    from .pdf import renderer

    report.released_at = _now().replace(microsecond=0)
    data = renderer().render(_doc(report))
    ev = store(data=data, country=report.country, uploaded_by=None, content_type="application/pdf",
               original_name=f"{report.reference}.pdf", source="generated", owner_type="case",
               owner_id=report.case_id, data_class="case_report", description=f"Report {report.reference}")
    link(ev, "report", report.pk, role="report_pdf", by=actor)
    register_issued(ev, "report", report.pk, kind="report_pdf", issued_at=report.released_at, by=actor)
    report.pdf_evidence, report.pdf_sha256, report.release_error = ev, ev.sha256, ""
    report.client_notified_at = _now()
    state.transition(report, "report", "released", actor=actor, event="report.released",
                     payload={"report_id": report.pk, "case_id": report.case_id, "asset_id": report.case.asset_id,
                              "pdf_evidence_id": ev.pk, "pdf_sha256": ev.sha256, "verdict": report.overall_verdict,
                              "released_at": report.released_at, "version": report.version,
                              "reference": report.reference, "supersedes_id": report.supersedes_id,
                              "client_id": report.case.client_id, "country": report.country.code,
                              "case_ref": report.case.reference, "notified": True},  # told below, in RPT's words
                     extra_fields=["released_at", "pdf_evidence", "pdf_sha256", "release_error", "client_notified_at"])
    if report.supersedes_id:
        old = Report.objects.select_for_update().get(pk=report.supersedes_id)
        if old.status == "released":
            state.transition(old, "report", "superseded", actor=actor, event="report.corrected",
                             payload={"report_id": old.pk, "superseded_by": report.pk, "case_id": report.case_id,
                                      "reason": report.correction_reason})
        if report.incident_id:
            Incident.objects.filter(pk=report.incident_id).update(correction_report=report,
                                                                  client_notified_at=report.client_notified_at)
    _work_accepted(report)
    _add_candidate("report", report.pk, report.case, report=report, occurred_at=report.released_at)
    case = report.case
    if case.client:
        from cases.services import _notify

        subject = (f"Corrected report {report.reference}" if report.supersedes_id
                   else f"Your report for case {case.reference} is ready")
        body = (f"We corrected your report. The new version {report.reference} replaces the old one. Reason: "
                f"{report.correction_reason}" if report.supersedes_id else
                f"Your report {report.reference} was released. Open it in Tenmina.")
        _notify(case.client, "report_released", subject=subject, body=body, obj=report, link=f"/reports/{report.pk}",
                channels="preferred", context={"case_ref": case.reference})
    return report


def _work_accepted(report):
    """work.accepted for each professional whose signed section passed second review (RUL-26: no verdict field)."""
    by_signer = {}
    for s in report.sections.filter(needs_signature=True).order_by("number"):
        sig = valid_signature(s)
        if sig and sig.signer_id not in by_signer:
            by_signer[sig.signer_id] = (sig, s)
    for pid, (sig, s) in by_signer.items():
        t = report.case.tasks.filter(Q(assignee_id=pid) | Q(second_assignee_id=pid), owner_role=sig.role) \
            .exclude(assigned_at__isnull=True).order_by("assigned_at").first()
        assigned_at = t.assigned_at if t else report.created_at
        publish("work.accepted", s.pk, {
            "work_kind": "report_section", "work_type": "report_section", "work_ref": s.pk, "person_id": pid,
            "role": sig.role, "case_id": report.case_id, "report_id": report.pk, "assigned_at": assigned_at,
            "accepted_at": report.released_at, "quantity": 1, "country": report.country.code})


@transaction.atomic
def retry_release(report, actor) -> Report:
    if not has_role(actor, "CM", "RV", country=report.country):
        raise Forbidden("Staff only.")
    return release(report, actor)


# --------------------------------------------------------------------------- corrections (FR-RPT-010)

@transaction.atomic
def correct(report, actor, reason, *, incident=None) -> Report:
    """A released report never changes: a correction is a new draft version with a reason. It goes through
    the same review; on release it supersedes the old version and the client is notified."""
    flags.read_only_guard()
    if not has_role(actor, "CM", "RV", country=report.country):
        raise Forbidden("Only a case manager or reviewer issues a correction.")
    if report.status != "released":
        raise StateConflict("Only the released version can be corrected.")
    if not (reason or "").strip():
        raise Invalid("Give the reason for the correction.")
    if Report.objects.filter(supersedes=report).exclude(status="superseded").exists():
        raise StateConflict("A correction of this version is already open.")
    case = report.case
    v = (Report.objects.filter(case=case).order_by("-version").values_list("version", flat=True).first() or 0) + 1
    new = Report.objects.create(case=case, country=report.country, version=v, reference=f"{case.reference}-R{v}",
                                template_version=report.template_version, scope_text_version=scope_text(case.country),
                                overall_verdict=report.overall_verdict, supersedes=report,
                                correction_reason=reason.strip(), incident=incident)
    _build_sections(new, report.template_version, new.scope_text_version, case, copy_from=report)
    for c in report.conditions.all():
        Condition.objects.create(report=new, position=c.position, key=c.key, text=c.text, responsible=c.responsible,
                                 closing_evidence=c.closing_evidence, release_part=c.release_part,
                                 created_by=c.created_by)
    if incident is not None:
        incident.correction_report = new
        incident.save(update_fields=["correction_report"])
    record(actor=actor, action="report.correction_opened", entity="report", entity_id=new.pk, country=case.country,
           data={"supersedes": str(report.pk), "reason": reason.strip()})
    return new


# --------------------------------------------------------------------------- public hash check (FR-RPT-008)

def verify(reference: str, sha256: str, ip_hash="") -> dict:
    """Match or no match only; no report content, client name or date beyond the release day."""
    from evidence.services import normalise_sha256

    digest = normalise_sha256(sha256)
    report = Report.objects.filter(reference=(reference or "").strip()).first() if reference else None
    matched = bool(report and report.status in ("released", "superseded") and report.pdf_sha256 == digest)
    HashCheck.objects.create(reference=(reference or "")[:64], sha256=digest, report=report if matched else None,
                             matched=matched, ip_hash=ip_hash)
    out = {"match": matched, "released_on": report.released_at.date() if matched else None,
           "superseded": bool(matched and report.status == "superseded")}
    return out


# --------------------------------------------------------------------------- anonymised copies (FR-RPT-011)

@transaction.atomic
def anonymised_copy(report, actor) -> AnonymisedCopy:
    from dataprotection.selectors import active_consents
    from evidence.services import link, store

    if not has_role(actor, "RV", country=report.country):
        raise Forbidden("Only a reviewer makes an anonymised copy.")
    if report.status not in ("released", "superseded"):
        raise StateConflict("Only a released report can be used as a case study.")
    client = report.case.client
    consent = active_consents(client, "case_study").filter(report_id=report.pk).first() if client else None
    if consent is None:
        raise RuleBlocked("There is no written consent from the client for a case study of this report.",
                          code="consent-required",
                          blocking_reasons=[{"rule": "FR-RPT-011", "message": "No case-study consent on file."}])
    from .pdf import renderer

    data = renderer().render(_doc(report, anonymise=True))
    ev = store(data=data, country=report.country, uploaded_by=actor, content_type="application/pdf",
               original_name=f"case-study-{report.pk}.pdf", source="generated", data_class="case_report",
               description="Anonymised case study")
    link(ev, "report", report.pk, role="anonymised_copy", by=actor)
    copy = AnonymisedCopy.objects.create(report=report, country=report.country, evidence=ev, consent_id=consent.pk,
                                         created_by=actor, removed=["names", "plot numbers", "coordinates",
                                                                    "contacts", "references"])
    record(actor=actor, action="report.anonymised_copy", entity="report", entity_id=report.pk,
           country=report.country, data={"consent_id": str(consent.pk), "evidence_id": str(ev.pk)})
    return copy


# --------------------------------------------------------------------------- re-checks (FR-RPT-012, RUL-32)

def _month(d) -> date:
    return date(d.year, d.month, 1)


def _add_candidate(subject_type, subject_id, case, *, report=None, occurred_at=None, linked=()):
    when = occurred_at or _now()
    RecheckCandidate.objects.get_or_create(
        subject_type=subject_type, subject_id=subject_id,
        defaults={"country": case.country, "case": case, "report": report, "occurred_at": when,
                  "sample_month": _month(timezone.localtime(when)),
                  "linked_person_ids": [str(x) for x in linked if x]})


def note_condition_closed(payload: dict):
    """condition.closed from ESC: a closed release condition joins the month's population."""
    from cases.models import Case

    cid = payload.get("condition_id")
    case = None
    if payload.get("case_id"):
        case = Case.objects.filter(pk=payload["case_id"]).first()
    elif payload.get("report_id"):
        r = Report.objects.filter(pk=payload["report_id"]).first()
        case = r.case if r else None
    if not cid or case is None:
        log.warning("condition.closed without a case: %s", payload)
        return
    when = payload.get("closed_at")
    from django.utils.dateparse import parse_datetime

    when = parse_datetime(when) if isinstance(when, str) else when
    _add_candidate("escrow_condition", cid, case, occurred_at=when, linked=[payload.get("closed_by_id")])


def _pick(seed: bytes, keys: list[str], n: int) -> list[str]:
    """Pure function of the seed and the population, so an auditor can repeat it."""
    return sorted(keys, key=lambda k: hashlib.sha256(seed + k.encode()).hexdigest())[:n]


@transaction.atomic
def draw(country, month: date, *, by=None) -> RecheckDraw:
    """One draw per country and month (TC-RUL-32-04). Nobody who worked on a selected case is told."""
    from administration.selectors import setting

    month = _month(month)
    if RecheckDraw.objects.filter(country=country, sample_month=month).exists():
        raise StateConflict(f"The re-check sample for {month:%B %Y} was already drawn. It cannot be drawn again or "
                            "changed.", code="recheck-already-drawn")
    pct = Decimal(str(setting("recheck_sample_pct", country, "5") or "5"))
    next_month = _month(month + timedelta(days=32))
    items = {f"{c.subject_type}:{c.subject_id}": ("candidate", c) for c in RecheckCandidate.objects.filter(
        country=country, sample_month=month)}
    prev = RecheckDraw.objects.filter(country=country, sample_month__lt=month).order_by("-sample_month").first()
    if prev:
        for r in prev.rechecks.filter(status="skipped"):
            items.setdefault(f"{r.subject_type}:{r.subject_id}", ("skipped", r))
    keys = sorted(items)
    population_sha = hashlib.sha256("\n".join(keys).encode()).hexdigest()
    seed = secrets.token_bytes(32)
    n = min(len(keys), max(1, math.ceil(len(keys) * pct / 100))) if keys else 0
    picked = _pick(seed, keys, n)
    d = RecheckDraw.objects.create(country=country, sample_month=month, sample_pct=pct, population_count=len(keys),
                                   population_sha256=population_sha, seed=seed.hex(), selected_count=len(picked),
                                   drawn_by=by)
    for k in picked:
        kind, obj = items[k]
        st, sid = k.split(":", 1)
        Recheck.objects.create(draw=d, country=country, subject_type=st, subject_id=sid, case=obj.case,
                               report=obj.report, carried_from=obj if kind == "skipped" else None)
    record(actor=by, action="recheck.drawn", entity="recheck_draw", entity_id=d.pk, country=country,
           data={"month": month.isoformat(), "population": len(keys), "selected": len(picked), "pct": str(pct),
                 "population_sha256": population_sha, "seed": d.seed})
    _alert_reviewers(d, f"{len(picked)} item(s) were drawn for re-check for {month:%B %Y}. Assign each to a "
                        "licensed professional with no link to the case.")
    del next_month
    return d


def _alert_reviewers(d, body):
    from cases.services import _notify, _staff_people

    for p in _staff_people(d.country, "RV"):
        _notify(p, "generic", subject="Monthly re-checks", body=body, link="/rechecks")


def link_reasons(recheck, person) -> list[str]:
    """RUL-32: no link to the case (02 6.15 rpt.recheck_no_link)."""
    from accounts.models import Membership
    from core.models import Approval

    from cases.selectors import people_linked_to_case

    case = recheck.case
    linked = people_linked_to_case(case)
    reasons = []
    if person.pk in linked:
        reasons.append("worked on the case, is its client or a party, or represents the client")
    rep_ids = Report.objects.filter(case=case).values_list("pk", flat=True)
    if Signature.objects.filter(report__case=case, signer=person).exists():
        reasons.append("signed a section of the case's report")
    if Approval.objects.filter(request__subject_type="report_release", request__subject_id__in=list(rep_ids),
                               approver=person).exists():
        reasons.append("approved the case's report")
    cand = RecheckCandidate.objects.filter(subject_type=recheck.subject_type, subject_id=recheck.subject_id).first()
    if cand and str(person.pk) in (cand.linked_person_ids or []):
        reasons.append("closed the condition being re-checked")
    sig_ids = set(Signature.objects.filter(report__case=case).values_list("signer_id", flat=True))
    orgs = set(Membership.objects.filter(person=person, status="active").values_list("organisation_id", flat=True))
    if orgs and Membership.objects.filter(organisation_id__in=orgs, status="active",
                                          person_id__in=list(linked | sig_ids)).exclude(person=person).exists():
        reasons.append("works for the same organisation as someone on the case")
    return reasons


def recheck_candidates(recheck) -> list[dict]:
    """SCR-BO-45: only eligible people are listed: a lawyer or surveyor in the country, with no link to the
    case (RUL-32) and a licence in date until the due date (RUL-20). assign_recheck checks again."""
    from django.db.models import Q

    from accounts.models import Person
    from accounts.services import require_valid_licence

    due = (_now() + timedelta(days=DEFAULT_RECHECK_DUE_DAYS)).date()
    people = (Person.objects.filter(status="active", role_grants__revoked_at__isnull=True,
                                    role_grants__role__in=["LW", "SV"])
              .filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=recheck.country))
              .distinct().order_by("full_name"))
    out = []
    for p in people[:200]:
        if link_reasons(recheck, p):
            continue
        for role in sorted(p.roles(recheck.country) & {"LW", "SV"}):
            try:
                lic = require_valid_licence(p, role, on=due)
            except DomainError:
                continue
            out.append({"id": str(p.pk), "name": p.full_name, "role": role, "licence_number": lic.number,
                        "licence_expires_on": lic.expires_on})
    return out


def _visible_to(user, recheck) -> bool:
    return has_role(user, "RV", "AD", country=recheck.country) and not link_reasons(recheck, user)


@transaction.atomic
def assign_recheck(recheck: Recheck, actor, person, *, role) -> Recheck:
    from accounts.services import require_valid_licence

    recheck = Recheck.objects.select_for_update().get(pk=recheck.pk)
    if not has_role(actor, "RV", country=recheck.country) or link_reasons(recheck, actor):
        raise NotFound("Re-check not found.")
    if recheck.status not in ("selected", "assigned"):
        raise StateConflict("This re-check is finished.")
    if role not in ("LW", "SV"):
        raise Invalid("A re-check is done by a lawyer or a surveyor.")
    if not person.has_tenmina_role(role, country=recheck.country):
        raise Invalid(f"{person.full_name} does not hold the role {role}.")
    reasons = link_reasons(recheck, person)
    if reasons:
        raise RuleBlocked(f"{person.full_name} cannot re-check this case.", code="recheck-linked",
                          blocking_reasons=[{"rule": "RUL-32", "message": r} for r in reasons])
    due = _now() + timedelta(days=DEFAULT_RECHECK_DUE_DAYS)
    lic = require_valid_licence(person, role, on=due.date())  # RUL-20: in date until the due date
    recheck.assignee, recheck.assignee_role, recheck.licence = person, role, lic
    recheck.assigned_by, recheck.assigned_at, recheck.due_at = actor, _now(), due
    if recheck.status == "selected":
        state.transition(recheck, "recheck", "assigned", actor=actor, event="recheck.assigned",
                         payload={"recheck_id": recheck.pk},
                         extra_fields=["assignee", "assignee_role", "licence", "assigned_by", "assigned_at", "due_at"])
    else:
        recheck.save()
    from cases.services import _notify

    _notify(person, "task_assigned", subject="New re-check", obj=recheck, link=f"/rechecks/{recheck.pk}",
            context={"task_title": "Independent re-check", "due_date": f"{due:%d %B %Y}"},
            body=f"You have an independent re-check due on {due:%d %B %Y}. Do not contact the original team.")
    return recheck


@transaction.atomic
def skip_recheck(recheck: Recheck, actor, reason) -> Recheck:
    if not has_role(actor, "RV", country=recheck.country) or link_reasons(recheck, actor):
        raise NotFound("Re-check not found.")
    if not (reason or "").strip():
        raise Invalid("Say why no unlinked professional is available.")
    recheck.skipped_by, recheck.skip_reason = actor, reason.strip()
    return state.transition(recheck, "recheck", "skipped", actor=actor, reason=reason,
                            payload={"recheck_id": recheck.pk}, extra_fields=["skipped_by", "skip_reason"])


@transaction.atomic
def record_recheck_result(recheck: Recheck, actor, *, result, findings="") -> Recheck:
    recheck = Recheck.objects.select_for_update().get(pk=recheck.pk)
    if recheck.assignee_id != actor.pk:
        raise NotFound("Re-check not found.")
    if recheck.status != "assigned":
        raise StateConflict("This re-check is not open.")
    if result not in Recheck.RESULTS:
        raise Invalid(f"Result must be one of {', '.join(Recheck.RESULTS)}.")
    if result != "confirmed" and not (findings or "").strip():
        raise Invalid("Describe what you found.")
    now = _now()
    recheck.result, recheck.findings, recheck.result_at = result, findings or "", now
    incident = None
    if result != "confirmed":
        owner = recheck.assigned_by
        incident = Incident.objects.create(country=recheck.country, case=recheck.case, recheck=recheck,
                                           report=recheck.report,
                                           condition_id=recheck.subject_id
                                           if recheck.subject_type == "escrow_condition" else None,
                                           kind=result, summary=(findings or "")[:500], owner=owner)
        recheck.incident = incident
    state.transition(recheck, "recheck", "done", actor=actor, event="recheck.recorded",
                     payload={"recheck_id": recheck.pk, "case_id": recheck.case_id},
                     extra_fields=["result", "findings", "result_at", "incident"])
    # RUL-26: paid at the same flat rate whatever the result; no result field in this event.
    publish("work.accepted", recheck.pk, {
        "work_kind": "recheck", "work_type": "recheck", "work_ref": recheck.pk, "person_id": actor.pk,
        "role": recheck.assignee_role, "case_id": recheck.case_id, "assigned_at": recheck.assigned_at,
        "accepted_at": now, "quantity": 1, "country": recheck.country.code})
    if incident is not None:
        report_ids = _report_chain(recheck.report) if recheck.report else []
        payload = {"incident_id": incident.pk, "recheck_id": recheck.pk, "case_id": recheck.case_id,
                   "report_id": recheck.report_id, "report_ids": report_ids, "condition_id": incident.condition_id,
                   "kind": result, "country": recheck.country.code}
        publish("recheck.failed", recheck.pk, payload)
        publish("incident.opened", incident.pk, payload)
        record(actor=actor, action="incident.opened", entity="rpt_incident", entity_id=incident.pk,
               country=recheck.country, data={"case_id": str(recheck.case_id), "kind": result})
        from cases.services import _notify

        _notify(incident.owner, "generic", subject=f"Re-check incident on {recheck.case.reference}", obj=incident,
                link=f"/report-incidents/{incident.pk}",
                body="A re-check did not confirm the original work. Releases on affected escrows are frozen until "
                     "you close the incident. Issue a correction if the report must change.")
    return recheck


def _report_chain(report) -> list:
    ids = [report.pk]
    r = report
    while r.supersedes_id:
        ids.append(r.supersedes_id)
        r = r.supersedes
    for nxt in Report.objects.filter(supersedes_id=report.pk):
        ids.append(nxt.pk)
    return ids


@transaction.atomic
def close_incident(incident: Incident, actor, note) -> Incident:
    incident = Incident.objects.select_for_update().get(pk=incident.pk)
    if not has_role(actor, "RV", country=incident.country):
        raise Forbidden("Only a reviewer closes an incident.")
    if incident.status != "open":
        raise StateConflict("This incident is closed.")
    if not (note or "").strip():
        raise Invalid("Record what was found and done.")
    if incident.kind == "correction_needed" and incident.correction_report_id is None:
        raise RuleBlocked("Issue the correction first (FR-RPT-010).", code="correction-required",
                          blocking_reasons=[{"rule": "FR-RPT-012", "message": "No correction issued."}])
    if incident.correction_report_id:
        cr = incident.correction_report
        if cr.status != "released" or incident.client_notified_at is None:
            raise RuleBlocked("The correction must be released and the client told before the incident closes.",
                              code="correction-required",
                              blocking_reasons=[{"rule": "FR-RPT-012", "message": "Correction not released yet."}])
    incident.closed_by, incident.closure_note, incident.closed_at = actor, note.strip(), _now()
    state.transition(incident, "rpt_incident", "closed", actor=actor, event="incident.closed",
                     payload={"incident_id": incident.pk, "case_id": incident.case_id,
                              "report_id": incident.report_id, "condition_id": incident.condition_id,
                              "country": incident.country.code},
                     extra_fields=["closed_by", "closure_note", "closed_at"])
    return incident


def recheck_due(now=None) -> int:
    """Job reports.recheck_due (daily): unassigned or overdue re-checks go to a reviewer."""
    now = now or _now()
    n = 0
    for r in Recheck.objects.filter(due_alerted_at__isnull=True).filter(
            Q(status="selected", draw__drawn_at__lt=now - timedelta(days=5)) | Q(status="assigned", due_at__lt=now)):
        r.due_alerted_at = now
        r.save(update_fields=["due_alerted_at"])
        _alert_reviewers(r.draw, "A re-check is unassigned or past its due date. Assign it, or skip it with a reason.")
        n += 1
    return n


def month_summary(country, month) -> dict:
    d = RecheckDraw.objects.filter(country=country, sample_month=_month(month)).first()
    if d is None:
        return {"month": _month(month), "drawn": False}
    rs = list(d.rechecks.all())
    return {"month": d.sample_month, "drawn": True, "population": d.population_count, "selected": d.selected_count,
            "share_pct": str(d.sample_pct), "assigned": sum(r.status == "assigned" for r in rs),
            "skipped": sum(r.status == "skipped" for r in rs),
            "confirmed": sum(r.result == "confirmed" for r in rs),
            "correction_needed": sum(r.result == "correction_needed" for r in rs),
            "failed": sum(r.result == "failed" for r in rs), "open": sum(r.status == "selected" for r in rs)}
