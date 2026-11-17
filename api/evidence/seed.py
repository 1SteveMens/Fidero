"""Demo evidence: a link to the released report PDF opened by a reviewer, and a clean integrity run.

The evidence itself comes from the modules that own the subjects: the client's site plan with her order
(ORD), the runner's photos on the case tasks (CASE) and the released report PDF (RPT). Every link and owner
is a real row, so this seed runs late, once those exist."""
from .models import Evidence, IntegrityRun, IssuedDocument


def run(ctx):
    """Nothing to do before the other modules have seeded: see run_late."""


def run_late(ctx):
    from . import services

    p = ctx["people"]
    report = ctx.get("report")
    report_pdf = None
    if report is not None:
        doc = IssuedDocument.objects.filter(subject_type="report", subject_id=report.pk, kind="report_pdf").first()
        report_pdf = doc.evidence if doc else Evidence.objects.filter(pk=report.pdf_evidence_id).first()
    if report_pdf is not None and not report_pdf.access_log.exists():
        services.issue_link(report_pdf, p["reviewer"])
    if not IntegrityRun.objects.exists():
        services.integrity_sample(size=10, seed="seed-run", by=p["admin"])
    ctx["evidence"] = {"report_pdf": report_pdf, "report_id": report.pk if report is not None else None}
