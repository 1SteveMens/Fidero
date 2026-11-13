"""Demo evidence: a client's site plan, a runner's uploaded photo, a released report PDF whose
fingerprint can be checked, a link opened by the client, and a clean integrity run.
Subjects are fixed UUIDs other module seeds can link to (ctx["evidence"])."""
import uuid

from .models import Evidence, IntegrityRun

NS = uuid.UUID("6f1c3a52-6a51-4c55-9a43-0d1f5e7e0a01")


def sid(name: str) -> uuid.UUID:
    return uuid.uuid5(NS, name)


PDF = (b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [] /Count 0 >>"
       b" endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n")


def _once(key, make):
    ev = Evidence.objects.filter(description=f"seed:{key}").first()
    return ev or make()


def run(ctx):
    from mobile.devtools import jpeg

    from . import services

    gh, p = ctx["gh"], ctx["people"]
    order_id, report_id, case_id = sid("order-ama-east-legon"), sid("report-ama-east-legon"), sid("case-ama")

    site_plan = _once("site-plan", lambda: services.store(
        data=PDF + b"% site plan, East Legon plot 14 [demo]\n", country=gh, uploaded_by=p["client"],
        content_type="application/pdf", original_name="site-plan-east-legon.pdf", source="upload",
        description="seed:site-plan", owner_type="order", owner_id=order_id))
    services.link(site_plan, "order", order_id, role="site_plan", by=p["client"])

    photo = _once("runner-photo", lambda: services.store(
        data=jpeg("seed-runner-photo", model="SM-A045F"), country=gh, uploaded_by=p["runner"],
        content_type="image/jpeg", original_name="gate-and-beacon.jpg", source="upload",
        description="seed:runner-photo", owner_type="case", owner_id=case_id, latitude="5.650120",
        longitude="-0.180310"))
    services.link(photo, "case", case_id, role="site_photo", by=p["runner"])

    report_pdf = _once("report-pdf", lambda: services.store(
        data=PDF + b"% Tenmina verification report, East Legon plot 14, verdict Green [demo]\n", country=gh,
        uploaded_by=p["reviewer"], content_type="application/pdf", original_name="tenmina-report-TM-0001.pdf",
        source="generated", description="seed:report-pdf", owner_type="case", owner_id=case_id))
    services.link(report_pdf, "report", report_id, role="released_report", by=p["reviewer"])
    services.register_issued(report_pdf, "report", report_id, kind="report_pdf", by=p["reviewer"])

    if not report_pdf.access_log.exists():
        services.issue_link(report_pdf, p["reviewer"])
    if not IntegrityRun.objects.exists():
        services.integrity_sample(size=10, seed="seed-run", by=p["admin"])

    ctx["evidence"] = {"site_plan": site_plan, "runner_photo": photo, "report_pdf": report_pdf,
                       "order_id": order_id, "report_id": report_id, "case_id": case_id}
