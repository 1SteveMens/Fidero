"""ANL Analytics: exports (FR-ANL-002, FR-ANL-003, FR-DPR-005, issue I-11).

A metric table leaves the platform only as aggregates with small groups
blanked, whoever asks, and every export is logged in `anl_export_log` and in
the audit chain. A table with personal data (the client register) is never
produced here: the request becomes a DPR bulk export that two administrators
must approve, and the log row points at it.
"""
import csv
import hashlib
import io

from django.db import transaction

from audit.services import record
from core.errors import Forbidden, Invalid
from core.permissions import has_role

from . import metrics as m
from . import selectors
from .models import ExportLog


def country_of(f: m.Filters):
    if f.countries and len(f.countries) == 1:
        from countries.models import Country

        return Country.objects.filter(code=f.countries[0]).first()
    return None


def render_csv(t: dict) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(t["columns"])
    for r in t["rows"]:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in t["columns"]])
    return buf.getvalue().encode()


@transaction.atomic
def export_csv(by, name: str, f: m.Filters, *, purpose: str = "") -> tuple[bytes, ExportLog]:
    """FR-ANL-002: the metric table as CSV, logged. Always suppressed (FR-ANL-003): exports go to investors and
    partners."""
    if not has_role(by, *selectors.EXPORT_ROLES):
        raise Forbidden("Only reviewers, administrators and analysts export metric tables.")
    if name in selectors.PERSONAL_TABLES:
        raise Invalid("This table holds personal data. Ask for it as a bulk export with a purpose.",
                      code="validation-error")
    t = selectors.table(name, f, by, force_suppress=True)
    data = render_csv(t)
    country = country_of(f)
    log = ExportLog.objects.create(
        requested_by=by, country=country, countries=f.countries or [], metric=name, filters=f.as_dict(),
        row_count=len(t["rows"]), sha256=hashlib.sha256(data).hexdigest(),
        suppressed_cells=t["suppression"]["cells_blanked"], purpose=purpose)
    record(actor=by, action="analytics.exported", entity="anl_export_log", entity_id=log.pk,
           data={"metric": name, "filters": f.as_dict(), "rows": log.row_count, "sha256": log.sha256}, country=country)
    return data, log


@transaction.atomic
def request_personal_export(by, name: str, *, country, purpose: str, fields=None) -> ExportLog:
    """A table with personal data goes through DPR's two-person bulk export (FR-DPR-005). Nothing is produced
    until a second administrator approves it there."""
    from dataprotection.services import request_bulk_export

    if name not in selectors.PERSONAL_TABLES:
        raise Invalid(f"{name} is not a personal-data table.", code="validation-error")
    if not has_role(by, *selectors.PERSONAL_EXPORT_ROLES):
        raise Forbidden("Only an administrator asks for an export of personal data.")
    if country is None:
        raise Invalid("Choose one country for an export of personal data.", code="validation-error")
    scope = selectors.viewer_countries(by)
    if scope is not None and country.code not in scope:
        raise Forbidden("You can export only for the countries you work in.")
    allowed = selectors.PERSONAL_TABLES[name]["fields"]
    fields = tuple(fields or allowed)
    if set(fields) - set(allowed):
        raise Invalid(f"These fields are not in the {name} table: {', '.join(sorted(set(fields) - set(allowed)))}.",
                      code="validation-error")
    be = request_bulk_export(by, purpose=purpose, country=country, roles=("CL",), fields=fields)
    log = ExportLog.objects.create(
        requested_by=by, country=country, countries=[country.code], metric=name,
        filters={"country": country.code, "fields": list(fields)}, status="sent_for_approval", personal_data=True,
        bulk_export=be, purpose=purpose)
    record(actor=by, action="analytics.personal_export_requested", entity="anl_export_log", entity_id=log.pk,
           data={"metric": name, "bulk_export_id": be.pk, "fields": list(fields)}, country=country)
    return log
