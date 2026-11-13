"""RPT event subscribers and registrations. Every handler is idempotent.

Consumes: case.status_changed (a land or building case in progress gets its report), overlay.completed
(section 7 proposal), condition.closed (re-check population), approval.approved and approval.rejected
(subject report_release).
Registers: evidence access for `report`, the client's home items for released reports, the field inbox
for re-checks, and the data protection exporter.
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


@subscribe("case.status_changed")
def on_case_status(ev):
    from cases.models import Case

    from . import services

    p = ev.payload
    if p.get("to") != "in_progress" or p.get("product_line") not in services.REPORT_LINES:
        return
    case = Case.objects.filter(pk=_uuid(p.get("case_id") or p.get("id"))).first()
    if case is None:
        return
    try:
        with transaction.atomic():
            services.create_report(case)
    except DomainError as exc:
        from cases.services import _alert

        _alert(case.country, ("CM",), subject=f"No report could be built for {case.reference}", body=exc.detail,
               obj=case, link=f"/cases/{case.pk}")


@subscribe("overlay.completed")
def on_overlay(ev):
    from . import services

    if ev.payload.get("asset_id"):
        services.refresh_geo(_uuid(ev.payload["asset_id"]))


@subscribe("condition.closed")
def on_condition_closed(ev):
    from . import services

    services.note_condition_closed(ev.payload)


@subscribe("approval.approved", "approval.rejected")
def on_approval(ev):
    from . import services

    if ev.payload.get("subject_type") != "report_release":
        return
    services.on_approval_closed(_uuid(ev.payload.get("subject_id")), ev.topic == "approval.approved")


def _register():
    from accounts import home
    from dataprotection import registry
    from evidence import access
    from mobile import inbox

    from . import services
    from .models import Recheck, Report

    def _r(sid):
        return Report.objects.filter(pk=sid).select_related("case", "country").first()

    def can_attach(u, sid):
        r = _r(sid)
        if r is None or r.status != "draft":
            return False
        return any(services.can_edit_section(u, r, s) for s in r.sections.all())

    access.register("report", can_view=lambda u, sid: (lambda r: r is not None and services.can_view(u, r))(_r(sid)),
                    can_attach=can_attach, country=lambda sid: _r(sid).country,
                    owner=lambda sid: ("case", _r(sid).case_id))

    @home.register
    def report_items(person):
        return [home.item(kind="report", id=r.pk, title=f"Report {r.reference}", status="released",
                          status_text=f"Released on {r.released_at:%d %B %Y}.", needs_action=False,
                          link=f"/reports/{r.pk}", line="property")
                for r in Report.objects.filter(case__client=person, status="released").select_related("case")]

    @inbox.register
    def recheck_items(person):
        for r in Recheck.objects.filter(assignee=person, status="assigned").select_related("case", "country"):
            yield inbox.InboxItem(subject_type="recheck", subject_id=str(r.pk), title="Independent re-check",
                                  kind="recheck", country=r.country, due_at=r.due_at, accepts_submissions=False,
                                  details={"case_ref": r.case.reference, "subject_type": r.subject_type})

    @registry.exporter("reports")
    def export_reports(person):
        return [{"reference": r.reference, "version": r.version, "status": r.status,
                 "released_at": r.released_at.isoformat() if r.released_at else None, "pdf_sha256": r.pdf_sha256}
                for r in Report.objects.filter(case__client=person, status__in=["released", "superseded"])]


_register()
