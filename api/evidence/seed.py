"""Demo evidence: a client's site plan, a runner's uploaded photo, a released report PDF whose
fingerprint can be checked, a link opened by the client, and a clean integrity run.
Subjects are fixed UUIDs other module seeds can link to (ctx["evidence"])."""
import uuid

from .models import Evidence, IntegrityRun

NS = uuid.UUID("6f1c3a52-6a51-4c55-9a43-0d1f5e7e0a01")


def sid(name: str) -> uuid.UUID:
    return uuid.uuid5(NS, name)


def _once(key, make):
    ev = Evidence.objects.filter(description=f"seed:{key}").first()
    return ev or make()


def run(ctx):
    from core import samples

    from . import services

    gh, p = ctx["gh"], ctx["people"]
    order_id, report_id, case_id = sid("order-ama-east-legon"), sid("report-ama-east-legon"), sid("case-ama")

    site_plan = _once("site-plan", lambda: services.store(
        data=samples.pdf("site_plan", "east-legon-plot-14", title="Site plan: East Legon plot 14"), country=gh,
        uploaded_by=p["client"],
        content_type="application/pdf", original_name="site-plan-east-legon.pdf", source="upload",
        description="seed:site-plan", owner_type="order", owner_id=order_id))
    services.link(site_plan, "order", order_id, role="site_plan", by=p["client"])

    photo = _once("runner-photo", lambda: services.store(
        data=samples.photo("gate", "seed-runner-photo", caption="Gate and beacon, East Legon plot 14",
                           model="SM-A045F"), country=gh, uploaded_by=p["runner"],
        content_type="image/jpeg", original_name="gate-and-beacon.jpg", source="upload",
        description="seed:runner-photo", owner_type="case", owner_id=case_id, latitude="5.650120",
        longitude="-0.180310"))
    services.link(photo, "case", case_id, role="site_photo", by=p["runner"])

    report_pdf = _once("report-pdf", lambda: services.store(
        data=samples.pdf("report", "tenmina-report-TM-0001", title="Tenmina verification report: East Legon plot 14",
                         issuer="Tenmina", lines=["Overall verdict: GREEN (sample).",
                                                  "Every finding is a sample for demo data."]), country=gh,
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
