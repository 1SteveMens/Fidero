"""Report templates (FR-RPT-001; docs/operations/verification-report-template.md).

A report template is an `adm_config_version` of kind `report_template` keyed by
country and product line (land, building). Content (schema version 1):

    {"sections": [{"number": 1, "key": "cover", "title": "Cover page", "owner": "CM"}, ...],
     "extra_sections": [{"number": 15, "label": "10A", "after": 10, "key": "building_permit", ...}]}

Sections 1 to 14 must all be there, in order. Section 12 is the locked scope
statement and section 13 the signatures; the system fills both. Extra
sections (the building checks, FR-CASE-013) sit after section 10 and count in
the verdict rule like sections 4 to 10 (RUL-02).
"""
from core.errors import Invalid

OWNERS = {"CM", "LW", "SV", "IN", "system"}
SIGNING_ROLES = {"LW", "SV", "IN"}  # RUL-20: licensed professionals sign their sections
VERDICT_RULE = range(4, 11)  # RUL-02: sections 4 to 10


def _s(number, key, title, owner, **kw):
    return {"number": number, "key": key, "title": title, "owner": owner, **kw}


LAND_SECTIONS = [
    _s(1, "cover", "Cover page", "CM"),
    _s(2, "summary", "Summary", "LW"),
    _s(3, "scope_of_engagement", "Scope of engagement", "CM"),
    _s(4, "plot_identity", "Plot identity", "SV"),
    _s(5, "searches", "Lands Commission searches", "LW"),
    _s(6, "survey", "Surveyor's report", "SV"),
    _s(7, "overlays", "Overlay checks", "SV"),
    _s(8, "seller_authority", "Seller authority and consent", "LW"),
    _s(9, "chain_of_ownership", "Chain of ownership", "LW"),
    _s(10, "occupation", "Occupation and ground conditions", "SV"),
    _s(11, "verdict_conditions", "Verdict and conditions", "LW"),
    _s(12, "scope_statement", "Scope and limitation statement", "system", locked=True),
    _s(13, "signatures", "Signatures", "system", locked=True),
    _s(14, "appendices", "Appendices", "CM"),
]

BUILDING_EXTRA = [
    _s(15, "building_permit", "Building permit", "LW", label="10A", after=10),
    _s(16, "structural", "Structural inspection", "IN", label="10B", after=10),
    _s(17, "occupancy_tenancy", "Occupancy and tenancy", "LW", label="10C", after=10),
    _s(18, "rates_bills", "Property rates and utility bills", "CM", label="10D", after=10),
]

DEFAULT_TEMPLATES = {
    "land": {"sections": LAND_SECTIONS},
    "building": {"sections": LAND_SECTIONS, "extra_sections": BUILDING_EXTRA},
}


def validate(content) -> tuple[list, list]:
    """TC-RPT-001-02: a template with a missing or reordered section is refused."""
    if not isinstance(content, dict) or not isinstance(content.get("sections"), list):
        raise Invalid("A report template needs a list of sections.", code="config-invalid")
    sections = content["sections"]
    numbers = [s.get("number") if isinstance(s, dict) else None for s in sections]
    if numbers != list(range(1, 15)):
        raise Invalid("A report template needs sections 1 to 14, each once and in order.", code="config-invalid")
    for s in sections:
        if not s.get("key") or not s.get("title") or s.get("owner") not in OWNERS:
            raise Invalid(f"Section {s['number']} needs a key, a title and an owner "
                          f"({', '.join(sorted(OWNERS))}).", code="config-invalid")
    if sections[11].get("owner") != "system" or not sections[11].get("locked"):
        raise Invalid("Section 12 must be the locked scope statement.", code="config-invalid")
    extra = content.get("extra_sections") or []
    seen = set(numbers)
    for s in extra:
        n = s.get("number")
        if not isinstance(n, int) or n <= 14 or n > 30 or n in seen:
            raise Invalid("Extra sections need their own number from 15 to 30.", code="config-invalid")
        seen.add(n)
        if not s.get("key") or not s.get("title") or s.get("owner") not in OWNERS - {"system"}:
            raise Invalid(f"Extra section {n} needs a key, a title and an owner.", code="config-invalid")
        if s.get("after") not in range(4, 11):
            raise Invalid(f"Extra section {n} must sit after one of sections 4 to 10.", code="config-invalid")
    return sections, extra


def layout(content) -> list[dict]:
    """Every section with its position, label, verdict-rule and signature flags."""
    sections, extra = validate(content)
    out, pos = [], 0
    for s in sections:
        pos += 1
        n = s["number"]
        out.append({**s, "position": pos, "label": str(n), "in_verdict_rule": n in VERDICT_RULE,
                    "locked": bool(s.get("locked")), "needs_signature": s["owner"] in SIGNING_ROLES})
        for x in [e for e in extra if e["after"] == n]:
            pos += 1
            out.append({**x, "position": pos, "label": x.get("label") or str(x["number"]), "in_verdict_rule": True,
                        "locked": False, "needs_signature": x["owner"] in SIGNING_ROLES})
    return out
