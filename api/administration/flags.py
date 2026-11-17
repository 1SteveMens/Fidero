"""Feature flag checks (document 06, 2.6).

A `lines.*` flag is on in a country only when the platform value is on,
the country is open, and the country's own value for that line is on. A
country is open when its `country.<code>` flag is on, or, with no such flag,
when the country is active (the launch country needs no country flag;
country is configuration, so no code is named here).
"""
from django.conf import settings

from core.errors import DomainError, FeatureOff

from .models import FeatureFlag


def _country_open(code):
    flag = _value(f"country.{code.lower()}")
    if flag is not None:
        return flag
    from countries.models import Country

    return Country.objects.filter(code=code.upper(), status="active").exists()


def _value(name, country_code=None):
    qs = FeatureFlag.objects.filter(name=name)
    if country_code:
        f = qs.filter(country__code=country_code.upper()).first()
        return None if f is None else f.enabled
    f = qs.filter(country__isnull=True).first()
    return None if f is None else f.enabled


def enabled(name: str, country=None) -> bool:
    code = getattr(country, "code", country)
    overrides = getattr(settings, "TENMINA_FLAG_OVERRIDES", {})
    if name in overrides:
        return overrides[name]
    platform = bool(_value(name))
    if not code:
        return platform
    if not _country_open(code):
        return False
    if name.startswith("lines."):
        local = _value(name, code)
        return platform and (local if local is not None else True)
    local = _value(name, code)
    return local if local is not None else platform


def setting(name: str, country=None, default=""):
    code = getattr(country, "code", country)
    f = None
    if code:
        f = FeatureFlag.objects.filter(name=name, country__code=code.upper()).first()
    f = f or FeatureFlag.objects.filter(name=name, country__isnull=True).first()
    return f.value if f and f.value else default


def require(name: str, country=None):
    if not enabled(name, country):
        raise FeatureOff(f"This service is not open yet ({name}).", extra={"flag": name})


def read_only_guard():
    if enabled("maintenance.read_only"):
        raise DomainError("Tenmina is in maintenance. Changes are paused for a short time.",
                          code="maintenance-read-only", status=503)


def instructions_paused() -> bool:
    return enabled("escrow.instructions_paused")
