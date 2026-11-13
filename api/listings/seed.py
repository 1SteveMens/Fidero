"""LST demo data (Ghana), built through the real services so every rule runs (sequence 5.5, J-04).

- Ato Estates (screened, established seller): plot A-12 live with the badge from its paid checked-plot report;
  a plot reserved by Ama with a fresh search and a proposed purchase escrow; a plot suspended by a case
  manager; a plot sold through its escrow; a plot rejected on an amber report.
- Sunrise Homes (developer, screening in progress): an off-plan unit in verification and a draft.
- An enquiry about A-12 and a 'looking for land' enquiry answered by Tenmina.
Every price is a synthetic figure [TO VERIFY], not market data.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from core.errors import DomainError

log = logging.getLogger(__name__)

TITLES = {
    "live": "Serviced plot A-12, Ato Estates",
    "reserved": "Corner plot B-03, Ato Estates",
    "suspended": "Plot C-07, Ato Estates",
    "sold": "Plot D-01, Ato Estates",
    "rejected": "Plot E-09, Ato Estates",
    "in_verification": "Two-bedroom off-plan unit, Sunrise Gardens",
    "draft": "Three-bedroom house, Sunrise Gardens phase 2",
}


def doc(person, gh, name, kind="application/pdf"):
    from evidence.services import store

    data = (b"\xff\xd8\xff\xe0" + f"listing photo {name}".encode()) if kind == "image/jpeg" \
        else f"%PDF-1.4 listing document {name}".encode()
    return store(data=data, country=gh, uploaded_by=person, content_type=kind, original_name=name)


def pay_invoice(inv, payer):
    """Pay a seller invoice by card through the fake provider, as PAY's seed does."""
    from payments import adapters
    from payments import services as pay

    if inv is None or inv.status != "issued":
        return inv
    p = pay._start(payer=payer, country=inv.country, purpose=inv.purpose, amount=inv.amount, currency=inv.currency,
                   method="card", invoice=inv)
    pay.handle_webhook(*adapters.provider().complete(p.provider_ref, "success"))
    inv.refresh_from_db()
    return inv


def listing_fee_invoice(listing):
    from payments.models import Invoice

    return Invoice.objects.filter(kind="listing_fee", subject_type="listing", subject_id=listing.pk).exclude(
        status="void").first()


def check_invoice(listing):
    from payments.models import Invoice

    if not listing.verification_order_id:
        return None
    return Invoice.objects.filter(order_id=listing.verification_order_id).exclude(status="void").first()


def release_report(case, gh, people, verdict="green"):
    """Sequence 5.2 to a released report with the given verdict (green, or amber with conditions)."""
    from reports import services as rs
    from reports.models import Report
    from reports.seed import release_demo_case

    if verdict == "amber":
        return release_demo_case(case, gh, people)
    report = release_demo_case(case, gh, people, stop="sections")
    report = Report.objects.get(pk=report.pk)
    if report.status == "draft":
        rs.set_overall_verdict(report, people["lawyer"], verdict)
        if not report.conditions.exists():
            rs.add_condition(report, people["lawyer"], key="fresh_search",
                             text="Fresh official search within the window before release", responsible="tenmina",
                             closing_evidence="Official search result from Tenmina's registry account")
        rs.sign_sections(report, people["surveyor"])
        rs.sign_sections(report, people["lawyer"])
        report = rs.submit_review(report, people["cm"])
    if report.status == "in_review":
        now = timezone.now()
        rs.approve(report, people["lawyer"], mfa_at=now, note="Legal sections reviewed.")
        rs.approve(report, people["reviewer"], mfa_at=now, note="Second review done.")
    report.refresh_from_db()
    return report


def new_listing(gh, people, *, seller="seller", org=None, title, plot, price="150000.00", kind="plot",
                locality="Ato Estates, Afienya", location=None, submit=True, pay_fee=True, pay_check=True,
                verdict="green"):
    """A seller's listing taken as far as asked: draft, submitted, fees paid, check released."""
    from orders import legal

    from . import services

    person = people[seller]
    listing = services.create_listing(actor=person, country=gh, data={
        "organisation_id": org.pk if org else None, "kind": kind, "title": title,
        "description": f"{title}. Dry land, road access, electricity nearby. [demo]",
        "price": {"amount": price, "currency": "GHS"}, "size_sqm": "464.00",
        "asset": {"locality": locality, "region": "Greater Accra", "district": "Kpone-Katamanso",
                  "plot_number": plot, "site_plan_ref": f"GA/AFI/{plot}", "location": location}})
    services.add_media(listing, person, kind="site_plan", evidence=doc(person, gh, f"site-plan-{plot}.pdf"))
    services.add_media(listing, person, kind="photo", caption="View from the access road",
                       evidence=doc(person, gh, f"{plot}.jpg", "image/jpeg"))
    if not submit:
        return listing
    t = legal.current(gh)
    listing = services.submit(listing, person, terms_version=t["terms_version"], scope_version=t["scope_version"])
    if pay_fee:
        pay_invoice(listing_fee_invoice(listing), person)
    if pay_check and listing.verification_order_id:
        pay_invoice(check_invoice(listing), person)
        listing.refresh_from_db()
        from cases.models import Case

        case = Case.objects.filter(order_id=listing.verification_order_id).first()
        if case is not None and verdict:
            release_report(case, gh, people, verdict)
    listing.refresh_from_db()
    return listing


def prepare_sellers(gh, people, orgs):
    """Sellers act for their organisation through an organisation-scoped role grant, as accounts gives every
    member (FR-ACC-011); a seller ordering a check is a client of that check and passes the identity check."""
    from accounts.models import Membership, RoleGrant
    from accounts.services import grant_role

    for key, org_key, role in (("seller", "ato", "SE"), ("developer", "developer", "DV")):
        person, org = people.get(key), orgs.get(org_key)
        if person is None or org is None:
            continue
        g = RoleGrant.objects.filter(person=person, role=role, organisation=org, revoked_at__isnull=True).first()
        if g is None:
            g = grant_role(person, role, country=gh, organisation=org, granted_by=people["admin"],
                           scope_type="organisation", scope_id=org.pk)
            Membership.objects.filter(person=person, organisation=org, status="active",
                                      role_grant__isnull=True).update(role_grant=g)
        if person.id_check_status not in ("passed", "manual_passed"):
            person.id_check_status = "passed"
            person.save(update_fields=["id_check_status"])


def _existing(title):
    from .models import Listing

    return Listing.objects.filter(title=title).order_by("-created_at").first()


def run(ctx):
    from administration import flags

    gh, people = ctx["gh"], ctx["people"]
    if not flags.enabled("listings.enabled", gh):
        return
    seeded = ctx.setdefault("listings", {})
    orgs = ctx.get("orgs") or {}
    ato, sunrise = orgs.get("ato"), orgs.get("developer")
    if ato is None:
        return
    prepare_sellers(gh, people, orgs)
    for key, fn in (("screenings", _screenings), ("live", _live), ("reserved", _reserved),
                    ("suspended", _suspended), ("sold", _sold), ("rejected", _rejected),
                    ("developer", _developer), ("enquiries", _enquiries)):
        try:
            fn(ctx, gh, people, ato, sunrise, seeded)
        except DomainError as exc:
            log.warning("seed listings %s: %s %s", key, exc.detail, getattr(exc, "blocking_reasons", ""))


def _screenings(ctx, gh, people, ato, sunrise, seeded):
    from . import services
    from .models import SellerScreening

    s = SellerScreening.objects.filter(organisation=ato).first()
    if s is None:
        s = services.open_screening(people["cm"], ato)
        for key in SellerScreening.CHECKS:
            status = "not_applicable" if key == "agency_licence" else "passed"
            services.record_screening_check(s, people["cm"], key=key, status=status,
                                            note="[demo] checked against the original",
                                            evidence=None if status != "passed" else doc(people["cm"], gh,
                                                                                         f"ato-{key}.pdf"))
        services.decide_screening(s, people["reviewer"], outcome="established",
                                  note="All checks passed. Three past buyers confirmed. [demo]")
    seeded["ato_screening"] = SellerScreening.objects.filter(organisation=ato).first()
    if sunrise is not None and not SellerScreening.objects.filter(organisation=sunrise).exists():
        s2 = services.open_screening(people["cm"], sunrise)
        services.record_screening_check(s2, people["cm"], key="registered_company", status="passed",
                                        evidence=doc(people["cm"], gh, "sunrise-registration.pdf"))


def _live(ctx, gh, people, ato, sunrise, seeded):
    """A-12: Ato's checked plot (paid in PAY's seed), released green, then listed on that report."""
    from orders import legal

    from . import services

    x = _existing(TITLES["live"])
    if x is None:
        case = (ctx.get("cases") or {}).get("ato_checked_plot_1")
        if case is None:
            return
        case.refresh_from_db()
        release_report(case, gh, people, "green")
        case.refresh_from_db()
        x = services.create_listing(actor=people["seller"], country=gh, data={
            "organisation_id": ato.pk, "kind": "plot", "title": TITLES["live"], "asset_id": case.asset_id,
            "description": "Half plot (70 x 70 ft) in a gated estate. Tarred road, water and electricity. [demo]",
            "price": {"amount": "185000.00", "currency": "GHS"}, "size_sqm": "455.00", "estate_name": "Ato Estates"})
        services.add_media(x, people["seller"], kind="photo", caption="Plot A-12 from the estate road",
                           evidence=doc(people["seller"], gh, "a12.jpg", "image/jpeg"))
        t = legal.current(gh)
        x = services.submit(x, people["seller"], terms_version=t["terms_version"], scope_version=t["scope_version"])
        pay_invoice(listing_fee_invoice(x), people["seller"])
        x.refresh_from_db()
    seeded["live"] = x


def _reserved(ctx, gh, people, ato, sunrise, seeded):
    from . import services

    x = _existing(TITLES["reserved"])
    if x is None:
        x = new_listing(gh, people, org=ato, title=TITLES["reserved"], plot="B-03", price="210000.00",
                        location={"lng": 0.0170, "lat": 5.7890})
        if x.status == "live":
            services.reserve(x, people["client"])
            x.refresh_from_db()
    seeded["reserved"] = x
    seeded["reservation"] = x.reservations.order_by("-created_at").first()


def _suspended(ctx, gh, people, ato, sunrise, seeded):
    from . import services

    x = _existing(TITLES["suspended"])
    if x is None:
        x = new_listing(gh, people, org=ato, title=TITLES["suspended"], plot="C-07", price="160000.00",
                        location={"lng": 0.0210, "lat": 5.7920})
        if x.status == "live":
            services.staff_suspend(x, people["cm"], "An outside advert for this plot quoted a different price. "
                                                    "Checking with the seller. [demo]")
            x.refresh_from_db()
    seeded["suspended"] = x


def _sold(ctx, gh, people, ato, sunrise, seeded):
    """J-04 to the end: reserved, fresh search, escrow agreed and funded, released, sold."""
    from cases.models import Case
    from escrow import services as esc
    from escrow.models import Escrow
    from escrow.seed import _agree, _close_all, _confirm, _deposit, _release

    from . import services

    x = _existing(TITLES["sold"])
    if x is None:
        x = new_listing(gh, people, org=ato, title=TITLES["sold"], plot="D-01", price="140000.00",
                        location={"lng": 0.0250, "lat": 5.7950})
        if x.status != "live":
            seeded["sold"] = x
            return
        res = services.reserve(x, people["client2"] if people["client2"].id_check_status == "passed"
                               else people["client"])
        fs = Case.objects.filter(product_line="fresh_search", origin="reservation", origin_ref=res.pk).first()
        today = timezone.localdate()
        services.on_fresh_search_completed({"origin": "reservation", "origin_ref": str(res.pk),
                                            "case_id": str(fs.pk) if fs else None,
                                            "registry_result_date": today.isoformat()})
        cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
        e = Escrow.objects.get(pk=res.escrow_id)
        _agree(e, people, cm, "VA-GH-000190")
        _deposit(Escrow.objects.get(pk=e.pk), cm, rv, "140000.00", "DEP-LST-D01")
        e = Escrow.objects.get(pk=e.pk)
        _close_all(e, cm)
        esc.record_fresh_search(e, cm, case_id=fs.pk if fs else res.pk, registry_result_date=today,
                                site_check_date=today)
        ins = _release(Escrow.objects.get(pk=e.pk), cm, res.buyer, rv, rv2)
        if ins.status == "sent":
            _confirm(ins, cm, rv, "PAY-LST-D01")
        x.refresh_from_db()
    seeded["sold"] = x


def _rejected(ctx, gh, people, ato, sunrise, seeded):
    x = _existing(TITLES["rejected"])
    if x is None:
        x = new_listing(gh, people, org=ato, title=TITLES["rejected"], plot="E-09", price="120000.00",
                        verdict="amber")
    seeded["rejected"] = x


def _developer(ctx, gh, people, ato, sunrise, seeded):
    if sunrise is None:
        return
    x = _existing(TITLES["in_verification"])
    if x is None:
        x = new_listing(gh, people, seller="developer", org=sunrise, title=TITLES["in_verification"],
                        plot="SG-2B-14", price="520000.00", kind="offplan_unit", locality="Sunrise Gardens, Oyibi",
                        location={"lng": -0.1000, "lat": 5.8000}, pay_check=False)
    seeded["in_verification"] = x
    d = _existing(TITLES["draft"])
    if d is None:
        d = new_listing(gh, people, seller="developer", org=sunrise, title=TITLES["draft"], plot="SG-3A-02",
                        price="780000.00", kind="building", locality="Sunrise Gardens, Oyibi", submit=False)
    seeded["draft"] = d


def _enquiries(ctx, gh, people, ato, sunrise, seeded):
    from . import services
    from .models import Enquiry

    live = seeded.get("live")
    if live is not None and live.status == "live" and not Enquiry.objects.filter(listing=live).exists():
        services.enquire(people["client2"], listing=live, message="Is the estate road tarred all the way to the "
                                                                   "main road? Can I visit in December?")
    if not Enquiry.objects.filter(listing__isnull=True, buyer=people["client"]).exists():
        e = services.enquire(people["client"], country=gh, message="I am looking for a plot near Oyarifa for a "
                             "family house, about 100 x 70 ft.", wanted_region="Greater Accra",
                             wanted_locality="Oyarifa", budget={"amount": "250000.00", "currency": "GHS"})
        services.answer_enquiry(e, people["cm"], "We have two checked plots near Afienya with green reports. "
                                "See the listings page. Each one gets a fresh search for you before you buy.")
    seeded["enquiries"] = list(Enquiry.objects.all()[:5])
    seeded["expires_soon"] = timezone.now() + timedelta(days=1)
