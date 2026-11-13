"""ANL Analytics: read-only queries (FR-ANL-001, FR-ANL-003, FR-CTY-003).

- resolve_filters(person, ...)      the viewer's filters, limited to the countries they may see
- table(name, filters, viewer)      one metric table, small groups suppressed unless the viewer may see them
- dashboard(filters, viewer, names) every tile at once
- catalogue()                       the metrics, their columns and the filters each one applies
- export_log(person)                the export log the viewer may see
"""
from datetime import date

from django.utils import timezone

from core.errors import Forbidden, Invalid, NotFound
from core.permissions import has_role

from . import metrics as m
from .models import ExportLog

ANL_ROLES = ("CM", "RV", "AD", "AN")   # who may open the dashboard
EXPORT_ROLES = ("RV", "AD", "AN")      # who may export metric tables (FR-ANL-002)
PERSONAL_EXPORT_ROLES = ("AD",)        # who may ask for a personal-data export (through DPR, FR-DPR-005)
FULL_DETAIL_ROLES = ("AD",)            # who sees groups smaller than the minimum size on screen

PERSONAL_TABLES = {
    "client_register": {
        "title": "Client register (personal data)",
        "description": "Clients with their contact details. Goes through the two-person bulk export (FR-DPR-005).",
        "fields": ("full_name", "email", "phone", "residence_country", "created_at", "status"),
    },
}


def viewer_countries(person):
    """None: every country. A set: only these. Empty: none."""
    from accounts.selectors import staff_country_codes

    return staff_country_codes(person, roles=ANL_ROLES)


def _date(value, name):
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise Invalid(f"{name} must be a date like 2027-01-31.", code="validation-error") from None


def default_window(today=None):
    today = today or timezone.localdate()
    y, mth = today.year, today.month - 11
    while mth <= 0:
        mth += 12
        y -= 1
    return date(y, mth, 1), today


def _codes(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        value = [value]
    out = []
    for v in value:
        out.extend(c.strip().upper() for c in str(v).split(",") if c.strip())
    return sorted(set(out))


def resolve_filters(person, *, date_from=None, date_to=None, country=None, line="", tier="") -> m.Filters:
    """FR-ANL-001 filters and FR-CTY-003 country scope. Asking for a country outside the viewer's grants is
    refused rather than silently narrowed, so a figure is never mistaken for another country's."""
    d_from, d_to = default_window()
    d_from = _date(date_from, "date_from") or d_from
    d_to = _date(date_to, "date_to") or d_to
    if d_from > d_to:
        raise Invalid("date_from must be on or before date_to.", code="validation-error")
    if line and line not in m.LINES:
        raise Invalid(f"line must be one of {', '.join(m.LINES)}.", code="validation-error")
    scope = viewer_countries(person)
    asked = _codes(country)
    if asked:
        if scope is not None and set(asked) - scope:
            raise Forbidden("You can see analytics only for the countries you work in.")
        countries = asked
    else:
        countries = None if scope is None else sorted(scope)
    return m.Filters(date_from=d_from, date_to=d_to, countries=countries, line=line or "", tier=tier or "")


def _metric(name) -> m.Metric:
    if name not in m.METRICS:
        raise NotFound(f"There is no metric called {name}.")
    return m.METRICS[name]


def sees_small_groups(person) -> bool:
    return has_role(person, *FULL_DETAIL_ROLES)


def _k(f: m.Filters) -> int:
    codes = f.countries
    if codes is None:
        from countries.models import Country

        codes = list(Country.objects.values_list("code", flat=True))
    return m.min_group_size(codes)


def table(name: str, f: m.Filters, viewer=None, *, force_suppress=False) -> dict:
    metric = _metric(name)
    rows = metric.run(f)
    k = _k(f)
    blanked = 0
    suppressed = force_suppress or viewer is None or not sees_small_groups(viewer)
    if suppressed:
        rows, blanked = m.suppress(metric, rows, k)
    ignored = [x for x in ("line", "tier") if getattr(f, x) and x not in metric.uses]
    return {"name": metric.name, "title": metric.title, "description": metric.description, "source": metric.source,
            "columns": metric.columns, "rows": rows, "suppression": {"applied": suppressed, "min_group_size": k,
                                                                     "cells_blanked": blanked},
            "filters_ignored": ignored}


def dashboard(f: m.Filters, viewer, names=None) -> dict:
    names = names or [n for n in m.METRICS]
    for n in names:
        _metric(n)
    return {"filters": f.as_dict(), "generated_at": timezone.now(),
            "tiles": [table(n, f, viewer) for n in names]}


def catalogue() -> list[dict]:
    out = [{"name": x.name, "title": x.title, "description": x.description, "source": x.source,
            "columns": x.columns, "filters": ["date", "country", *x.uses], "personal_data": False}
           for x in m.METRICS.values()]
    for name, t in PERSONAL_TABLES.items():
        out.append({"name": name, "title": t["title"], "description": t["description"], "source": "Accounts",
                    "columns": ["id", *t["fields"]], "filters": ["country"], "personal_data": True})
    return out


def export_log(person):
    qs = ExportLog.objects.select_related("country", "bulk_export").order_by("-created_at")
    if has_role(person, "AD"):
        scope = viewer_countries(person)
        if scope is None:
            return qs
        from django.db.models import Q

        return qs.filter(Q(country__code__in=scope) | Q(requested_by=person))
    return qs.filter(requested_by=person)
