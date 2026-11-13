"""EVD event subscribers. Idempotent: each looks up current state first."""
from django.utils.dateparse import parse_datetime

from core.events import subscribe

from .models import Evidence


@subscribe("evidence.stored")
def make_previews(ev):
    """Job evidence.make_previews (02 section 7.12), run inline in development."""
    from .services import make_previews as run

    e = Evidence.objects.filter(pk=ev.payload.get("evidence_id")).first()
    if e is not None and e.scan_status == "clean":
        run(e)


@subscribe("report.released")
def register_released_report(ev):
    """A released report's PDF becomes an issued document whose fingerprint anyone can check.
    Expects `pdf_evidence_id` (or `evidence_id`) and `report_id` (or `id`) in the payload."""
    from .services import register_issued

    p = ev.payload
    eid = p.get("pdf_evidence_id") or p.get("evidence_id")
    rid = p.get("report_id") or p.get("id")
    e = Evidence.objects.filter(pk=eid).first() if eid else None
    if e is None or not rid:
        return
    when = parse_datetime(p["released_at"]) if p.get("released_at") else None
    register_issued(e, "report", rid, kind="report_pdf", issued_at=when)
