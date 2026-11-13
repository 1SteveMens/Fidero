"""RPT Reports: read-only queries other modules may use.

- conditions_for(report)            FR-RPT-009: section 11 conditions as items ESC copies into an escrow
- escrow_blockers(report)           why an escrow cannot open from this report (red verdict, not released)
- latest_released(case_id), latest_released_for_asset(asset_id)
- open_incidents_for_report(report_id)   ESC: an open re-check incident freezes releases (FR-RPT-012)
- visible_reports(user)
"""
from django.db.models import Q

from core.permissions import has_role

from .models import Incident, Recheck, Report


def latest_released(case_id) -> Report | None:
    return Report.objects.filter(case_id=case_id, status="released").order_by("-version").first()


def latest_released_for_asset(asset_id) -> Report | None:
    return Report.objects.filter(case__asset_id=asset_id, status="released").order_by("-released_at").first()


def report(pk) -> Report | None:
    return Report.objects.filter(pk=pk).first()


def conditions_for(report) -> list[dict]:
    """Structured items with text, the party responsible and the evidence that closes each one."""
    if report is None or report.status != "released" or report.overall_verdict == "red":
        return []
    return [{"source_condition_id": c.pk, "position": c.position, "key": c.key, "text": c.text,
             "responsible": c.responsible, "closing_evidence": c.closing_evidence, "release_part": c.release_part}
            for c in report.conditions.order_by("position")]


def escrow_blockers(report) -> list[dict]:
    """TC-RPT-009-02: a red report cannot open an escrow; nor can a report that is not the released version."""
    if report is None:
        return [{"rule": "FR-RPT-009", "message": "No report."}]
    out = []
    if report.status != "released":
        out.append({"rule": "FR-RPT-010", "message": "Only the released, current version of a report backs an "
                                                     "escrow."})
    if report.overall_verdict == "red":
        out.append({"rule": "RUL-02", "message": "The report's verdict is red: do not buy."})
    if open_incidents_for_report(report.pk):
        out.append({"rule": "RUL-32", "message": "A re-check incident on this report is open."})
    return out


def open_incidents_for_report(report_id) -> list[Incident]:
    r = Report.objects.filter(pk=report_id).first()
    if r is None:
        return []
    ids = {r.pk}
    x = r
    while x.supersedes_id:
        ids.add(x.supersedes_id)
        x = x.supersedes
    return list(Incident.objects.filter(status="open").filter(Q(report_id__in=ids) | Q(case_id=r.case_id)))


def visible_reports(user):
    if not user or not user.is_authenticated:
        return Report.objects.none()
    from accounts.selectors import representative_subject_ids
    from cases.models import Task

    released = Q(status__in=["released", "superseded"])
    q = (Q(case__client=user) & released) | (Q(case_id__in=representative_subject_ids(user, "case")) & released)
    q |= Q(case_id__in=Task.objects.filter(Q(assignee=user) | Q(second_assignee=user)).values("case_id"))
    if has_role(user, "CM", "RV"):
        grants = user.role_grants.filter(revoked_at__isnull=True, role__in=["CM", "RV"])
        if grants.filter(country__isnull=True).exists():
            return Report.objects.all()
        q |= Q(country_id__in=list(grants.values_list("country_id", flat=True)))
    return Report.objects.filter(q)


def rechecks_for_assignee(user):
    return Recheck.objects.filter(assignee=user, status="assigned")
