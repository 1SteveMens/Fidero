"""ADM read-only queries other modules may use.

- setting(key, country)            a configurable value (FR-ADM-005)
- current_config(kind, country)    the published configuration version to start new work with (ADR-11)
- current_price(country, tier)     Tenmina's fee now; store the row id and amount on the order (FR-ADM-002)
- guide_rate(country, base, quote) the exchange-rate guide with its date (RUL-18)
- assignable_partner(id)           a partner that may be assigned (FR-ADM-003)
- current_locked_text(kind, country) the locked text version in force (RUL-04)
"""
from django.db.models import Q
from django.utils import timezone

from core.errors import NotFound, StateConflict

from .models import AppVersion, ConfigVersion, FxRate, LockedTextVersion, Partner, Price, Setting
from .registry import REGISTRY, definition


def _code(country):
    return (getattr(country, "code", country) or "").upper() or None


def setting(key: str, country=None, default=None):
    """Country value, else platform value, else the registry default."""
    row = setting_row(key, country)
    if row is not None:
        return row.value
    d = REGISTRY.get(key)
    if d is None:
        return default
    return d.default


def setting_row(key: str, country=None) -> Setting | None:
    code = _code(country)
    if code:
        row = Setting.objects.filter(key=key, country__code=code).first()
        if row:
            return row
    return Setting.objects.filter(key=key, country__isnull=True).first()


def setting_is_set(key: str, country=None) -> bool:
    """False while the value is still a [TO VERIFY] default nobody has set."""
    d = definition(key)
    row = setting_row(key, country)
    if row is not None:
        return row.confirmed or not d.to_verify
    return not d.to_verify


def unset_settings(keys, country=None) -> list[str]:
    return [k for k in keys if not setting_is_set(k, country)]


def current_config(kind: str, country=None, product_line: str = "") -> ConfigVersion | None:
    """The latest published version for the country, else a shareable one."""
    qs = ConfigVersion.objects.filter(kind=kind, product_line=product_line, state="published")
    code = _code(country)
    if code:
        own = qs.filter(country__code=code).order_by("-version").first()
        if own:
            return own
    return qs.filter(country__isnull=True).order_by("-version").first()


def config_version(pk) -> ConfigVersion:
    cv = ConfigVersion.objects.filter(pk=pk).first()
    if not cv:
        raise NotFound("No such configuration version.")
    return cv


def current_price(country, tier: str, product_line: str = "land", audience: str = "standard", at=None) -> Price:
    at = at or timezone.now()
    qs = Price.objects.filter(country__code=_code(country), product_line=product_line, tier=tier,
                              valid_from__lte=at).filter(Q(valid_to__isnull=True) | Q(valid_to__gt=at))
    p = qs.filter(audience=audience).order_by("-valid_from").first()
    if p is None and audience != "standard":
        p = qs.filter(audience="standard").order_by("-valid_from").first()
    if p is None:
        raise NotFound(f"No price is set for tier '{tier}' in this country.")
    return p


def current_prices(country, product_line: str | None = None):
    qs = Price.objects.filter(country__code=_code(country), valid_to__isnull=True)
    if product_line:
        qs = qs.filter(product_line=product_line)
    return qs.order_by("product_line", "tier", "audience")


def guide_rate(country, base: str, quote: str) -> FxRate | None:
    return FxRate.objects.filter(country__code=_code(country), base_currency=base.upper(),
                                 quote_currency=quote.upper()).order_by("-rate_date", "-created_at").first()


def partner(pk) -> Partner:
    p = Partner.objects.filter(pk=pk).first()
    if not p:
        raise NotFound("No such partner.")
    return p


def assignable_partner(pk, kind: str | None = None) -> Partner:
    """FR-ADM-003: a deactivated partner cannot be assigned."""
    p = partner(pk)
    if p.status != "active":
        raise StateConflict(f"{p.name} is deactivated and cannot be assigned.", code="partner-inactive")
    if kind and p.kind != kind:
        raise StateConflict(f"{p.name} is not a partner of kind '{kind}'.", code="partner-wrong-kind")
    return p


def partners(country=None, kind: str | None = None, active_only=True):
    qs = Partner.objects.all()
    if country is not None:
        qs = qs.filter(country__code=_code(country))
    if kind:
        qs = qs.filter(kind=kind)
    if active_only:
        qs = qs.filter(status="active")
    return qs


def current_locked_text(kind: str, country) -> LockedTextVersion | None:
    return LockedTextVersion.objects.filter(kind=kind, country__code=_code(country),
                                            status="published").order_by("-version").first()


def app_version(app: str, platform: str) -> AppVersion | None:
    return AppVersion.objects.filter(app=app, platform=platform).first()
