"""The product catalogue for Tenmina's fee side (FR-ORD-001, FR-ORD-002, FR-ORD-007).

Every product a client can buy from Tenmina is an order kind here. The list
of kinds is code (each kind needs its own fields and its own downstream
handler); everything that differs by country, such as prices, tiers, names
and turnaround, is data read through `pricing.py`.

Each kind maps to exactly one `pay_fee_payment.purpose`. There is no kind
for purchase, construction, project or premium money (RUL-01, RUL-25).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Product:
    kind: str
    name: str
    purpose: str                       # pay_fee_payment.purpose (ADR-03)
    line: str                          # product family: property, family, projects
    product_line: str = ""             # case template line for CASE (land, building, ...)
    flag: str | None = None            # feature flag that opens the product in a country
    tiered: bool = False               # price depends on a tier
    needs_asset: bool = False          # locality, plot number, site plan ref, seller (FR-ORD-001)
    needs_seller: bool = False
    needs_documents: bool = False      # at least one document, the site plan for land (FR-ORD-001)
    subject_type: str = ""             # the object the order is about, owned by another module
    roles: tuple = ("CL",)             # roles that may place the order themselves
    bill_to: str = "client"            # client pays, or "organisation" pays by invoice (PAY-007)
    asset_types: tuple = ()
    description: str = ""
    required_details: tuple = field(default_factory=tuple)


PRODUCTS: dict[str, Product] = {p.kind: p for p in [
    Product("verification", "Land or house verification report", "report_fee", "property",
            tiered=True, needs_asset=True, needs_seller=True, needs_documents=True, roles=("CL", "SE", "DV"),
            asset_types=("plot", "building"),
            description="We check the plot or house at the registry, on site and with a lawyer, and give you "
                        "a signed report with a verdict."),
    Product("fresh_search", "Fresh official search", "report_fee", "property", product_line="fresh_search",
            needs_asset=True, roles=("CL", "SE", "DV"), asset_types=("plot", "building"),
            description="A new search at the registry on a plot we checked before, for an escrow release or "
                        "a reservation."),
    Product("extra_inspection", "Extra inspection on your build", "inspection_fee", "property",
            product_line="construction", flag="building.construction", subject_type="project",
            description="An inspector visits your build between milestones to check a worry."),
    # US-LST-009: an authority representative (AR) orders the check for a family or stool listing, billed to
    # the authority's organisation, on the same terms as a seller.
    Product("listing_verification", "Checked plot (seller pays)", "report_fee", "property",
            needs_asset=True, needs_documents=True, roles=("SE", "DV", "AR"), bill_to="organisation",
            asset_types=("plot", "building"),
            description="A seller pays a fixed fee per plot checked, the same whatever the verdict. "
                        "There is no success fee."),
    Product("institution_verification", "Verify a school, hospital or provider", "institution_service_fee",
            "family", product_line="institution", flag="lines.fee", subject_type="institution",
            description="We check the institution's registration, its account in its own name and a named "
                        "contact before you pay it."),
    Product("family_payment_fee", "Verify and confirm one payment", "institution_service_fee", "family",
            flag="lines.fee", subject_type="fee_invoice",
            description="We check the bill with the institution, and confirm your payment reached it."),
    Product("family_plan", "Family payments monthly plan", "institution_service_fee", "family",
            flag="lines.fee", required_details=("period_month",),
            description="Every payment to your verified institutions for one month, checked and confirmed."),
    Product("property_onboarding", "Register a property for management", "property_mgmt_fee", "property",
            product_line="property_onboarding", flag="lines.pmg", needs_asset=True, asset_types=("building",),
            description="We inspect your house and record its condition before we manage it."),
    Product("errand", "Paperwork and errands", "errand_fee", "projects", product_line="errand",
            flag="lines.tsk", required_details=("errand_code",),
            description="A vetted agent gets a document done for you. Official fees are paid separately to "
                        "the partner bank."),
    Product("care_plan", "Care visits plan", "care_service_fee", "family", product_line="care",
            flag="lines.care", subject_type="care_plan",
            description="Visits to your relative by a vetted carer, each one confirmed by the family."),
    Product("event_service", "Event payments service", "event_service_fee", "projects", product_line="event",
            flag="lines.evt", subject_type="event",
            description="We check your event vendors and pay them against signed quotes."),
]}

KINDS = list(PRODUCTS)

# Lead sources (FR-ORD-005). A country may configure its own list under
# `lead_sources`; this is the default from document 01.
LEAD_SOURCES = ["association", "webinar", "referral", "remittance_partner", "other"]

# Fee purposes allowed on pay_fee_payment (02 section 6.4). Kept here too so
# orders never create a kind whose purpose PAY would refuse.
FEE_PURPOSES = ["report_fee", "escrow_fee", "inspection_fee", "listing_fee", "success_fee",
                "construction_mgmt_fee", "api_fee", "conveyancing_fee", "institution_service_fee",
                "care_service_fee", "property_mgmt_fee", "errand_fee", "event_service_fee"]

assert all(p.purpose in FEE_PURPOSES for p in PRODUCTS.values())


def product(kind: str) -> Product:
    from core.errors import Invalid

    p = PRODUCTS.get(kind)
    if p is None:
        raise Invalid(f"'{kind}' is not something Tenmina sells.", code="validation-error")
    return p


def product_line(kind: str, asset_type: str = "") -> str:
    """The case template line CASE uses for the order (US-ORD-001 AC4, US-CASE-013)."""
    p = PRODUCTS[kind]
    if kind in ("verification", "listing_verification"):
        return "building" if asset_type == "building" else "land"
    return p.product_line
