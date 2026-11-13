"""Guide prices and re-pricing (FR-BLD-007, RUL-18). The guide rate is the administration's exchange-rate
guide for the country's price currency (FR-ADM-002); it is never a quote for converting money (FR-ESC-023)."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from core.money import q

from .common import cfg, now, today
from .models import Reprice


def guide_currency(country) -> str:
    from countries.selectors import config

    return (config(country, "price_currency") or country.currency).upper()


def current_rate(country):
    """(FxRate or None, rate). None and 1 when the price currency is the local currency."""
    from administration.selectors import guide_rate

    base = guide_currency(country)
    if base == country.currency:
        return None, Decimal("1")
    fx = guide_rate(country, base, country.currency)
    return fx, (fx.rate if fx else None)


def to_guide(country, amount):
    fx, rate = current_rate(country)
    if rate is None:
        return None
    return (Decimal(amount) / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def stale_reason(country, fx, project_type="construction") -> str:
    """Why the guide rate cannot back a release now, or ''."""
    if guide_currency(country) == country.currency:
        return ""
    if fx is None:
        return "There is no guide rate for this country."
    latest, _ = current_rate(country)
    if latest is not None and latest.pk != fx.pk:
        return "A newer guide rate was published after this re-price."
    max_age = int(cfg(country, project_type, "reprice_max_age_days"))
    if fx.rate_date < today(country) - timedelta(days=max_age):
        return f"The guide rate dated {fx.rate_date:%d %B %Y} is older than {max_age} days."
    return ""


@transaction.atomic
def reprice(milestone) -> Reprice:
    """Re-price the milestone in the local currency from its guide amount at today's guide rate."""
    country = milestone.country
    fx, rate = current_rate(country)
    if rate is None:
        from core.errors import RuleBlocked

        raise RuleBlocked("The milestone cannot be re-priced: there is no guide rate for this country.",
                          code="release-blocked",
                          blocking_reasons=[{"rule": "RUL-18", "code": "reprice-missing",
                                             "message": "Re-pricing missing: no guide rate."}])
    guide = milestone.guide_amount
    if guide is None or not milestone.guide_currency:
        guide = to_guide(country, milestone.amount) if fx is not None else milestone.amount
        milestone.guide_amount, milestone.guide_currency = guide, guide_currency(country)
        milestone.save(update_fields=["guide_amount", "guide_currency"])
    local = q(Decimal(guide) * rate)
    previous = milestone.amount
    if abs(local - previous) <= q(rate * Decimal("0.01")):
        local = previous  # only the rounding of the guide amount, not a change in the rate
    r = Reprice.objects.create(country=country, milestone=milestone, guide_amount=guide,
                               guide_currency=milestone.guide_currency, local_amount=local,
                               local_currency=milestone.currency, previous_amount=previous, fx_rate=fx, rate=rate,
                               rate_date=fx.rate_date if fx else today(country))
    if local != previous:
        milestone.amount = local
        milestone.save(update_fields=["amount"])
    return r


def latest(milestone):
    return Reprice.objects.filter(milestone=milestone).order_by("-created_at").first()


def reprice_reasons(milestone, r, project_type="construction") -> list[dict]:
    if r is None:
        return [{"rule": "RUL-18", "code": "reprice-missing", "message": "Re-pricing missing for this milestone."}]
    why = stale_reason(milestone.country, r.fx_rate, project_type)
    if why:
        return [{"rule": "RUL-18", "code": "reprice-stale", "message": f"Re-pricing stale: {why}"}]
    return []


def shown(r: Reprice):
    if r is not None and r.shown_to_client_at is None:
        r.shown_to_client_at = now()
        r.save(update_fields=["shown_to_client_at"])
