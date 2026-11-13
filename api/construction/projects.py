"""Projects: creation on a verified plot (FR-BLD-001), off-plan checks (FR-BLD-011), the bill of quantities and
split (FR-BLD-002), the budget, the contractor, the contract, the escrow or the direct route, the start, site
handover, inspector assignment (FR-BLD-004), variations (FR-BLD-008, RUL-19) and completion."""
import json
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from administration import flags
from core import state
from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from . import pricing, registry, stages
from .common import (alert_staff, audit, cfg, evidence_objects, fmt, is_staff, link_all, log, notify, now,
                     require_on, require_staff, staff_in, today)
from .models import BUILD_TYPES, ESCROW_KIND, PROJECT_TYPES, ROUTES, BillOfQuantities, Milestone, PanelMember, \
    Project, Variation

VERIFIED_VERDICTS = ("green", "amber")


def project_payload(p: Project, **extra) -> dict:
    return {"project_id": p.pk, "id": p.pk, "asset_id": p.asset_id, "client_id": p.client_id, "type": p.type,
            "country": p.country.code, "title": p.title, "route": p.payment_route, "escrow_id": p.escrow_id,
            "link": f"/projects/{p.pk}", **extra}


def _route_for(country, project_type, requested, actor):
    default = cfg(country, project_type, "payment_route")
    if default not in ROUTES:
        default = "client_direct"
    route = requested or default
    if route not in ROUTES:
        raise Invalid("Payment route must be escrow or client_direct.", code="validation-error")
    if route != default:
        allowed = cfg(country, project_type, "payment_routes", ["client_direct", "escrow"]) or []
        if not is_staff(actor, country) or route not in allowed:
            raise Forbidden("The payment route is set for the country. A case manager may change it where the "
                            "country allows.")
    if route == "escrow" and not flags.enabled("escrow.enabled", country):
        raise RuleBlocked("Escrow is not open in this country yet. Stages are paid directly after Tenmina "
                          "checks them.", code="feature-off",
                          blocking_reasons=[{"rule": "FR-ESC-001", "message": "escrow.enabled is off"}])
    return route


def _verified_asset(asset, client, project_type):
    """US-BLD-001: only a plot with a released green or amber report. Off-plan units are checked through the
    developer's off-plan case instead."""
    from reports.selectors import latest_released_for_asset

    if project_type == "offplan":
        return None
    if asset.owner_id and asset.owner_id != client.pk:
        raise NotFound("We could not find that plot among yours.")
    rpt = latest_released_for_asset(asset.pk)
    if rpt is None or rpt.overall_verdict not in VERIFIED_VERDICTS:
        raise RuleBlocked("This plot has no released green or amber report. Order a verification of the plot "
                          "first.", code="asset-not-verified",
                          blocking_reasons=[{"rule": "FR-BLD-001", "message": "No released green or amber report."
                                             if rpt is None else f"The report's verdict is {rpt.overall_verdict}."}])
    return rpt


@transaction.atomic
def create_project(actor, *, type, country=None, title, asset_id=None, budget, description="", client=None,
                   payment_route=None, contractor_id=None) -> Project:
    """FR-BLD-001, FR-BLD-011. `budget` is the client's first estimate in the local currency; the quantity
    surveyor's bill of quantities replaces it."""
    from accounts.selectors import is_representative  # noqa: F401
    from geo.models import Asset

    if type not in PROJECT_TYPES:
        raise Invalid(f"Type must be one of {', '.join(PROJECT_TYPES)}.", code="validation-error")
    if type not in BUILD_TYPES:
        create = registry.hook(type, "create")
        if create is None:
            raise Invalid("This project type is not available.", code="validation-error")
        return create(actor, {"country": country, "title": title, "budget": budget, "description": description,
                              "client": client, "payment_route": payment_route})
    client = client or actor
    if client.pk != actor.pk and not has_role(actor, "CM", "RV", country=country):
        raise Forbidden("A client starts their own project; otherwise a case manager does.")
    if not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client starts a project.")
    asset = Asset.objects.filter(pk=asset_id).first() if asset_id else None
    if asset is None:
        raise Invalid("Choose the plot or building.", code="validation-error")
    country = asset.country
    require_on(type, country)
    rpt = _verified_asset(asset, client, type)
    try:
        amount = q(budget)
    except Exception:  # noqa: BLE001
        raise Invalid("Enter the budget as a number.", code="validation-error") from None
    if amount <= 0:
        raise Invalid("Enter your budget for the build.", code="validation-error")
    if not (title or "").strip():
        raise Invalid("Give the project a name.", code="validation-error")
    from administration.selectors import current_config

    schedule = current_config("milestone_schedule", country, "building")
    if schedule is None and type != "offplan":
        raise StateConflict("No milestone schedule is published for this country.", code="config-missing")
    route = _route_for(country, type, payment_route, actor)
    p = Project.objects.create(
        country=country, type=type, title=title.strip(), description=description or "", asset=asset,
        report_id=rpt.pk if rpt else None, client=client, schedule_version=schedule, budget_amount=amount,
        budget_currency=country.currency, guide_amount=pricing.to_guide(country, amount),
        guide_currency=pricing.guide_currency(country), payment_route=route, created_by=actor,
        case_manager=actor if has_role(actor, "CM", country=country) else None)
    if type == "offplan":
        if not contractor_id:
            raise Invalid("Choose the developer from the panel.", code="validation-error")
        choose_contractor(p, actor if actor.pk == client.pk else client, contractor_id, _by=actor)
        open_offplan_check(p, None)
    audit(actor, "project.created", p, {"type": type, "route": route})
    publish("project.created", p.pk, project_payload(p))
    alert_staff(country, ("CM",), "project_created", f"{client.full_name} started a {type} project: {p.title}. "
                                                     "Assign a quantity surveyor.", obj=p,
                link=f"/back-office/projects/{p.pk}")
    return p


def open_offplan_check(p: Project, by):
    """FR-BLD-011, US-BLD-011a: the developer's title, permits and company, as an off-plan case for this estate.
    A verified check on the same developer and estate is reused."""
    from cases.models import Case
    from cases.services import open_case

    if p.type != "offplan" or p.contractor is None:
        return None
    prior = Case.objects.filter(product_line="offplan_check", subject_type="bld_project",
                                subject_id__in=Project.objects.filter(contractor=p.contractor, asset=p.asset)
                                .values_list("pk", flat=True), outcome="verified").first()
    if prior is not None:
        p.offplan_case_id = prior.pk
        p.save(update_fields=["offplan_case_id"])
        return prior
    cm = by if by is not None and has_role(by, "CM", country=p.country) else p.case_manager or \
        staff_in(p.country, "CM").first()
    case = open_case("offplan_check", p.country, "bld_project", p.pk, client=p.client, actor=cm,
                     asset=p.asset, title=f"Off-plan check: {p.contractor.name}, {p.title}", case_manager=cm)
    p.offplan_case_id = case.pk
    p.save(update_fields=["offplan_case_id"])
    return case


def offplan_reasons(p: Project) -> list[dict]:
    if p.type != "offplan":
        return []
    from cases.models import Case

    c = Case.objects.filter(pk=p.offplan_case_id).first() if p.offplan_case_id else None
    if c is None or c.outcome != "verified":
        msg = "The developer's off-plan check (title, permits and company) is not verified." if (
            c is None or not c.outcome) else "The developer's off-plan check failed. No escrow can open on it."
        return [{"rule": "FR-BLD-011", "code": "developer-not-verified", "message": msg}]
    return []


# ----------------------------------------------------------------- quantity surveyor and bill of quantities

def _active_member(pk, kind, country) -> PanelMember:
    m = PanelMember.objects.filter(pk=pk, kind=kind, country=country).first()
    if m is None:
        raise NotFound(f"That {kind.replace('_', ' ')} is not on the panel.")
    if m.status != "active":
        raise RuleBlocked(f"{m.name} is not active on the panel.", code="panel-not-active",
                          blocking_reasons=[{"rule": "FR-BLD-003", "message": f"Status: {m.status}"}])
    return m


@transaction.atomic
def assign_quantity_surveyor(p: Project, by, member_id) -> Project:
    from accounts.services import require_valid_licence

    require_on(p.type, p.country)
    require_staff(by, p.country, "CM", message="Only a case manager assigns the quantity surveyor.")
    if p.budget_approved_at:
        raise StateConflict("The budget is already approved.")
    m = _active_member(member_id, "quantity_surveyor", p.country)
    require_valid_licence(m.person, "QS")
    p.quantity_surveyor, p.qs_assigned_at = m, now()
    p.case_manager = p.case_manager or by
    p.save(update_fields=["quantity_surveyor", "qs_assigned_at", "case_manager"])
    audit(by, "project.qs_assigned", p, {"panel_member_id": str(m.pk)})
    notify(m.person, "task_assigned", f"Please prepare the bill of quantities for {p.title}.", obj=p,
           link=f"/projects/{p.pk}", needs_action=True, channels=("in_app", "email"))
    return p


def _split_from_schedule(p: Project):
    content = (p.schedule_version.content if p.schedule_version else {}) or {}
    return [{"key": m["key"], "name": m["name"], "share_pct": str(m["share_pct"])}
            for m in content.get("milestones", [])]


def _check_split(split):
    if not isinstance(split, list) or not split:
        raise Invalid("Give the milestone split.", code="validation-error")
    keys, total = set(), Decimal("0")
    for i, s in enumerate(split):
        key, name = (s.get("key") or "").strip(), (s.get("name") or "").strip()
        try:
            share = Decimal(str(s.get("share_pct")))
        except Exception:  # noqa: BLE001
            raise Invalid(f"Milestone {i + 1} needs a share.", code="validation-error") from None
        if not key or not name or share <= 0 or share > 100:
            raise Invalid(f"Milestone {i + 1} needs a key, a name and a share above 0.", code="validation-error")
        if key in keys:
            raise Invalid(f"Milestone '{key}' appears twice.", code="validation-error")
        keys.add(key)
        total += share
    if total != Decimal("100"):
        raise Invalid(f"The shares must total 100%. They total {total}%.", code="split-not-100",
                      extra={"total": str(total)})


def build_milestones(p: Project, rows, *, funds=False):
    """rows: [{key, name, share_pct, amount?, visit_required?}]. Amounts follow the shares; the last row takes
    the rounding so the milestones add up to the budget exactly."""
    Milestone.objects.filter(project=p).delete()
    total = p.budget_amount
    out, running = [], Decimal("0")
    for seq, r in enumerate(rows):
        share = Decimal(str(r["share_pct"]))
        amount = q(r["amount"]) if r.get("amount") is not None else q(total * share / 100)
        if seq == len(rows) - 1:
            amount = q(total - running)
        running += amount
        key = r["key"]
        out.append(Milestone.objects.create(
            country=p.country, project=p, seq=seq, key=key, name=r["name"], share_pct=share, amount=amount,
            currency=p.budget_currency, guide_amount=pricing.to_guide(p.country, amount),
            guide_currency=pricing.guide_currency(p.country),
            required_evidence=[] if funds else stages.evidence_for(p.country, key),
            checklist=stages.checklist_for(p.country, key, funds=funds),
            visit_required=bool(r.get("visit_required", True))))
    return out


@transaction.atomic
def submit_boq(p: Project, by, *, items, evidence_ids, split=None, note="") -> BillOfQuantities:
    """FR-BLD-002: the assigned quantity surveyor (or a case manager) uploads the bill of quantities. The standard
    schedule from mobilisation to handover and retention is proposed; shares must total 100%."""
    require_on(p.type, p.country)
    if not p.is_build:
        raise StateConflict("Project funds have stages, not a bill of quantities.")
    qs_member = p.quantity_surveyor
    is_qs = qs_member is not None and qs_member.person_id == by.pk
    if not is_qs and not has_role(by, "CM", country=p.country):
        if by.has_tenmina_role("QS"):
            raise NotFound("This project is not assigned to you.")
        raise Forbidden("Only the assigned quantity surveyor or a case manager sets the split.")
    if p.budget_approved_at:
        raise StateConflict("The budget is approved and the split is locked.")
    if not isinstance(items, list) or not items:
        raise Invalid("List the bill of quantities items.", code="validation-error")
    clean, total = [], Decimal("0")
    for i, it in enumerate(items):
        try:
            amount = q(it.get("amount") if it.get("amount") is not None else
                       Decimal(str(it["quantity"])) * Decimal(str(it["rate"])))
        except Exception:  # noqa: BLE001
            raise Invalid(f"Item {i + 1} needs an amount, or a quantity and a rate.", code="validation-error") \
                from None
        if amount <= 0 or not (it.get("description") or "").strip():
            raise Invalid(f"Item {i + 1} needs a description and an amount above zero.", code="validation-error")
        clean.append({"description": it["description"].strip(), "quantity": str(it.get("quantity", "")),
                      "unit": it.get("unit", ""), "rate": str(it.get("rate", "")), "amount": f"{amount:.2f}"})
        total += amount
    split = split or _split_from_schedule(p)
    _check_split(split)
    evidence = evidence_objects(evidence_ids, by, p.country, what="bill of quantities")
    BillOfQuantities.objects.filter(project=p, status="submitted").update(status="superseded")
    version = BillOfQuantities.objects.filter(project=p).count() + 1
    boq = BillOfQuantities.objects.create(country=p.country, project=p, version=version, items=clean, split=split,
                                          total_amount=q(total), total_currency=p.budget_currency,
                                          evidence=evidence[0], uploaded_by=by, note=note or "")
    link_all(evidence, "bld_project", p.pk, "quote", by)
    p.budget_amount = q(total)
    p.guide_amount = pricing.to_guide(p.country, total)
    p.save(update_fields=["budget_amount", "guide_amount"])
    build_milestones(p, split)
    audit(by, "boq.submitted", boq, {"version": version, "total": f"{total:.2f}"})
    notify(p.client, "approval_needed", f"The quantity surveyor's bill of quantities for {p.title} is ready: "
                                        f"{fmt(total, p.budget_currency)} in {len(split)} milestones. Please review "
                                        "and approve the budget.", subject="Your budget is ready", needs_action=True,
           obj=p, link=f"/projects/{p.pk}", category="approval")
    return boq


@transaction.atomic
def approve_budget(p: Project, client) -> Project:
    """US-BLD-002 AC3: when the client approves the budget, the split is locked."""
    require_on(p.type, p.country)
    if p.client_id != client.pk:
        raise NotFound()
    if p.budget_approved_at:
        raise StateConflict("The budget is already approved.")
    if p.is_build:
        boq = BillOfQuantities.objects.filter(project=p, status="submitted").order_by("-version").first()
        if boq is None:
            raise StateConflict("The quantity surveyor has not uploaded the bill of quantities yet.")
        boq.status, boq.accepted_at = "accepted", now()
        boq.save(update_fields=["status", "accepted_at"])
        qs_member = p.quantity_surveyor
        if qs_member is not None and qs_member.person_id == boq.uploaded_by_id:
            # RUL-26: pay is for accepted work, never for a result.
            publish("work.accepted", boq.pk, {
                "work_kind": "bill_of_quantities", "work_type": "bill_of_quantities", "work_ref": boq.pk,
                "person_id": boq.uploaded_by_id, "role": "QS", "project_id": p.pk,
                "assigned_at": p.qs_assigned_at or boq.created_at, "accepted_at": boq.accepted_at, "quantity": 1,
                "country": p.country.code})
    if not p.milestones.exists():
        raise StateConflict("The project has no milestones yet.")
    p.budget_approved_at, p.budget_approved_by = now(), client
    p.save(update_fields=["budget_approved_at", "budget_approved_by"])
    audit(client, "project.budget_approved", p, {"budget": f"{p.budget_amount:.2f}"})
    from .common import resolve

    resolve(p)
    alert_staff(p.country, ("CM",), "budget_approved", f"{p.client.full_name} approved the budget for {p.title}.",
                obj=p, link=f"/back-office/projects/{p.pk}")
    _try_start(p, None)
    return p


# ----------------------------------------------------------------- contractor, contract, start

@transaction.atomic
def choose_contractor(p: Project, client, member_id, _by=None) -> Project:
    """US-BLD-003 AC2: only active panel members are offered; a suspended contractor cannot be chosen."""
    require_on(p.type, p.country)
    actor = _by or client
    if p.client_id != client.pk and not has_role(actor, "CM", country=p.country):
        raise NotFound()
    if p.status != "setup" or p.contract_signed_at:
        raise StateConflict("The contractor is chosen before the contract is signed.")
    kind = "developer" if p.type == "offplan" else "contractor"
    m = _active_member(member_id, kind, p.country)
    p.contractor = m
    fields = ["contractor"]
    if p.inspector_id:
        from .panel import conflict_reasons

        if conflict_reasons(p.inspector, m):
            p.inspector = None
            fields.append("inspector")
            alert_staff(p.country, ("CM",), "inspector_conflict", f"The inspector on {p.title} has a link to the "
                                                                  "new contractor. Assign another.", obj=p)
    p.save(update_fields=fields)
    audit(actor, "project.contractor_chosen", p, {"panel_member_id": str(m.pk)})
    return p


@transaction.atomic
def sign_contract(p: Project, by, *, evidence_ids) -> Project:
    require_on(p.type, p.country)
    require_staff(by, p.country, "CM", message="A case manager records the signed contract.")
    if p.contract_signed_at:
        raise StateConflict("The contract is already recorded.")
    if p.contractor is None and p.is_build:
        raise StateConflict("Choose the contractor first.")
    if not p.budget_approved_at:
        raise StateConflict("The client approves the budget first.")
    evidence = evidence_objects(evidence_ids, by, p.country, what="signed contract")
    link_all(evidence, "bld_project", p.pk, "agreement", by)
    p.contract_signed_at, p.contract_evidence = now(), evidence[0]
    p.case_manager = p.case_manager or by
    p.save(update_fields=["contract_signed_at", "contract_evidence", "case_manager"])
    audit(by, "project.contract_signed", p)
    _try_start(p, by)
    return p


def start_blockers(p: Project) -> list[dict]:
    out = []
    if not p.budget_approved_at:
        out.append({"rule": "FR-BLD-002", "code": "budget-not-approved", "message": "The budget is not approved."})
    if p.is_build:
        if p.contractor is None:
            out.append({"rule": "FR-BLD-003", "code": "contractor-missing", "message": "No contractor is chosen."})
        elif p.contractor.status != "active":
            out.append({"rule": "FR-BLD-003", "code": "panel-not-active",
                        "message": f"{p.contractor.name} is not active on the panel."})
        elif p.contractor.payee is None or p.contractor.payee.verification_status != "verified":
            out.append({"rule": "RUL-22", "code": "payee-not-verified",
                        "message": f"{p.contractor.name} has no verified payee account yet."})
        if not p.contract_signed_at:
            out.append({"rule": "RUL-09", "code": "contract-unsigned", "message": "The contract is not signed."})
    out.extend(offplan_reasons(p))
    extra = registry.hook(p.type, "start_blockers")
    if extra is not None:
        out.extend(extra(p) or [])
    return out


@transaction.atomic
def open_escrow(p: Project, by):
    """The escrow route: a construction, off-plan or project fund escrow at the partner bank, with the
    contractor, developer or suppliers as its only payees (RUL-28). The project starts when the bank confirms
    the deposit."""
    from escrow import services as esc

    require_on(p.type, p.country)
    require_staff(by, p.country, "CM", message="A case manager opens the escrow.")
    if p.payment_route != "escrow":
        raise StateConflict("This project is paid directly against Tenmina's confirmation, not through escrow.")
    if p.escrow_id:
        raise StateConflict("This project already has its escrow.")
    reasons = start_blockers(p)
    if reasons:
        raise RuleBlocked("The escrow cannot open yet.", code="release-blocked", blocking_reasons=reasons)
    payees = [p.contractor.payee] if p.is_build else list(_fund_payees(p))
    e = esc.open_line_escrow(kind=ESCROW_KIND[p.type], client=p.client, country=p.country,
                             agreed_amount=p.budget_amount, by=by, title=p.title, currency=p.budget_currency,
                             asset_id=p.asset_id, project_id=p.pk, payees=payees)
    p.escrow = e
    p.save(update_fields=["escrow"])
    audit(by, "project.escrow_opened", p, {"escrow_id": str(e.pk)})
    notify(p.client, "escrow_terms", f"The escrow for {p.title} is ready. Please read and accept its terms, then "
                                     "pay the bank using its instructions.", needs_action=True, obj=p,
           link=f"/escrows/{e.pk}", category="money")
    return e


def _fund_payees(p):
    from django.apps import apps

    try:
        Supplier = apps.get_model("projectfunds", "Supplier")
    except LookupError:
        return []
    return [s.payee for s in Supplier.objects.filter(project=p, payee__isnull=False).select_related("payee")]


def _try_start(p: Project, by):
    p.refresh_from_db()
    if p.status != "setup" or p.payment_route != "client_direct":
        return p
    if start_blockers(p):
        return p
    return start(p, by)


@transaction.atomic
def start(p: Project, by=None) -> Project:
    p.refresh_from_db()
    if p.status != "setup":
        return p
    reasons = start_blockers(p)
    if p.payment_route == "escrow":
        if p.escrow is None or p.escrow.status in ("proposed", "agreed", "cancelled"):
            reasons.append({"rule": "RUL-34", "code": "escrow-not-funded",
                            "message": "The bank has not confirmed the deposit yet."})
    if reasons:
        raise RuleBlocked("The project cannot start yet.", code="release-blocked", blocking_reasons=reasons)
    p.started_at = now()
    state.transition(p, "project", "active", actor=by, event="project.started", extra_fields=["started_at"],
                     payload=project_payload(p))
    notify(p.client, "project_started", f"{p.title} has started. You will see every stage, photo and inspection "
                                        "here.", obj=p, link=f"/projects/{p.pk}")
    if p.contractor and p.contractor.person:
        notify(p.contractor.person, "field_new_work", f"{p.title} has started. Open Tenmina Field to see it.",
               obj=p, channels=("in_app", "push"))
    return p


def on_escrow_funded(payload: dict):
    p = Project.objects.filter(escrow_id=payload.get("escrow_id"), status="setup").first()
    if p is None:
        return
    try:
        start(p, None)
    except RuleBlocked as exc:
        log.warning("project %s funded but not started: %s", p.pk, exc.blocking_reasons)
        alert_staff(p.country, ("CM",), "project_not_started", f"The bank confirmed the deposit for {p.title}, but "
                                                               "it cannot start yet. Check the project.", obj=p)


@transaction.atomic
def confirm_handover(p: Project, by, *, evidence_ids=(), note="") -> Project:
    """RUL-09 exception: milestone 0 (mobilisation) is paid when the contract is signed and a Tenmina staff
    member confirms site handover. The contractor cannot confirm it (TC-RUL-09-06)."""
    from .milestones import prepare_main

    require_on(p.type, p.country)
    if not has_role(by, "CM", "RV", country=p.country):
        raise Forbidden("Only Tenmina staff confirm site handover.")
    if not p.is_build:
        raise StateConflict("Project funds have no site handover.")
    if p.handover_confirmed_at:
        raise StateConflict("Site handover is already confirmed.")
    if not p.contract_signed_at:
        raise RuleBlocked("The contract is not signed.", code="release-blocked",
                          blocking_reasons=[{"rule": "RUL-09", "code": "contract-unsigned",
                                             "message": "The contract must be signed first."}])
    if p.status != "active":
        raise StateConflict("The project has not started.")
    evidence = evidence_objects(evidence_ids, by, p.country, required=False)
    link_all(evidence, "bld_project", p.pk, "agreement", by)
    p.handover_confirmed_at, p.handover_confirmed_by = now(), by
    p.save(update_fields=["handover_confirmed_at", "handover_confirmed_by"])
    audit(by, "project.site_handover_confirmed", p, {"note": note})
    m = p.milestones.filter(seq=0, key="mobilisation").first()
    if m is not None and m.status == "not_started":
        try:
            prepare_main(m, by)
        except RuleBlocked as exc:
            log.warning("mobilisation for %s not prepared: %s", p.pk, exc.blocking_reasons)
    return p


@transaction.atomic
def assign_inspector(p: Project, by, member_id) -> Project:
    """FR-BLD-004: only an inspector with no recorded link to the contractor (RUL-10). Only a case manager
    assigns; a contractor has no way to choose or pay the inspector."""
    from .panel import require_assignable_inspector

    require_on(p.type, p.country)
    if not has_role(by, "CM", country=p.country):
        raise Forbidden("Only a case manager assigns the inspector.")
    m = PanelMember.objects.filter(pk=member_id, kind="inspector").first()
    if m is None:
        raise NotFound("That inspector is not on the panel.")
    require_assignable_inspector(m, p.contractor, p.country)
    p.inspector = m
    p.save(update_fields=["inspector"])
    audit(by, "project.inspector_assigned", p, {"panel_member_id": str(m.pk)})
    notify(m.person, "field_new_work", f"You are the inspector on {p.title}. You have no link to this contractor; "
                                       "if you do, tell us before you visit.", obj=p, channels=("in_app", "push"))
    return p


# ----------------------------------------------------------------- variations (FR-BLD-008, RUL-19)

def _side(p: Project, person):
    if person.pk == p.client_id:
        return "client"
    c = p.contractor
    if c is not None and (c.person_id == person.pk or (c.organisation_id and _member_of(person, c.organisation_id))):
        return "contractor"
    return None


def _member_of(person, org_id):
    from accounts.selectors import is_member

    return is_member(person, org_id)


@transaction.atomic
def propose_variation(p: Project, by, *, milestone_id, description, cost_change, time_effect_days=0) -> Variation:
    require_on(p.type, p.country)
    side = _side(p, by)
    if side is None and not has_role(by, "CM", country=p.country):
        raise NotFound()
    if not p.is_build:
        raise StateConflict("Variations are for building projects.")
    if p.status not in ("setup", "active"):
        raise StateConflict(f"The project is {p.status}.")
    m = p.milestones.filter(pk=milestone_id).first()
    if m is None:
        raise Invalid("Choose the milestone the variation changes.", code="validation-error")
    if m.status in ("client_approved", "release_approved", "paid"):
        raise StateConflict("This milestone is already approved for payment. Propose the change on a later one.")
    if not (description or "").strip():
        raise Invalid("Describe the change.", code="validation-error")
    change = q(cost_change)
    if m.amount + change < 0:
        raise Invalid("The change would make the milestone negative.", code="validation-error")
    v = Variation.objects.create(country=p.country, project=p, milestone=m, description=description.strip(),
                                 cost_change_amount=change, cost_change_currency=p.budget_currency,
                                 time_effect_days=int(time_effect_days or 0), proposed_by=by)
    t = now()
    if side == "client":
        v.client_agreed_at = t
    elif side == "contractor":
        v.contractor_agreed_at, v.contractor_agreed_by = t, by
    v.save()
    audit(by, "variation.proposed", v, {"cost_change": f"{change:.2f}", "milestone": m.key})
    other = p.client if side != "client" else (p.contractor.person if p.contractor else None)
    notify(other, "approval_needed", f"A change to {m.name} on {p.title} needs your agreement: {v.description} "
                                     f"({fmt(change, v.cost_change_currency)}, {v.time_effect_days} days).",
           needs_action=True, obj=v, link=f"/projects/{p.pk}/variations/{v.pk}", category="approval")
    return v


@transaction.atomic
def decide_variation(v: Variation, by, *, decision, reason="") -> Variation:
    """Both the client and the contractor agree in writing in the app before the work (RUL-19)."""
    p = v.project
    side = _side(p, by)
    if side is None:
        raise NotFound()
    if v.status != "proposed":
        raise StateConflict(f"This variation is {v.status}.")
    if decision not in ("agree", "decline"):
        raise Invalid("Decision must be agree or decline.", code="validation-error")
    if decision == "decline":
        v.declined_by, v.decline_reason = by, reason or ""
        state.transition(v, "bld_variation", "declined", actor=by, reason=reason,
                         extra_fields=["declined_by", "decline_reason"], payload={"project_id": p.pk})
        return v
    t = now()
    if side == "client":
        v.client_agreed_at = v.client_agreed_at or t
    else:
        v.contractor_agreed_at, v.contractor_agreed_by = v.contractor_agreed_at or t, v.contractor_agreed_by or by
    v.save(update_fields=["client_agreed_at", "contractor_agreed_at", "contractor_agreed_by"])
    if v.client_agreed_at and v.contractor_agreed_at:
        _apply_variation(v, by)
    return v


def _apply_variation(v: Variation, by):
    from evidence.services import store

    p, m = v.project, v.milestone
    record = {"project": p.title, "milestone": m.name, "description": v.description,
              "cost_change": f"{v.cost_change_amount:.2f} {v.cost_change_currency}",
              "time_effect_days": v.time_effect_days, "client": p.client.full_name,
              "client_agreed_at": v.client_agreed_at.isoformat(),
              "contractor": p.contractor.name if p.contractor else "",
              "contractor_agreed_at": v.contractor_agreed_at.isoformat()}
    ev = store(data=json.dumps(record, sort_keys=True, indent=1).encode(), country=p.country, uploaded_by=by,
               content_type="application/json", source="generated", original_name=f"variation-{v.pk}.json",
               description="Variation agreed in writing by client and contractor")
    from evidence.services import link

    link(ev, "bld_variation", v.pk, role="variation_agreement", by=by)
    v.agreed_at, v.agreement_evidence = now(), ev
    state.transition(v, "bld_variation", "agreed", actor=by, extra_fields=["agreed_at", "agreement_evidence"],
                     payload={"project_id": p.pk, "milestone_id": m.pk})
    m.amount = q(m.amount + v.cost_change_amount)
    if m.guide_amount is not None:
        delta = pricing.to_guide(p.country, v.cost_change_amount)
        m.guide_amount = q(m.guide_amount + (delta or 0))
    # RUL-19 / TC-RUL-19-03: agreed only after the work was captured.
    if m.captured_from and v.agreed_at > m.captured_from and m.status in ("submitted", "evidence_checked",
                                                                          "inspection_scheduled", "inspected"):
        m.concerns = list(m.concerns or []) + [{"kind": "variation_after_work", "variation_id": str(v.pk),
                                                "status": "open",
                                                "message": "The variation was agreed after the work was captured."}]
    m.save(update_fields=["amount", "guide_amount", "concerns"])
    p.budget_amount = q(p.budget_amount + v.cost_change_amount)
    p.guide_amount = pricing.to_guide(p.country, p.budget_amount)
    p.save(update_fields=["budget_amount", "guide_amount"])
    audit(by, "variation.agreed", v, {"milestone": m.key, "new_amount": f"{m.amount:.2f}"})
    if p.payment_route == "escrow" and v.cost_change_amount > 0:
        notify(p.client, "escrow_top_up", f"The agreed change adds {fmt(v.cost_change_amount, p.budget_currency)} "
                                          f"to {m.name}. Please add it at the bank before that stage is paid.",
               needs_action=True, obj=p, link=f"/projects/{p.pk}", category="money")


# ----------------------------------------------------------------- completion and cancellation

def on_milestone_paid(m: Milestone):
    p = m.project
    if m.key == "handover" and p.practical_completion_on is None:
        days = int(cfg(p.country, p.type, "defects_period_days"))
        p.practical_completion_on = today(p.country)
        p.defects_period_ends_on = p.practical_completion_on + timedelta(days=days)
        p.save(update_fields=["practical_completion_on", "defects_period_ends_on"])
        notify(p.client, "money_update", f"Handover is paid. The retention stays held for the defects period, "
                                         f"until {p.defects_period_ends_on:%d %B %Y}.", obj=p,
               link=f"/projects/{p.pk}")
    if p.status == "active" and not p.milestones.exclude(status="paid").exists():
        complete(p)


@transaction.atomic
def complete(p: Project, by=None) -> Project:
    p.completed_at = now()
    state.transition(p, "project", "completed", actor=by, event="project.completed",
                     extra_fields=["completed_at"], payload=project_payload(p))
    notify(p.client, "project_completed", f"{p.title} is complete. Every stage was checked and paid.", obj=p,
           link=f"/projects/{p.pk}")
    return p


@transaction.atomic
def cancel(p: Project, by, *, reason) -> Project:
    from . import payments
    from .models import Payment

    require_staff(by, p.country, "CM", "RV")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if p.status in ("completed", "cancelled"):
        raise StateConflict(f"The project is {p.status}.")
    for pay in Payment.objects.filter(project=p, status__in=Payment.LIVE):
        payments.withdraw(pay, by, reason=f"Project cancelled: {reason}", system=True)
    p.status_reason = reason.strip()
    state.transition(p, "project", "cancelled", actor=by, event="project.closed", reason=reason,
                     extra_fields=["status_reason"], payload=project_payload(p))
    if p.escrow_id and p.escrow.status not in ("released", "cancelled"):
        alert_staff(p.country, ("CM",), "escrow_cancel_needed", f"{p.title} was cancelled. Request the escrow "
                                                                f"{p.escrow.reference} cancellation and refund.",
                    obj=p, link=f"/back-office/escrows/{p.escrow_id}")
    return p


@transaction.atomic
def resume(p: Project, by, *, contractor_id=None) -> Project:
    """After a contractor's removal a reviewer resumes the project, usually with a new contractor."""
    if not has_role(by, "RV", country=p.country):
        raise Forbidden("Only a reviewer resumes a paused project.")
    if p.status != "paused":
        raise StateConflict("Only a paused project is resumed.")
    if contractor_id:
        m = _active_member(contractor_id, "developer" if p.type == "offplan" else "contractor", p.country)
        p.contractor = m
        p.save(update_fields=["contractor"])
    if p.contractor is None or p.contractor.status != "active":
        raise RuleBlocked("Choose an active contractor first.", code="panel-not-active",
                          blocking_reasons=[{"rule": "FR-BLD-010", "message": "The contractor was removed."}])
    from .milestones import unfreeze_milestone

    for m in p.milestones.filter(status="frozen", freeze_kind="contractor_removed"):
        unfreeze_milestone(m, by=by)
    p.status_reason = ""
    state.transition(p, "project", "active", actor=by, extra_fields=["status_reason"],
                     payload=project_payload(p))
    return p


def round_share(part, whole) -> Decimal:
    return (Decimal(part) * 100 / Decimal(whole)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
