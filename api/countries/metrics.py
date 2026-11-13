"""FR-CTY-003: every metric by country.

`by_country(viewer)` counts what exists now in every table that carries a
country, split by country, and adds whatever other modules register with
`register(name, fn)` where fn(country) returns a number or a dict of numbers.
Money is never summed across currencies here; modules that report amounts
return them per currency.
"""
from django.apps import apps
from django.db.models import Count

from .models import Country

_providers: dict = {}


def register(name: str, fn):
    _providers[name] = fn


def _country_tables():
    out = []
    for m in apps.get_models():
        f = next((f for f in m._meta.get_fields() if getattr(f, "name", "") == "country"
                  and getattr(f, "related_model", None) is Country and f.many_to_one), None)
        if f is not None:
            out.append(m)
    return out


def by_country(viewer=None, codes=None) -> list[dict]:
    from .selectors import staff_country_codes

    visible = staff_country_codes(viewer, "CM", "RV", "AD", "AN") if viewer is not None else None
    qs = Country.objects.all().order_by("code")
    if visible is not None:
        qs = qs.filter(code__in=visible)
    if codes:
        qs = qs.filter(code__in=[c.upper() for c in codes])
    countries = list(qs)
    ids = [c.pk for c in countries]
    counts = {c.pk: {} for c in countries}
    for m in _country_tables():
        for row in m.objects.filter(country_id__in=ids).values("country_id").annotate(n=Count("pk")):
            counts[row["country_id"]][m._meta.db_table] = row["n"]
    from accounts.models import Person

    for row in Person.objects.filter(home_country_id__in=ids).values("home_country_id").annotate(n=Count("pk")):
        counts[row["home_country_id"]]["people"] = row["n"]
    out = []
    for c in countries:
        extra = {}
        for name, fn in _providers.items():
            try:
                extra[name] = fn(c)
            except Exception as exc:  # noqa: BLE001 - one bad provider must not hide the rest
                extra[name] = {"error": str(exc)}
        out.append({"country": c.code, "name": c.name, "status": c.status, "currency": c.currency,
                    "counts": counts[c.pk], "metrics": extra})
    return out
