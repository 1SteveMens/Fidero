"""The errand catalogue per country (FR-TSK-001): configuration, never code.

Read from the country's published configuration, key `errand_catalogue`:

    [{"code": "birth_cert", "name": "Birth certificate copy", "agency": "Births and Deaths Registry",
      "checklist": [{"key": "parent_id", "label": "Parent's Ghana Card", "required": true}],
      "official_fees": {"amount": "120.00", "currency": "GHS"},
      "tenmina_charge": "40.00",   # in the configured price_currency, as ORD prices it
      "target_days": 21,
      "steps": [{"key": "lodge", "description": "Lodge the application", "official_fee": "120.00",
                 "documents": ["parent_id"]},
                {"key": "collect", "description": "Collect the certificate", "official_fee": "0.00"}],
      "office": {"address": "...", "lat": 5.55, "lng": -0.2}}]

An item is orderable only when it is complete: a checklist, official fees, Tenmina's charge, a target time
and steps whose fees add up to the official fees (TC-TSK-001-02). Incomplete items are listed for staff with
what is missing, never offered to clients. Every figure is a working assumption [TO VERIFY].
"""
from decimal import Decimal, InvalidOperation

from core.errors import Invalid, NotFound


def _dec(v):
    if isinstance(v, dict):
        v = v.get("amount")
    try:
        return Decimal(str(v)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _cur(v, default):
    if isinstance(v, dict) and v.get("currency"):
        return str(v["currency"]).upper()
    return default


def normalise(raw: dict, country, price_currency="USD") -> dict:
    """One catalogue item in a fixed shape, with `problems` listing what makes it incomplete. Official fees are
    in the country's currency unless stated; Tenmina's charge in the configured price currency (as ORD prices
    it from the same item)."""
    local = country.currency
    problems = []
    checklist = []
    for n, c in enumerate(raw.get("checklist") or []):
        if isinstance(c, str):
            c = {"key": c, "label": c.replace("_", " ").capitalize()}
        key = str(c.get("key") or "").strip()
        if not key:
            problems.append(f"Checklist item {n + 1} has no key.")
            continue
        checklist.append({"key": key, "label": c.get("label") or key.replace("_", " ").capitalize(),
                          "required": c.get("required", True) is not False, "hint": c.get("hint", "")})
    if not checklist:
        problems.append("No document checklist.")
    fees_raw = raw.get("official_fees")
    fees = _dec(fees_raw) if fees_raw is not None else None
    fees_cur = _cur(fees_raw, local)
    if fees is None or fees < 0:
        problems.append("No official fees.")
    charge_raw = raw.get("tenmina_charge")
    charge = _dec(charge_raw) if charge_raw is not None else None
    if charge is None or charge <= 0:
        problems.append("No Tenmina charge.")
    try:
        target = int(raw.get("target_days") or 0)
    except (TypeError, ValueError):
        target = 0
    if target <= 0:
        problems.append("No target time.")
    steps = []
    for n, s in enumerate(raw.get("steps") or []):
        key = str(s.get("key") or f"step_{n + 1}")
        fee = _dec(s.get("official_fee", 0)) or Decimal("0.00")
        steps.append({"seq": n + 1, "key": key, "description": s.get("description") or key.replace("_", " "),
                      "official_fee": f"{fee:.2f}", "documents": list(s.get("documents") or [])})
    if not steps:
        problems.append("No steps.")
    elif fees is not None and sum(Decimal(s["official_fee"]) for s in steps) != fees:
        problems.append("The step fees do not add up to the official fees.")
    return {
        "code": raw.get("code"), "name": raw.get("name") or raw.get("code"), "agency": raw.get("agency", ""),
        "description": raw.get("description", ""), "checklist": checklist,
        "official_fees": {"amount": f"{fees:.2f}" if fees is not None else None, "currency": fees_cur},
        "tenmina_charge": {"amount": f"{charge:.2f}" if charge is not None else None,
                           "currency": _cur(charge_raw, price_currency)},
        "target_days": target or None, "steps": steps, "office": raw.get("office") or None,
        "orderable": not problems, "problems": problems,
    }


def items(country, *, include_incomplete=False) -> list[dict]:
    from countries.selectors import config

    out = []
    price_currency = config(country, "price_currency", "USD") or "USD"
    for raw in config(country, "errand_catalogue", []) or []:
        if not isinstance(raw, dict) or not raw.get("code"):
            continue
        it = normalise(raw, country, price_currency)
        if it["orderable"] or include_incomplete:
            out.append(it)
    return out


def item(country, code) -> dict:
    """The orderable item, or 404 (not offered in this country) / 422 (incomplete)."""
    for it in items(country, include_incomplete=True):
        if it["code"] == code:
            if not it["orderable"]:
                raise Invalid("This errand is not ready to order: " + " ".join(it["problems"]),
                              code="catalogue-item-incomplete", extra={"problems": it["problems"]})
            return it
    raise NotFound("This errand is not offered in your country.")


def validate(raw_items, country) -> list[dict]:
    """For the configuration screens: every item's problems, so an incomplete errand is refused at publish."""
    return [{"code": r.get("code"), "problems": normalise(r, country)["problems"]}
            for r in raw_items or [] if normalise(r, country)["problems"]]
