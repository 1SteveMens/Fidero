"""BLD Construction: read-only queries other modules may use.

- visible_projects(person)      clients their own, staff their countries, panel members what they work on
- project(pk), milestone(pk)
- dashboard(project, person)    FR-BLD-009: budget against actual, milestones, photo timeline, inspections, payments
- active_panel(country, kind)   members a client may choose (US-BLD-003 AC2)
"""
from decimal import Decimal

from django.db.models import Q, Sum

from core.permissions import has_role

from .models import Defect, Inspection, Milestone, PanelMember, Payment, Project, Variation

STAFF = ("CM", "RV", "AD")


def project(pk) -> Project | None:
    return Project.objects.filter(pk=pk).first()


def milestone(pk) -> Milestone | None:
    return Milestone.objects.filter(pk=pk).first()


def _panel_q(person, prefix=""):
    """Projects where the person works as contractor, inspector or quantity surveyor (or for their company)."""
    from accounts.models import Membership

    orgs = list(Membership.objects.filter(person=person, status="active").values_list("organisation_id", flat=True))
    q = Q()
    for f in ("contractor", "inspector", "quantity_surveyor"):
        q |= Q(**{f"{prefix}{f}__person": person})
        if orgs:
            q |= Q(**{f"{prefix}{f}__organisation_id__in": orgs})
    return q


def visible_projects(person):
    from accounts.selectors import representative_subject_ids, scope_to_staff_countries

    if not person or not person.is_authenticated:
        return Project.objects.none()
    if has_role(person, *STAFF):
        return scope_to_staff_countries(Project.objects.all(), person)
    q = Q(client=person) | Q(runner_person=person) | Q(pk__in=representative_subject_ids(person, "project"))
    if person.has_tenmina_role("CT", "IN", "QS", "DV"):
        q |= _panel_q(person)
    return Project.objects.filter(q).distinct()


def visible_milestones(person):
    return Milestone.objects.filter(project__in=visible_projects(person))


def visible_inspections(person):
    if not person or not person.is_authenticated:
        return Inspection.objects.none()
    if has_role(person, *STAFF):
        return Inspection.objects.filter(project__in=visible_projects(person))
    q = Q(project__client=person) | Q(inspector__person=person)
    return Inspection.objects.filter(q).distinct()


def visible_payments(person):
    from accounts.selectors import scope_to_staff_countries

    if not person or not person.is_authenticated:
        return Payment.objects.none()
    if has_role(person, *STAFF):
        return scope_to_staff_countries(Payment.objects.all(), person)
    from accounts.models import Membership

    orgs = list(Membership.objects.filter(person=person, status="active").values_list("organisation_id", flat=True))
    return Payment.objects.filter(Q(project__client=person) | Q(payee__person=person)
                                  | Q(payee__organisation_id__in=orgs)).distinct()


def visible_panel(person, country=None):
    """Staff see the whole panel; everyone else sees only active members (US-BLD-003 AC2)."""
    from accounts.selectors import scope_to_staff_countries

    qs = PanelMember.objects.all()
    if country is not None:
        qs = qs.filter(country=country)
    if has_role(person, *STAFF):
        return scope_to_staff_countries(qs, person)
    return qs.filter(status="active")


def active_panel(country, kind):
    return PanelMember.objects.filter(country=country, kind=kind, status="active")


def is_client_side(person, p: Project) -> bool:
    from accounts.selectors import is_representative

    return person.pk == p.client_id or is_representative(person, "project", p.pk)


def _evidence_items(p: Project):
    from evidence.models import EvidenceLink

    ms = {str(m.pk): m for m in p.milestones.all()}
    insp = {str(i.pk): i for i in Inspection.objects.filter(project=p)}
    links = EvidenceLink.objects.filter(
        Q(subject_type="milestone", subject_id__in=list(ms)) | Q(subject_type="milestone_inspection",
                                                                  subject_id__in=list(insp)) |
        Q(subject_type="defect", subject_id__in=list(Defect.objects.filter(project=p).values_list("pk", flat=True)))
    ).select_related("evidence").order_by("-evidence__created_at")
    out = []
    for lk in links[:200]:
        ev = lk.evidence
        if not (ev.content_type or "").startswith(("image/", "video/")):
            continue
        m = ms.get(str(lk.subject_id))
        if m is None and str(lk.subject_id) in insp:
            m = insp[str(lk.subject_id)].milestone
        out.append({"evidence_id": str(ev.pk), "kind": "video" if ev.content_type.startswith("video/") else "photo",
                    "milestone": m.name if m else "", "role": lk.role,
                    "captured_at": getattr(ev, "captured_at", None) or ev.created_at,
                    "app_captured": ev.provenance == "app_captured",
                    "preview": f"/v1/evidence/{ev.pk}/link?variant=preview",
                    "full": f"/v1/evidence/{ev.pk}/link?variant=original"})
    return out


def dashboard(p: Project, person=None) -> dict:
    """FR-BLD-009: budget against actual, each milestone's status, the photo timeline (previews first),
    inspector results and payments."""
    from . import registry

    paid = Payment.objects.filter(project=p, status="paid")
    paid_total = paid.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    live = Payment.objects.filter(project=p, status__in=Payment.LIVE)
    held_back = Decimal("0.00")
    for pay in paid.filter(part="main", holdback_amount__gt=0):
        if not Payment.objects.filter(milestone=pay.milestone, part="defect_holdback", status="paid").exists():
            held_back += pay.holdback_amount
    retention = p.milestones.filter(key="retention").exclude(status="paid").aggregate(s=Sum("amount"))["s"] or 0
    agreed_variations = Variation.objects.filter(project=p, status="agreed").aggregate(
        s=Sum("cost_change_amount"))["s"] or Decimal("0.00")
    held = None
    if p.escrow_id:
        try:
            from escrow.selectors import held_at_bank

            held = held_at_bank(p.escrow)
        except Exception:  # noqa: BLE001
            held = None
    data = {
        "project_id": str(p.pk), "title": p.title, "type": p.type, "status": p.status, "route": p.payment_route,
        "budget": {"amount": f"{p.budget_amount:.2f}", "currency": p.budget_currency},
        "guide_budget": {"amount": f"{p.guide_amount:.2f}", "currency": p.guide_currency} if p.guide_amount else None,
        "variations_agreed": {"amount": f"{agreed_variations:.2f}", "currency": p.budget_currency},
        "paid": {"amount": f"{paid_total:.2f}", "currency": p.budget_currency},
        "remaining": {"amount": f"{p.budget_amount - paid_total:.2f}", "currency": p.budget_currency},
        "defect_value_held": {"amount": f"{held_back:.2f}", "currency": p.budget_currency},
        "retention_held": {"amount": f"{Decimal(retention):.2f}", "currency": p.budget_currency},
        "held_at_bank": {"amount": f"{held:.2f}", "currency": p.budget_currency} if held is not None else None,
        "defects_period_ends_on": p.defects_period_ends_on,
        "contractor": p.contractor.name if p.contractor else None,
        "inspector": p.inspector.name if p.inspector else None,
        "milestones": [{
            "id": str(m.pk), "seq": m.seq, "key": m.key, "name": m.name, "status": m.status,
            "amount": {"amount": f"{m.amount:.2f}", "currency": m.currency},
            "paid": {"amount": f"{(Payment.objects.filter(milestone=m, status='paid').aggregate(s=Sum('amount'))['s'] or 0):.2f}",  # noqa: E501
                     "currency": m.currency},
            "needs_client": Payment.objects.filter(milestone=m, status="awaiting_client").exists(),
        } for m in p.milestones.order_by("seq")],
        "inspections": [{
            "id": str(i.pk), "milestone": i.milestone.name if i.milestone else None, "kind": i.kind,
            "status": i.status, "scheduled_for": i.scheduled_for, "outcome": i.outcome,
            "inspector": i.inspector.name if i.inspector else None, "recorded_at": i.recorded_at,
            "defect_value": {"amount": f"{i.defect_value:.2f}", "currency": i.defect_currency or p.budget_currency},
            "defects": [{"id": str(d.pk), "description": d.description, "status": d.status,
                         "value": {"amount": f"{d.value_amount:.2f}", "currency": d.value_currency}}
                        for d in i.defects.all()],
        } for i in Inspection.objects.filter(project=p).order_by("-created_at")],
        "payments": [{
            "id": str(x.pk), "label": x.label, "part": x.part, "status": x.status, "route": x.route,
            "amount": {"amount": f"{x.amount:.2f}", "currency": x.currency}, "payee": x.payee.legal_name,
            "paid_at": x.paid_at,
        } for x in Payment.objects.filter(project=p).select_related("payee").order_by("-created_at")],
        "photo_timeline": _evidence_items(p),
        "needs_action": live.filter(status="awaiting_client").exists() or Variation.objects.filter(
            project=p, status="proposed", client_agreed_at__isnull=True).exists(),
    }
    extra = registry.hook(p.type, "dashboard")
    if extra is not None:
        data.update(extra(p, person) or {})
    return data


def open_projects_of(person):
    return Project.objects.filter(client=person, status__in=["setup", "active", "paused"])
