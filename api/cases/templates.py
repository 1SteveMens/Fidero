"""Case templates (FR-CASE-001, FR-CASE-002, FR-CASE-013, FR-CASE-014; ADR-11, ADR-21).

A case template is an `adm_config_version` of kind `case_template`, keyed by
country and product line. New cases use the latest published version; a case
keeps the version it started with (US-CASE-001 AC2).

Content (schema version 1):

    {"tasks": [
        {"key": "site_visit", "title": "Visit the site", "role": "RN", "due_days": 5,
         "evidence": ["site_photo", "pillar_photo"], "after": ["intake"],
         "site_visit": true, "search": "", "review": false,
         "client_message": "Our team visited the plot on {date}. Next update by {next_date}."},
        ...]}

- role: the owner role (CM, RV, LW, SV, RN, IN, QS, CE).
- due_days: target duration, counted in days from the day the case is accepted.
- evidence: evidence kinds that must be linked to the task before it can be done (FR-CASE-004).
- after: steps that must be done first; until then the step shows as waiting.
- site_visit: a field visit, so a risk screen is needed before assignment (FR-CASE-009, RUL-17).
- search: "lodge" needs an official search recorded as submitted from Tenmina's registry account;
  "result" needs a usable result received from the registry's own channel (FR-CASE-016, RUL-30).
- review: done by the review and release of the report or verification decision, not by hand.
- client_message: the plain-language status the client sees when the step is done (FR-CASE-007).

The defaults below are working assumptions [TO VERIFY] that the seed publishes per
country; administrators publish new versions in the back office.
"""
from core.errors import Invalid

ROLES = {"CM", "RV", "LW", "SV", "RN", "IN", "QS", "CE"}
SEARCH_KINDS = {"", "lodge", "result"}

# Product lines (02 6.5 case_case.product_line, plus the checks other lines start through open_case).
LINES = {
    "land": {"name": "Land verification", "needs_order": True, "needs_asset": True, "report": True, "flag": None},
    "building": {"name": "House or building check", "needs_order": True, "needs_asset": True, "report": True,
                 "flag": None},
    "fresh_search": {"name": "Fresh official search", "needs_order": False, "needs_asset": True, "report": False,
                     "flag": None},
    "institution_verification": {"name": "Institution verification", "needs_order": False, "needs_asset": False,
                                 "report": False, "flag": "lines.fee"},
    "property_onboarding": {"name": "Property onboarding", "needs_order": False, "needs_asset": True,
                            "report": False, "flag": "lines.pmg"},
    "vendor_verification": {"name": "Vendor verification", "needs_order": False, "needs_asset": False,
                            "report": False, "flag": "lines.evt"},
    "supplier_check": {"name": "Supplier check", "needs_order": False, "needs_asset": False, "report": False,
                       "flag": "projects.funds"},
    "contractor_check": {"name": "Contractor check", "needs_order": False, "needs_asset": False, "report": False,
                         "flag": "building.construction"},
    "developer_check": {"name": "Developer check", "needs_order": False, "needs_asset": False, "report": False,
                        "flag": "listings.enabled"},
}

SEARCH_NOTICE = "Search results come from Tenmina's office, not from you."


def _t(key, title, role, due_days, evidence=(), after=(), site_visit=False, search="", review=False, msg=""):
    return {"key": key, "title": title, "role": role, "due_days": due_days, "evidence": list(evidence),
            "after": list(after), "site_visit": site_visit, "search": search, "review": review,
            "client_message": msg}


LAND_TASKS = [
    _t("intake", "Check the order and the documents", "CM", 1,
       msg="We checked your order and documents on {date}. Next update by {next_date}."),
    _t("searches_lodged", "Lodge the official searches from Tenmina's registry account", "CM", 2,
       evidence=["search_fee_receipt"], after=["intake"], search="lodge",
       msg="Searches lodged at the {registry} on {date}. Results expected by {next_date}."),
    _t("site_visit", "Visit the plot and capture evidence", "RN", 5, evidence=["site_photo", "pillar_photo"],
       after=["intake"], site_visit=True,
       msg="Our team visited the plot on {date}. Next update by {next_date}."),
    _t("overlay_check", "Check the boundary and the overlays", "SV", 7, evidence=["survey_report"],
       after=["site_visit"], msg="The surveyor checked the boundary and the maps on {date}. "
                                 "Next update by {next_date}."),
    _t("consent_meeting", "Hold and record the consent meeting", "LW", 8,
       evidence=["consent_form", "consent_video"], after=["intake"],
       msg="The consent meeting was held and recorded on {date}. Next update by {next_date}."),
    _t("official_search", "Receive the search results from the registry", "CM", 12, after=["searches_lodged"],
       search="result", msg="The search results came back from the {registry} on {date}. "
                            "Next update by {next_date}."),
    _t("legal_review", "Review the title and the chain of ownership", "LW", 14, evidence=["legal_note"],
       after=["official_search", "consent_meeting"],
       msg="The lawyer finished the legal review on {date}. Your report is next, by {next_date}."),
    _t("second_review", "Second review of the report", "RV", 16, after=["legal_review", "overlay_check"],
       review=True, msg="A second reviewer checked your report on {date}."),
    _t("release", "Release the report", "RV", 17, after=["second_review"], review=True,
       msg="Your report was released on {date}. You can open it now."),
]

BUILDING_EXTRA = [
    _t("building_permit_check", "Check the building permit with the assembly", "LW", 9,
       evidence=["permit_copy"], after=["intake"],
       msg="The building permit was checked on {date}. Next update by {next_date}."),
    _t("structural_inspection", "Inspect the structure", "IN", 9, evidence=["structural_report", "site_photo"],
       after=["intake"], site_visit=True,
       msg="An inspector checked the structure on {date}. Next update by {next_date}."),
    _t("occupancy_check", "Check who lives there and any tenancy", "RN", 9, evidence=["occupancy_note"],
       after=["intake"], site_visit=True,
       msg="We checked who lives in the house on {date}. Next update by {next_date}."),
    _t("rates_bills_check", "Check property rates and utility bills", "CM", 10, evidence=["rates_bills"],
       after=["intake"], msg="Property rates and utility bills were checked on {date}. Next update by {next_date}."),
]


def _building_tasks():
    out = []
    for t in LAND_TASKS:
        t = dict(t)
        if t["key"] == "legal_review":
            t["after"] = t["after"] + ["building_permit_check", "occupancy_check"]
        if t["key"] == "second_review":
            t["after"] = t["after"] + ["structural_inspection", "rates_bills_check"]
        out.append(t)
        if t["key"] == "consent_meeting":
            out.extend(BUILDING_EXTRA)
    return out


FRESH_SEARCH_TASKS = [
    _t("fresh_search", "Repeat the official search from Tenmina's registry account", "CM", 7, search="result",
       msg="A new official search came back from the {registry} on {date}."),
    _t("site_check", "Check the plot again on site", "RN", 5, evidence=["site_photo"], site_visit=True,
       msg="Our team checked the plot again on {date}."),
]


def _verification(first, visit_role="RN", visit_title="Visit the address", extra=()):
    return [
        *first,
        _t("site_visit", visit_title, visit_role, 5, evidence=["site_photo"], site_visit=True,
           msg="Our team visited on {date}. Next update by {next_date}."),
        *extra,
        _t("decision", "Decide whether it is verified", "RV", 8,
           after=[t["key"] for t in first] + ["site_visit"] + [t["key"] for t in extra], review=True,
           msg="The check was finished on {date}."),
    ]


DEFAULT_TEMPLATES = {
    "land": {"tasks": LAND_TASKS},
    "building": {"tasks": _building_tasks()},
    "fresh_search": {"tasks": FRESH_SEARCH_TASKS},
    "institution_verification": {"tasks": _verification([
        _t("registration_check", "Check the registration with the regulator", "CM", 2,
           evidence=["registration_certificate"], msg="We checked the registration on {date}."),
        _t("account_check", "Check the account is in the institution's own name", "CM", 3,
           evidence=["bank_letter"], msg="We checked the institution's bank account on {date}."),
        _t("contact_check", "Confirm a named contact at the institution", "CM", 3,
           evidence=["contact_confirmation"], msg="We spoke to a named contact on {date}."),
    ])},
    "property_onboarding": {"tasks": _verification([
        _t("ownership_check", "Check the owner's documents", "CM", 2, evidence=["title_document"],
           msg="We checked the ownership documents on {date}."),
    ], visit_role="IN", visit_title="Inspect the property and record its condition")},
    "vendor_verification": {"tasks": _verification([
        _t("registration_check", "Check the vendor's registration", "CM", 2, evidence=["registration_certificate"],
           msg="We checked the vendor's registration on {date}."),
        _t("identity_check", "Check the person who signs for the vendor", "CM", 2,
           evidence=["identity_check_reference"], msg="We checked the vendor's signatory on {date}."),
    ])},
    "supplier_check": {"tasks": _verification([
        _t("registration_check", "Check the supplier's registration", "CM", 2, evidence=["registration_certificate"],
           msg="We checked the supplier's registration on {date}."),
        _t("trade_reference", "Take up trade references", "CM", 3, evidence=["trade_reference"],
           msg="We took up the supplier's references on {date}."),
    ], visit_title="Visit the supplier's yard")},
    "contractor_check": {"tasks": _verification([
        _t("registration_check", "Check the contractor's registration and class", "CM", 2,
           evidence=["registration_certificate"], msg="We checked the contractor's registration on {date}."),
        _t("past_work", "Inspect past work and take references", "IN", 5, evidence=["site_photo", "reference_note"],
           site_visit=True, msg="An inspector looked at the contractor's past work on {date}."),
    ], visit_role="IN", visit_title="Visit the contractor's office or yard")},
    "developer_check": {"tasks": _verification([
        _t("registration_check", "Check the developer's registration and licence", "CM", 2,
           evidence=["registration_certificate"], msg="We checked the developer's registration on {date}."),
        _t("land_title_check", "Check title to the development land", "LW", 7, evidence=["legal_note"],
           msg="The lawyer checked the development land on {date}."),
    ], visit_title="Visit the development site")},
}

# Fallback status texts by step key when a template step has none (TC-CASE-007-02: never a blank status).
GENERIC_MESSAGE = "{title} was done on {date}. Next update by {next_date}."


def validate(content) -> list[dict]:
    """Raise Invalid with a plain message unless the content is a usable case template.
    TC-CASE-002-02: every step needs an owner role and an evidence list."""
    if not isinstance(content, dict):
        raise Invalid("A case template must be an object.", code="config-invalid")
    tasks = content.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise Invalid("A case template needs a non-empty list of tasks.", code="config-invalid")
    keys = set()
    for i, t in enumerate(tasks, 1):
        if not isinstance(t, dict):
            raise Invalid(f"Step {i} is not an object.", code="config-invalid")
        key = t.get("key")
        if not key or not t.get("title"):
            raise Invalid(f"Step {i} needs a key and a title.", code="config-invalid")
        if key in keys:
            raise Invalid(f"Step '{key}' appears twice.", code="config-invalid")
        keys.add(key)
        if t.get("role") not in ROLES:
            raise Invalid(f"Step '{key}' needs an owner role ({', '.join(sorted(ROLES))}).", code="config-invalid")
        if not isinstance(t.get("evidence"), list):
            raise Invalid(f"Step '{key}' needs a list of required evidence (it may be empty).", code="config-invalid")
        try:
            if int(t.get("due_days")) < 0:
                raise ValueError
        except (TypeError, ValueError):
            raise Invalid(f"Step '{key}' needs a target duration in days.", code="config-invalid") from None
        if t.get("search", "") not in SEARCH_KINDS:
            raise Invalid(f"Step '{key}' has an unknown search kind.", code="config-invalid")
    for t in tasks:
        for dep in t.get("after", []) or []:
            if dep not in keys:
                raise Invalid(f"Step '{t['key']}' waits for '{dep}', which is not in the template.",
                              code="config-invalid")
    return tasks
