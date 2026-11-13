"""CASE event subscribers and registrations. Every handler is idempotent and never raises a domain error
back into the producer's transaction (a paid order must stay paid even if its case cannot open yet).

Consumes: order.paid, listing.verification_requested, reservation.created, report.released,
national_id_check.completed, asset.dispute_flag_changed, submission.received, flags.cleared,
order.refunded.
Registers: client home items, field inbox items, evidence access for case, task and search_request,
data protection open matters and exporter, the owner check for representatives.
"""
import logging
import uuid

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)


def _uuid(v):
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


def _alert_unopened(order_id, reason):
    from orders.models import Order

    from . import services

    order = Order.objects.filter(pk=order_id).select_related("country").first()
    if order is None:
        return
    services._alert(order.country, ("CM",), subject=f"Order {order.reference} is paid but has no case",
                    body=f"Order {order.reference} is paid but its case could not open: {reason}",
                    link=f"/orders/{order.pk}")
    from audit.services import record

    record(action="case.open_failed", entity="order", entity_id=order.pk, country=order.country,
           data={"reason": reason})


@subscribe("order.paid")
def on_order_paid(ev):
    """FR-CASE-001, 02 7.12 cases.create_from_order."""
    from . import services

    oid = _uuid(ev.payload.get("order_id"))
    if not oid or ev.payload.get("product_line") not in ("land", "building", "fresh_search"):
        return
    try:
        with transaction.atomic():
            services.create_from_order(oid)
    except DomainError as exc:
        _alert_unopened(oid, exc.detail)


@subscribe("listing.verification_requested")
def on_listing_verification(ev):
    from . import services

    oid = _uuid(ev.payload.get("order_id"))
    if not oid:
        return
    try:
        with transaction.atomic():
            services.create_from_order(oid)
    except DomainError as exc:
        _alert_unopened(oid, exc.detail)


@subscribe("reservation.created")
def on_reservation(ev):
    """RUL-14, RUL-07: a reservation starts a fresh search on the plot."""
    from geo.models import Asset

    from . import services

    asset = Asset.objects.filter(pk=_uuid(ev.payload.get("asset_id"))).first()
    if asset is None:
        return
    try:
        with transaction.atomic():
            services.open_fresh_search(asset, origin="reservation",
                                       origin_ref=_uuid(ev.payload.get("reservation_id")) or ev.aggregate_id)
    except DomainError as exc:
        log.warning("reservation %s: fresh search not started: %s", ev.payload.get("reservation_id"), exc.detail)


@subscribe("report.released")
def on_report_released(ev):
    from . import services

    p = ev.payload
    if p.get("case_id"):
        services.on_report_released(_uuid(p["case_id"]), report_id=p.get("report_id"),
                                    correction=bool(p.get("supersedes_id")))


@subscribe("national_id_check.completed")
def on_national_id(ev):
    from . import services

    services.note_national_id_result(ev.payload)


@subscribe("asset.dispute_flag_changed")
def on_dispute_flag(ev):
    from . import services

    if ev.payload.get("disputed") and ev.payload.get("asset_id"):
        services.recheck_disputed(_uuid(ev.payload["asset_id"]))


@subscribe("submission.received", "flags.cleared")
def on_field_submission(ev):
    """Tenmina Field evidence for a case task: close the task when it has everything (FR-CASE-006)."""
    from accounts.models import Person

    from . import services

    p = ev.payload
    if p.get("subject_type") != "task" or p.get("flagged") or p.get("outcome") == "upheld":
        return
    person = Person.objects.filter(pk=_uuid(p.get("person_id"))).first()
    if person is not None:
        services.try_complete_from_field(_uuid(p.get("subject_id")), person)


@subscribe("order.refunded")
def on_order_refunded(ev):
    """A fee refunded outside a case cancellation closes the case that has not been released."""
    from .models import Case

    c = Case.objects.filter(order_id=_uuid(ev.payload.get("order_id")),
                            status__in=["paid", "in_progress", "on_hold"]).first()
    if c is None:
        return
    from core import state

    from . import services

    with transaction.atomic():
        c.cancel_reason, c.refund_decision = "The fee was refunded.", "refund"
        services._close_work(c, None, "Fee refunded")
        state.transition(c, "case", "cancelled", reason=c.cancel_reason,
                         payload=services.case_payload(c) | {"status": "cancelled"},
                         extra_fields=["cancel_reason", "refund_decision"])


# --------------------------------------------------------------------------- registries

def _register():
    from accounts import home
    from accounts.services import register_owner_check
    from dataprotection import registry
    from evidence import access
    from mobile import inbox

    from . import services
    from .models import Case, DocumentRequest, SearchRequest, Task

    def _case(sid):
        return Case.objects.filter(pk=sid).select_related("country").first()

    def _task(sid):
        return Task.objects.filter(pk=sid).select_related("case", "case__country").first()

    access.register(
        "case",
        can_view=lambda u, sid: (lambda c: c is not None and services.can_view(u, c))(_case(sid)),
        can_attach=lambda u, sid: (lambda c: c is not None and (services.is_case_staff(u, c) or services.is_client(
            u, c) or services.is_assigned(u, c)))(_case(sid)),
        country=lambda sid: _case(sid).country, owner=lambda sid: ("case", sid))
    access.register(
        "task",
        can_view=lambda u, sid: (lambda t: t is not None and services.can_work_on(u, t))(_task(sid)),
        can_attach=lambda u, sid: (lambda t: t is not None and services.can_work_on(u, t))(_task(sid)),
        country=lambda sid: _task(sid).case.country, owner=lambda sid: ("case", _task(sid).case_id))
    access.register(
        "search_request",
        can_view=lambda u, sid: (lambda s: s is not None and services.is_case_staff(u, s.case))(
            SearchRequest.objects.filter(pk=sid).select_related("case").first()),
        can_attach=lambda u, sid: (lambda s: s is not None and services.is_search_staff(u, s.country))(
            SearchRequest.objects.filter(pk=sid).first()),
        country=lambda sid: SearchRequest.objects.get(pk=sid).country,
        owner=lambda sid: ("case", SearchRequest.objects.get(pk=sid).case_id))

    register_owner_check("case", lambda person, sid: Case.objects.filter(pk=sid, client=person).exists())

    @home.register
    def case_items(person):
        out = []
        for c in Case.objects.filter(client=person).exclude(status="cancelled").order_by("-created_at")[:20]:
            last = c.status_messages.order_by("-created_at").first()
            out.append(home.item(kind="case", id=c.pk, title=c.title or c.reference, status=c.status,
                                 status_text=last.text if last else "", needs_action=False,
                                 next_date=last.next_expected_date if last else None, link=f"/cases/{c.pk}",
                                 line="property" if c.asset_id else "family"))
        for r in DocumentRequest.objects.filter(case__client=person, status="open").select_related("case"):
            out.append(home.item(kind="document_request", id=r.pk, title=f"Send: {r.title}", status="open",
                                 status_text=f"Your case manager needs this for case {r.case.reference}.",
                                 next_date=r.due_on, needs_action=True,
                                 link=f"/cases/{r.case_id}/document-requests/{r.pk}", line="property"))
        return out

    @inbox.register
    def task_items(person):
        from .templates import SEARCH_NOTICE

        qs = Task.objects.filter(status__in=["open", "in_progress"], case__status="in_progress").filter(
            assignee=person) | Task.objects.filter(status__in=["open", "in_progress"], case__status="in_progress",
                                                   second_assignee=person)
        for t in qs.select_related("case", "case__asset", "case__country"):
            asset = t.case.asset
            waiting = services.waiting_for(t)
            details = {"case_ref": t.case.reference, "step_key": t.step_key, "role": t.owner_role}
            if t.site_visit or t.search_kind or t.case.product_line in ("land", "building", "fresh_search"):
                details["notice"] = SEARCH_NOTICE
            if t.site_visit:
                details["risk_screen_required"] = True
            point = None
            if asset is not None and asset.location is not None:
                point = (asset.location.y, asset.location.x)
            yield inbox.InboxItem(
                subject_type="task", subject_id=str(t.pk), title=f"{t.title} ({t.case.reference})", kind="case_task",
                country=t.case.country, address=", ".join(x for x in (asset.locality, asset.address) if x)
                if asset else "", point=point,
                required_evidence=[{"key": k, "label": k.replace("_", " ").capitalize(),
                                    "media": "video" if k.endswith("video") else
                                    "photo" if services.PHOTO_KINDS.search(k) else "document", "required": True}
                                   for k in t.required_evidence],
                accepts_submissions=not waiting, state_reason=f"Waiting for: {', '.join(waiting)}" if waiting else "",
                due_at=t.due_at, details=details, updated_at=t.updated_at)

    @registry.open_matters
    def open_cases(person):
        return [{"kind": "case", "id": str(c.pk), "title": c.title or c.reference,
                 "reason": "This verification case is still open."}
                for c in Case.objects.filter(client=person, status__in=["paid", "in_progress", "on_hold",
                                                                        "in_review"])]

    @registry.exporter("cases")
    def export_cases(person):
        out = []
        for c in Case.objects.filter(client=person).order_by("created_at"):
            out.append({
                "reference": c.reference, "title": c.title, "status": c.status, "created_at": c.created_at.isoformat(),
                "status_messages": [{"date": m.message_date.isoformat(), "text": m.text}
                                    for m in c.status_messages.all()],
                "messages": [{"at": m.created_at.isoformat(), "from": m.side, "body": m.body}
                             for m in c.messages.all()],
                "document_requests": [{"title": r.title, "status": r.status} for r in c.document_requests.all()],
            })
        return out


_register()
