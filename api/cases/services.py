"""CASE Verification cases: the public interface other modules may call.

- create_from_order(order_id)            ORD's order.paid: land, building and fresh-search cases (FR-CASE-001)
- open_case(template_code, country, ...) other lines start their verification case (ADR-21)
- open_fresh_search(asset, ...)          FR-CASE-014, RUL-07; LST reservations and ESC releases
- add_cost(case, ...)                    FR-CASE-011; PRO writes accepted pay and expenses (FR-PRO-010)
- log_safety_incident(...)               FR-CASE-010; CARE and TSK use the same restricted log
- mark_in_review / return_to_progress / on_report_released   RPT drives the review states (5.2)

Every rule raises a problem code from 02 section 7.2. Every status change goes
through core.state.transition, which audits and publishes.
"""
import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from administration import flags
from audit.services import record
from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.ids import uuid7
from core.permissions import has_role

from . import templates
from .models import (Case, CostItem, DocumentRequest, Message, Party, ReferenceCounter, RiskScreen, SafetyIncident,
                     SafetyReader, SearchCopyCheck, SearchRequest, StatusMessage, Task)

log = logging.getLogger(__name__)

STAFF = ("CM", "RV")
LICENSED = {"LW", "SV", "IN", "QS"}
FIELD_ROLES = {"RN", "SV", "IN", "LW", "QS", "CE", "CM"}
SEARCH_EXCLUDED = ("RN", "SE", "DV", "CL", "CE")  # RUL-30: never handle an official search
INCIDENT_ROLES = ("CM", "RV", "LW", "SV", "RN", "IN", "QS", "CE")
DEFAULT_RISK_SCREEN_DAYS = 14  # [TO VERIFY] how long a risk screen stays valid
PHOTO_KINDS = re.compile(r"(photo|image)$")


# --------------------------------------------------------------------------- helpers

def _now():
    return timezone.now()


def _cfg(country, key, default=None):
    from countries.selectors import config

    try:
        return config(country, key, default)
    except Exception:  # noqa: BLE001
        return default


def _staff_people(country, *roles):
    from accounts.models import Person

    code = getattr(country, "code", country)
    return Person.objects.filter(
        Q(role_grants__country__isnull=True) | Q(role_grants__country__code=code),
        role_grants__role__in=roles, role_grants__revoked_at__isnull=True, is_active=True).distinct()


def _notify(person, template, *, body="", subject="", obj=None, link="", needs_action=False, context=None,
            channels=("in_app",), category=None):
    from notifications.services import notify

    if person is None:
        return []
    return notify(person, template, body=body, subject=subject, subject_obj=obj, link=link,
                  needs_action=needs_action, context=context or {}, channels=channels, category=category)


def _alert(country, roles, *, subject, body, obj=None, link="", template="generic", category=None, exclude=()):
    for p in _staff_people(country, *roles):
        if p.pk in exclude:
            continue
        _notify(p, template, subject=subject, body=body, obj=obj, link=link, category=category)


def _case_link(case):
    return f"/cases/{case.pk}"


def is_case_staff(user, case, roles=STAFF) -> bool:
    return has_role(user, *roles, country=case.country)


def is_assigned(user, case) -> bool:
    if not user or not user.is_authenticated:
        return False
    return Task.objects.filter(case=case).filter(Q(assignee=user) | Q(second_assignee=user)).exists()


def is_client(user, case) -> bool:
    return bool(user and user.is_authenticated and case.client_id == user.pk)


def is_representative(user, case) -> bool:
    from accounts.selectors import is_representative as rep

    return bool(user and user.is_authenticated and rep(user, "case", case.pk))


def can_view(user, case) -> bool:
    return (is_case_staff(user, case) or is_client(user, case) or is_representative(user, case)
            or is_assigned(user, case))


def _require_staff(actor, case, roles=STAFF, msg="Only a case manager or reviewer can do this."):
    if not is_case_staff(actor, case, roles):
        raise Forbidden(msg)


def _require_open(case):
    if case.status not in ("paid", "in_progress", "on_hold", "in_review"):
        raise StateConflict(f"Case {case.reference} is {case.status.replace('_', ' ')}.")


def case_payload(case, *, notified=False) -> dict:
    """The case.* event payload. `case_ref` and `status_label` are the keys NTF reads; `notified=True`
    tells NTF that post_status already told the client in the case's own words, so it sends nothing more."""
    return {"case_id": case.pk, "reference": case.reference, "case_ref": case.reference, "country": case.country.code,
            "product_line": case.product_line, "client_id": case.client_id, "asset_id": case.asset_id,
            "order_id": case.order_id, "subject_type": case.subject_type, "subject_id": case.subject_id,
            "status": case.status, "outcome": case.outcome, "parent_case_id": case.parent_case_id,
            "origin": case.origin, "origin_ref": case.origin_ref, "notified": notified}


@transaction.atomic
def next_reference(country) -> str:
    year = _now().year
    ctr, _ = ReferenceCounter.objects.select_for_update().get_or_create(country_code=country.code, year=year)
    ctr.last += 1
    ctr.save(update_fields=["last"])
    return f"TMC-{country.code}-{year}-{ctr.last:05d}"


# --------------------------------------------------------------------------- templates (FR-CASE-001)

def template_for(product_line: str, country):
    """The case template version new work starts with. TC-CASE-001-02: no template, a clear error."""
    from administration.selectors import current_config

    cv = current_config("case_template", country, product_line)
    if cv is None:
        raise DomainError(f"No case template is published for '{product_line}' in {country.name}. An administrator "
                          "must publish one before cases can open.", code="case-template-missing", status=409)
    try:
        templates.validate(cv.content)
    except Invalid as exc:
        raise DomainError(f"The published case template for '{product_line}' in {country.name} (version "
                          f"{cv.version}) cannot be used: {exc.detail}", code="case-template-invalid",
                          status=409) from None
    return cv


def _title_for(line, asset=None, subject_label=""):
    name = templates.LINES[line]["name"]
    if asset is not None:
        where = " ".join(x for x in (asset.locality, f"plot {asset.plot_number}" if asset.plot_number else "") if x)
        return f"{name}: {where}"
    return f"{name}: {subject_label}" if subject_label else name


# --------------------------------------------------------------------------- creating cases

def _create(*, country, line, client=None, asset=None, order=None, subject_type="", subject_id=None, title="",
            origin="order", origin_ref=None, parent_case=None, actor=None, case_manager=None) -> Case:
    cv = template_for(line, country)
    case = Case.objects.create(
        country=country, reference=next_reference(country), order=order, asset=asset, client=client,
        product_line=line, template_version=cv, title=title or _title_for(line, asset), subject_type=subject_type,
        subject_id=subject_id, origin=origin, origin_ref=origin_ref, parent_case=parent_case,
        case_manager=case_manager, risk_flag=bool(asset is not None and asset.disputed_flag))
    record(actor=actor, action="case.created", entity="case", entity_id=case.pk, country=country,
           data={"reference": case.reference, "product_line": line, "template_version_id": str(cv.pk),
                 "template_version": cv.version, "order_id": str(order.pk) if order else None,
                 "origin": origin})
    publish("case.created", case.pk, {**case_payload(case), "id": case.pk, "template_version_id": cv.pk,
                                      "template_version": cv.version})
    if order is not None:
        from orders.services import attach_case

        attach_case(order.pk, case.pk)
    return case


def _asset_for_order(order):
    """The order's geo_asset, created through GEO when the order has none yet."""
    from geo.models import Asset
    from geo.services import create_asset
    from orders.services import attach_asset

    if order.asset_id:
        asset = Asset.objects.filter(pk=order.asset_id).first()
        if asset:
            return asset
    if order.parent_order_id and order.parent_order.asset_id:
        asset = Asset.objects.filter(pk=order.parent_order.asset_id).first()
        if asset:
            attach_asset(order.pk, asset.pk)
            return asset
    asset = create_asset(actor=None, country=order.country, type=order.asset_type or "plot",
                         locality=order.locality or "Not given", owner=order.client, plot_number=order.plot_number,
                         site_plan_ref=order.site_plan_ref, ghana_post_gps=order.ghana_post_gps)
    attach_asset(order.pk, asset.pk)
    return asset


@transaction.atomic
def create_from_order(order_id, *, actor=None) -> Case | None:
    """FR-ORD-004, FR-CASE-001: a case exists only once its order is paid. Idempotent."""
    from orders import catalogue
    from orders.models import Order

    order = Order.objects.select_for_update(of=("self",)).select_related("country", "client", "parent_order").filter(
        pk=order_id).first()
    if order is None:
        raise NotFound("No such order.")
    existing = Case.objects.filter(order=order).first()
    if existing:
        return existing
    line = catalogue.product_line(order.kind, order.asset_type)
    if line not in ("land", "building", "fresh_search"):
        return None  # other lines open their own cases through open_case()
    if order.status != "paid":
        raise StateConflict("A case opens only when its order is paid (FR-ORD-004).",
                            extra={"order_status": order.status})
    asset = _asset_for_order(order)
    if line == "fresh_search":
        _require_verified(asset)
    case = _create(country=order.country, line=line, client=order.client, asset=asset, order=order,
                   origin="order", origin_ref=order.pk, actor=actor,
                   parent_case=Case.objects.filter(order_id=order.parent_order_id).first()
                   if order.parent_order_id else None)
    for ev in _order_documents(order):
        from evidence.services import link

        link(ev, "case", case.pk, role="client_document", by=None)
    post_status(case, None, "case_opened",
                "We received your order and payment on {date}. A case manager will start your case by {next_date}.",
                next_date=(_now() + timedelta(days=1)).date())
    if line == "fresh_search":
        case = accept(case, None)
    return case


def _order_documents(order):
    from evidence.selectors import for_subject

    return list(for_subject("order", order.pk))


def _require_verified(asset):
    """TC-CASE-014-02: a fresh search runs only on a plot a released report covers."""
    from reports.selectors import latest_released_for_asset

    if asset is None or (asset.verified_at is None and latest_released_for_asset(asset.pk) is None):
        raise StateConflict("A fresh search runs only on a plot with a released Tenmina report.",
                            code="asset-not-verified")


@transaction.atomic
def open_case(template_code, country, subject_type="", subject_id=None, client=None, *, asset=None, actor=None,
              title="", case_manager=None, origin="line", origin_ref=None, order=None) -> Case:
    """For other lines (FEE, PMG, EVT, PRJ, BLD, LST): start the verification case for a subject.
    The case starts in progress with its tasks created (ADR-21)."""
    flags.read_only_guard()
    if template_code not in templates.LINES:
        raise Invalid(f"'{template_code}' is not a case template.", code="validation-error")
    line = templates.LINES[template_code]
    if line["flag"]:
        flags.require(line["flag"], country)
    if line["needs_asset"] and asset is None:
        raise Invalid("This check needs the property it is about.", code="validation-error")
    if line["needs_order"] and order is None:
        raise Invalid("This case opens only from a paid order.", code="validation-error")
    if subject_id:
        existing = Case.objects.filter(product_line=template_code, subject_type=subject_type, subject_id=subject_id,
                                       status__in=["paid", "in_progress", "on_hold", "in_review"]).first()
        if existing:
            return existing
    case = _create(country=country, line=template_code, client=client, asset=asset, order=order,
                   subject_type=subject_type, subject_id=subject_id, title=title or _title_for(template_code, asset),
                   origin=origin, origin_ref=origin_ref or subject_id, actor=actor, case_manager=case_manager)
    return accept(case, actor)


@transaction.atomic
def open_fresh_search(asset, *, actor=None, order=None, origin="staff", origin_ref=None, reason="") -> Case:
    """FR-CASE-014: repeat the official search and a site check on a verified asset (RUL-07)."""
    flags.read_only_guard()
    if actor is not None and not has_role(actor, *STAFF, country=asset.country):
        raise Forbidden("Only a case manager starts a fresh search.")
    _require_verified(asset)
    open_one = Case.objects.filter(asset=asset, product_line="fresh_search",
                                   status__in=["paid", "in_progress", "on_hold"]).first()
    if open_one and origin_ref is None:
        return open_one
    parent = Case.objects.filter(asset=asset, product_line__in=["land", "building"], status="released") \
        .order_by("-closed_at").first()
    case = _create(country=asset.country, line="fresh_search", client=parent.client if parent else asset.owner,
                   asset=asset, order=order, origin=origin, origin_ref=origin_ref, parent_case=parent, actor=actor,
                   case_manager=actor)
    if reason:
        record(actor=actor, action="case.fresh_search_reason", entity="case", entity_id=case.pk,
               country=case.country, data={"reason": reason})
    return accept(case, actor)


# --------------------------------------------------------------------------- accepting (FR-CASE-002)

def _next_open_due(case, exclude=None):
    qs = case.tasks.filter(status__in=["open", "in_progress"])
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    t = qs.order_by("due_at").first()
    return t.due_at.date() if t else None


@transaction.atomic
def accept(case: Case, actor) -> Case:
    """Paid to in progress: the case manager accepts and the template's steps become tasks."""
    case = Case.objects.select_for_update().get(pk=case.pk)
    if actor is not None and case.origin == "order":
        _require_staff(actor, case, ("CM",), "Only a case manager accepts a case.")
    if case.status != "paid":
        raise StateConflict(f"Case {case.reference} has already been accepted.")
    steps = templates.validate(case.template_version.content)
    now = _now()
    for i, s in enumerate(steps, 1):
        Task.objects.create(
            case=case, country=case.country, step_key=s["key"], title=s["title"], position=i, owner_role=s["role"],
            due_at=now + timedelta(days=int(s.get("due_days") or 0)), required_evidence=list(s.get("evidence") or []),
            depends_on=list(s.get("after") or []), site_visit=bool(s.get("site_visit")),
            search_kind=s.get("search") or "", review_step=bool(s.get("review")),
            client_message=s.get("client_message") or "")
    case.accepted_at = now
    if actor is not None and case.case_manager_id is None and has_role(actor, "CM", country=case.country):
        case.case_manager = actor
    state.transition(case, "case", "in_progress", actor=actor,
                     payload=case_payload(case, notified=case.origin == "order") | {"status": "in_progress"},
                     extra_fields=["accepted_at", "case_manager"])
    if case.origin == "order":
        post_status(case, None, "case_started", "Your case started on {date}. Next update by {next_date}.")
    return case


# --------------------------------------------------------------------------- status messages (FR-CASE-007)

def _render(text, *, case, task=None, date=None, next_date=None):
    registry = _cfg(case.country, "land_registry.name", "registry") or "registry"
    values = {"date": f"{date:%d %B %Y}" if date else "", "next_date": f"{next_date:%d %B %Y}" if next_date else "",
              "registry": registry, "title": task.title if task else case.title, "reference": case.reference}
    if not next_date:
        # Never a blank date: drop the sentence that would hold it.
        text = re.sub(r"[^.]*\{next_date\}[^.]*\.?", "", text).strip()
    out = text
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return re.sub(r"\s+", " ", out).strip()


def post_status(case, task, key, text=None, *, actor=None, next_date=None, notify_client=True) -> StatusMessage:
    today = timezone.localdate()
    nd = next_date if next_date is not None else _next_open_due(case, exclude=task)
    if not text:
        text = templates.GENERIC_MESSAGE
        _alert(case.country, ("CM",), subject=f"No client message for step '{key}'",
               body=f"Step '{key}' on case {case.reference} has no client message in its template. The client saw "
                    "a default message. Add one to the template.", obj=case, link=_case_link(case))
    msg = StatusMessage.objects.create(case=case, country=case.country, task=task, template_key=key,
                                       text=_render(text, case=case, task=task, date=today, next_date=nd),
                                       message_date=today, next_expected_date=nd, created_by=actor)
    if notify_client and case.client_id:
        _notify(case.client, "case_status_changed", subject=f"Case {case.reference}", body=msg.text, obj=case,
                link=_case_link(case), channels="preferred",
                context={"case_ref": case.reference, "status_label": _status_label(case)})
    return msg


def _status_label(case):
    return {"paid": "Opened", "in_progress": "In progress", "on_hold": "On hold", "in_review": "In review",
            "released": "Report released", "completed": "Finished", "cancelled": "Cancelled"}[case.status]


# --------------------------------------------------------------------------- tasks (FR-CASE-003 to 006)

def waiting_for(task) -> list[str]:
    if not task.depends_on:
        return []
    done = set(task.case.tasks.filter(step_key__in=task.depends_on, status__in=["done", "cancelled"])
               .values_list("step_key", flat=True))
    return [k for k in task.depends_on if k not in done]


def latest_risk_screen(task):
    return task.risk_screens.order_by("-created_at").first()


def _valid_screen(task):
    s = latest_risk_screen(task)
    if s is None or s.valid_until < _now() or s.outcome == "do_not_visit":
        return None
    return s


def _disputed(case) -> bool:
    from geo.selectors import is_disputed

    return bool(case.risk_flag or (case.asset_id and is_disputed(case.asset_id)))


def visit_blockers(task, assignee, second) -> list[dict]:
    """FR-CASE-009, RUL-17: a risk screen before any site visit; two people on a disputed plot."""
    if not task.site_visit:
        return []
    out = []
    screen = latest_risk_screen(task)
    if screen is None or screen.valid_until < _now():
        out.append({"rule": "RUL-17", "message": "Record a risk screen for this site visit first."})
        return out
    if screen.outcome == "do_not_visit":
        out.append({"rule": "RUL-17", "message": "The risk screen says no one should visit. Record a new screen."})
        return out
    disputed = _disputed(task.case)
    need = max(screen.people_required, 2 if disputed else 1)
    if disputed and not screen.disputed_at_screen:
        out.append({"rule": "RUL-17", "message": "The plot was flagged as disputed after the risk screen. Record a "
                                                 "new screen."})
    people = len([p for p in (assignee, second) if p is not None])
    if people < need:
        out.append({"rule": "RUL-17", "message": f"This visit needs at least {need} people. Assign a second person."})
    return out


def _check_assignee(task, person, *, second=False):
    case = task.case
    if second:
        if not person.has_tenmina_role(*FIELD_ROLES, country=case.country):
            raise Invalid(f"{person.full_name} is not a Tenmina field professional.", code="wrong-role")
        role = task.owner_role if person.has_tenmina_role(task.owner_role, country=case.country) else None
    else:
        if not person.has_tenmina_role(task.owner_role, country=case.country):
            raise Invalid(f"This step needs a person with the role {task.owner_role}. {person.full_name} does not "
                          "hold it.", code="wrong-role")
        role = task.owner_role
    if role in LICENSED:
        from accounts.services import require_valid_licence

        require_valid_licence(person, role)  # RUL-20
    _require_pay_agreement(person, role, case.country)


def _require_pay_agreement(person, role, country):
    """US-PRO-001 AC1: work is assigned only to a professional with a signed, active agreement with Tenmina and
    a verified pay account (PRO), so every assignment can be paid from Tenmina's own account (RUL-27)."""
    from profpay.models import CODE_FOR_ROLE
    from profpay.selectors import assignment_blockers

    pro_roles = set(CODE_FOR_ROLE.values())
    codes = [role] if role in pro_roles else [r for r in sorted(pro_roles) if person.has_tenmina_role(r, country=country)]
    for code in codes[:1]:
        reasons = assignment_blockers(person, code, country)
        if reasons:
            raise RuleBlocked(f"{person.full_name} cannot be given this work yet: {reasons[0]['message']}",
                              code="no-pro-agreement", blocking_reasons=reasons)


def _grant_asset_access(task, person, actor):
    from geo.models import AssetAccess
    from geo.services import grant_access

    case = task.case
    if case.asset_id is None or person is None:
        return
    roles = [r for r in AssetAccess.ROLES if person.has_tenmina_role(r, country=case.country)]
    role = task.owner_role if task.owner_role in roles else (roles[0] if roles else None)
    if role:
        grant_access(case.asset, person, role=role, actor=actor, case_id=case.pk)


def _revoke_asset_access(case, person, actor):
    """Access ends when the person has no open task left on the case."""
    from geo.models import AssetAccess
    from geo.services import revoke_access

    if person is None:
        return
    if case.tasks.filter(status__in=["open", "in_progress"]).filter(
            Q(assignee=person) | Q(second_assignee=person)).exists():
        return
    for g in AssetAccess.objects.filter(case_id=case.pk, person=person, revoked_at__isnull=True):
        revoke_access(g, actor=actor)


_UNSET = object()


@transaction.atomic
def assign_task(task: Task, actor, *, assignee=_UNSET, second_assignee=_UNSET) -> Task:
    """FR-CASE-003: assign a named person with the right role (and a valid licence, RUL-20)."""
    flags.read_only_guard()
    task = Task.objects.select_for_update().select_related("case", "case__country").get(pk=task.pk)
    case = task.case
    _require_staff(actor, case, msg="Only a case manager or reviewer assigns tasks.")
    _require_open(case)
    if task.status in ("done", "cancelled"):
        raise StateConflict("This task is finished.")
    old = {"assignee": task.assignee_id, "second_assignee": task.second_assignee_id}
    new_a = task.assignee if assignee is _UNSET else assignee
    new_b = task.second_assignee if second_assignee is _UNSET else second_assignee
    if new_a is None and new_b is not None:
        raise Invalid("Assign the main person first.")
    if new_a is not None and new_b is not None and new_a.pk == new_b.pk:
        raise Invalid("The second person must be someone else.", code="same-person")
    if assignee is not _UNSET and new_a is not None:
        _check_assignee(task, new_a)
    if second_assignee is not _UNSET and new_b is not None:
        _check_assignee(task, new_b, second=True)
    if new_a is not None:
        blockers = visit_blockers(task, new_a, new_b)
        if blockers:
            raise RuleBlocked("This site visit cannot be assigned yet. No one is sent into danger.",
                              code="visit-not-safe", blocking_reasons=blockers)
    task.assignee, task.second_assignee = new_a, new_b
    task.assigned_at, task.assigned_by = (_now(), actor) if new_a is not None else (None, None)
    task.save(update_fields=["assignee", "second_assignee", "assigned_at", "assigned_by"])
    record(actor=actor, action="task.assigned", entity="task", entity_id=task.pk, country=case.country,
           data={"old": {k: str(v) if v else None for k, v in old.items()},
                 "new": {"assignee": str(new_a.pk) if new_a else None,
                         "second_assignee": str(new_b.pk) if new_b else None}})
    for person in {new_a, new_b} - {None}:
        if person.pk not in old.values():
            _grant_asset_access(task, person, actor)
            _notify(person, "task_assigned", subject=f"New task: {task.title}", obj=task,
                    link=f"/tasks/{task.pk}", channels="preferred",
                    context={"task_title": task.title, "case_ref": case.reference,
                             "due_date": f"{task.due_at:%d %B %Y}"},
                    body=f"You have a new task on case {case.reference}: {task.title}. It is due on "
                         f"{task.due_at:%d %B %Y}.")
    from accounts.models import Person

    for pid in set(old.values()) - {getattr(new_a, "pk", None), getattr(new_b, "pk", None), None}:
        _revoke_asset_access(case, Person.objects.get(pk=pid), actor)
    # cases tells each new assignee itself (above), so NTF is told not to repeat it ("notified").
    publish("task.assigned", task.pk, {"task_id": task.pk, "case_id": case.pk, "step_key": task.step_key, "notified": True,
                                       "role": task.owner_role, "assignee_id": getattr(new_a, "pk", None),
                                       "second_assignee_id": getattr(new_b, "pk", None),
                                       "assigned_at": task.assigned_at, "country": case.country.code})
    return task


@transaction.atomic
def change_due(task: Task, actor, due_at, reason: str) -> Task:
    """FR-CASE-003: a due date changes only with a reason; old, new and reason are audited."""
    flags.read_only_guard()
    _require_staff(actor, task.case, msg="Only a case manager or reviewer changes due dates.")
    if not (reason or "").strip():
        raise Invalid("Give the reason for the new due date.",
                      extra={"errors": [{"pointer": "/reason", "message": "Required."}]})
    if task.status in ("done", "cancelled"):
        raise StateConflict("This task is finished.")
    old = task.due_at
    task.due_at, task.due_change_reason, task.overdue_alerted_at = due_at, reason.strip(), None
    task.save(update_fields=["due_at", "due_change_reason", "overdue_alerted_at"])
    record(actor=actor, action="task.due_changed", entity="task", entity_id=task.pk, country=task.case.country,
           data={"old_due_at": old, "new_due_at": due_at, "reason": reason.strip()})
    return task


def can_work_on(user, task) -> bool:
    return bool(user and user.is_authenticated and (
        user.pk in (task.assignee_id, task.second_assignee_id) or is_case_staff(user, task.case)))


@transaction.atomic
def attach_task_evidence(task: Task, actor, evidence, kind: str):
    """FR-CASE-006: evidence for a task, e.g. a receipt photographed in the phone browser.
    RUL-30: an official search result is never attached here; a copy is kept only as 'not evidence'."""
    from evidence.services import link

    if not can_work_on(actor, task):
        raise NotFound("Task not found.")
    kind = (kind or "").strip()
    if kind in ("official_search_result", "search_result"):
        raise Invalid("Search results come from Tenmina's office, not from the field. Keep a copy you were given "
                      "as 'search_copy_unverified'; it is not evidence.", code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-30", "message": "Official search results are received only "
                                                                      "from the registry's channel by Tenmina staff."}],
                      extra={"reason": "not_official_channel"})
    allowed = set(task.required_evidence) | {"supporting", "search_copy_unverified"}
    if kind not in allowed:
        raise Invalid(f"This task takes: {', '.join(sorted(allowed))}.")
    if task.status in ("done", "cancelled"):
        raise StateConflict("This task is finished.")
    lk = link(evidence, "task", task.pk, role=kind, by=actor)
    if kind == "search_copy_unverified":
        _note_search_copy(task.case, evidence, actor)
    return lk


def missing_evidence(task) -> list[str]:
    from evidence.selectors import has_role_evidence

    return [k for k in task.required_evidence if not has_role_evidence("task", task.pk, k)]


def task_blockers(task) -> list[dict]:
    out = []
    for k in waiting_for(task):
        out.append({"rule": "FR-CASE-002", "message": f"Waiting for step '{k}'."})
    for k in missing_evidence(task):
        out.append({"rule": "FR-CASE-004", "message": f"Missing evidence: {k.replace('_', ' ')}."})
    if task.search_kind == "lodge" and not task.case.search_requests.exclude(status="rejected").exists():
        out.append({"rule": "RUL-30", "message": "Record the official search lodged from Tenmina's registry account."})
    if task.search_kind == "result" and not any(sr.usable for sr in _requests_for_result_task(task)):
        out.append({"rule": "RUL-30", "message": "No search result received from the registry's own channel yet."})
    return out


def _requests_for_result_task(task):
    qs = task.case.search_requests.exclude(status="rejected")
    if task.step_key == "fresh_search":
        qs = qs.filter(task=task)
    return list(qs)


@transaction.atomic
def complete_task(task: Task, actor, *, note="", system=False) -> Task:
    """FR-CASE-004: a task is done only when its required evidence is attached and the step is not waiting."""
    flags.read_only_guard()
    task = Task.objects.select_for_update().select_related("case", "case__country").get(pk=task.pk)
    case = task.case
    if not system:
        if not can_work_on(actor, task):
            raise NotFound("Task not found.")
        if task.review_step:
            raise StateConflict("This step is done by the review and release, not by hand.")
        if case.status not in ("in_progress",):
            raise StateConflict(f"Case {case.reference} is {case.status.replace('_', ' ')}.")
    if task.status == "done":
        return task
    if task.status == "cancelled":
        raise StateConflict("This task was cancelled.")
    blockers = task_blockers(task)
    if blockers:
        missing = [b["message"] for b in blockers]
        raise DomainError("This task cannot be marked done yet: " + " ".join(missing), code="task-incomplete",
                          status=409, blocking_reasons=blockers)
    task.completed_at, task.completed_by = _now(), (None if system else actor)
    task.note = note or task.note
    state.transition(task, "task", "done", actor=actor, event="task.completed",
                     payload={"task_id": task.pk, "case_id": case.pk, "step_key": task.step_key,
                              "role": task.owner_role, "assignee_id": task.assignee_id,
                              "second_assignee_id": task.second_assignee_id, "assigned_at": task.assigned_at,
                              "completed_at": task.completed_at, "site_visit": task.site_visit,
                              "country": case.country.code},
                     extra_fields=["completed_at", "completed_by", "note"])
    post_status(case, task, task.step_key, task.client_message or None, actor=actor)
    for p in (task.assignee, task.second_assignee):
        _revoke_asset_access(case, p, actor)
    _after_task(case)
    return task


def _after_task(case):
    if case.status != "in_progress":
        return
    open_work = case.tasks.filter(status__in=["open", "in_progress"], review_step=False).exists()
    if open_work:
        return
    if case.product_line == "fresh_search":
        _finish_fresh_search(case)
    elif not case.has_report:
        _alert(case.country, ("RV",), subject=f"Case {case.reference} is ready for a decision",
               body=f"Every check on case {case.reference} is done. Record whether it is verified.", obj=case,
               link=_case_link(case))


@transaction.atomic
def start_task(task: Task, actor) -> Task:
    if actor is None or actor.pk not in (task.assignee_id, task.second_assignee_id):
        raise NotFound("Task not found.")
    blockers = [b for b in task_blockers(task) if b["rule"] == "FR-CASE-002"]
    if task.site_visit:
        blockers += visit_blockers(task, task.assignee, task.second_assignee)
    if blockers:
        raise RuleBlocked("This task cannot start yet.", code="task-waiting", blocking_reasons=blockers)
    return state.transition(task, "task", "in_progress", actor=actor, event="task.started",
                            payload={"task_id": task.pk, "case_id": task.case_id})


def try_complete_from_field(task_id, person):
    """A Tenmina Field submission for a case task: close it when everything it needs is there."""
    task = Task.objects.filter(pk=task_id).first()
    if task is None or task.status in ("done", "cancelled"):
        return None
    try:
        with transaction.atomic():
            return complete_task(task, person, note="Submitted from Tenmina Field")
    except DomainError as exc:
        log.info("field submission did not close task %s: %s", task_id, exc.detail)
        return None


def mark_overdue(now=None) -> int:
    """Job cases.task_overdue (daily): publish task.overdue once and tell the owner and the case manager."""
    now = now or _now()
    n = 0
    for t in Task.objects.filter(status__in=["open", "in_progress"], due_at__lt=now, overdue_alerted_at__isnull=True,
                                 case__status__in=["in_progress", "in_review"]).select_related("case", "assignee"):
        t.overdue_alerted_at = now
        t.save(update_fields=["overdue_alerted_at"])
        publish("task.overdue", t.pk, {"task_id": t.pk, "case_id": t.case_id, "step_key": t.step_key,
                                       "assignee_id": t.assignee_id, "due_at": t.due_at})
        ctx = {"task_title": t.title, "case_ref": t.case.reference, "due_date": f"{t.due_at:%d %B %Y}"}
        for p in {t.assignee, t.case.case_manager} - {None}:
            _notify(p, "task_overdue", subject=f"Overdue: {t.title}", obj=t, link=f"/tasks/{t.pk}", context=ctx,
                    body=f"The task '{t.title}' on case {t.case.reference} was due on {t.due_at:%d %B %Y}.")
        n += 1
    return n


# --------------------------------------------------------------------------- risk screens (FR-CASE-009, RUL-17)

@transaction.atomic
def record_risk_screen(case: Case, actor, *, task, outcome, hazards="", people_required=1, valid_days=None,
                       notes="") -> RiskScreen:
    flags.read_only_guard()
    _require_staff(actor, case, msg="Only a case manager or reviewer records a risk screen.")
    _require_open(case)
    if task.case_id != case.pk or not task.site_visit:
        raise Invalid("A risk screen is recorded for a site visit task on this case.")
    if outcome not in RiskScreen.OUTCOMES:
        raise Invalid(f"Outcome must be one of {', '.join(RiskScreen.OUTCOMES)}.")
    disputed = _disputed(case)
    people_required = int(people_required or 1)
    if outcome == "proceed_with_two":
        people_required = max(people_required, 2)
    if disputed and outcome != "do_not_visit" and people_required < 2:
        raise RuleBlocked("This plot is flagged as disputed. A visit needs at least two people.",
                          code="visit-not-safe",
                          blocking_reasons=[{"rule": "RUL-17", "message": "Disputed plot: two people at least."}])
    days = int(valid_days or _cfg(case.country, "case.risk_screen_valid_days", DEFAULT_RISK_SCREEN_DAYS))
    screen = RiskScreen.objects.create(case=case, country=case.country, task=task, screened_by=actor,
                                       outcome=outcome, hazards=hazards, people_required=people_required,
                                       disputed_at_screen=disputed, valid_until=_now() + timedelta(days=days),
                                       notes=notes)
    record(actor=actor, action="risk_screen.recorded", entity="task", entity_id=task.pk, country=case.country,
           data={"screen_id": str(screen.pk), "outcome": outcome, "people_required": people_required,
                 "disputed": disputed})
    publish("risk_screen.recorded", screen.pk, {"screen_id": screen.pk, "task_id": task.pk, "case_id": case.pk,
                                                "outcome": outcome})
    return screen


@transaction.atomic
def recheck_disputed(asset_id, *, actor=None) -> list[Task]:
    """TC-RUL-17-04: a plot flagged disputed after a visit was assigned. Assignments that no longer meet
    RUL-17 are taken back until a new screen and a second person are recorded."""
    out = []
    Case.objects.filter(asset_id=asset_id, status__in=["paid", "in_progress", "on_hold"]).update(risk_flag=True)
    for t in Task.objects.filter(case__asset_id=asset_id, site_visit=True, status__in=["open", "in_progress"],
                                 assignee__isnull=False).select_related("case", "assignee", "second_assignee"):
        if not visit_blockers(t, t.assignee, t.second_assignee):
            continue
        people = [t.assignee, t.second_assignee]
        t.assignee = t.second_assignee = None
        t.assigned_at = t.assigned_by = None
        t.save(update_fields=["assignee", "second_assignee", "assigned_at", "assigned_by"])
        if t.status == "in_progress":
            state.transition(t, "task", "open", actor=actor, reason="Plot flagged as disputed (RUL-17)")
        record(actor=actor, action="task.unassigned_for_safety", entity="task", entity_id=t.pk, country=t.country,
               data={"reason": "RUL-17: plot flagged as disputed after assignment"})
        for p in people:
            _revoke_asset_access(t.case, p, actor)
            _notify(p, "generic", subject="Site visit on hold", obj=t, link=f"/tasks/{t.pk}", category="safety",
                    body=f"The visit '{t.title}' on case {t.case.reference} is on hold: the plot is now flagged as "
                         "disputed. Do not go until a new risk screen is done.")
        _alert(t.country, ("CM",), subject=f"Disputed plot: re-screen the visit on {t.case.reference}",
               body="The plot was flagged as disputed. Record a new risk screen and assign two people.", obj=t,
               link=_case_link(t.case), category="safety")
        out.append(t)
    return out


# --------------------------------------------------------------------------- safety incidents (FR-CASE-010)

def is_safety_reader(user, country=None) -> bool:
    if not user or not user.is_authenticated:
        return False
    qs = SafetyReader.objects.filter(person=user, revoked_at__isnull=True)
    if country is not None:
        qs = qs.filter(Q(country__isnull=True) | Q(country=country))
    return qs.exists()


@transaction.atomic
def log_safety_incident(*, actor, country, occurred_at, severity, narrative, case=None, subject_type="case",
                        subject_id=None, persons_named="", location_note="") -> SafetyIncident:
    """Write only. Goes to the restricted log in schema `safety`; the case manager and the safety
    readers are alerted with no details (FR-CASE-010, 02 10.9)."""
    if case is not None:
        if not (is_case_staff(actor, case) or (is_assigned(actor, case)
                                                 and actor.has_tenmina_role(*INCIDENT_ROLES, country=case.country))):
            raise NotFound("Case not found.")
        country = case.country
    elif not has_role(actor, *INCIDENT_ROLES, country=country):
        raise Forbidden("Only Tenmina staff and field professionals log safety incidents.")
    if severity not in SafetyIncident.SEVERITIES:
        raise Invalid(f"Severity must be one of {', '.join(SafetyIncident.SEVERITIES)}.")
    if not (narrative or "").strip():
        raise Invalid("Say what happened.", extra={"errors": [{"pointer": "/narrative", "message": "Required."}]})
    inc = SafetyIncident.objects.create(
        id=uuid7(), case_id=case.pk if case else None, country_code=country.code,
        subject_type=subject_type if case is None else "case", subject_id=subject_id or (case.pk if case else None),
        reported_by=actor.pk, occurred_at=occurred_at or _now(), severity=severity, narrative=narrative.strip(),
        persons_named=persons_named or "", location_note=location_note or "")
    record(actor=actor, action="safety_incident.logged", entity="safety_incident", entity_id=inc.pk, country=country,
           data={"case_id": str(case.pk) if case else None, "severity": severity})  # no narrative in the audit log
    publish("safety_incident.logged", inc.pk, {"incident_id": inc.pk, "case_id": case.pk if case else None,
                                               "severity": severity, "country": country.code})
    if case is not None and severity in ("high", "critical") and not case.risk_flag:
        case.risk_flag = True
        case.save(update_fields=["risk_flag"])
    body = (f"A {severity} safety incident was logged{f' on case {case.reference}' if case else ''}. "
            "Open the safety log for details.")
    told = set()
    targets = [case.case_manager] if case is not None and case.case_manager else list(_staff_people(country, "CM"))
    for r in SafetyReader.objects.filter(revoked_at__isnull=True).filter(
            Q(country__isnull=True) | Q(country=country)).select_related("person"):
        targets.append(r.person)
    for p in targets:
        if p and p.pk not in told:
            told.add(p.pk)
            _notify(p, "generic", subject="Safety incident logged", body=body, category="safety",
                    link="/safety-incidents")
    return inc


def read_incidents(user, *, case=None, country=None):
    """Only people individually granted safety.read; every read is audited (02 10.9)."""
    if not is_safety_reader(user, country or (case.country if case else None)):
        raise NotFound("Not found.")
    qs = SafetyIncident.objects.all().order_by("-occurred_at")
    if case is not None:
        qs = qs.filter(case_id=case.pk)
    if country is not None:
        qs = qs.filter(country_code=country.code)
    readers = SafetyReader.objects.filter(person=user, revoked_at__isnull=True)
    if not readers.filter(country__isnull=True).exists():
        qs = qs.filter(country_code__in=list(readers.values_list("country__code", flat=True)))
    items = list(qs[:200])
    record(actor=user, action="safety_incident.read", entity="safety_log", entity_id=case.pk if case else uuid7(),
           data={"count": len(items), "case_id": str(case.pk) if case else None})
    return items


@transaction.atomic
def grant_safety_read(by, person, *, country=None, reason="") -> SafetyReader:
    if not has_role(by, "AD"):
        raise Forbidden("Only an administrator grants access to the safety log.")
    if not has_role(person, "CM", "RV"):
        raise Invalid("Only a case manager or reviewer can be named to read the safety log.")
    existing = SafetyReader.objects.filter(person=person, country=country, revoked_at__isnull=True).first()
    if existing:
        return existing
    r = SafetyReader.objects.create(person=person, country=country, granted_by=by, reason=reason)
    record(actor=by, action="safety_read.granted", entity="person", entity_id=person.pk,
           data={"country": getattr(country, "code", None), "reason": reason})
    return r


@transaction.atomic
def revoke_safety_read(by, reader: SafetyReader, reason="") -> SafetyReader:
    if not has_role(by, "AD"):
        raise Forbidden("Only an administrator removes access to the safety log.")
    if reader.revoked_at is None:
        reader.revoked_at, reader.revoked_by = _now(), by
        reader.save(update_fields=["revoked_at", "revoked_by"])
        record(actor=by, action="safety_read.revoked", entity="person", entity_id=reader.person_id,
               data={"reason": reason})
    return reader


# --------------------------------------------------------------------------- document requests (FR-CASE-008)

@transaction.atomic
def request_document(case: Case, actor, *, title, description="", due_on=None) -> DocumentRequest:
    flags.read_only_guard()
    _require_staff(actor, case, msg="Only a case manager or reviewer asks the client for documents.")
    _require_open(case)
    if not (title or "").strip():
        raise Invalid("Say which document you need.", extra={"errors": [{"pointer": "/title", "message": "Required."}]})
    if case.client_id is None:
        raise StateConflict("This case has no client to ask.")
    req = DocumentRequest.objects.create(case=case, country=case.country, title=title.strip(),
                                         description=description or "", due_on=due_on, requested_by=actor)
    record(actor=actor, action="document_request.created", entity="case", entity_id=case.pk, country=case.country,
           data={"request_id": str(req.pk), "title": req.title})
    publish("case.document_requested", req.pk, {"request_id": req.pk, "case_id": case.pk,
                                                "client_id": case.client_id})
    _notify(case.client, "request_received", subject=f"We need a document for case {case.reference}",
            body=f"Please upload: {req.title}." + (f" {req.description}" if req.description else ""),
            obj=req, link=f"{_case_link(case)}/document-requests/{req.pk}", needs_action=True, channels="preferred",
            context={"case_ref": case.reference, "request_label": req.title})
    return req


@transaction.atomic
def respond_document_request(req: DocumentRequest, actor, evidence) -> DocumentRequest:
    """Only the client answers; a representative has read-only access (TC-CASE-008-02)."""
    from evidence.services import link
    from notifications.services import resolve_action

    req = DocumentRequest.objects.select_for_update().select_related("case").get(pk=req.pk)
    case = req.case
    if not is_client(actor, case):
        if is_representative(actor, case):
            raise Forbidden("A representative can see the case but only the client can send documents.")
        raise NotFound("Not found.")
    if req.status != "open":
        raise StateConflict("This request is already closed.")
    link(evidence, "case", case.pk, role="client_document", by=actor)
    req.received_at, req.received_evidence, req.responded_by = _now(), evidence, actor
    state.transition(req, "document_request", "received", actor=actor, event="case.document_received",
                     payload={"request_id": req.pk, "case_id": case.pk, "evidence_id": evidence.pk},
                     extra_fields=["received_at", "received_evidence", "responded_by"])
    resolve_action(req)
    _notify(req.requested_by, "generic", subject=f"Document received on {case.reference}",
            body=f"The client sent '{req.title}' for case {case.reference}.", obj=case, link=_case_link(case))
    return req


@transaction.atomic
def cancel_document_request(req: DocumentRequest, actor, reason) -> DocumentRequest:
    from notifications.services import resolve_action

    _require_staff(actor, req.case)
    if not (reason or "").strip():
        raise Invalid("Give a reason.")
    req.cancel_reason = reason.strip()
    state.transition(req, "document_request", "cancelled", actor=actor, reason=reason,
                     extra_fields=["cancel_reason"])
    resolve_action(req)
    return req


# --------------------------------------------------------------------------- messages (FR-CASE-015)

@transaction.atomic
def post_message(case: Case, actor, body: str) -> Message:
    flags.read_only_guard()
    if not (body or "").strip():
        raise Invalid("Write a message.")
    if is_client(actor, case):
        side = "client"
    elif is_case_staff(actor, case):
        side = "tenmina"
    elif is_representative(actor, case):
        raise Forbidden("A representative can read the case but cannot send messages.")
    else:
        raise NotFound("Case not found.")
    msg = Message.objects.create(case=case, country=case.country, sender=actor, side=side, body=body.strip())
    publish("case.message_posted", msg.pk, {"message_id": msg.pk, "case_id": case.pk, "side": side})
    if side == "client":
        targets = [case.case_manager] if case.case_manager else list(_staff_people(case.country, "CM"))
        for p in targets:
            _notify(p, "generic", subject=f"New message on case {case.reference}", obj=case, link=_case_link(case),
                    body=f"{actor.full_name} wrote on case {case.reference}: {msg.body[:300]}")
    else:
        # US-CASE-015 AC2: SMS and WhatsApp carry only the template text, never the message.
        _notify(case.client, "generic", subject=f"New message about case {case.reference}", obj=case,
                link=_case_link(case), channels="preferred", body=msg.body)
    return msg


# --------------------------------------------------------------------------- costs (FR-CASE-011, FR-PRO-010)

@transaction.atomic
def add_cost(case: Case, *, item_type, amount, currency, incurred_on=None, description="", actor=None,
             source="manual", source_id=None) -> CostItem:
    if source == "manual":
        if actor is None or not is_case_staff(actor, case, ("CM", "RV")):
            raise Forbidden("Only a case manager records case costs.")
    elif source not in CostItem.SOURCES:
        raise Invalid("Unknown cost source.")
    if source_id is not None:
        existing = CostItem.objects.filter(source=source, source_id=source_id).first()
        if existing:
            return existing
    if item_type not in CostItem.ITEM_TYPES:
        raise Invalid(f"Item must be one of {', '.join(CostItem.ITEM_TYPES)}.")
    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount < 0:
        raise Invalid("A cost cannot be negative.")
    if not currency or len(str(currency)) != 3:
        raise Invalid("Give the currency as a three-letter code.")
    item = CostItem.objects.create(case=case, country=case.country, item_type=item_type, amount=amount,
                                   currency=str(currency).upper(), incurred_on=incurred_on or timezone.localdate(),
                                   description=description or "", source=source, source_id=source_id,
                                   recorded_by=actor)
    record(actor=actor, action="case.cost_added", entity="case", entity_id=case.pk, country=case.country,
           data={"item_type": item_type, "amount": amount, "currency": item.currency, "source": source})
    return item


# --------------------------------------------------------------------------- hold, resume, cancel (FR-CASE-012)

@transaction.atomic
def hold(case: Case, actor, reason: str, client_message: str = "") -> Case:
    flags.read_only_guard()
    _require_staff(actor, case, ("CM",), "Only a case manager pauses a case.")
    if not (reason or "").strip():
        raise Invalid("Give the reason for the pause.", extra={"errors": [{"pointer": "/reason",
                                                                          "message": "Required."}]})
    case.hold_reason = reason.strip()
    state.transition(case, "case", "on_hold", actor=actor, reason=case.hold_reason,
                     payload=case_payload(case, notified=True) | {"status": "on_hold"}, extra_fields=["hold_reason"])
    post_status(case, None, "on_hold", client_message or "Your case is on hold from {date}: " + case.hold_reason
                + ". Your case manager will tell you when it starts again.", actor=actor, next_date=None)
    return case


@transaction.atomic
def resume(case: Case, actor) -> Case:
    _require_staff(actor, case, ("CM",), "Only a case manager resumes a case.")
    case.hold_reason = ""
    state.transition(case, "case", "in_progress", actor=actor,
                     payload=case_payload(case, notified=True) | {"status": "in_progress"}, extra_fields=["hold_reason"])
    post_status(case, None, "resumed", "Your case started again on {date}. Next update by {next_date}.", actor=actor)
    return case


@transaction.atomic
def cancel(case: Case, actor, reason: str, refund_decision: str, refund_amount=None) -> Case:
    """Any state before released: cancel with a reason and a refund decision (PAY's refund, FR-PAY-004)."""
    flags.read_only_guard()
    _require_staff(actor, case, ("CM",), "Only a case manager cancels a case.")
    if case.status in ("released", "completed", "cancelled"):
        raise StateConflict(f"A {case.status} case cannot be cancelled.")
    if not (reason or "").strip():
        raise Invalid("Give the reason for the cancellation.")
    if refund_decision not in ("refund", "no_refund"):
        raise Invalid("Decide whether the fee is refunded: refund or no_refund.",
                      extra={"errors": [{"pointer": "/refund_decision", "message": "Required."}]})
    if refund_decision == "refund":
        if case.order_id is None:
            raise Invalid("This case has no fee order to refund.")
        from payments.services import request_refund_for_order

        refund = request_refund_for_order(actor, case.order_id, amount=refund_amount,
                                          reason=f"Case {case.reference} cancelled: {reason.strip()}")
        case.refund_id = refund.pk
    case.cancel_reason, case.refund_decision, case.closed_at = reason.strip(), refund_decision, _now()
    _close_work(case, actor, "Case cancelled")
    state.transition(case, "case", "cancelled", actor=actor, reason=case.cancel_reason,
                     payload=case_payload(case, notified=True) | {"status": "cancelled", "refund_decision": refund_decision},
                     extra_fields=["cancel_reason", "refund_decision", "refund_id", "closed_at"])
    post_status(case, None, "cancelled", "Your case was cancelled on {date}."
                + (" Your fee will be refunded to the way you paid." if refund_decision == "refund" else ""),
                actor=actor, next_date=None)
    return case


def _close_work(case, actor, why):
    from geo.services import revoke_case_access
    from notifications.services import resolve_action

    for t in case.tasks.filter(status__in=["open", "in_progress"]):
        state.transition(t, "task", "cancelled", actor=actor, reason=why)
    for r in case.document_requests.filter(status="open"):
        r.cancel_reason = why
        state.transition(r, "document_request", "cancelled", actor=actor, reason=why, extra_fields=["cancel_reason"])
        resolve_action(r)
    revoke_case_access(case.pk, actor=actor)


# --------------------------------------------------------------------------- verification decision (line cases)

@transaction.atomic
def decide_verification(case: Case, actor, *, outcome, note="") -> Case:
    """Institution, property, vendor, supplier, contractor and developer checks end with a reviewer's
    decision once every check is done. Line modules react to case.status_changed with the outcome."""
    flags.read_only_guard()
    case = Case.objects.select_for_update().get(pk=case.pk)
    _require_staff(actor, case, ("RV",), "Only a reviewer records the verification decision.")
    if case.has_report or case.product_line == "fresh_search":
        raise StateConflict("This case ends with its report, not a decision.")
    if case.status != "in_progress":
        raise StateConflict(f"Case {case.reference} is {case.status.replace('_', ' ')}.")
    if outcome not in ("verified", "not_verified"):
        raise Invalid("Outcome must be verified or not_verified.")
    if outcome == "not_verified" and not (note or "").strip():
        raise Invalid("Say why it is not verified.")
    open_work = case.tasks.filter(status__in=["open", "in_progress"], review_step=False)
    if open_work.exists():
        raise DomainError("Every check must be done first.", code="task-incomplete", status=409,
                          blocking_reasons=[{"rule": "FR-CASE-002", "message": f"Open: {t.title}"} for t in open_work])
    for t in case.tasks.filter(status__in=["open", "in_progress"], review_step=True):
        t.completed_at, t.completed_by = _now(), actor
        state.transition(t, "task", "done", actor=actor, event="task.completed",
                         payload={"task_id": t.pk, "case_id": case.pk, "step_key": t.step_key},
                         extra_fields=["completed_at", "completed_by"])
    case.outcome, case.outcome_note, case.decided_by, case.closed_at = outcome, note or "", actor, _now()
    state.transition(case, "case", "completed", actor=actor,
                     payload=case_payload(case, notified=True) | {"status": "completed"},
                     extra_fields=["outcome", "outcome_note", "decided_by", "closed_at"])
    from geo.services import revoke_case_access

    revoke_case_access(case.pk, actor=actor)
    if case.client_id:
        post_status(case, None, "decision", "The check was finished on {date}: " +
                    ("verified." if outcome == "verified" else "not verified. Your case manager will explain."),
                    actor=actor, next_date=None)
    return case


def _finish_fresh_search(case):
    sr = (case.search_requests.filter(status__in=["result_received", "confirmed"]).order_by("-registry_result_date")
          .first())
    site = case.tasks.filter(step_key="site_check", status="done").first()
    if sr is None or not sr.usable or site is None:
        return
    case.outcome, case.closed_at = "verified", _now()
    state.transition(case, "case", "completed", payload=case_payload(case) | {"status": "completed"},
                     extra_fields=["outcome", "closed_at"])
    publish("fresh_search.completed", case.pk, {
        "case_id": case.pk, "asset_id": case.asset_id, "order_id": case.order_id, "parent_case_id": case.parent_case_id,
        "search_request_id": sr.pk, "registry_result_date": sr.registry_result_date,
        "site_check_date": timezone.localtime(site.completed_at).date(), "origin": case.origin,
        "origin_ref": case.origin_ref, "country": case.country.code})


# --------------------------------------------------------------------------- review states, driven by RPT (5.2)

@transaction.atomic
def mark_in_review(case: Case, actor) -> Case:
    if case.status == "in_review":
        return case
    open_work = case.tasks.filter(status__in=["open", "in_progress"], review_step=False)
    if open_work.exists():
        raise DomainError("Every task must be done before the report goes to review.", code="task-incomplete",
                          status=409, blocking_reasons=[{"rule": "FR-CASE-002", "message": f"Open: {t.title}"}
                                                        for t in open_work])
    state.transition(case, "case", "in_review", actor=actor, payload=case_payload(case, notified=True) | {"status": "in_review"})
    post_status(case, None, "in_review", "Your report went to its two-person review on {date}.", actor=actor,
                next_date=None)
    return case


@transaction.atomic
def return_to_progress(case: Case, actor, reason="") -> Case:
    if case.status != "in_review":
        return case
    state.transition(case, "case", "in_progress", actor=actor, reason=reason,
                     payload=case_payload(case) | {"status": "in_progress"})
    return case


@transaction.atomic
def on_report_released(case_id, *, report_id=None, released_at=None, correction=False) -> Case | None:
    """report.released: the review steps are done, the case is released and field access ends."""
    from geo.services import revoke_case_access

    case = Case.objects.select_for_update().filter(pk=case_id).first()
    if case is None:
        return None
    for t in case.tasks.filter(status__in=["open", "in_progress"], review_step=True):
        t.completed_at = released_at or _now()
        state.transition(t, "task", "done", event="task.completed",
                         payload={"task_id": t.pk, "case_id": case.pk, "step_key": t.step_key},
                         extra_fields=["completed_at"])
    if case.status == "in_review":
        case.closed_at = released_at or _now()
        state.transition(case, "case", "released", payload=case_payload(case, notified=True) | {
                             "status": "released", "report_id": report_id},
                         extra_fields=["closed_at"])
        post_status(case, None, "release", next((t.client_message for t in case.tasks.filter(step_key="release")),
                                                "") or "Your report was released on {date}. You can open it now.",
                    next_date=None)
    revoke_case_access(case.pk)
    if case.asset_id:
        start_waiting_fresh_searches(case.asset_id)
    return case


def start_waiting_fresh_searches(asset_id) -> list[Case]:
    """A fresh search paid for while the plot's first report was still open starts once that report is released."""
    from . import selectors

    out = []
    for order in selectors.waiting_fresh_search_orders(asset_id):
        try:
            with transaction.atomic():
                c = create_from_order(order.pk)
                if c:
                    out.append(c)
        except DomainError as exc:
            log.warning("fresh search order %s still cannot start: %s", order.pk, exc.detail)
    return out


# --------------------------------------------------------------------------- parties (FR-ACC-013, RUL-31)

def _may_handle_parties(actor, case):
    return is_case_staff(actor, case, ("CM", "RV")) or (
        has_role(actor, "LW", country=case.country) and is_assigned(actor, case))


@transaction.atomic
def add_party(case: Case, actor, *, role, name, person=None, for_organisation=None, organisation_name="",
              id_number="", national_id_check=None, adapter="api") -> Party:
    flags.read_only_guard()
    if not _may_handle_parties(actor, case):
        raise Forbidden("Only the case manager or the assigned lawyer records parties.")
    _require_open(case)
    if role not in Party.ROLES:
        raise Invalid(f"Role must be one of {', '.join(Party.ROLES)}.")
    if not (name or "").strip():
        raise Invalid("Give the name on the deal documents.")
    if role == "signatory" and for_organisation is None and not (organisation_name or "").strip():
        raise Invalid("Say which organisation the signatory signs for.")
    party = Party.objects.create(case=case, country=case.country, role=role, person=person,
                                 for_organisation=for_organisation, organisation_name=organisation_name or "",
                                 name=name.strip(), added_by=actor)
    record(actor=actor, action="case_party.added", entity="case", entity_id=case.pk, country=case.country,
           data={"party_id": str(party.pk), "role": role})
    if national_id_check is not None:
        _attach_check(party, national_id_check)
    elif id_number:
        check_party(party, actor, id_number=id_number, adapter=adapter)
    return party


def _attach_check(party, chk):
    if chk.subject_role != party.role or chk.country_id != party.country_id:
        raise Invalid("That identity check was for another role or country.", code="identity-result-mismatch")
    party.national_id_check = chk
    party.save(update_fields=["national_id_check"])


@transaction.atomic
def check_party(party: Party, actor, *, id_number, adapter="api") -> Party:
    """RUL-31: against the national identity system only. No card image is accepted anywhere."""
    from accounts.services import request_national_id_check

    if not _may_handle_parties(actor, party.case):
        raise Forbidden("Only the case manager or the assigned lawyer checks parties.")
    chk = request_national_id_check(by=actor, country=party.country, subject_role=party.role,
                                    subject_name=party.name, id_number=id_number, person=party.person,
                                    context_type="case", context_id=party.case_id, adapter=adapter)
    _attach_check(party, chk)
    return party


@transaction.atomic
def remove_party(party: Party, actor, reason) -> Party:
    if not _may_handle_parties(actor, party.case):
        raise Forbidden("Only the case manager or the assigned lawyer removes parties.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.")
    party.status, party.removed_reason = "removed", reason.strip()
    party.save(update_fields=["status", "removed_reason"])
    record(actor=actor, action="case_party.removed", entity="case", entity_id=party.case_id, country=party.country,
           data={"party_id": str(party.pk), "reason": reason})
    return party


def party_blockers(case) -> list[dict]:
    from accounts.services import national_id_blockers

    checks = {f"{p.role.replace('_', ' ').capitalize()} {p.name}": p.national_id_check
              for p in case.parties.filter(status="active").select_related("national_id_check")}
    return national_id_blockers(checks)


def failed_parties(case) -> list[Party]:
    return [p for p in case.parties.filter(status="active").select_related("national_id_check")
            if p.national_id_check and p.national_id_check.result in ("no_match", "not_found")]


# --------------------------------------------------------------------------- official searches (FR-CASE-016, RUL-30)

def is_search_staff(person, country) -> bool:
    return bool(person and person.has_tenmina_role("CM", "RV", country=country)
                and not person.has_tenmina_role(*SEARCH_EXCLUDED, country=country))


def _require_search_staff(actor, case):
    if not is_search_staff(actor, case.country):
        raise Forbidden("Only Tenmina case managers and reviewers submit or receive official searches (RUL-30).")


def registry_partner(country, partner_id=None):
    from administration.selectors import assignable_partner, partners

    if partner_id:
        return assignable_partner(partner_id, kind="registry")
    p = partners(country, "registry").first()
    if p is None:
        raise DomainError(f"No registry partner is set up for {country.name}.", code="registry-missing", status=409)
    return p


def tenmina_accounts(partner, country) -> list[str]:
    """Tenmina's own accounts at the registry, from the partner record and the country configuration."""
    d = partner.details or {}
    out = list(d.get("tenmina_accounts") or [])
    if d.get("tenmina_account_ref"):
        out.append(d["tenmina_account_ref"])
    out += list(_cfg(country, "land_registry.tenmina_accounts", []) or [])
    return [a for a in out if a and "TO VERIFY" not in str(a)]


def has_remote_channel(partner) -> bool:
    from .adapters import registry_adapter

    return registry_adapter().has_remote_channel(partner)


@transaction.atomic
def submit_search(case: Case, actor, *, task, channel, tenmina_account_ref, registry_reference, submitted_at=None,
                  search_on="", partner_id=None) -> SearchRequest:
    """US-CASE-016 AC1: channel, Tenmina account, the staff member and the registry's reference are required."""
    flags.read_only_guard()
    _require_search_staff(actor, case)
    _require_open(case)
    if task.case_id != case.pk or task.search_kind not in ("lodge", "result"):
        raise Invalid("Record the search against this case's search task.")
    partner = registry_partner(case.country, partner_id)
    if channel not in SearchRequest.CHANNELS:
        raise Invalid(f"Channel must be one of {', '.join(SearchRequest.CHANNELS)}.")
    if channel == "online_portal" and not has_remote_channel(partner):
        raise Invalid(f"{partner.name} has no online channel. Lodge the search at the registry office.",
                      code="registry-no-remote-channel")
    accounts = tenmina_accounts(partner, case.country)
    if (tenmina_account_ref or "").strip() not in accounts:
        record(actor=actor, action="search.account_refused", entity="case", entity_id=case.pk, country=case.country,
               data={"account": tenmina_account_ref})
        raise Invalid("Searches are lodged only from Tenmina's own registry account. That account is not one of "
                      "them.", code="registry-account-invalid",
                      blocking_reasons=[{"rule": "RUL-30", "message": "Not a Tenmina registry account."}])
    if not (registry_reference or "").strip():
        raise Invalid("Give the registry's search or application number.",
                      extra={"errors": [{"pointer": "/registry_reference", "message": "Required."}]})
    when = submitted_at or _now()
    if when > _now() + timedelta(minutes=5):
        raise Invalid("The submission time cannot be in the future.")
    target = task
    if task.search_kind == "lodge":
        target = case.tasks.filter(search_kind="result").first() or task
    sr = SearchRequest.objects.create(
        case=case, country=case.country, task=target, registry_partner=partner, channel=channel,
        tenmina_account_ref=tenmina_account_ref.strip(), submitted_by=actor, submitted_at=when,
        registry_reference=registry_reference.strip(), search_on=search_on or "")
    record(actor=actor, action="search.submitted", entity="search_request", entity_id=sr.pk, country=case.country,
           data={"case_id": str(case.pk), "channel": channel, "account": sr.tenmina_account_ref,
                 "registry_reference": sr.registry_reference})
    publish("search.submitted", sr.pk, {"search_request_id": sr.pk, "case_id": case.pk, "task_id": target.pk,
                                        "channel": channel, "registry_reference": sr.registry_reference})
    return sr


@transaction.atomic
def record_result(sr: SearchRequest, actor, *, evidence, registry_result_date, registry_reference="", summary="",
                  confirmed_with="", confirmed_at=None) -> SearchRequest:
    """US-CASE-016 AC3, AC4: the result exactly as received from the registry's channel, by staff.
    Without a remote channel, the staff member who confirmed it with the registry and the date are required."""
    from evidence.services import link

    sr = SearchRequest.objects.select_for_update().select_related("case", "case__country").get(pk=sr.pk)
    case = sr.case
    _require_search_staff(actor, case)
    if sr.status != "submitted":
        raise StateConflict("A result is already recorded for this search.")
    if registry_result_date is None or registry_result_date > timezone.localdate():
        raise Invalid("Give the date on the registry's result (not in the future).")
    if evidence.uploaded_by_id != actor.pk:
        raise Invalid("Upload the result you received from the registry's channel yourself.",
                      code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-30", "message": "The result must be received by Tenmina staff."}])
    if registry_reference:
        sr.registry_reference = registry_reference.strip()
    link(evidence, "search_request", sr.pk, role="official_search_result", by=actor)
    sr.result_evidence, sr.result_received_by, sr.result_received_at = evidence, actor, _now()
    sr.registry_result_date, sr.result_summary = registry_result_date, summary or ""
    fields = ["result_evidence", "result_received_by", "result_received_at", "registry_result_date",
              "result_summary", "registry_reference"]
    if sr.channel == "registry_office":
        if not (confirmed_with or "").strip() or confirmed_at is None:
            raise Invalid("This registry has no remote channel. Record who at the registry you confirmed the result "
                          "with, and when.", code="registry-confirmation-required",
                          blocking_reasons=[{"rule": "RUL-30", "message": "Staff confirmation with the registry is "
                                                                          "required."}])
        sr.confirmed_by, sr.confirmed_with, sr.confirmed_at = actor, confirmed_with.strip(), confirmed_at
        fields += ["confirmed_by", "confirmed_with", "confirmed_at"]
        to = "confirmed"
    else:
        to = "result_received"
    state.transition(sr, "search_request", to, actor=actor, event="search.result_received",
                     payload={"search_request_id": sr.pk, "case_id": case.pk, "task_id": sr.task_id,
                              "asset_id": case.asset_id, "registry_result_date": sr.registry_result_date,
                              "channel": sr.channel}, extra_fields=fields)
    _compare_copies(sr, actor)
    task = sr.task
    if task.status in ("open", "in_progress") and task.search_kind == "result" and case.status == "in_progress":
        try:
            with transaction.atomic():
                complete_task(task, actor, note="Result received from the registry's channel")
        except DomainError:
            pass
    return sr


@transaction.atomic
def confirm_result(sr: SearchRequest, actor, *, confirmed_with, confirmed_at) -> SearchRequest:
    _require_search_staff(actor, sr.case)
    if sr.status != "result_received":
        raise StateConflict("Only a received result can be confirmed.")
    if not (confirmed_with or "").strip() or confirmed_at is None:
        raise Invalid("Record who at the registry confirmed it, and when.")
    sr.confirmed_by, sr.confirmed_with, sr.confirmed_at = actor, confirmed_with.strip(), confirmed_at
    return state.transition(sr, "search_request", "confirmed", actor=actor, event="search.confirmed",
                            payload={"search_request_id": sr.pk, "case_id": sr.case_id},
                            extra_fields=["confirmed_by", "confirmed_with", "confirmed_at"])


@transaction.atomic
def reject_search(sr: SearchRequest, actor, reason) -> SearchRequest:
    _require_search_staff(actor, sr.case)
    if not (reason or "").strip():
        raise Invalid("Give the reason.")
    sr.rejected_reason = reason.strip()
    return state.transition(sr, "search_request", "rejected", actor=actor, reason=reason,
                            extra_fields=["rejected_reason"], payload={"search_request_id": sr.pk})


def _copies_for(case):
    from evidence.models import EvidenceLink

    subjects = [("case", case.pk)] + [("task", t) for t in case.tasks.values_list("pk", flat=True)] + \
        [("search_request", s) for s in case.search_requests.values_list("pk", flat=True)]
    q = Q()
    for st, sid in subjects:
        q |= Q(subject_type=st, subject_id=sid)
    return [lk.evidence for lk in EvidenceLink.objects.filter(q, role="search_copy_unverified")
            .select_related("evidence")]


def _note_search_copy(case, evidence, actor):
    record(actor=actor, action="search.copy_kept_unverified", entity="case", entity_id=case.pk,
           country=case.country, data={"evidence_id": str(evidence.pk)})
    for sr in case.search_requests.filter(status__in=["result_received", "confirmed"]):
        _compare_copies(sr, actor)


def _compare_copies(sr, actor):
    """FR-CASE-016: a copy handed in by anyone is compared with the official result; a difference opens a
    fraud review. Identical bytes match at once; anything else goes to a reviewer to compare."""
    if sr.result_evidence_id is None:
        return
    done = set(sr.copy_checks.values_list("evidence_id", flat=True))
    for ev in _copies_for(sr.case):
        if ev.pk in done:
            continue
        if ev.sha256 == sr.result_evidence.sha256:
            SearchCopyCheck.objects.create(search_request=sr, country=sr.country, evidence=ev, matches=True,
                                           note="Same file as the official result.")
        else:
            _alert(sr.country, ("RV",), subject=f"Compare a search copy on {sr.case.reference}",
                   body="A copy of a search result was handed in on this case. Compare it with the official result "
                        "and record whether it matches.", obj=sr.case, link=_case_link(sr.case))


@transaction.atomic
def compare_copy(sr: SearchRequest, actor, *, evidence, matches: bool, note="") -> SearchCopyCheck:
    _require_search_staff(actor, sr.case)
    if sr.result_evidence_id is None:
        raise StateConflict("Record the official result first.")
    chk, created = SearchCopyCheck.objects.get_or_create(
        search_request=sr, evidence=evidence,
        defaults={"country": sr.country, "matches": bool(matches), "checked_by": actor, "note": note or ""})
    if not created:
        raise StateConflict("This copy was already compared.")
    record(actor=actor, action="search.copy_compared", entity="search_request", entity_id=sr.pk, country=sr.country,
           data={"evidence_id": str(evidence.pk), "matches": bool(matches)})
    if not matches:
        publish("search.copy_mismatch", sr.pk, {"search_request_id": sr.pk, "case_id": sr.case_id,
                                                "evidence_id": evidence.pk})
        _alert(sr.country, ("RV",), subject=f"Fraud review: search copy differs on {sr.case.reference}",
               body="A search copy handed in on this case differs from the registry's result. Open a fraud review.",
               obj=sr.case, link=_case_link(sr.case))
    return chk


def search_result_watch(now=None) -> int:
    """Job cases.search_result_watch (daily): a submitted search with no result after
    `search_result_overdue_days` is raised to the case manager."""
    from administration.selectors import setting

    now = now or _now()
    n = 0
    for sr in SearchRequest.objects.filter(status="submitted", overdue_alerted_at__isnull=True) \
            .select_related("case", "country"):
        days = int(setting("search_result_overdue_days", sr.country, 10) or 10)
        if sr.submitted_at > now - timedelta(days=days):
            continue
        sr.overdue_alerted_at = now
        sr.save(update_fields=["overdue_alerted_at"])
        targets = [sr.case.case_manager] if sr.case.case_manager else list(_staff_people(sr.country, "CM"))
        for p in targets:
            _notify(p, "generic", subject=f"Search result overdue on {sr.case.reference}", obj=sr.case,
                    link=_case_link(sr.case),
                    body=f"Search {sr.registry_reference} was lodged on {sr.submitted_at:%d %B %Y} and no result has "
                         "come back from the registry's channel.")
        n += 1
    return n


def note_national_id_result(payload: dict):
    """national_id_check.completed for a party on a case: tell the case manager."""
    if payload.get("context_type") != "case" or not payload.get("context_id"):
        return
    case = Case.objects.filter(pk=payload["context_id"]).first()
    if case is None or payload.get("result") == "match":
        return
    targets = [case.case_manager] if case.case_manager else list(_staff_people(case.country, "CM"))
    for p in targets:
        _notify(p, "generic", subject=f"Identity check failed on {case.reference}", obj=case, link=_case_link(case),
                body=f"A party's national identity check on case {case.reference} came back "
                     f"{str(payload.get('result')).replace('_', ' ')}. The report can be released only as red, and "
                     "no money can be paid to that party.")
