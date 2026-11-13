"""The seed builds demo journeys in several states and runs twice without change."""
import importlib

from cases.models import Case
from reports.models import Report


def test_seed_journeys_and_idempotent(seeded):
    """FR-CASE-001, FR-RPT-007: seeded paid orders have cases; Ama's report is released with a hash."""
    statuses = set(Case.objects.values_list("status", flat=True))
    assert {"in_progress", "released", "completed"} <= statuses
    r = Report.objects.get(status="released")
    assert len(r.pdf_sha256) == 64 and r.pdf_evidence_id
    n = Case.objects.count()
    for m in ("cases.seed", "reports.seed"):
        importlib.import_module(m).run(seeded)
    assert Case.objects.count() == n
