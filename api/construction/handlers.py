"""BLD event subscribers and registry hooks. Idempotent: each acts only on objects still waiting."""
from datetime import datetime, time

from accounts import home
from core.events import subscribe
from dataprotection import registry as dpr
from escrow import registry as esc_registry
from evidence import access
from mobile import inbox

from . import materials, milestones, payments  # noqa: F401 - registers the payment subjects


# ----------------------------------------------------------------- MOB (sequence 5.4)

@subscribe("submission.received")
def on_submission(ev):
    milestones.on_submission(ev.payload or {})


@subscribe("flags.cleared")
def on_flags_cleared(ev):
    milestones.on_flags_cleared(ev.payload or {})


# ----------------------------------------------------------------- ESC

@subscribe("release.client_approved", "release.approved", "release.confirmed", "release.withdrawn",
           "release.rejected", "release.rejected_by_bank")
def on_release(ev):
    payments.on_instruction_event(ev.topic, ev.payload or {})


@subscribe("escrow.funded")
def on_escrow_funded(ev):
    from . import projects

    projects.on_escrow_funded(ev.payload or {})


for _st in ("milestone", "offplan_stage"):
    esc_registry.register_subject_check(_st, payments.escrow_subject_check)
    esc_registry.subject_label(_st, payments.label_for)


@subscribe("approval.approved", "approval.rejected")
def on_approval(ev):
    """client_direct payments: two staff confirmed (or one rejected)."""
    if (ev.payload or {}).get("subject_type") not in ("milestone_release", "project_release"):
        return
    payments.on_direct_approval(ev.payload.get("subject_id"), ev.topic == "approval.approved")


# ----------------------------------------------------------------- other modules

@subscribe("dispute.opened")
def on_dispute_opened(ev):
    milestones.on_dispute(ev.payload or {}, opened=True)


@subscribe("dispute.resolved", "dispute.withdrawn", "dispute.closed")
def on_dispute_closed(ev):
    milestones.on_dispute(ev.payload or {}, opened=False)


@subscribe("order.paid")
def on_order_paid(ev):
    milestones.order_extra_inspection(ev.payload or {})


@subscribe("case.status_changed")
def on_case(ev):
    from . import panel

    p = ev.payload or {}
    panel.on_check_case(p)
    if p.get("product_line") == "offplan_check" and p.get("subject_type") == "bld_project" \
            and p.get("status") == "completed":
        from .common import alert_staff, notify
        from .models import Project

        proj = Project.objects.filter(pk=p.get("subject_id")).first()
        if proj is None:
            return
        if p.get("outcome") == "verified":
            notify(proj.client, "case_status_changed", f"The developer's title, permits and company for {proj.title} "
                                                       "were verified.", obj=proj, link=f"/projects/{proj.pk}")
        else:
            notify(proj.client, "case_status_changed", f"The developer's checks for {proj.title} failed. No money "
                                                       "can be held for this purchase.", obj=proj,
                   link=f"/projects/{proj.pk}")
            alert_staff(proj.country, ("CM",), "offplan_failed", f"The off-plan check for {proj.title} failed.",
                        obj=proj)


@subscribe("fx_rate.updated")
def on_rate(ev):
    milestones.on_guide_rate(ev.payload or {})


# ----------------------------------------------------------------- Tenmina Field inbox (FR-MOB-001)

def _site(p):
    a = p.asset
    if a is None:
        return None, [], ""
    point, boundary = None, []
    b = a.current_boundary
    if b is not None:
        point = (round(b.centroid.y, 6), round(b.centroid.x, 6))
        try:
            ring = b.geom[0][0]
            boundary = [[round(y, 6), round(x, 6)] for x, y in ring.coords]
        except Exception:  # noqa: BLE001
            boundary = []
    elif a.location is not None:
        point = (round(a.location.y, 6), round(a.location.x, 6))
    address = ", ".join(x for x in (a.name, a.plot_number, a.locality) if x)
    return point, boundary, address


@inbox.register
def field_work(person):
    from .models import Inspection, Milestone

    if not person.has_tenmina_role("CT", "IN", "DV"):
        return
    if person.has_tenmina_role("CT", "DV"):
        from django.db.models import Q

        from accounts.models import Membership

        orgs = list(Membership.objects.filter(person=person, status="active").values_list("organisation_id",
                                                                                          flat=True))
        q = Q(project__contractor__person=person)
        if orgs:
            q |= Q(project__contractor__organisation_id__in=orgs)
        for m in Milestone.objects.filter(q, project__status="active", project__type__in=[
                "construction", "completion", "offplan"], status__in=["not_started", "returned"]) \
                .select_related("project", "project__asset", "project__asset__current_boundary"):
            ok, why = milestones.submission_state(m)
            if not ok:
                continue
            point, boundary, address = _site(m.project)
            prev = Milestone.objects.filter(project=m.project, seq__lt=m.seq, inspected_at__isnull=False) \
                .order_by("-seq").first()
            yield inbox.InboxItem(subject_type="milestone", subject_id=m.pk, title=m.label, kind="milestone",
                                  country=m.country, address=address, point=point, boundary=boundary, buffer_m=50,
                                  required_evidence=m.required_evidence or [], project_key=str(m.project_id),
                                  previous_pass_at=prev.inspected_at if prev else None,
                                  details={"return_reasons": m.return_reasons[-1:] if m.return_reasons else []},
                                  updated_at=m.updated_at)
    if person.has_tenmina_role("IN"):
        for i in Inspection.objects.filter(inspector__person=person, status="scheduled") \
                .select_related("project", "project__asset", "project__contractor", "milestone"):
            point, boundary, address = _site(i.project)
            title = f"Inspect {i.milestone.name if i.milestone else 'the build'}, {i.project.title}"
            due = datetime.combine(i.scheduled_for, time(17, 0)) if i.scheduled_for else None
            yield inbox.InboxItem(
                subject_type="milestone_inspection", subject_id=i.pk, title=title, kind="inspection",
                country=i.country, address=address, point=point, radius_m=150, boundary=boundary, buffer_m=50,
                checklist=i.checklist or [], project_key=str(i.project_id), due_at=due,
                details={"independence": "You have no link to this contractor.",
                         "contractor": i.project.contractor.name if i.project.contractor else "",
                         "concern": i.concern, "kind": i.kind}, updated_at=i.updated_at)


# ----------------------------------------------------------------- client home (FR-ACC-012)

@home.register
def project_home_items(person):
    from .models import Payment, Project, Variation

    out = []
    for p in Project.objects.filter(client=person, status__in=["setup", "active", "paused"]).order_by("-created_at"):
        waiting = Payment.objects.filter(project=p, status="awaiting_client").first()
        paying = Payment.objects.filter(project=p, status="release_approved", route="client_direct",
                                        client_paid_at__isnull=True).first()
        var = Variation.objects.filter(project=p, status="proposed", client_agreed_at__isnull=True).first()
        budget = p.status == "setup" and not p.budget_approved_at and p.boqs.filter(status="submitted").exists()
        if waiting:
            text = f"Approve {waiting.label}. Nothing is paid until you approve."
        elif paying:
            text = f"Tenmina checked {paying.label}. Pay the builder's verified account."
        elif var:
            text = "A change to the work needs your agreement."
        elif budget:
            text = "Your budget is ready. Please review and approve it."
        else:
            text = {"setup": "Setting up your project.", "active": "Building. Every stage is inspected first.",
                    "paused": "On hold. Your case manager will call you."}[p.status]
        out.append(home.item(kind="project", id=p.pk, title=p.title, status=p.status, status_text=text,
                             needs_action=bool(waiting or paying or var or budget), link=f"/projects/{p.pk}",
                             line="funds" if p.type == "funds" else "construction",
                             amount={"amount": f"{p.budget_amount:.2f}", "currency": p.budget_currency}))
    return out


# ----------------------------------------------------------------- evidence access

def _project_of(subject_type, sid):
    from .models import Defect, Inspection, MaterialsOrder, Milestone, Payment, Project, Variation

    model = {"bld_project": Project, "milestone": Milestone, "milestone_inspection": Inspection, "defect": Defect,
             "bld_variation": Variation, "bld_payment": Payment, "bld_materials_order": MaterialsOrder,
             "panel_member": None}[subject_type]
    if model is None:
        return None
    obj = model.objects.filter(pk=sid).first()
    if obj is None:
        return None
    return obj if isinstance(obj, Project) else obj.project


def _can_view(subject_type):
    def fn(user, sid):
        from .selectors import visible_projects

        p = _project_of(subject_type, sid)
        return p is not None and visible_projects(user).filter(pk=p.pk).exists()

    return fn


def _can_attach(subject_type):
    def fn(user, sid):
        from core.permissions import has_role

        p = _project_of(subject_type, sid)
        if p is None:
            return False
        if has_role(user, "CM", "RV", country=p.country):
            return True
        return subject_type in ("bld_payment",) and user.pk == p.client_id

    return fn


def _country_of(subject_type):
    def fn(sid):
        p = _project_of(subject_type, sid)
        return p.country if p else None

    return fn


for _st in ("bld_project", "milestone", "milestone_inspection", "defect", "bld_variation", "bld_payment",
            "bld_materials_order"):
    access.register(_st, can_view=_can_view(_st), can_attach=_can_attach(_st), country=_country_of(_st),
                    owner=lambda sid, _s=_st: ("bld_project", getattr(_project_of(_s, sid), "pk", None)))


def _panel_view(user, sid):
    from core.permissions import has_role

    from .models import PanelMember

    m = PanelMember.objects.filter(pk=sid).first()
    return m is not None and (has_role(user, "CM", "RV", "AD", country=m.country) or m.person_id == user.pk)


def _panel_country(sid):
    from .models import PanelMember

    m = PanelMember.objects.filter(pk=sid).first()
    return m.country if m else None


access.register("panel_member", can_view=_panel_view,
                can_attach=lambda user, sid: _panel_view(user, sid) and user.has_tenmina_role("CM", "RV", "AD"),
                country=_panel_country)


# ----------------------------------------------------------------- representatives and data protection

def _owner(person, sid):
    from .models import Project

    return Project.objects.filter(pk=sid, client=person).exists()


def _register_owner():
    from accounts.services import register_owner_check

    register_owner_check("project", _owner)


_register_owner()


@dpr.open_matters
def open_projects(person):
    from .models import Payment, Project

    out = []
    for p in Project.objects.filter(client=person, status__in=["setup", "active", "paused"]):
        live = Payment.objects.filter(project=p, status__in=Payment.LIVE).exists()
        if p.escrow_id or live or p.status == "active":
            out.append({"kind": "project", "id": str(p.pk), "title": p.title,
                        "reason": "A building or project with stage payments is still open."})
    return out


@dpr.exporter("projects")
def export_projects(person):
    from .models import Payment, Project, Variation

    out = []
    for p in Project.objects.filter(client=person):
        out.append({"id": str(p.pk), "title": p.title, "type": p.type, "status": p.status,
                    "budget": f"{p.budget_amount:.2f} {p.budget_currency}", "created_at": p.created_at.isoformat(),
                    "milestones": [{"name": m.name, "status": m.status, "amount": f"{m.amount:.2f}"}
                                   for m in p.milestones.order_by("seq")],
                    "variations": [{"description": v.description, "status": v.status,
                                    "cost_change": f"{v.cost_change_amount:.2f}"}
                                   for v in Variation.objects.filter(project=p)],
                    "payments": [{"label": x.label, "status": x.status, "amount": f"{x.amount:.2f}",
                                  "payee": x.payee.legal_name} for x in Payment.objects.filter(project=p)]})
    return {"projects": out}
