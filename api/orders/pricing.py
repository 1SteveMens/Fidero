"""Prices for every order kind (FR-ORD-002, FR-ORD-007).

`quote()` is the only function that reads a price. Today it reads, in order:

1. an `administration` price table, if ADM provides `administration.selectors.fee_price`;
2. the country configuration `order_catalogue.<code>` (and `report_tiers` for reports);
3. the defaults below.

So when ADM's price table arrives, only step 1 starts answering. Every
default is a working assumption, not verified pricing: [TO VERIFY].

Card payments are charged in the price currency (USD); mobile money in the
country's own currency (GHS in Ghana). GBP, EUR and CAD are guides only.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from core.errors import Invalid
from core.money import Money
from countries.models import Country

from . import catalogue

# [TO VERIFY] every figure: working assumptions for development and demos.
DEFAULT_TIERS = {
    "diaspora_standard": {"name": "Diaspora standard", "price": "450.00", "turnaround_days": 21, "audience": "diaspora"},
    "local_standard": {"name": "Local standard", "price": "250.00", "turnaround_days": 21, "audience": "local"},
    "rush": {"name": "Rush", "price": "650.00", "turnaround_days": 10},
    "extra_plot_same_seller": {"name": "Extra plot, same seller", "price": "300.00", "turnaround_days": 21,
                               "requires_same_seller": True},
}
DEFAULT_TIER_NAMES = {"basic": "Basic", "standard": "Standard", "premium": "Premium"}
DEFAULT_BUILDING_SURCHARGE = "150.00"  # house checks need a structural inspection (J-08) [TO VERIFY]
DEFAULT_FLAT = {
    "fresh_search": "90.00",
    "extra_inspection": "120.00",
    "listing_verification": "200.00",   # seller-paid checked plot, same fee whatever the verdict
    "institution_verification": "25.00",
    "family_payment_fee": "5.00",
    "family_plan": "15.00",
    "property_onboarding": "100.00",
    "errand": "40.00",
    "care_plan": "30.00",
    "event_service": "50.00",
    # Invoice-only products (PAY-007)
    "listing_fee": "100.00",
    "success_fee": "250.00",            # only if Q-31 allows; flat and disclosed
}
# Units of each currency per 1 USD. Guides only, never a charge rate [TO VERIFY].
DEFAULT_FX_GUIDES = {"GHS": "15.50", "NGN": "1600.00", "GBP": "0.79", "EUR": "0.92", "CAD": "1.37"}
GUIDE_CURRENCIES = ["GBP", "EUR", "CAD"]
EURO_COUNTRIES = {"AT", "BE", "CY", "DE", "EE", "ES", "FI", "FR", "GR", "HR", "IE", "IT", "LT", "LU", "LV", "MT",
                  "NL", "PT", "SI", "SK"}


@dataclass
class Quote:
    kind: str
    code: str
    tier: str
    tier_name: str
    price: Money                 # charged by card
    local_price: Money | None    # charged by mobile money
    guides: dict = field(default_factory=dict)
    guide_for_you: dict | None = None
    source: str = "default"
    config_version: int | None = None
    turnaround_days: int | None = None
    requires_same_seller: bool = False

    def as_dict(self):
        return {
            "kind": self.kind, "code": self.code, "tier": self.tier, "tier_name": self.tier_name,
            "price": self.price.as_dict(),
            "local_price": self.local_price.as_dict() if self.local_price else None,
            "guides": self.guides, "guide_for_you": self.guide_for_you, "source": self.source,
            "config_version": self.config_version, "turnaround_days": self.turnaround_days,
            "requires_same_seller": self.requires_same_seller,
        }


def _country(country) -> Country:
    if isinstance(country, Country):
        return country
    return Country.objects.get(code=str(country).upper())


def _config(country: Country, key, default=None):
    from countries.selectors import config

    return config(country, key, default)


def _config_version(country: Country):
    c = country.configs.filter(status="published").order_by("-version").first()
    return c.version if c else None


def _admin_price(country, code, tier):
    try:
        from administration import selectors as adm
    except ImportError:  # pragma: no cover
        return None
    fn = getattr(adm, "fee_price", None)
    return fn(country, code, tier) if fn else None


def _catalogue_entry(country: Country, code: str):
    """`order_catalogue` in the country configuration, keyed by product code (codes contain dots)."""
    return (_config(country, "order_catalogue", {}) or {}).get(code)


def product_code(kind: str, asset_type: str = "") -> str:
    if kind == "verification":
        return f"verification.{asset_type or 'plot'}"
    return kind


def _tier_table(country: Country, kind: str, asset_type: str):
    """(tiers dict, source) for a tiered product."""
    code = product_code(kind, asset_type)
    own = (_catalogue_entry(country, code) or {}).get("tiers")
    if own:
        return own, f"country_config:{code}"
    base = _config(country, "report_tiers")
    source = "country_config:report_tiers"
    if not base:
        base, source = DEFAULT_TIERS, "default"
    if asset_type == "building":
        surcharge = Decimal(str(_config(country, "order_catalogue.building_surcharge", DEFAULT_BUILDING_SURCHARGE)))
        base = {k: {**v, "price": str(Decimal(str(v["price"])) + surcharge),
                    **({"price_local": None} if "price_local" in v else {})} for k, v in base.items()}
        source += "+building_surcharge"
    return base, source


def _flat(country: Country, kind: str, details: dict | None):
    if kind == "errand" and details and details.get("errand_code"):
        for item in _config(country, "errand_catalogue", []) or []:
            if item.get("code") == details["errand_code"] and item.get("tenmina_charge"):
                return {"price": str(item["tenmina_charge"]), "name": item.get("name", "")}, "country_config:errand_catalogue"
    own = _catalogue_entry(country, kind)
    if own and own.get("price"):
        return own, f"country_config:{kind}"
    if kind not in DEFAULT_FLAT:
        raise Invalid(f"No price is set for '{kind}' in {country.code}.", code="price-not-configured")
    return {"price": DEFAULT_FLAT[kind]}, "default"


def fx_guides(country: Country) -> dict:
    return {**DEFAULT_FX_GUIDES, **(_config(country, "fx_guides", {}) or {})}


def guide_currency_for(residence: str) -> str | None:
    r = (residence or "").upper()
    if r == "GB":
        return "GBP"
    if r == "CA":
        return "CAD"
    if r in EURO_COUNTRIES:
        return "EUR"
    return None


def _round_local(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def quote(country, kind: str, tier: str | None = None, *, asset_type: str = "", details: dict | None = None,
          residence: str = "") -> Quote:
    """The price of one product in one country. Never trust a price from a request."""
    c = _country(country)
    p = catalogue.product(kind)
    code = product_code(kind, asset_type)
    price_currency = _config(c, "price_currency", "USD")
    entry, source = None, None
    admin = _admin_price(c, code, tier)
    if admin:
        entry, source = admin, "administration"
    elif p.tiered:
        table, source = _tier_table(c, kind, asset_type)
        if not tier:
            raise Invalid("Choose a tier.", code="validation-error", extra={"errors": [
                {"pointer": "/tier", "message": "Choose a tier."}]})
        if tier not in table:
            raise Invalid(f"'{tier}' is not a tier offered in {c.code}.", code="validation-error",
                          extra={"errors": [{"pointer": "/tier", "message": "This tier is not offered."}],
                                 "tiers": sorted(table)})
        entry = table[tier]
    else:
        entry, source = _flat(c, kind, details)
        tier = tier or ""
    amount = Decimal(str(entry["price"]))
    price = Money(amount, entry.get("currency", price_currency))
    guides_rates = fx_guides(c)
    local_price = None
    if c.currency != price.currency:
        if entry.get("price_local"):
            local_price = Money(Decimal(str(entry["price_local"])), c.currency)
        elif c.currency in guides_rates:
            local_price = Money(_round_local(amount * Decimal(str(guides_rates[c.currency]))), c.currency)
    else:
        local_price = price
    guides = {cur: f"{(amount * Decimal(str(guides_rates[cur]))).quantize(Decimal('0.01'))}"
              for cur in GUIDE_CURRENCIES if cur in guides_rates and cur != price.currency}
    yours = guide_currency_for(residence)
    tier_name = entry.get("name") or DEFAULT_TIER_NAMES.get(tier or "", "") or (tier or "").replace("_", " ").capitalize()
    return Quote(kind=kind, code=code, tier=tier or "", tier_name=tier_name or p.name, price=price,
                 local_price=local_price, guides=guides,
                 guide_for_you={"amount": guides[yours], "currency": yours} if yours in guides else None,
                 source=source, config_version=_config_version(c),
                 turnaround_days=entry.get("turnaround_days"),
                 requires_same_seller=bool(entry.get("requires_same_seller")))


def tiers(country, kind: str, *, asset_type: str = "", residence: str = "") -> list[Quote]:
    c = _country(country)
    p = catalogue.product(kind)
    if not p.tiered:
        return [quote(c, kind, asset_type=asset_type, residence=residence)]
    table, _ = _tier_table(c, kind, asset_type)
    return [quote(c, kind, t, asset_type=asset_type, residence=residence) for t in table]


def invoice_price(country, code: str) -> tuple[Money, str]:
    """Flat fees that are invoiced rather than ordered (listing fee, success fee; FR-PAY-007)."""
    c = _country(country)
    entry, source = _flat(c, code, None)
    return Money(Decimal(str(entry["price"])), entry.get("currency", _config(c, "price_currency", "USD"))), source


def apply_discount(q: Quote, pct: Decimal) -> tuple[Money, Money | None, Money]:
    """Referral discount (FR-ORD-006). Returns (price, local_price, discount)."""
    pct = Decimal(str(pct))
    off = Money(q.price.amount * pct / 100, q.price.currency)
    price = q.price - off
    local = None
    if q.local_price:
        local = Money(_round_local(q.local_price.amount * (100 - pct) / 100), q.local_price.currency)
    return price, local, off
