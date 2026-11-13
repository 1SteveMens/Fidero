"""The configurable values of FR-ADM-005 and 02 section 6.8 (`adm_setting`).

Every default here is a working assumption, not verified data. Defaults
marked `to_verify` count as unset: a feature flag that depends on them cannot
be switched on until an administrator sets the value (US-ADM-005 criterion 2).

`affects_release`: a change needs a second administrator
(approval `release_setting_change`). `second_admin`: a change needs a second
administrator for another reason (approval `setting_change`).
"""
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from core.errors import Invalid


@dataclass(frozen=True)
class SettingDef:
    key: str
    type: str  # int | decimal | money | text | choice | json | list | bool
    default: object
    description: str
    unit: str = ""
    min: object = None
    max: object = None
    choices: tuple = ()
    affects_release: bool = False
    second_admin: bool = False
    to_verify: bool = False
    source: str = ""
    per_country: bool = True
    tags: tuple = field(default_factory=tuple)


S = SettingDef
DEFS = [
    S("fresh_search_window_days", "int", 14, "Fresh-search window, counted from the registry result date",
      "days", 1, 90, affects_release=True, to_verify=True, source="RUL-07"),
    S("listing_report_max_age_days", "int", 90, "Oldest report a listing may show", "days", 1, 365,
      affects_release=True, to_verify=True, source="RUL-12"),
    S("badge_validity_days", "int", 180, "How long a verified badge stays valid", "days", 1, 730,
      affects_release=True, to_verify=True, source="FR-LST-006"),
    S("plot_buffer_m", "decimal", "50", "Buffer distance around a plot for overlays", "m", "0", "1000",
      to_verify=True, source="FR-GEO-002"),
    S("device_time_gap_s", "int", 300, "Largest gap between device and server time before a flag", "s", 1, 86400,
      to_verify=True, source="FR-MOB-011"),
    S("dispute_deadlines", "json", {"response_days": 5, "evidence_days": 10, "decision_days": 10, "appeal_days": 10},
      "Dispute deadlines", "working days", affects_release=True, to_verify=True, source="FR-DSP-003"),
    S("client_approval_reminder_days", "int", 3, "Days before the client is reminded of an approval", "days", 1, 30,
      affects_release=True, to_verify=True, source="FR-ESC-006"),
    S("ntf_amount_threshold", "money", {"amount": "500.00", "currency": "USD"},
      "Amounts above this never appear in SMS, WhatsApp or push", "money", "0", None, to_verify=True,
      source="FR-NTF-004"),
    S("prj_enhanced_check_amount", "money", {"amount": "10000.00", "currency": "USD"},
      "Project fund amount that triggers enhanced checks", "money", "0", None, affects_release=True,
      to_verify=True, source="FR-PRJ-005"),
    S("checkin_radius_m", "int", 100, "Check-in distance from the registered address", "m", 10, 2000,
      to_verify=True, source="ADR-19"),
    S("visit_confirm_hours", "int", 24, "Hours a family member has to confirm a visit", "hours", 1, 72,
      source="FR-CARE-005"),
    S("rent_grace_days", "int", 5, "Days after the due date before rent is late", "days", 0, 60, to_verify=True,
      source="FR-PMG-003"),
    S("receipt_target_days", "int", 10, "Days for an institution to return a receipt", "days", 1, 60,
      to_verify=True, source="FR-FEE-004"),
    S("payee_cooling_off_hours", "int", 72, "Cooling-off after a payee account change", "hours", 1, 720,
      affects_release=True, to_verify=True, source="RUL-28"),
    S("recheck_sample_pct", "decimal", "5", "Monthly re-check share", "%", "0.5", "100", affects_release=True,
      to_verify=True, source="RUL-32"),
    S("search_result_overdue_days", "int", 10, "Days before a missing registry result is overdue", "days", 1, 90,
      to_verify=True, source="FR-CASE-016"),
    S("release_bank_pay_working_days", "int", 2, "Working days for the bank to pay after sending", "working days",
      1, 20, affects_release=True, to_verify=True, source="NFR-PERF-06"),
    S("release_median_target_working_days", "int", 5, "Median release time target (a reporting target)",
      "working days", 1, 30, affects_release=True, to_verify=True, source="NFR-PERF-06"),
    S("fx_hold_buffer_pct", "decimal", "5", "Foreign currency buffer for conversion at release", "%", "0", "50",
      affects_release=True, to_verify=True, source="RUL-36"),
    S("fx_comparison_providers", "list", [], "Providers in the daily rate comparison, per corridor", "",
      second_admin=True, to_verify=True, source="FR-ESC-024"),
    S("fx_comparison_amounts", "json", {}, "Send amounts per corridor for the comparison bands", "",
      to_verify=True, source="FR-ESC-024"),
    S("fx_rate_stale_hours", "int", 24, "A reference rate older than this cannot back a quote", "hours", 1, 168,
      to_verify=True, source="FR-ESC-023"),
    S("fx_quote_valid_minutes", "int", 15, "How long a quote holds", "minutes", 1, 240, to_verify=True,
      source="FR-ESC-023"),
    S("fx_delivery_tolerance", "decimal", "1.00", "Rounding allowed between quoted and delivered amount",
      "local currency", "0", "100", to_verify=True, source="IF-15"),
    S("app_fee_payment_mode", "choice", "web", "How the apps take Tenmina's fees (per country)", "",
      choices=("web", "in_app_provider"), second_admin=True, source="FR-APP-005"),
    # Keys the line modules read from the country configuration (countries.selectors.config). A value in the
    # published country configuration wins; else an administrator's setting row; else the module's default,
    # which is the default shown here. All are working assumptions [TO VERIFY].
    S("fees.payment_route", "choice", "client_direct", "How family payments to institutions are paid: the client "
      "pays the verified account directly, or the bank pays from money held for the client", "",
      choices=("client_direct", "held_funds"), affects_release=True, to_verify=True, source="FR-FEE-003"),
    S("fees.service_fee", "choice", "per_payment", "Tenmina's own fee on a family payment: per payment, or none",
      "", choices=("per_payment", "none"), second_admin=True, to_verify=True, source="FR-FEE-003"),
    S("fees.term_months", "int", 4, "Length of a school term for recurring fee schedules", "months", 1, 12,
      to_verify=True, source="FR-FEE-005"),
    S("construction.payment_route", "choice", "client_direct", "How stage payments on a build are paid: the client "
      "pays the verified contractor directly, or the bank pays from escrow", "",
      choices=("client_direct", "escrow"), affects_release=True, to_verify=True, source="FR-BLD-005"),
    S("pmg.repair_single_quote_max_amount", "decimal", None, "Largest repair that may go ahead on one quote (unset: "
      "every repair needs two quotes)", "local currency", "0", None, affects_release=True, to_verify=True,
      source="FR-PMG-004"),
    S("pmg.inspection_interval_months", "int", 6, "Months between routine inspections of a managed property",
      "months", 1, 24, to_verify=True, source="FR-PMG-002"),
    S("evt.deposit_share_pct", "decimal", "50", "Share of an event vendor's price paid as a deposit", "%", "0",
      "100", affects_release=True, to_verify=True, source="FR-EVT-002"),
    S("insurance.renewal_reminder_days", "int", 30, "Days before renewal that the client is reminded", "days", 1,
      120, to_verify=True, source="FR-INS-003"),
    S("insurance.premium_lead_days", "int", 14, "Days before a premium is due that the client is reminded", "days",
      1, 60, to_verify=True, source="FR-INS-002"),
    S("insurance.intermediary_licence_required", "bool", True, "Tenmina must hold an intermediary licence before "
      "insurance is offered in the country", "", second_admin=True, to_verify=True, source="C-11"),
]
REGISTRY = {d.key: d for d in DEFS}

# Settings a feature needs before it can be switched on (US-ADM-005 criterion 2).
FLAG_REQUIRES = {
    "escrow.enabled": ["fresh_search_window_days", "client_approval_reminder_days", "payee_cooling_off_hours",
                       "release_bank_pay_working_days", "release_median_target_working_days",
                       "fx_hold_buffer_pct", "fx_rate_stale_hours", "fx_quote_valid_minutes", "recheck_sample_pct"],
    "listings.enabled": ["listing_report_max_age_days", "badge_validity_days", "fresh_search_window_days"],
    "mobile.capture": ["device_time_gap_s", "plot_buffer_m"],
    "projects.funds": ["prj_enhanced_check_amount"],
    "building.construction": ["device_time_gap_s"],
    "lines.fee": ["receipt_target_days", "ntf_amount_threshold"],
    "lines.care": ["checkin_radius_m", "visit_confirm_hours"],
    "lines.pmg": ["rent_grace_days"],
    "lines.tsk": ["search_result_overdue_days"],
}


def definition(key: str) -> SettingDef:
    d = REGISTRY.get(key)
    if d is None:
        raise Invalid(f"There is no setting called '{key}'.", code="unknown-setting")
    return d


def _range_msg(d):
    lo = "" if d.min is None else f"from {d.min}"
    hi = "" if d.max is None else f"to {d.max}"
    return " ".join(x for x in (lo, hi) if x) + (f" {d.unit}" if d.unit else "")


def validate(key: str, value):
    """Check a value against its definition; return the normalised value.
    Unsafe values are refused with the allowed range (TC-ADM-005-02)."""
    d = definition(key)
    err = {"allowed": {"min": d.min, "max": d.max, "choices": list(d.choices), "type": d.type}}
    if d.type == "int":
        try:
            v = int(value)
            if str(value).strip() not in (str(v), f"{v}.0"):
                raise ValueError
        except (TypeError, ValueError):
            raise Invalid(f"{key} must be a whole number.", code="setting-out-of-range", extra=err) from None
        if (d.min is not None and v < d.min) or (d.max is not None and v > d.max):
            raise Invalid(f"{key} must be {_range_msg(d)}.", code="setting-out-of-range", extra=err)
        return v
    if d.type in ("decimal", "money"):
        raw = value.get("amount") if (d.type == "money" and isinstance(value, dict)) else value
        try:
            v = Decimal(str(raw))
        except (InvalidOperation, TypeError):
            raise Invalid(f"{key} must be a number.", code="setting-out-of-range", extra=err) from None
        if (d.min is not None and v < Decimal(str(d.min))) or (d.max is not None and v > Decimal(str(d.max))):
            raise Invalid(f"{key} must be {_range_msg(d)}.", code="setting-out-of-range", extra=err)
        if d.type == "money":
            cur = str((value or {}).get("currency", "")).upper() if isinstance(value, dict) else ""
            if len(cur) != 3:
                raise Invalid(f'{key} needs a currency: {{"amount": "500.00", "currency": "USD"}}.',
                              code="setting-out-of-range", extra=err)
            return {"amount": f"{v:.2f}", "currency": cur}
        return str(v)
    if d.type == "choice":
        if value not in d.choices:
            raise Invalid(f"{key} must be one of {', '.join(d.choices)}.", code="setting-out-of-range", extra=err)
        return value
    if d.type == "bool":
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in ("true", "false"):
            return str(value).strip().lower() == "true"
        raise Invalid(f"{key} must be true or false.", code="setting-out-of-range", extra=err)
    if d.type == "list":
        if not isinstance(value, list):
            raise Invalid(f"{key} must be a list.", code="setting-out-of-range", extra=err)
        return value
    if d.type == "json":
        if not isinstance(value, dict):
            raise Invalid(f"{key} must be an object.", code="setting-out-of-range", extra=err)
        for k, v in value.items():
            if isinstance(v, (int, float)) and v <= 0:
                raise Invalid(f"{key}.{k} must be above zero.", code="setting-out-of-range", extra=err)
        return value
    if not isinstance(value, str):
        raise Invalid(f"{key} must be text.", code="setting-out-of-range", extra=err)
    return value
