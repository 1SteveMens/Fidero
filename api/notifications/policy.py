"""Template rendering and the content policy (FR-NTF-002, FR-NTF-004)."""
import re
from decimal import Decimal, InvalidOperation

from core.errors import Invalid

from . import catalogue

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
HIDDEN_AMOUNT = "an amount (see the app)"


def placeholders(text: str) -> set[str]:
    return set(PLACEHOLDER.findall(text or ""))


def validate_template(code: str, channel: str, subject: str, body: str) -> None:
    """Refuse unknown placeholders, missing required ones, and blocked fields
    on SMS, WhatsApp and push (TC-NTF-002-02, TC-NTF-004-02)."""
    e = catalogue.entry(code)
    if e is None:
        raise Invalid(f"There is no notification called '{code}'.", code="template-invalid")
    if channel not in catalogue.CHANNELS:
        raise Invalid(f"Unknown channel '{channel}'.", code="template-invalid")
    if not (body or "").strip():
        raise Invalid("The template text cannot be empty.", code="template-invalid")
    if (body or "").count("{{") != (body or "").count("}}") or (subject or "").count("{{") != (subject or "").count("}}"):
        raise Invalid("A placeholder is not closed. Use {{ name }}.", code="template-invalid")
    used = placeholders(body) | placeholders(subject)
    unknown = sorted(used - set(e["variables"]))
    if unknown:
        raise Invalid(f"Unknown placeholder: {', '.join(unknown)}. Allowed: {', '.join(e['variables'])}.",
                      code="template-invalid", extra={"unknown": unknown, "allowed": e["variables"]})
    missing = sorted(set(e.get("required", [])) - used) if channel in ("in_app", "email") else []
    if e.get("allows_code") and "otp_code" not in used:
        missing = ["otp_code"]
    if missing:
        raise Invalid(f"The template must use: {', '.join(missing)}.", code="template-invalid",
                      extra={"missing": missing})
    if channel in catalogue.PHONE_CHANNELS:
        blocked = sorted(v for v in used if catalogue.VARIABLES.get(v) == "sensitive"
                         or (catalogue.VARIABLES.get(v) == "code" and not e.get("allows_code")))
        if blocked:
            raise Invalid(f"These fields may not go by {channel}: {', '.join(blocked)} (FR-NTF-004).",
                          code="template-blocked-field", extra={"blocked": blocked})


def _amount_text(value, country, phone: bool) -> str:
    if isinstance(value, dict):
        amt, cur = value.get("amount"), (value.get("currency") or "").upper()
    else:
        amt, cur = value, ""
    try:
        d = Decimal(str(amt))
    except (InvalidOperation, TypeError):
        return "" if phone else str(value)
    if phone and above_threshold(d, cur, country):
        return HIDDEN_AMOUNT
    return f"{cur} {d:,.2f}".strip()


def above_threshold(amount: Decimal, currency: str, country) -> bool:
    """FR-NTF-004: compare with ntf_amount_threshold, converting with the
    exchange-rate guide. With no rate to compare, the amount counts as above."""
    from administration.selectors import guide_rate, setting

    t = setting("ntf_amount_threshold", country) or {}
    try:
        limit, lcur = Decimal(str(t.get("amount"))), (t.get("currency") or "").upper()
    except (InvalidOperation, TypeError, AttributeError):
        return True
    if not currency or currency == lcur:
        return amount > limit
    if country is None:
        return True
    r = guide_rate(country, lcur, currency)
    if r:
        return amount > limit * r.rate
    r = guide_rate(country, currency, lcur)
    if r:
        return amount * r.rate > limit
    return True


def render(text: str, context: dict, *, channel: str, country=None, allows_code=False) -> str:
    phone = channel in catalogue.PHONE_CHANNELS

    def sub(m):
        name = m.group(1)
        cls = catalogue.VARIABLES.get(name, "sensitive")
        value = (context or {}).get(name, "")
        if phone and (cls == "sensitive" or (cls == "code" and not allows_code)):
            return ""
        if cls == "amount":
            return _amount_text(value, country, phone) if value not in ("", None) else ""
        return "" if value is None else str(value)

    out = PLACEHOLDER.sub(sub, text or "")
    out = re.sub(r"\(\s*\)", "", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


# --- Free text on phone channels ------------------------------------------------

URL = re.compile(r"https?://\S+", re.I)
LONG_NUMBER = re.compile(r"(?<![\d.])\d[\d \-]{6,}\d(?![\d.])")
CODE_WORDS = re.compile(r"\b(code|pin|otp|password|passcode)\b\W{0,3}[A-Za-z0-9]{3,10}", re.I)
MONEY = re.compile(r"(?:(USD|GHS|GBP|EUR|NGN|KES|US\$|\$|£|€|₵|GH₵)\s?([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s?"
                   r"(USD|GHS|GBP|EUR|NGN|KES|cedis))", re.I)
SYMBOLS = {"$": "USD", "US$": "USD", "£": "GBP", "€": "EUR", "₵": "GHS", "GH₵": "GHS", "CEDIS": "GHS"}
BLOCKED_LINK_PARTS = ("evidence", "signature=", "x-amz", "token=", "/files/", "download")


def _long_number(m):
    s = m.group(0)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) or sum(ch.isdigit() for ch in s) < 8:
        return s
    return "[hidden]"


def safe_link(link: str) -> str:
    """Only links into the app or portal, never evidence or signed file links."""
    low = (link or "").lower()
    if not link or any(p in low for p in BLOCKED_LINK_PARTS):
        return ""
    return link


def sanitize(text: str, *, channel: str, country=None, allows_code=False) -> str:
    """Make free text safe for SMS, WhatsApp and push: no account numbers, codes,
    links other than app links, or amounts above the threshold."""
    if channel not in catalogue.PHONE_CHANNELS:
        return text
    out = URL.sub(lambda m: safe_link(m.group(0)), text or "")

    def money(m):
        cur = (m.group(1) or m.group(4) or "").upper()
        raw = (m.group(2) or m.group(3) or "").replace(",", "")
        try:
            amt = Decimal(raw)
        except InvalidOperation:
            return HIDDEN_AMOUNT
        cur = SYMBOLS.get(cur, cur)
        return HIDDEN_AMOUNT if above_threshold(amt, cur, country) else m.group(0)

    out = MONEY.sub(money, out)
    if not allows_code:
        out = CODE_WORDS.sub("[hidden]", out)
    out = LONG_NUMBER.sub(_long_number, out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()
