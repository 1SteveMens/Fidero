"""CTY read-only queries other modules may use."""
from datetime import date, timedelta

from .models import Cell, Country, CountryConfig


def by_code(code: str) -> Country:
    return Country.objects.get(code=code.upper())


def config(country: Country | str, key: str, default=None):
    """A value from the country's published configuration, by dotted path."""
    c = by_code(country) if isinstance(country, str) else country
    data = c.config()
    for part in key.split("."):
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def current_config(country: Country | str) -> CountryConfig | None:
    """The published configuration row; store its id on work started under it."""
    c = by_code(country) if isinstance(country, str) else country
    return c.configs.filter(status="published").order_by("-version").first()


def ref(country: Country | str, group: str, key: str):
    """A reference from the published configuration, e.g.
    ref(gh, "locked_texts", "scope_statement") -> the locked text version id."""
    return config(country, f"refs.{group}.{key}")


def active_countries():
    return Country.objects.filter(status="active")


def staff_country_codes(user, *roles) -> set[str] | None:
    """The countries a staff member may see for the given roles. None means
    every country (a grant with no country). An empty set means none."""
    if not user or not user.is_authenticated:
        return set()
    grants = user.role_grants.filter(revoked_at__isnull=True)
    if roles:
        grants = grants.filter(role__in=roles)
    codes = set()
    for g in grants.select_related("country"):
        if g.country_id is None:
            return None
        codes.add(g.country.code)
    return codes


def can_see_country(user, country, *roles) -> bool:
    codes = staff_country_codes(user, *roles)
    code = getattr(country, "code", country)
    return codes is None or (code or "").upper() in codes


def storage_route(country: Country | str) -> dict:
    """Where this country's data goes (FR-CTY-002): cell, region, evidence prefix
    and key alias. Evidence and backups are routed with this."""
    c = by_code(country) if isinstance(country, str) else country
    cell = c.cell
    return {
        "country": c.code, "cell": cell.name if cell else "", "region": cell.aws_region if cell else "",
        "data_location": c.data_location, "evidence_prefix": c.evidence_prefix or f"{c.code}/",
        "backup_location": c.backup_location, "kms_key_alias": c.kms_key_alias or f"alias/tenmina-{c.code.lower()}",
    }


def default_cell() -> Cell | None:
    return Cell.objects.filter(status="active").order_by("created_at").first()


# --- Working days per country (holiday calendar in the configuration) --------

def _holidays(country) -> set[date]:
    out = set()
    for d in config(country, "holiday_calendar", []) or []:
        try:
            out.add(date.fromisoformat(d["date"] if isinstance(d, dict) else d))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _weekend(country) -> set[int]:
    return set(config(country, "weekend_days", [5, 6]) or [5, 6])


def is_working_day(country, day: date) -> bool:
    return day.weekday() not in _weekend(country) and day not in _holidays(country)


def add_working_days(country, start: date, n: int) -> date:
    """The date n working days after start (n may be negative)."""
    hol, wk = _holidays(country), _weekend(country)
    step = 1 if n >= 0 else -1
    d, left = start, abs(n)
    while left:
        d += timedelta(days=step)
        if d.weekday() not in wk and d not in hol:
            left -= 1
    return d


def working_days_between(country, start: date, end: date) -> int:
    """Working days after start up to and including end (negative if end is earlier)."""
    if end == start:
        return 0
    hol, wk = _holidays(country), _weekend(country)
    sign = 1 if end > start else -1
    a, b = (start, end) if sign == 1 else (end, start)
    n, d = 0, a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() not in wk and d not in hol:
            n += 1
    return n * sign
