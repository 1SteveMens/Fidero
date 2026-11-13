"""DPR event subscribers and the home dashboard provider. Idempotent."""
import logging

from accounts import home
from core.events import subscribe

from . import selectors, services
from .models import BulkExport, DataRequest, LegalHold

log = logging.getLogger(__name__)


@subscribe("person.registered")
def on_person_registered(ev):
    """FR-DPR-001: record the notice version accepted at sign-up."""
    from accounts.models import Person

    version = ev.payload.get("privacy_notice_version")
    p = Person.objects.filter(pk=ev.payload.get("person_id")).first()
    if p is None or not version:
        return
    try:
        services.accept_notice(p, version, source=ev.payload.get("source", "signup"), ip=ev.payload.get("ip", ""))
    except Exception:  # noqa: BLE001 - a stale version is asked for again at next sign-in
        log.warning("privacy notice version %s not recorded for %s", version, p.pk)


@subscribe("approval.approved", "approval.rejected")
def on_approval_closed(ev):
    st = ev.payload.get("subject_type")
    sid = ev.payload.get("subject_id")
    approved = ev.topic == "approval.approved"
    if st == "legal_hold":
        h = LegalHold.objects.filter(pk=sid, status="lift_pending").first()
        if h is not None:
            services.apply_lift(h, approved)
    elif st == "bulk_export":
        be = BulkExport.objects.filter(pk=sid, status="pending_approval").first()
        if be is None:
            return
        if approved:
            services.produce_bulk_export(be)
        else:
            from core import state

            state.transition(be, "bulk_export", "rejected")


@home.register
def dpr_home_items(person):
    out = []
    version = selectors.pending_notice_version(person)
    if version:
        out.append(home.item(kind="privacy_notice", id=person.pk, title="Read the updated privacy notice",
                             status="pending", needs_action=True, link="/account/privacy",
                             status_text=f"Version {version} explains how we use your data. Accept it to continue."))
    for r in DataRequest.objects.filter(subject=person, status__in=["open", "in_progress", "waiting"]):
        text = {"waiting": "Your account is closed to new orders. We delete the rest when open matters end.",
                "open": "We have your request and will answer by the due date.",
                "in_progress": "We are working on your request."}[r.status]
        out.append(home.item(kind="data_request", id=r.pk, title=f"Your {r.type} request", status=r.status,
                             status_text=text, next_date=r.due_on, link=f"/account/data-requests/{r.pk}"))
    return out
