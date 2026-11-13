"""Materials ordered in bulk for a build (FR-BLD-013, R3, kept simple). The supplier is a verified payee; the
bank pays it from the project's escrow (or the client pays it directly on the launch route) after the client
and two staff approve. Deliveries are shown on the dashboard with app-captured evidence."""
from django.db import transaction

from core import state
from core.errors import Forbidden, Invalid, NotFound, StateConflict
from core.money import q
from core.permissions import has_role

from . import payments
from .common import audit, evidence_objects, fmt, link_all, notify, now, require_on
from .models import MaterialsOrder, Milestone


@transaction.atomic
def request_materials(p, by, *, milestone_id, supplier_payee_id, description, amount, quote_evidence_ids,
                      items=()) -> MaterialsOrder:
    from escrow.models import Payee

    require_on(p.type, p.country)
    if not has_role(by, "CM", country=p.country):
        raise Forbidden("A case manager orders materials.")
    if not p.is_build or p.status != "active":
        raise StateConflict("Materials are ordered for an active build.")
    m = Milestone.objects.filter(pk=milestone_id, project=p).first()
    if m is None or m.status == "paid":
        raise Invalid("Choose a milestone that is not yet paid.", code="validation-error")
    payee = Payee.objects.filter(pk=supplier_payee_id, country=p.country, kind="supplier").first()
    if payee is None:
        raise NotFound("That supplier is not in the payee registry.")
    if not (description or "").strip():
        raise Invalid("Describe the materials.", code="validation-error")
    evidence = evidence_objects(quote_evidence_ids, by, p.country, what="supplier's quote")
    o = MaterialsOrder.objects.create(country=p.country, project=p, milestone=m, supplier_payee=payee,
                                      description=description.strip(), items=list(items or []), amount=q(amount),
                                      currency=p.budget_currency, quote_evidence=evidence[0], requested_by=by)
    link_all(evidence, "bld_materials_order", o.pk, "quote", by)
    payments.prepare(p, part="materials", subject_type="milestone", subject_id=o.pk, payee=payee, amount=o.amount,
                     by=by, milestone=m, label=f"Materials for {m.name}: {o.description}")
    audit(by, "materials.requested", o, {"amount": f"{o.amount:.2f}"})
    return o


def approve_materials(o: MaterialsOrder, client, **kw):
    """The client approves the materials payment (RUL-11)."""
    from .models import Payment

    pay = Payment.objects.filter(subject_id=o.pk, part="materials", status="awaiting_client").first()
    if pay is None:
        raise StateConflict("This order is not waiting for your approval.")
    return payments.client_approve(pay, client, **kw)


@transaction.atomic
def record_delivery(o: MaterialsOrder, by, *, evidence_ids, note="") -> MaterialsOrder:
    from evidence.models import Evidence

    p = o.project
    if not has_role(by, "CM", "RV", country=p.country) and not (p.inspector and p.inspector.person_id == by.pk):
        raise NotFound()
    if o.status != "paid":
        raise StateConflict("A delivery is recorded once the supplier is paid.")
    evidence = evidence_objects(evidence_ids, by, p.country, what="delivery photos")
    weak = [e for e in evidence if not Evidence.objects.get(pk=e.pk).is_release_grade]
    if weak:
        raise Invalid("Delivery photos must be taken in Tenmina Field.", code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-08", "message": "Not app-captured."}])
    link_all(evidence, "bld_materials_order", o.pk, "delivery_photo", by)
    o.delivered_at, o.delivery_evidence_ids = now(), [str(e.pk) for e in evidence]
    state.transition(o, "bld_materials_order", "delivered", actor=by, reason=note,
                     extra_fields=["delivered_at", "delivery_evidence_ids"], payload={"project_id": p.pk})
    notify(p.client, "milestone_update", f"The materials for {o.milestone.name} were delivered: {o.description}.",
           obj=o, link=f"/projects/{p.pk}")
    return o


def _blockers(pay, stage):
    o = MaterialsOrder.objects.filter(pk=pay.subject_id).first()
    if o is None:
        return [{"rule": "FR-BLD-013", "code": "subject-unknown", "message": "The materials order is missing."}]
    out = []
    if o.status not in ("requested", "approved"):
        out.append({"rule": "FR-BLD-013", "code": "materials-state", "message": f"The order is {o.status}."})
    if q(o.amount) != q(pay.amount) or o.supplier_payee_id != pay.payee_id:
        out.append({"rule": "RUL-22", "code": "amount-mismatch", "message": "The payment must match the order."})
    if o.milestone.status == "frozen":
        out.append({"rule": "RUL-15", "code": "milestone-frozen", "message": "The milestone is frozen."})
    return out


def _on_status(pay, to):
    o = MaterialsOrder.objects.select_for_update().filter(pk=pay.subject_id).first()
    if o is None:
        return
    if to == "client_approved" and o.status == "requested":
        state.transition(o, "bld_materials_order", "approved", payload={"project_id": o.project_id})
    elif to == "paid" and o.status == "approved":
        state.transition(o, "bld_materials_order", "paid", payload={"project_id": o.project_id})
        notify(o.project.client, "money_update", f"The supplier was paid {fmt(pay.amount, pay.currency)} for "
                                                 f"{o.description}.", obj=o, link=f"/projects/{o.project_id}")
    elif to in ("withdrawn", "rejected") and o.status in ("requested", "approved"):
        state.transition(o, "bld_materials_order", "cancelled", reason=pay.closed_reason,
                         payload={"project_id": o.project_id})


payments.register_subject("materials", blockers=_blockers, on_status=_on_status)
