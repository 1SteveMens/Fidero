"""PRJ event subscribers and registry hooks."""
from construction import payments
from construction import registry as bld_registry
from core.events import subscribe
from escrow import registry as esc_registry
from evidence import access

from . import services

bld_registry.register_type("funds", create=services.create_fund_project, start_blockers=services.funding_blockers,
                           dashboard=services.dashboard_extra)
esc_registry.register_subject_check("project_invoice", payments.escrow_subject_check)
esc_registry.subject_label("project_invoice", payments.label_for)


@subscribe("case.status_changed")
def on_case(ev):
    services.on_supplier_case(ev.payload or {})


@subscribe("milestone.status_changed")
def on_stage(ev):
    services.on_stage_confirmed(ev.payload or {})


@subscribe("payee.verified")
def on_payee_verified(ev):
    """A supplier's account was verified by two staff: the project may now start (client_direct)."""
    from construction import projects

    from .models import Supplier

    p = ev.payload or {}
    s = Supplier.objects.filter(pk=p.get("subject_id")).first() if p.get("subject_type") == "supplier" else None
    if s is not None:
        projects._try_start(s.project, None)


def _project_of(subject_type, sid):
    from .models import AmlReview, BackgroundCheck, Invoice, Supplier

    model = {"prj_supplier": Supplier, "prj_invoice": Invoice, "prj_background_check": BackgroundCheck,
             "prj_aml_review": AmlReview}[subject_type]
    obj = model.objects.filter(pk=sid).first()
    return obj.project if obj else None


def _can_view(subject_type):
    def fn(user, sid):
        from construction.selectors import visible_projects
        from core.permissions import has_role

        p = _project_of(subject_type, sid)
        if p is None:
            return False
        if subject_type in ("prj_background_check", "prj_aml_review"):
            return has_role(user, "CM", "RV", country=p.country)
        return visible_projects(user).filter(pk=p.pk).exists()

    return fn


def _can_attach(subject_type):
    def fn(user, sid):
        from core.permissions import has_role

        p = _project_of(subject_type, sid)
        if p is None:
            return False
        if has_role(user, "CM", "RV", country=p.country):
            return True
        # The client or the runner may attach an invoice file to a named supplier before submitting it
        # (FR-PRJ-003): the invoice itself does not exist until the file is stored.
        return subject_type in ("prj_invoice", "prj_supplier") and user.pk in (p.client_id, p.runner_person_id)

    return fn


for _st in ("prj_supplier", "prj_invoice", "prj_background_check", "prj_aml_review"):
    access.register(_st, can_view=_can_view(_st), can_attach=_can_attach(_st),
                    country=lambda sid, _s=_st: getattr(_project_of(_s, sid), "country", None),
                    owner=lambda sid, _s=_st: ("bld_project", getattr(_project_of(_s, sid), "pk", None)))
