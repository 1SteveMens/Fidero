"""The milestone path (FR-BLD-005, 01 C8 Milestone; sequence 5.4): submitted from Tenmina Field, evidence checked,
inspection scheduled with an inspector who has no link to the contractor (RUL-10), inspected, re-priced
(RUL-18), approved by the client (RUL-11), approved by two staff, paid. Defects hold back their value
(FR-BLD-006, RUL-09); the retention waits for the defects period (FR-BLD-012)."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from . import payments, pricing
from .common import alert_staff, audit, cfg, evidence_objects, fmt, log, notify, now, require_on, staff_in, today
from .models import BEFORE_PAID, Defect, Inspection, InspectionItem, Milestone, Payment, Project, Variation

MAIN_OK = {"inspected", "client_approved", "release_approved"}


def _payload(m: Milestone, **extra):
    p = m.project
    return {"milestone_id": m.pk, "project_id": p.pk, "client_id": p.client_id, "seq": m.seq, "key": m.key,
            "label": m.label, "subject_label": m.label, "country": p.country.code,
            "contractor_person_id": p.contractor.person_id if p.contractor else None,
            "link": f"/projects/{p.pk}/milestones/{m.pk}", **extra}


def move(m: Milestone, to, *, actor=None, reason="", extra_fields=None, event=None, **extra):
    if m.status == to:
        return m
    return state.transition(m, "milestone", to, actor=actor, reason=reason, extra_fields=extra_fields,
                            event=event, payload=_payload(m, **extra))


def get(pk) -> Milestone:
    m = Milestone.objects.select_related("project", "project__contractor").filter(pk=pk).first()
    if m is None:
        raise NotFound("Milestone not found.")
    return m


def _previous_passed(m: Milestone) -> bool:
    prev = Milestone.objects.filter(project=m.project, seq__lt=m.seq).order_by("-seq").first()
    if prev is None or prev.is_mobilisation and prev.status in ("client_approved", "release_approved", "paid"):
        return True
    return prev.status in ("inspected", "client_approved", "release_approved", "paid")


def submission_state(m: Milestone) -> tuple[bool, str]:
    """Whether the contractor may submit now, and why not (8.6; TC-STM-MIL-25: in order)."""
    p = m.project
    if p.status != "active":
        return False, f"The project is {p.status}."
    if m.is_mobilisation:
        return False, "Mobilisation is paid on the signed contract and site handover."
    if m.status not in ("not_started", "returned"):
        return False, f"The milestone is {m.status.replace('_', ' ')}."
    if not _previous_passed(m):
        return False, "The previous milestone has not passed inspection yet."
    if m.is_retention:
        if p.defects_period_ends_on is None or p.defects_period_ends_on > today(p.country):
            when = f" until {p.defects_period_ends_on:%d %B %Y}" if p.defects_period_ends_on else ""
            return False, f"The retention is held for the defects period{when}."
    return True, ""


# ----------------------------------------------------------------- submissions (FR-MOB-006, RUL-19)

def _captured_from(evidence_ids):
    from mobile.models import SignedManifest

    t = SignedManifest.objects.filter(evidence_id__in=evidence_ids).order_by("captured_at_device").values_list(
        "captured_at_device", flat=True).first()
    return t


@transaction.atomic
def on_submission(payload: dict):
    """submission.received from MOB for a milestone (contractor's evidence) or an inspection."""
    st = payload.get("subject_type")
    if st == "milestone":
        m = Milestone.objects.select_for_update().filter(pk=payload.get("subject_id")).first()
        if m is None or payload.get("kind") != "evidence_set":
            return
        _received(m, payload)
    elif st == "milestone_inspection":
        i = Inspection.objects.select_for_update().filter(pk=payload.get("subject_id")).first()
        if i is None or payload.get("kind") != "inspection":
            return
        if payload.get("flagged"):
            i.submission_id = payload.get("submission_id")
            i.save(update_fields=["submission_id"])
            alert_staff(i.country, ("RV",), "field_flags_review", "An inspection result has flagged evidence. "
                                                                  "Review the flags before it counts.", obj=i)
            return
        record_inspection(i, payload)


def _received(m: Milestone, payload):
    from accounts.models import Person

    ok, why = submission_state(m)
    if not ok:
        log.warning("submission for milestone %s ignored: %s", m.pk, why)
        return
    ids = [str(it["evidence_id"]) for it in payload.get("items", []) if it.get("evidence_id")]
    m.submission_id, m.evidence_ids = payload.get("submission_id"), ids
    m.captured_from = _captured_from(ids)
    m.submitted_at, m.submissions = now(), m.submissions + 1
    m.fraud_flagged = bool(payload.get("flagged"))
    concerns = [c for c in (m.concerns or []) if c.get("status") != "open"]
    for v in Variation.objects.filter(milestone=m, status="proposed"):
        concerns.append({"kind": "unagreed_variation", "variation_id": str(v.pk), "status": "open",
                         "message": f"A variation is not agreed by both sides: {v.description}"})
    m.concerns = concerns
    by = Person.objects.filter(pk=payload.get("person_id")).first()
    move(m, "submitted", actor=by, extra_fields=["submission_id", "evidence_ids", "captured_from", "submitted_at",
                                                 "submissions", "fraud_flagged", "concerns"])
    if m.fraud_flagged or any(c["status"] == "open" for c in m.concerns):
        alert_staff(m.country, ("RV",), "milestone_review", f"{m.label} was submitted with flags. A reviewer checks "
                                                            "it before an inspection is scheduled.", obj=m)
    else:
        alert_staff(m.country, ("CM",), "milestone_submitted", f"{m.label} was submitted. Check the evidence.",
                    obj=m, link=f"/back-office/milestones/{m.pk}")
    notify(m.project.client, "milestone_update", f"The builder submitted {m.name} with photos. Tenmina is checking "
                                                 "them.", obj=m, link=f"/projects/{m.project_id}")


@transaction.atomic
def submit_stage_evidence(m: Milestone, by, *, evidence_ids, note="") -> Milestone:
    """Project funds stages: receipts uploaded in the portal by the person running the project, the client or a
    case manager. Photos come from the visit in Tenmina Field (RUL-08)."""
    p = m.project
    require_on(p.type, p.country)
    if p.type != "funds":
        raise StateConflict("Building milestones are submitted from Tenmina Field.")
    allowed = by.pk in (p.client_id, p.runner_person_id) or has_role(by, "CM", country=p.country)
    if not allowed:
        raise NotFound()
    if p.status != "active":
        raise StateConflict(f"The project is {p.status}.")
    if m.status not in ("not_started", "returned"):
        raise StateConflict(f"The stage is {m.status.replace('_', ' ')}.")
    evidence = evidence_objects(evidence_ids, by, p.country, what="receipts")
    from .common import link_all

    link_all(evidence, "milestone", m.pk, "invoice", by)
    m.evidence_ids = [str(e.pk) for e in evidence]
    m.submitted_at, m.submissions, m.fraud_flagged = now(), m.submissions + 1, False
    move(m, "submitted", actor=by, reason=note, extra_fields=["evidence_ids", "submitted_at", "submissions",
                                                              "fraud_flagged"])
    alert_staff(p.country, ("CM",), "milestone_submitted", f"Receipts for {m.label} were sent. Check them.", obj=m)
    return m


# ----------------------------------------------------------------- evidence review (FR-BLD-005, FR-MOB-011)

def open_flag_reasons(m: Milestone) -> list[dict]:
    from mobile.services import evidence_blockers

    if not m.evidence_ids:
        return []
    out = evidence_blockers(m.evidence_ids)
    if m.project.type == "funds":
        out = [r for r in out if r["rule"] != "RUL-08"]  # receipts are documents, not field captures
    return out


@transaction.atomic
def review_evidence(m: Milestone, by, *, decision, reason="", note="") -> Milestone:
    """Accept or return a submitted milestone. Flagged evidence or an unagreed variation needs a reviewer
    (TC-STM-MIL-18)."""
    m = Milestone.objects.select_for_update().get(pk=m.pk)
    p = m.project
    require_on(p.type, p.country)
    if not has_role(by, "CM", "RV", country=p.country):
        raise Forbidden("Only a case manager or reviewer checks milestone evidence.")
    if m.status != "submitted":
        raise StateConflict(f"The milestone is {m.status.replace('_', ' ')}, not submitted.",
                            extra={"from_status": m.status})
    if decision == "return":
        if not (reason or "").strip():
            raise Invalid("Say what the contractor must fix.", code="validation-error")
        return_milestone(m, by, reason)
        return m
    if decision != "accept":
        raise Invalid("Decision must be accept or return.", code="validation-error")
    flagged = m.fraud_flagged or any(c.get("status") == "open" for c in (m.concerns or []))
    if flagged and not has_role(by, "RV", country=p.country):
        raise Forbidden("This submission has flags. Only a reviewer can accept it.")
    reasons = open_flag_reasons(m)
    if reasons:
        raise RuleBlocked("Clear or uphold the flags on the evidence first.", code="release-blocked",
                          blocking_reasons=reasons)
    if any(c.get("status") == "open" for c in (m.concerns or [])) and not (note or "").strip():
        raise Invalid("Record why the flagged items are acceptable.", code="validation-error")
    m.concerns = [dict(c, status="reviewed", reviewed_by=str(by.pk), note=note) if c.get("status") == "open" else c
                  for c in (m.concerns or [])]
    m.fraud_flagged = False
    _evidence_checked(m, by)
    return m


def _evidence_checked(m: Milestone, by):
    m.evidence_checked_at, m.evidence_checked_by = now(), by
    move(m, "evidence_checked", actor=by, extra_fields=["evidence_checked_at", "evidence_checked_by", "concerns",
                                                        "fraud_flagged"])
    p = m.project
    if p.type == "funds" and not m.visit_required:
        return m
    if p.inspector_id:  # US-BLD-005a AC1: an inspection is scheduled with the project's inspector
        lead = int(cfg(p.country, p.type, "inspection_lead_days"))
        try:
            schedule_inspection(m, _preparer(m, by if has_role(by, "CM", country=p.country) else None),
                                inspector_id=p.inspector_id,
                                scheduled_for=today(p.country) + timedelta(days=lead))
        except DomainError as exc:
            log.warning("no automatic inspection for %s: %s", m.pk, exc.detail)
            alert_staff(p.country, ("CM",), "inspection_needed", f"Schedule an inspection for {m.label}: "
                                                                 f"{exc.detail}", obj=m)
    else:
        alert_staff(p.country, ("CM",), "inspection_needed", f"Assign an inspector and schedule {m.label}.", obj=m)
    return m


def return_milestone(m: Milestone, by, reason):
    m.return_reasons = list(m.return_reasons or []) + [{"at": now().isoformat(), "reason": reason,
                                                        "by": str(by.pk) if by else None}]
    move(m, "returned", actor=by, reason=reason, extra_fields=["return_reasons"])
    p = m.project
    who = p.contractor.person if p.contractor else None
    notify(who, "milestone_returned", f"{m.label} was returned: {reason}. Fix it and submit again from Tenmina "
                                      "Field. Your saved evidence stays linked.", obj=m, needs_action=True,
           channels=("in_app", "push"))
    notify(p.client, "milestone_update", f"{m.name} needs more work before it is paid: {reason}", obj=m,
           link=f"/projects/{p.pk}")


@transaction.atomic
def on_flags_cleared(payload: dict):
    """flags.cleared from MOB: a reviewer cleared or upheld every flag on a submission."""
    st, sid, outcome = payload.get("subject_type"), payload.get("subject_id"), payload.get("outcome")
    if st == "milestone":
        m = Milestone.objects.select_for_update().filter(pk=sid).first()
        if m is None or m.status != "submitted":
            return
        reviewer = _reviewer_of(payload)
        if outcome == "upheld":
            return_milestone(m, reviewer, "A reviewer upheld a flag on the evidence.")
            return
        m.fraud_flagged = False
        if any(c.get("status") == "open" for c in (m.concerns or [])):
            m.save(update_fields=["fraud_flagged"])
            alert_staff(m.country, ("RV",), "milestone_review", f"The flags on {m.label} are cleared; the variation "
                                                                "concern still needs a reviewer.", obj=m)
            return
        _evidence_checked(m, reviewer)
    elif st == "milestone_inspection":
        i = Inspection.objects.select_for_update().filter(pk=sid, status="scheduled").first()
        if i is None or not i.submission_id:
            return
        if outcome == "upheld":
            i.submission_id = None
            i.save(update_fields=["submission_id"])
            alert_staff(i.country, ("CM",), "inspection_rejected", "A reviewer upheld a flag on an inspection. The "
                                                                   "inspector must inspect again.", obj=i)
            return
        from mobile.models import Submission

        sub = Submission.objects.filter(pk=i.submission_id).first()
        if sub is not None:
            record_inspection(i, {"submission_id": sub.pk, "person_id": sub.person_id, "outcome": sub.outcome,
                                  "defects": sub.defects, "reason": sub.reason, "note": sub.note,
                                  "checklist": sub.checklist})


def _reviewer_of(payload):
    from mobile.models import FraudFlag, Submission

    sub = Submission.objects.filter(pk=payload.get("submission_id")).first() if payload.get("submission_id") else None
    if sub is None:
        return None
    ev_ids = sub.items.exclude(evidence__isnull=True).values_list("evidence_id", flat=True)
    f = FraudFlag.objects.filter(evidence_id__in=ev_ids, reviewed_by__isnull=False).order_by("-reviewed_at").first()
    return f.reviewed_by if f else None


@transaction.atomic
def confirm_stage(m: Milestone, by, *, note="") -> Milestone:
    """Project funds stages with no visit configured are confirmed at the desk from the receipts (FR-PRJ-003)."""
    m = Milestone.objects.select_for_update().get(pk=m.pk)
    p = m.project
    require_on(p.type, p.country)
    if not has_role(by, "CM", "RV", country=p.country):
        raise Forbidden("Only a case manager confirms a stage.")
    if p.type != "funds" or m.visit_required:
        raise RuleBlocked("This stage needs an inspection visit.", code="release-blocked",
                          blocking_reasons=[{"rule": "RUL-09", "code": "inspection-missing",
                                             "message": "A visit is configured for this stage."}])
    if m.status != "evidence_checked":
        raise StateConflict(f"The stage is {m.status.replace('_', ' ')}.")
    m.inspected_at = now()
    move(m, "inspected", actor=by, reason=note or "Stage confirmed from the receipts", extra_fields=["inspected_at"])
    return m


# ----------------------------------------------------------------- inspections (FR-BLD-004, FR-BLD-005)

@transaction.atomic
def schedule_inspection(m: Milestone, by, *, inspector_id=None, scheduled_for=None) -> Inspection:
    """TC-BLD-005-03: needs an inspector with no link to the contractor and a visit date."""
    from .models import PanelMember
    from .panel import require_assignable_inspector

    m = Milestone.objects.select_for_update().get(pk=m.pk)
    p = m.project
    require_on(p.type, p.country)
    if not has_role(by, "CM", country=p.country):
        raise Forbidden("Only a case manager schedules inspections.")
    if m.status != "evidence_checked":
        raise StateConflict(f"The milestone is {m.status.replace('_', ' ')}. Evidence is checked before an "
                            "inspection.", extra={"from_status": m.status})
    if not inspector_id:
        raise Invalid("Choose the inspector.", code="validation-error")
    if not scheduled_for:
        raise Invalid("Choose the visit date.", code="validation-error")
    insp = PanelMember.objects.filter(pk=inspector_id, kind="inspector").first()
    if insp is None:
        raise NotFound("That inspector is not on the panel.")
    require_assignable_inspector(insp, p.contractor, p.country)
    i = Inspection.objects.create(country=p.country, project=p, milestone=m, inspector=insp,
                                  kind="retention" if m.is_retention else "milestone", scheduled_for=scheduled_for,
                                  assigned_by=by, assigned_at=now(), checklist=m.checklist)
    m.inspector = insp
    move(m, "inspection_scheduled", actor=by, extra_fields=["inspector"], inspection_id=i.pk)
    _tell_inspector(i)
    notify(p.client, "milestone_update", f"An independent inspector will visit {m.name} on "
                                         f"{scheduled_for:%d %B %Y}.", obj=m, link=f"/projects/{p.pk}")
    return i


def _tell_inspector(i: Inspection):
    publish("inspection.scheduled", i.pk, {"inspection_id": i.pk, "project_id": i.project_id,
                                           "milestone_id": i.milestone_id, "inspector_id": i.inspector.person_id,
                                           "person_id": i.inspector.person_id, "scheduled_for": i.scheduled_for,
                                           "country": i.country.code})
    audit(i.assigned_by, "inspection.scheduled", i, {"inspector": str(i.inspector_id)})


@transaction.atomic
def cancel_inspection(i: Inspection, by, *, reason) -> Inspection:
    if i.status != "scheduled":
        return i
    i.cancel_reason = reason
    state.transition(i, "bld_inspection", "cancelled", actor=by, reason=reason, extra_fields=["cancel_reason"],
                     payload={"inspection_id": i.pk, "project_id": i.project_id})
    m = i.milestone
    if m is not None and m.status == "inspection_scheduled":
        m.inspector = None
        move(m, "evidence_checked", actor=by, reason=reason, extra_fields=["inspector"])
    return i


@transaction.atomic
def declare_link(i: Inspection, by, *, has_link, reason="") -> Inspection:
    """The inspector sees "You have no link to this contractor". If they do have one, they say so: the link is
    recorded and the inspection goes to someone else (RUL-10)."""
    from .models import ConflictLink

    if i.inspector is None or i.inspector.person_id != by.pk:
        raise NotFound()
    if i.status != "scheduled":
        raise StateConflict("This inspection is closed.")
    if not has_link:
        i.declared_no_link_at = now()
        i.save(update_fields=["declared_no_link_at"])
        audit(by, "inspection.no_link_declared", i)
        return i
    contractor = i.project.contractor
    if contractor is not None:
        ConflictLink.objects.get_or_create(inspector=i.inspector, contractor=contractor, defaults=dict(
            reason="declared_by_inspector", note=reason or "", recorded_by=by))
    p = i.project
    if p.inspector_id == i.inspector_id:
        p.inspector = None
        p.save(update_fields=["inspector"])
    cancel_inspection(i, by, reason="The inspector declared a link to the contractor (RUL-10).")
    alert_staff(i.country, ("CM",), "inspector_conflict", f"The inspector on {p.title} declared a link to the "
                                                          "contractor. Assign another inspector.", obj=p)
    return i


def _require_recordable(i: Inspection, person_id):
    from .panel import conflict_reasons

    if i.status != "scheduled":
        raise StateConflict("This inspection is already recorded or cancelled.")
    if i.inspector is None or str(i.inspector.person_id) != str(person_id):
        raise Forbidden("Only the assigned inspector records the outcome (TC-STM-MIL-19).")
    reasons = conflict_reasons(i.inspector, i.project.contractor)
    if reasons:
        raise RuleBlocked("The inspector has a link to the contractor.", code="inspector-conflicted",
                          blocking_reasons=reasons)
    if i.milestone is not None and i.kind != "extra" and i.milestone.status != "inspection_scheduled":
        raise StateConflict(f"The milestone is {i.milestone.status.replace('_', ' ')}.")


@transaction.atomic
def record_inspection(i: Inspection, payload: dict) -> Inspection:
    """FR-MOB-007, RUL-09: pass, pass with defects (each with photos and a value) or fail."""
    from accounts.models import Person

    i = Inspection.objects.select_for_update().get(pk=i.pk)
    try:
        _require_recordable(i, payload.get("person_id"))
    except DomainError as exc:
        log.warning("inspection %s not recorded: %s", i.pk, exc.detail)
        alert_staff(i.country, ("CM",), "inspection_refused", f"An inspection result was refused: {exc.detail}",
                    obj=i)
        return i
    person = Person.objects.filter(pk=payload.get("person_id")).first()
    outcome = payload.get("outcome")
    labels = {c["key"]: c.get("label", "") for c in i.checklist or []}
    for c in payload.get("checklist") or []:
        InspectionItem.objects.create(inspection=i, key=c.get("key"), label=labels.get(c.get("key"), ""),
                                      result=c.get("result"), note=c.get("note", "") or "")
    total = Decimal("0")
    target = i.milestone
    for d in payload.get("defects") or []:
        v = d.get("value") or {}
        amount = q(v.get("amount"))
        total += amount
        Defect.objects.create(country=i.country, inspection=i, milestone=target, project=i.project,
                              description=d.get("description", ""), value_amount=amount,
                              value_currency=(v.get("currency") or i.project.budget_currency).upper(),
                              photo_evidence_ids=[str(x) for x in d.get("evidence_ids") or []])
    i.outcome, i.defect_value, i.defect_currency = outcome, q(total), i.project.budget_currency
    i.reason, i.note = payload.get("reason", "") or "", payload.get("note", "") or ""
    i.submission_id, i.recorded_at = payload.get("submission_id"), now()
    i.declared_no_link_at = i.declared_no_link_at or i.recorded_at
    # TC-RUL-09-04: defects worth the milestone or more go to a reviewer; never a negative release.
    i.needs_review = bool(target is not None and outcome == "pass_with_defects" and total >= target.amount)
    state.transition(i, "bld_inspection", "recorded", actor=person, event="inspection.recorded",
                     extra_fields=["outcome", "defect_value", "defect_currency", "reason", "note", "submission_id",
                                   "recorded_at", "declared_no_link_at", "needs_review"],
                     payload={"inspection_id": i.pk, "project_id": i.project_id, "milestone_id": i.milestone_id,
                              "outcome": outcome, "kind": i.kind, "client_id": i.project.client_id,
                              "asset_id": i.project.asset_id, "country": i.country.code})
    # RUL-26: the inspector is paid for the accepted visit, whatever the result.
    publish("work.accepted", i.pk, {"work_kind": "inspection", "work_type": "inspection", "work_ref": i.pk,
                                    "person_id": i.inspector.person_id, "role": "IN", "project_id": i.project_id,
                                    "assigned_at": i.assigned_at or i.created_at, "accepted_at": i.recorded_at,
                                    "quantity": 1, "country": i.country.code})
    if i.needs_review:
        alert_staff(i.country, ("RV",), "defects_exceed", f"The defects on {target.label} are worth more than the "
                                                          "milestone. Review before anything is paid.", obj=i)
    if i.kind == "extra" or target is None:
        notify(i.project.client, "inspection_result", f"The extra inspection on {i.project.title} is done: "
                                                      f"{outcome.replace('_', ' ')}.", obj=i,
               link=f"/projects/{i.project_id}")
        return i
    if outcome == "fail":
        target.inspected_at = now()
        move(target, "inspected", actor=person, extra_fields=["inspected_at"], outcome=outcome)
        return_milestone(target, person, f"The inspection failed: {i.reason}")
        return i
    target.inspected_at = now()
    move(target, "inspected", actor=person, extra_fields=["inspected_at"], outcome=outcome)
    notify(i.project.client, "inspection_result",
           f"{target.name} passed inspection" + (f" with defects worth {fmt(total, i.defect_currency)}, which stay "
                                                 "held until fixed." if outcome == "pass_with_defects" else ".")
           + " Please review and approve the payment.", obj=target, link=f"/projects/{i.project_id}")
    if not i.needs_review and i.project.is_build:
        try:
            prepare_main(target, None)
        except DomainError as exc:
            log.warning("payment for %s not prepared: %s %s", target.pk, exc.detail,
                        getattr(exc, "blocking_reasons", ""))
            alert_staff(i.country, ("CM",), "payment_not_prepared", f"The payment for {target.label} could not be "
                                                                    f"prepared: {exc.detail}", obj=target)
    return i


def latest_inspection(m: Milestone):
    return Inspection.objects.filter(milestone=m, status="recorded", kind__in=["milestone", "retention"]) \
        .order_by("-recorded_at").first()


def open_defects(m: Milestone):
    return Defect.objects.filter(milestone=m).exclude(status="closed")


@transaction.atomic
def order_extra_inspection(payload: dict):
    """order.paid for an extra inspection (FR-ORD-007): an inspector with no link to the contractor visits."""
    if payload.get("kind") != "extra_inspection" or payload.get("subject_type") != "project":
        return None
    p = Project.objects.filter(pk=payload.get("subject_id")).first()
    if p is None or Inspection.objects.filter(order_id=payload.get("order_id")).exists():
        return None
    current = p.milestones.exclude(status="paid").order_by("seq").first()
    concern = ((payload.get("details") or {}).get("concern") or "")[:2000]
    i = Inspection.objects.create(country=p.country, project=p, milestone=current, kind="extra",
                                  order_id=payload.get("order_id"), concern=concern,
                                  checklist=[{"key": "concern", "label": "The client's concern"},
                                             {"key": "workmanship", "label": "General workmanship"}])
    cm = p.case_manager or staff_in(p.country, "CM").first()
    if p.inspector_id and cm is not None:
        from .panel import conflict_reasons

        if not conflict_reasons(p.inspector, p.contractor):
            lead = int(cfg(p.country, p.type, "inspection_lead_days"))
            i.inspector, i.scheduled_for, i.assigned_by, i.assigned_at = p.inspector, today(p.country) + timedelta(
                days=lead), cm, now()
            i.save(update_fields=["inspector", "scheduled_for", "assigned_by", "assigned_at"])
            _tell_inspector(i)
            return i
    alert_staff(p.country, ("CM",), "inspection_needed", f"{p.client.full_name} paid for an extra inspection on "
                                                         f"{p.title}. Assign an inspector.", obj=i)
    return i


@transaction.atomic
def assign_extra_inspection(i: Inspection, by, *, inspector_id, scheduled_for) -> Inspection:
    from .models import PanelMember
    from .panel import require_assignable_inspector

    if not has_role(by, "CM", country=i.country):
        raise Forbidden("Only a case manager assigns inspections.")
    if i.kind != "extra" or i.status != "scheduled":
        raise StateConflict("Only an open extra inspection is assigned here.")
    insp = PanelMember.objects.filter(pk=inspector_id, kind="inspector").first()
    if insp is None or not scheduled_for:
        raise Invalid("Choose the inspector and the date.", code="validation-error")
    require_assignable_inspector(insp, i.project.contractor, i.country)
    i.inspector, i.scheduled_for, i.assigned_by, i.assigned_at = insp, scheduled_for, by, now()
    i.save(update_fields=["inspector", "scheduled_for", "assigned_by", "assigned_at"])
    _tell_inspector(i)
    return i


# ----------------------------------------------------------------- defects (FR-BLD-006, FR-BLD-012)

def _assigned_inspector(d: Defect, by) -> bool:
    insp = d.inspection.inspector
    proj_insp = d.project.inspector
    return any(x is not None and x.person_id == by.pk for x in (insp, proj_insp))


@transaction.atomic
def close_defect(d: Defect, by, *, evidence_ids, note="") -> Defect:
    """TC-BLD-006-02: never without evidence. The assigned inspector closes it outright; a case manager or the
    contractor marks it fixed and the inspector confirms."""
    d = Defect.objects.select_for_update().get(pk=d.pk)
    p = d.project
    require_on(p.type, p.country)
    is_insp = _assigned_inspector(d, by)
    from .projects import _side

    contractor = _side(p, by) == "contractor"
    if not (is_insp or contractor or has_role(by, "CM", country=p.country)):
        raise NotFound()
    if d.status == "closed":
        raise StateConflict("This defect is already closed.")
    evidence = evidence_objects(evidence_ids, by, p.country, what="evidence that the defect is fixed")
    from .common import link_all

    link_all(evidence, "defect", d.pk, "defect_closed", by)
    d.closing_evidence_ids = list(d.closing_evidence_ids or []) + [str(e.pk) for e in evidence]
    d.note = note or d.note
    if is_insp:
        d.confirmed_by, d.closed_at = by, now()
        d.fixed_by, d.fixed_at = d.fixed_by or by, d.fixed_at or now()
        state.transition(d, "bld_defect", "closed", actor=by, extra_fields=[
            "closing_evidence_ids", "note", "confirmed_by", "closed_at", "fixed_by", "fixed_at"],
            payload={"defect_id": d.pk, "project_id": p.pk, "milestone_id": d.milestone_id})
        _after_defect_closed(d, by)
    else:
        d.fixed_by, d.fixed_at = by, now()
        state.transition(d, "bld_defect", "fixed", actor=by, extra_fields=["closing_evidence_ids", "note", "fixed_by",
                                                                           "fixed_at"],
                         payload={"defect_id": d.pk, "project_id": p.pk})
        insp = d.inspection.inspector or p.inspector
        notify(insp.person if insp else None, "defect_to_confirm", f"A defect on {p.title} is marked fixed. "
                                                                   "Please confirm it.", obj=d, needs_action=True,
               channels=("in_app", "push"))
    return d


@transaction.atomic
def confirm_defect(d: Defect, by, *, confirm=True, note="") -> Defect:
    d = Defect.objects.select_for_update().get(pk=d.pk)
    if not _assigned_inspector(d, by):
        raise NotFound()
    if d.status != "fixed":
        raise StateConflict("The defect is not marked fixed.")
    if not confirm:
        d.note = note or "Not fixed"
        state.transition(d, "bld_defect", "open", actor=by, reason=d.note, extra_fields=["note"],
                         payload={"defect_id": d.pk})
        return d
    d.confirmed_by, d.closed_at, d.note = by, now(), note or d.note
    state.transition(d, "bld_defect", "closed", actor=by, extra_fields=["confirmed_by", "closed_at", "note"],
                     payload={"defect_id": d.pk, "project_id": d.project_id, "milestone_id": d.milestone_id})
    _after_defect_closed(d, by)
    return d


def _after_defect_closed(d: Defect, by):
    m = d.milestone
    if m is None or open_defects(m).exists():
        return
    main = Payment.objects.filter(milestone=m, part="main", status="paid").order_by("-paid_at").first()
    if main is None or main.holdback_amount <= 0:
        return
    try:
        prepare_holdback(m, None)
    except DomainError as exc:
        log.warning("holdback for %s not prepared: %s", m.pk, exc.detail)
        alert_staff(m.country, ("CM",), "payment_not_prepared", f"The held defect value on {m.label} could not be "
                                                                f"prepared: {exc.detail}", obj=m)


# ----------------------------------------------------------------- payments for a milestone

def _preparer(m, by):
    if by is not None and has_role(by, "CM", "RV", country=m.country):
        return by
    p = m.project
    if p.case_manager is not None and has_role(p.case_manager, "CM", country=p.country):
        return p.case_manager
    cm = staff_in(p.country, "CM").first()
    if cm is None:
        raise StateConflict("No case manager is available to prepare the payment.")
    return cm


def _payee(m):
    c = m.project.contractor
    return c.payee if c is not None else None


def defects_total(m: Milestone) -> Decimal:
    return open_defects(m).aggregate(s=Sum("value_amount"))["s"] or Decimal("0.00")


@transaction.atomic
def prepare_main(m: Milestone, by) -> Payment:
    """RUL-09, RUL-18: re-price, then prepare the milestone amount less the open defect value."""
    m = Milestone.objects.select_for_update().get(pk=m.pk)
    p = m.project
    if not p.is_build:
        raise StateConflict("Project funds are paid against supplier invoices.")
    if not (m.status == "inspected" or (m.is_mobilisation and m.status == "not_started")):
        raise StateConflict(f"The milestone is {m.status.replace('_', ' ')}, not ready for payment.")
    by = _preparer(m, by)
    r = pricing.reprice(m)
    m.refresh_from_db()
    hold = defects_total(m)
    amount = q(m.amount - hold)
    return payments.prepare(p, part="main", subject_type=p.release_subject, subject_id=m.pk, payee=_payee(m),
                            amount=amount, by=by, milestone=m, holdback_amount=hold, reprice=r,
                            label=f"{m.name}, {p.title}" + (" (less defects held)" if hold else ""))


@transaction.atomic
def prepare_holdback(m: Milestone, by) -> Payment:
    """FR-BLD-006: the held defect value, once every defect is closed with evidence and confirmed."""
    p = m.project
    by = _preparer(m, by)
    main = Payment.objects.filter(milestone=m, part="main", status="paid").order_by("-paid_at").first()
    if main is None or main.holdback_amount <= 0:
        raise StateConflict("Nothing is held back on this milestone.")
    return payments.prepare(p, part="defect_holdback", subject_type=p.release_subject, subject_id=m.pk,
                            payee=_payee(m), amount=main.holdback_amount, by=by, milestone=m,
                            label=f"{m.name}, {p.title}: defects fixed")


def _r(rule, code, message):
    return {"rule": rule, "code": code, "message": message}


def main_blockers(pay: Payment, stage) -> list[dict]:
    m = Milestone.objects.select_related("project").get(pk=pay.milestone_id)
    p = m.project
    out = []
    if m.status == "frozen":
        out.append(_r("RUL-15", "milestone-frozen", f"{m.name} is frozen ({m.freeze_kind.replace('_', ' ')})."))
    c = p.contractor
    if c is None or c.status != "active":
        out.append(_r("FR-BLD-010", "contractor-not-active", "The contractor is not active on the panel."))
    elif c.payee_id != pay.payee_id:
        out.append(_r("RUL-22", "payee-not-verified", "A milestone pays only the project's own contractor."))
    if m.is_mobilisation:
        if not p.contract_signed_at:
            out.append(_r("RUL-09", "contract-unsigned", "The contract is not signed."))
        hb = p.handover_confirmed_by
        if hb is None or not has_role(hb, "CM", "RV", country=p.country):
            out.append(_r("RUL-09", "handover-unconfirmed", "A Tenmina staff member has not confirmed site handover."))
        if m.status not in ("not_started", "client_approved", "release_approved"):
            out.append(_r("RUL-09", "milestone-state", f"Mobilisation is {m.status.replace('_', ' ')}."))
    else:
        insp = latest_inspection(m)
        if insp is None or insp.outcome not in ("pass", "pass_with_defects") or (
                m.submitted_at and insp.recorded_at < m.submitted_at):
            out.append(_r("RUL-09", "inspection-missing", f"{m.name} has no inspector's pass."))
        elif insp.needs_review:
            out.append(_r("RUL-09", "defects-exceed", "The defects are worth the milestone or more. A reviewer must "
                                                      "look first."))
        if m.status not in MAIN_OK:
            out.append(_r("RUL-09", "milestone-state", f"{m.name} is {m.status.replace('_', ' ')}."))
        out.extend({**r, "code": "evidence-flagged"} for r in open_flag_reasons(m))
        if any(cn.get("status") == "open" for cn in (m.concerns or [])):
            out.append(_r("RUL-19", "variation-unagreed", "A flag on the submission (an unagreed variation) is "
                                                          "still open."))
    if m.is_retention:
        if p.defects_period_ends_on is None or p.defects_period_ends_on > today(p.country):
            out.append(_r("FR-BLD-012", "defects-period", "The defects period has not ended."))
        if Defect.objects.filter(project=p).exclude(status="closed").exists():
            out.append(_r("FR-BLD-012", "defects-open", "A defect on the project is still open."))
    if pay.part == "main":
        out.extend(pricing.reprice_reasons(m, pricing.latest(m), p.type))
        r = pricing.latest(m)
        if r is not None and pay.reprice_id and r.pk != pay.reprice_id:
            out.append(_r("RUL-18", "reprice-stale", "The milestone was re-priced after this payment was prepared."))
        expected = q(m.amount - defects_total(m)) if stage == "prepare" else None
        if expected is not None and expected != pay.amount:
            out.append(_r("RUL-09", "amount-mismatch", f"The payment must be {fmt(expected, m.currency)}."))
        if pay.amount < 0 or pay.amount > m.amount:
            out.append(_r("RUL-09", "amount-mismatch", "The payment is more than the milestone."))
    return out


def holdback_blockers(pay: Payment, stage) -> list[dict]:
    m = Milestone.objects.get(pk=pay.milestone_id)
    out = []
    main = Payment.objects.filter(milestone=m, part="main", status="paid").first()
    if main is None:
        out.append(_r("RUL-09", "main-release-first", "The milestone itself is paid first."))
    elif q(pay.amount) != q(main.holdback_amount):
        out.append(_r("FR-BLD-006", "amount-mismatch", f"The held value is {fmt(main.holdback_amount, m.currency)}."))
    if open_defects(m).exists():
        out.append(_r("FR-BLD-006", "defects-open", "A defect is not closed with evidence and confirmed."))
    if m.status == "frozen":
        out.append(_r("RUL-15", "milestone-frozen", f"{m.name} is frozen."))
    c = m.project.contractor
    if c is None or c.status != "active" or c.payee_id != pay.payee_id:
        out.append(_r("FR-BLD-010", "contractor-not-active", "The contractor is not active on the panel."))
    return out


def on_main_status(pay: Payment, to):
    m = Milestone.objects.select_for_update().get(pk=pay.milestone_id)
    if to == "client_approved":
        if m.status in ("inspected", "not_started"):
            m.client_approved_at, m.client_approved_by = now(), m.project.client
            move(m, "client_approved", actor=m.project.client, extra_fields=["client_approved_at",
                                                                             "client_approved_by"])
            publish("milestone.client_approved", m.pk, _payload(m, amount=pay.amount, currency=pay.currency,
                                                                payment_id=pay.pk))
    elif to == "release_approved":
        if m.status == "client_approved":
            move(m, "release_approved")
    elif to == "paid":
        if m.status == "client_approved":
            move(m, "release_approved")
        m.refresh_from_db()
        if m.status == "release_approved":
            m.paid_at = now()
            move(m, "paid", extra_fields=["paid_at"], amount=pay.amount, held=pay.holdback_amount)
            from .projects import on_milestone_paid

            on_milestone_paid(m)
            notify(m.project.client, "money_update", f"{m.name} is paid: {fmt(pay.amount, pay.currency)} to "
                                                     f"{pay.payee.legal_name}." + (
                       f" {fmt(pay.holdback_amount, pay.currency)} stays held until the defects are fixed."
                       if pay.holdback_amount else ""), obj=m, link=f"/projects/{m.project_id}")
    elif to in ("withdrawn", "rejected"):
        if m.status in ("client_approved", "release_approved"):
            m.client_approved_at = None
            move(m, "inspected", reason=pay.closed_reason or to, extra_fields=["client_approved_at"])
        elif m.status == "frozen" and m.prior_status in ("client_approved", "release_approved"):
            m.prior_status = "inspected"
            m.save(update_fields=["prior_status"])


def on_holdback_status(pay: Payment, to):
    if to == "paid":
        m = pay.milestone
        notify(m.project.client, "money_update", f"The held value on {m.name} is paid now the defects are fixed.",
               obj=m, link=f"/projects/{m.project_id}")


payments.register_subject("main", blockers=main_blockers, on_status=on_main_status)
payments.register_subject("defect_holdback", blockers=holdback_blockers, on_status=on_holdback_status)


@transaction.atomic
def client_approve(m: Milestone, client, *, mfa_at=None, code=None, confirm_amount=None) -> Milestone:
    """US-BLD-005b, RUL-11, RUL-18: the client approves the inspected milestone with their second factor, seeing
    the re-priced amount. A changed amount must be confirmed."""
    p = m.project
    require_on(p.type, p.country)
    if p.client_id != client.pk:
        raise NotFound()
    pay = Payment.objects.filter(milestone=m, part__in=["main", "defect_holdback"], status="awaiting_client") \
        .order_by("-created_at").first()
    if pay is None:
        if m.status not in ("inspected",) and not (m.is_mobilisation and m.status == "not_started"):
            raise StateConflict(f"{m.name} is {m.status.replace('_', ' ')}. You approve a milestone once it passes "
                                "inspection.", extra={"from_status": m.status})
        raise StateConflict("The payment for this milestone is still being prepared.")
    if pay.reprice_id and pay.reprice.changed and confirm_amount is None:
        r = pay.reprice
        pricing.shown(r)
        raise Invalid(f"The amount changed from {fmt(r.previous_amount, r.local_currency)} to "
                      f"{fmt(r.local_amount, r.local_currency)} at the guide rate of {r.rate} on "
                      f"{r.rate_date:%d %B %Y}. Confirm the new amount to approve.", code="amount-changed",
                      extra={"previous": f"{r.previous_amount:.2f}", "amount": f"{pay.amount:.2f}",
                             "rate": str(r.rate), "rate_date": r.rate_date.isoformat()})
    payments.client_approve(pay, client, mfa_at=mfa_at, code=code, confirm_amount=confirm_amount)
    m.refresh_from_db()
    return m


def remind_clients(at=None) -> int:
    """Daily job: reminders to approve inspected milestones. Silence is never approval (RUL-11, Q-13)."""
    from administration.selectors import setting

    at = at or now()
    n = 0
    for pay in Payment.objects.filter(status="awaiting_client", milestone__isnull=False).select_related(
            "milestone", "project", "project__client"):
        days = int(setting("client_approval_reminder_days", pay.country, 3))
        m = pay.milestone
        last = m.last_reminder_at or pay.created_at
        if at - last < timedelta(days=days):
            continue
        notify(pay.project.client, "approval_reminder", f"{m.label} passed inspection and waits for your approval. "
                                                        "Nothing is paid until you approve.", needs_action=True,
               obj=pay, link=f"/projects/{pay.project_id}", category="reminder")
        m.last_reminder_at = at
        m.save(update_fields=["last_reminder_at"])
        n += 1
    return n


@transaction.atomic
def on_guide_rate(payload: dict):
    """fx_rate.updated: a payment the client approved at an older rate is prepared again and the client approves
    the new amount (TC-RUL-18-03)."""
    from countries.models import Country

    country = Country.objects.filter(code=payload.get("country")).first()
    if country is None:
        return
    for pay in Payment.objects.filter(country=country, part="main", status__in=["awaiting_client",
                                                                                 "client_approved"]):
        if pay.reprice_id is None or not pricing.stale_reason(country, pay.reprice.fx_rate, pay.project.type):
            continue
        m = pay.milestone
        try:
            payments.withdraw(pay, None, reason="The guide rate changed. The client approves the new amount.",
                              system=True)
            prepare_main(Milestone.objects.get(pk=m.pk), None)
        except DomainError as exc:
            log.warning("re-pricing %s after a rate change failed: %s", m.pk, exc.detail)


# ----------------------------------------------------------------- freezes (disputes, removals)

def freeze_milestone(m: Milestone, *, kind, source_id, by=None, reason=""):
    if m.status in ("paid", "frozen"):
        return m
    m.prior_status, m.freeze_kind, m.freeze_source_id = m.status, kind, source_id
    return move(m, "frozen", actor=by, reason=reason, extra_fields=["prior_status", "freeze_kind",
                                                                    "freeze_source_id"])


def unfreeze_milestone(m: Milestone, *, by=None, reason=""):
    if m.status != "frozen":
        return m
    to = m.prior_status or "not_started"
    m.freeze_kind, m.freeze_source_id = "", None
    return move(m, to, actor=by, reason=reason or "Freeze lifted", extra_fields=["freeze_kind", "freeze_source_id"])


@transaction.atomic
def on_dispute(payload: dict, opened: bool):
    did = payload.get("dispute_id") or payload.get("id")
    if not did:
        return
    ms = []
    if payload.get("milestone_id"):
        ms = list(Milestone.objects.filter(pk=payload["milestone_id"]))
    elif payload.get("subject_type") == "milestone" and payload.get("subject_id"):
        ms = list(Milestone.objects.filter(pk=payload["subject_id"]))
    else:
        q_ = Project.objects.none()
        if payload.get("project_id"):
            q_ = Project.objects.filter(pk=payload["project_id"])
        elif payload.get("escrow_id"):
            q_ = Project.objects.filter(escrow_id=payload["escrow_id"])
        for p in q_:
            ms += list(p.milestones.all())
    for m in ms:
        if opened:
            freeze_milestone(m, kind="dispute", source_id=did, reason=payload.get("reason", "Dispute opened"))
        elif m.status == "frozen" and m.freeze_kind == "dispute" and str(m.freeze_source_id) == str(did):
            unfreeze_milestone(m, reason="Dispute resolved")


def overdue_actions():
    """Milestones whose next step is waiting on Tenmina, for the back office."""
    return Milestone.objects.filter(status__in=["submitted", "evidence_checked"]).select_related("project")


__all__ = ["BEFORE_PAID"]
