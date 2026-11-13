"""ORD demo data: orders in every state for the seeded cast (Ghana). Idempotent.

Each seeded order carries details["seed"] so a second run finds it. PAY's seed
then pays, fails, refunds and reconciles some of them."""
from core.errors import DomainError

from . import legal, services
from .models import Order

ORDERS = [
    # key, person, kind, data, submit
    ("ama_land_card", "client", "verification", {
        "tier": "standard", "lead_source": "webinar", "lead_source_detail": "Diaspora association webinar, London",
        "asset": {"type": "plot", "locality": "Kasoa, Millennium City", "plot_number": "118",
                  "site_plan_ref": "CR/KAS/2026/118", "ghana_post_gps": "CX-123-4567"},
        "seller": {"name": "Nii Armah Quaye", "phone": "+233244100118"}}, True),
    ("ama_house_draft", "client", "verification", {
        "tier": "premium", "lead_source": "webinar",
        "asset": {"type": "building", "locality": "East Legon, Accra"},
        "details": {"building_permit_number": "AMA/BP/2019/221", "occupied": True}}, False),
    ("ama_land_refunded", "client", "verification", {
        "tier": "basic", "lead_source": "webinar",
        "asset": {"type": "plot", "locality": "Oyibi", "plot_number": "44", "site_plan_ref": "GA/OYB/2025/44"},
        "seller": {"name": "Oyibi Family Secretary", "phone": "+233200440044"}}, True),
    ("ama_family_plan", "client", "family_plan", {
        "lead_source": "association", "details": {"period_month": "2026-12"}}, True),
    ("kofi_land_momo_failed", "client2", "verification", {
        "tier": "basic", "lead_source": "association",
        "asset": {"type": "plot", "locality": "Prampram", "plot_number": "7", "site_plan_ref": "GA/PRA/2026/7"},
        "seller": {"name": "Prampram Stool Land Secretariat", "phone": "+233302700700"}}, True),
    ("kofi_land_offline_paid", "client2", "verification", {
        "tier": "standard", "lead_source": "remittance_partner",
        "asset": {"type": "plot", "locality": "Dawhenya", "plot_number": "201", "site_plan_ref": "GA/DAW/2026/201"},
        "seller": {"name": "Esther Lartey", "phone": "+233201000201"}}, True),
    ("kofi_house_offline_pending", "client2", "verification", {
        "tier": "premium", "lead_source": "remittance_partner",
        "asset": {"type": "building", "locality": "Tema Community 25", "site_plan_ref": "TMA/C25/2018/9"},
        "seller": {"name": "Joseph Tetteh", "phone": "+233208000009"},
        "details": {"building_permit_number": "TMA/BP/2018/090"}}, True),
]


def _doc(person, gh, key):
    from evidence.services import store

    return store(data=f"%PDF-1.4 demo site plan for {key}".encode(), country=gh, uploaded_by=person,
                 content_type="application/pdf", original_name=f"{key}-site-plan.pdf", source="upload")


def _accept(gh):
    t = legal.current(gh)
    return {"accept_terms": True, "terms_version": t["terms_version"], "scope_version": t["scope_version"]}


def run(ctx):
    gh, people = ctx["gh"], ctx["people"]
    seeded = ctx.setdefault("orders", {})
    for key, who, kind, data, submit in ORDERS:
        existing = Order.objects.filter(details__seed=key).first()
        if existing:
            seeded[key] = existing
            continue
        person = people[who]
        payload = {**data, "details": {**data.get("details", {}), "seed": key}}
        if submit:
            payload.update(_accept(gh))
            if kind == "verification":
                payload["upload_ids"] = [_doc(person, gh, key).pk]
        seeded[key] = services.create_order(actor=person, country=gh, kind=kind, data=payload, draft=not submit,
                                            ip="127.0.0.1", user_agent="seed")

    # A referral: Kofi orders a fresh search with Ama's code (reward owed once PAY's seed pays it).
    code = services.my_referral_code(people["client"], gh)
    key = "kofi_fresh_search_referred"
    if not Order.objects.filter(details__seed=key).exists():
        parent = seeded["kofi_land_offline_paid"]
        seeded[key] = services.create_order(
            actor=people["client2"], country=gh, kind="fresh_search", draft=False,
            data={"parent_order_id": parent.pk, "lead_source": "referral", "referral_code": code.code,
                  "asset": {"type": "plot", "locality": parent.locality, "plot_number": parent.plot_number,
                            "site_plan_ref": parent.site_plan_ref},
                  "details": {"seed": key}, **_accept(gh)})
    else:
        seeded[key] = Order.objects.get(details__seed=key)
    if not services.ReferralCode.objects.filter(code="GHUNION-UK").exists():
        services.create_referral_code(people["cm"], country=gh, code="GHUNION-UK",
                                      owner_label="Ghana Union UK (association) [TO VERIFY terms]")

    # Checked plots (seller pays by invoice): two plots from Ato Estates, placed by a case manager.
    from accounts.models import Organisation

    org = Organisation.objects.filter(name="Ato Estates Ltd").first()
    for key, plot in (("ato_checked_plot_1", "A-12"), ("ato_checked_plot_2", "A-13")):
        if org is None:
            break
        existing = Order.objects.filter(details__seed=key).first()
        if existing:
            seeded[key] = existing
            continue
        seeded[key] = services.create_order(
            actor=people["cm"], on_behalf_of=people["seller"], country=gh, kind="listing_verification",
            draft=True, data={"organisation_id": org.pk, "lead_source": "other",
                              "asset": {"type": "plot", "locality": "Ato Estates, Afienya", "plot_number": plot,
                                        "site_plan_ref": f"GA/AFI/ATO/{plot}"},
                              "details": {"seed": key}})
        services.link_uploads(seeded[key], people["seller"], [_doc(people["seller"], gh, key).pk])
        t = legal.current(gh)
        services.accept_terms(seeded[key], people["seller"], t["terms_version"], t["scope_version"])
        seeded[key] = services.submit(seeded[key], people["cm"])

    # An extra inspection on a build, when the construction module can confirm the project.
    project = ctx.get("project")
    if project is not None and not Order.objects.filter(details__seed="ama_extra_inspection").exists():
        try:
            seeded["ama_extra_inspection"] = services.order_extra_inspection(
                actor=people["client"], project_id=project.pk,
                data={"concern": "Cracks in the ring beam after the rains", "details": {"seed": "ama_extra_inspection"},
                      "country": gh, **_accept(gh)})
        except DomainError:
            pass
