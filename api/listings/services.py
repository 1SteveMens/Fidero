"""LST Verified listings: the public interface other modules may call.

FR-LST-001 submit a plot, building, estate plot or off-plan unit and pay the listing fee
FR-LST-002 publish only with a released green report within the configured age (RUL-12)
FR-LST-003 badge, date of the checks and the full report behind it (RUL-14)
FR-LST-004 search, filters and map (selectors)
FR-LST-005 enquiries through Tenmina; reservations start a fresh search and a purchase escrow
FR-LST-006 badge expiry and suspension on an unresolved monitoring alert (RUL-13)
FR-LST-007 sold when the escrow releases; PAY invoices the success fee if Q-31 allows it
FR-LST-008 removal of a listing or a seller for misconduct, with a reason
FR-LST-009 family and stool listings (flag listings.family_and_stool), same rules
Checked plots and established sellers (decision of 12 November 2026): every seller-paid check is
disclosed to buyers; an established seller earns no shortcut on checks.

Events published: listing.submitted, listing.verification_requested, listing.live, listing.rejected,
listing.suspended, listing.reinstated, listing.expired, listing.reserved, reservation.created,
reservation.ended, listing.sold, listing.withdrawn, listing.removed, listing.enquiry_received.
Payload keys: listing_id, asset_id, organisation_id, submitted_by, reference, country.

Events consumed: seller_invoice.paid, report.released, monitoring.alert_raised, monitoring.alert_resolved,
fresh_search.completed, release.confirmed, escrow.cancelled, dispute.opened, dispute.resolved,
dispute.withdrawn.
"""
import logging
import secrets
from datetime import timedelta

from django.contrib.postgres.search import SearchVector
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from administration import flags
from audit.services import record
from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from .models import (ACTIVE_STATUSES, PUBLIC_STATUSES, Enquiry, Listing, ListingMedia, Removal, Reservation,
                     SellerScreening, Suspension)

log = logging.getLogger(__name__)

STAFF = ("CM", "RV", "AD")
SELLER_ROLES = ("SE", "DV")
DOCUMENT_KINDS = ("site_plan", "document")
DISCLOSURE = ("This plot comes from a seller who pays Tenmina a fixed fee to check plots. The fee is the same "
              "whatever the verdict, and the seller never sees your report before you do. If you reserve it, "
              "Tenmina runs a fresh search for you and you remain Tenmina's client. [Working text, TO VERIFY "
              "by the lawyer: client terms clause 1.3.]")
DEFAULT_RESERVATION_DAYS = 14  # [TO VERIFY]


# --------------------------------------------------------------------------- helpers

def _now():
    return timezone.now()


def _cfg(country, key, default=None):
    from countries.selectors import config

    try:
        v = config(country, key, default)
    except Exception:  # noqa: BLE001
        return default
    return default if v in (None, "") else v


def setting(key, country, default=None):
    from administration.selectors import setting as adm_setting

    v = adm_setting(key, country, default)
    return default if v in (None, "") else v


def _on(country, family=False):
    flags.require("listings.enabled", country)
    if family:
        flags.require("listings.family_and_stool", country)
    flags.read_only_guard()


def is_staff(person, country, *roles) -> bool:
    return has_role(person, *(roles or STAFF), country=country)


def _members(org):
    if org is None:
        return []
    from accounts.models import Person

    return list(Person.objects.filter(memberships__organisation=org, memberships__status="active", is_active=True))


def is_seller(person, listing) -> bool:
    if person is None or not getattr(person, "is_authenticated", False):
        return False
    if listing.submitted_by_id == person.pk:
        return True
    if listing.organisation_id:
        from accounts.selectors import is_member

        return is_member(person, listing.organisation_id)
    return False


def _notify(person, template, body, *, subject="", obj=None, link="", needs_action=False, category=None):
    if person is None:
        return
    from notifications.services import notify

    try:
        notify(person, template, body=body, subject=subject, subject_obj=obj, link=link, needs_action=needs_action,
               category=category)
    except Exception:  # noqa: BLE001 - a notification never stops a listing step
        log.exception("notification %s failed", template)


def _tell_seller(listing, template, body, *, subject="", needs_action=False):
    people = {p.pk: p for p in _members(listing.organisation)}
    people.setdefault(listing.submitted_by_id, listing.submitted_by)
    for p in people.values():
        _notify(p, template, body, subject=subject or f"Listing {listing.reference}", obj=listing,
                link=f"/listings/{listing.pk}", needs_action=needs_action)


def _alert_staff(country, roles, template, body, *, obj=None, link=""):
    from accounts.models import Person
    from django.db.models import Q

    staff = Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                  role_grants__role__in=roles, role_grants__revoked_at__isnull=True,
                                  is_active=True).distinct()
    for p in staff:
        _notify(p, template, body, obj=obj, link=link, needs_action=True, category="task")


def _audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=type(obj).__name__.lower(), entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None))


def listing_payload(listing, **extra) -> dict:
    return {"listing_id": listing.pk, "asset_id": listing.asset_id, "organisation_id": listing.organisation_id,
            "submitted_by": listing.submitted_by_id, "reference": listing.reference,
            "country": listing.country.code, "status": listing.status, "kind": listing.kind,
            "origin": listing.origin, "price": {"amount": listing.price_amount, "currency": listing.price_currency},
            "report_id": listing.report_id, **extra}


def _reference(country, prefix="LST") -> str:
    return f"{prefix}-{country.code}-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}"


def _move(listing, to, *, actor=None, event=None, reason="", extra_fields=(), **payload):
    return state.transition(listing, "listing", to, actor=actor, event=event, reason=reason,
                            payload=listing_payload(listing, **payload), extra_fields=list(extra_fields))


def refresh_search(listing):
    Listing.objects.filter(pk=listing.pk).update(search_doc=(
        SearchVector("title", weight="A") + SearchVector("locality", "region", "district", "estate_name", weight="B")
        + SearchVector("description", weight="C")))


def badge_valid(listing, at=None) -> bool:
    """RUL-13 at read time (TC-RUL-13-03): never rely on the expiry job alone."""
    at = at or _now()
    return (listing.status in PUBLIC_STATUSES and listing.badge_expires_at is not None
            and listing.badge_expires_at > at and listing.report_id is not None)


def disclosure(country) -> str:
    return _cfg(country, "listings.disclosure_text", DISCLOSURE) or DISCLOSURE


def is_banned(*, organisation=None, person=None) -> Removal | None:
    from django.db.models import Q

    q_ = Q(pk__in=[])
    if organisation is not None:
        q_ |= Q(organisation=organisation)
    if person is not None:
        q_ |= Q(person=person)
    return Removal.objects.filter(q_, scope="seller").first()


# --------------------------------------------------------------------------- the publish rule (RUL-12)

def _report_owner_ok(listing, report) -> bool:
    """Tenmina stays neutral: a listing shows only a check its own seller paid for, never a buyer's report."""
    case = report.case
    if case.subject_type == "listing" and case.subject_id == listing.pk:
        return True
    if case.order_id and case.order.organisation_id and case.order.organisation_id == listing.organisation_id:
        return True
    if case.order_id and listing.verification_order_id == case.order_id:
        return True
    return case.client_id == listing.submitted_by_id


def report_reasons(listing, report) -> list[dict]:
    """Why this report cannot back this listing at all (TC-RUL-12-04)."""
    if report is None:
        return [{"rule": "RUL-12", "message": "There is no report for this plot yet."}]
    out = []
    if report.status != "released":
        out.append({"rule": "RUL-12", "message": "Only a released report can back a listing."})
    if report.case.asset_id != listing.asset_id:
        out.append({"rule": "RUL-12", "message": "The report is for a different plot (asset mismatch)."})
    elif not _report_owner_ok(listing, report):
        out.append({"rule": "RUL-12", "message": "The report belongs to another client. A listing shows only a "
                                                 "check the seller ordered."})
    return out


def max_report_age_days(country) -> int:
    return int(setting("listing_report_max_age_days", country, 90))


def badge_validity_days(country) -> int:
    return int(setting("badge_validity_days", country, 180))


def publish_blockers(listing, report, at=None) -> list[dict]:
    """RUL-12: released, green, this plot, a check the seller paid for, and younger than the configured age."""
    at = at or _now()
    out = report_reasons(listing, report)
    if report is None:
        return out
    if report.overall_verdict != "green":
        out.append({"rule": "RUL-12", "message": f"The report's verdict is {report.overall_verdict or 'not set'}. "
                                                 "Only a green report can be listed."})
    if report.released_at is not None:
        age = (at - report.released_at).days
        limit = max_report_age_days(listing.country)
        if age > limit:
            out.append({"rule": "RUL-12", "message": f"The report is {age} days old; the limit is {limit} days. "
                                                     "Report too old: order re-verification."})
    from reports.selectors import open_incidents_for_report

    if open_incidents_for_report(report.pk):
        out.append({"rule": "RUL-32", "message": "A re-check incident on this report is open."})
    return out


def find_report(listing):
    """The newest released report on the plot from a check this seller paid for."""
    from reports.models import Report

    for r in Report.objects.filter(case__asset_id=listing.asset_id, status="released").select_related(
            "case", "case__order").order_by("-released_at"):
        if not report_reasons(listing, r):
            return r
    return None


# --------------------------------------------------------------------------- submitting (FR-LST-001)

def _organisation(actor, organisation_id, origin):
    from accounts.models import Organisation
    from accounts.selectors import is_member, organisations_of

    if not organisation_id:
        orgs = list(organisations_of(actor))
        if len(orgs) != 1:
            raise Invalid("Choose the organisation that offers this listing.", extra={"errors": [
                {"pointer": "/organisation_id", "message": "This field is required."}]})
        org = orgs[0]
    else:
        org = Organisation.objects.filter(pk=organisation_id).first()
        if org is None:
            raise Invalid("Unknown organisation.")
    if not is_member(actor, org.pk):
        raise Forbidden("You can only list for an organisation you belong to.")
    allowed = {"seller": ("seller", "developer"), "developer": ("developer", "seller"),
               "family": ("authority",), "stool": ("authority",)}[origin]
    if org.kind not in allowed:
        raise Invalid(f"A {origin} listing is offered by a {' or '.join(allowed)} organisation.")
    if org.status != "active":
        raise Forbidden("This organisation is not active.")
    return org


def _asset_for(actor, country, data, org, kind):
    from geo.models import Asset
    from geo.services import create_asset

    if data.get("asset_id"):
        asset = Asset.objects.filter(pk=data["asset_id"], country=country).first()
        if asset is None:
            raise Invalid("Unknown plot.", extra={"errors": [{"pointer": "/asset_id", "message": "Not found."}]})
        from orders.models import Order

        mine = asset.owner_id == actor.pk or asset.created_by_id == actor.pk or (
            org is not None and Order.objects.filter(asset_id=asset.pk, organisation=org).exists())
        if not mine:
            raise Forbidden("You can only list a plot you registered or had checked.")
        return asset
    a = data.get("asset") or {}
    typ = {"plot": "plot", "estate_plot": "plot", "building": "building", "offplan_unit": "offplan_unit"}[kind]
    return create_asset(actor=actor, country=country, type=typ, locality=a.get("locality", ""), owner=actor,
                        name=a.get("name", "") or data.get("title", ""), region=a.get("region", ""),
                        district=a.get("district", ""), plot_number=a.get("plot_number", ""),
                        site_plan_ref=a.get("site_plan_ref", ""), ghana_post_gps=a.get("ghana_post_gps", ""),
                        location=a.get("location"))


def _price(country, price):
    if not isinstance(price, dict) or "amount" not in price:
        raise Invalid("Give the price.", extra={"errors": [{"pointer": "/price", "message": "Required."}]})
    amount = q(price["amount"])
    currency = str(price.get("currency") or country.currency).upper()
    allowed = set(_cfg(country, "listings.price_currencies", [country.currency]) or [country.currency])
    if amount <= 0:
        raise Invalid("The price must be more than zero.")
    if currency not in allowed:
        raise Invalid(f"Prices in {country.name} are in {', '.join(sorted(allowed))}.", code="price-currency")
    return amount, currency


@transaction.atomic
def create_listing(*, actor, country, data: dict) -> Listing:
    origin = data.get("origin") or ("developer" if has_role(actor, "DV", country=country) and not has_role(
        actor, "SE", country=country) else "seller")
    if origin not in Listing.ORIGINS:
        raise Invalid(f"Origin must be one of {', '.join(Listing.ORIGINS)}.")
    family = origin in ("family", "stool")
    _on(country, family=family)
    if family:
        if not has_role(actor, "AR", country=country):
            raise Forbidden("Family and stool listings are submitted by an authority representative.")
    elif not has_role(actor, *SELLER_ROLES, country=country):
        raise Forbidden("Only a seller or developer can list.")
    org = _organisation(actor, data.get("organisation_id"), origin)
    ban = is_banned(organisation=org, person=actor)
    if ban:
        raise Forbidden("This seller was removed from listings for misconduct.", extra={"removal_id": str(ban.pk)})
    kind = data.get("kind") or "plot"
    if kind not in Listing.KINDS:
        raise Invalid(f"Kind must be one of {', '.join(Listing.KINDS)}.")
    title = (data.get("title") or "").strip()
    if not title:
        raise Invalid("Give the listing a title.", extra={"errors": [{"pointer": "/title", "message": "Required."}]})
    amount, currency = _price(country, data.get("price"))
    asset = _asset_for(actor, country, data, org, kind)
    if Listing.objects.filter(asset=asset, status__in=ACTIVE_STATUSES).exists():
        raise StateConflict("This plot already has a listing.", code="listing-exists")
    listing = Listing.objects.create(
        country=country, reference=_reference(country), asset=asset, organisation=org, submitted_by=actor,
        origin=origin, kind=kind, title=title, description=(data.get("description") or "").strip(),
        estate_name=data.get("estate_name", "") or "", records_reference=data.get("records_reference", "") or "",
        price_amount=amount, price_currency=currency, size_sqm=data.get("size_sqm") or None,
        region=asset.region, district=asset.district, locality=asset.locality, seller_paid_check=True)
    listing.slug = slugify(f"{title}-{asset.locality}")[:100] or listing.reference.lower()
    listing.save(update_fields=["slug"])
    if data.get("report_id"):
        attach_report(listing, actor, data["report_id"])
    refresh_search(listing)
    _audit(actor, "listing.drafted", listing, {"reference": listing.reference, "origin": origin, "kind": kind})
    return listing


def attach_report(listing, actor, report_id):
    """A seller names a report they already have (TC-RUL-12-04: a report for another plot is refused)."""
    from reports.models import Report

    report = Report.objects.filter(pk=report_id).select_related("case", "case__order").first()
    if report is None:
        raise Invalid("Unknown report.")
    reasons = report_reasons(listing, report)
    if reasons:
        raise RuleBlocked("This report cannot back the listing.", code="publish-rule", blocking_reasons=reasons)
    listing.report = report
    listing.save(update_fields=["report"])
    _audit(actor, "listing.report_named", listing, {"report_id": str(report.pk)})
    return listing


SELLER_EDITABLE = {"title", "description", "estate_name", "price", "size_sqm", "kind"}
SYSTEM_FIELDS = {"badge_expires_at", "report", "report_id", "status", "checks_date", "verification_order",
                 "fee_paid_at", "live_at", "seller_paid_check", "report_url", "badge"}


@transaction.atomic
def update_listing(listing, actor, data: dict) -> Listing:
    """Sellers edit the description and price. The badge, the report link and the status are system-set
    (TC-LST-006-02, TC-RUL-14-02)."""
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    staff = is_staff(actor, listing.country, "CM", "RV")
    if not (is_seller(actor, listing) or staff):
        raise NotFound()
    touched = SYSTEM_FIELDS & set(data)
    if touched:
        _audit(actor, "listing.system_field_refused", listing, {"fields": sorted(touched)})
        raise Forbidden("The badge, its expiry, the report link and the status are set by Tenmina, not by "
                        "the seller.", extra={"fields": sorted(touched)})
    unknown = set(data) - SELLER_EDITABLE
    if unknown:
        raise Invalid(f"These fields cannot be changed: {', '.join(sorted(unknown))}.")
    if listing.status in ("sold", "withdrawn", "removed", "rejected", "reserved"):
        raise StateConflict(f"A {listing.status} listing cannot be edited.")
    if "kind" in data and listing.status != "draft":
        raise StateConflict("The kind can change only while the listing is a draft.")
    changes = {}
    for f in ("title", "description", "estate_name", "kind", "size_sqm"):
        if f in data:
            if f == "kind" and data[f] not in Listing.KINDS:
                raise Invalid(f"Kind must be one of {', '.join(Listing.KINDS)}.")
            if f == "title" and not (data[f] or "").strip():
                raise Invalid("The title cannot be empty.")
            changes[f] = data[f]
            setattr(listing, f, data[f] if data[f] is not None else ("" if f != "size_sqm" else None))
    if "price" in data:
        listing.price_amount, listing.price_currency = _price(listing.country, data["price"])
        changes["price"] = f"{listing.price_currency} {listing.price_amount}"
    listing.save()
    refresh_search(listing)
    _audit(actor, "listing.updated", listing, {k: str(v) for k, v in changes.items()})
    return listing


@transaction.atomic
def add_media(listing, actor, *, kind="photo", caption="", evidence=None, data=None, content_type="",
              name="") -> ListingMedia:
    from evidence.services import link, store

    if not (is_seller(actor, listing) or is_staff(actor, listing.country, "CM")):
        raise NotFound()
    if listing.status in ("sold", "withdrawn", "removed"):
        raise StateConflict("This listing is closed.")
    if kind not in ListingMedia.KINDS:
        raise Invalid(f"Kind must be one of {', '.join(ListingMedia.KINDS)}.")
    if evidence is None:
        if not data:
            raise Invalid("Attach a file.", code="evidence-rejected")
        evidence = store(data=data, country=listing.country, uploaded_by=actor, content_type=content_type,
                         original_name=name, source="upload", owner_type="listing", owner_id=listing.pk,
                         data_class="listing", description=f"Listing {listing.reference}: {kind}")
    elif evidence.uploaded_by_id != actor.pk and not is_staff(actor, listing.country, "CM"):
        raise Forbidden("You can only add files you uploaded.")
    public = kind not in DOCUMENT_KINDS
    link(evidence, "listing" if public else "listing_private", listing.pk, role=kind, by=actor)
    m, _ = ListingMedia.objects.get_or_create(
        listing=listing, evidence=evidence, defaults=dict(country=listing.country, kind=kind, caption=caption or "",
                                                          public=public, added_by=actor,
                                                          position=listing.media.count()))
    _audit(actor, "listing.media_added", listing, {"evidence_id": str(evidence.pk), "kind": kind})
    return m


def _verification_order(listing, actor, terms_version, scope_version):
    """The seller-paid check of the plot (checked plot, same fee whatever the verdict)."""
    from orders import legal
    from orders import services as orders

    if listing.origin in ("family", "stool"):
        return None  # verification for family and stool plots is opened by a case manager with REC (R3)
    cur = legal.current(listing.country)
    if not terms_version or not scope_version:
        raise Invalid("Read and accept the scope statement and terms first.", code="terms-not-accepted",
                      extra={"terms_version": cur["terms_version"], "scope_version": cur["scope_version"]})
    docs = [m.evidence_id for m in listing.media.filter(kind__in=DOCUMENT_KINDS)]
    if not docs:
        raise Invalid("Upload the site plan so the plot can be checked.", code="validation-error",
                      extra={"errors": [{"pointer": "/media", "message": "A site plan or document is needed."}]})
    a = listing.asset
    order = orders.create_order(actor=actor, country=listing.country, kind="listing_verification", draft=True, data={
        "organisation_id": listing.organisation_id, "lead_source": "other",
        "asset": {"type": "building" if a.type == "building" else "plot", "locality": a.locality,
                  "plot_number": a.plot_number or listing.reference, "site_plan_ref": a.site_plan_ref or "see upload",
                  "ghana_post_gps": a.ghana_post_gps},
        "details": {"listing_id": str(listing.pk), "listing_reference": listing.reference}})
    orders.attach_asset(order.pk, a.pk)
    from evidence.models import Evidence

    for ev in Evidence.objects.filter(pk__in=docs):
        from evidence.services import link

        link(ev, "order", order.pk, role="site_plan" if ev.pk == docs[0] else "document", by=actor)
    orders.accept_terms(order, actor, terms_version, scope_version)
    return orders.submit(order, actor)


@transaction.atomic
def submit(listing, actor, *, terms_version="", scope_version="") -> Listing:
    """Draft, submitted: PAY invoices the listing fee (listing.submitted). Without a current check the seller
    also gets the fixed check fee; with one, the listing waits only for the fee."""
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    _on(listing.country, family=listing.origin in ("family", "stool"))
    if not is_seller(actor, listing):
        raise NotFound()
    if listing.status != "draft" or listing.submitted_at:
        raise StateConflict("This listing was already submitted.")
    if is_banned(organisation=listing.organisation, person=actor):
        raise Forbidden("This seller was removed from listings for misconduct.")
    report = listing.report or find_report(listing)
    if report is not None and not report_reasons(listing, report):
        listing.report = report
    else:
        listing.report = None
        listing.verification_order = _verification_order(listing, actor, terms_version, scope_version)
    listing.submitted_at = _now()
    listing.save(update_fields=["report", "verification_order", "submitted_at"])
    _audit(actor, "listing.submitted", listing, {"verification_order_id": str(listing.verification_order_id or ""),
                                                  "report_id": str(listing.report_id or "")})
    publish("listing.submitted", listing.pk, listing_payload(listing))
    from payments.models import Invoice

    inv = Invoice.objects.filter(kind="listing_fee", subject_type="listing", subject_id=listing.pk).exclude(
        status="void").first()
    if inv is not None:
        listing.fee_invoice_id = inv.pk
        listing.save(update_fields=["fee_invoice_id"])
        if inv.status == "paid":
            return on_fee_paid(listing.pk)
    _tell_seller(listing, "listing_submitted", f"Listing {listing.reference} is submitted. Pay the listing fee to "
                 "start the checks." + (" The plot check is invoiced separately at a fixed fee, the same whatever "
                                        "the verdict." if listing.verification_order_id else ""),
                 needs_action=True)
    return listing


@transaction.atomic
def on_fee_paid(listing_id) -> Listing | None:
    """Draft to In verification once the listing fee is paid (01 C8)."""
    listing = Listing.objects.select_for_update().filter(pk=listing_id).first()
    if listing is None or listing.status != "draft" or not listing.submitted_at:
        return listing
    listing.fee_paid_at = _now()
    order = listing.verification_order
    _move(listing, "in_verification", event="listing.verification_requested", extra_fields=["fee_paid_at"],
          order_id=order.pk if order else None, case_id=getattr(order, "case_id", None) if order else None)
    report = listing.report
    if report is None and order is not None and order.case_id:
        from reports.selectors import latest_released

        report = latest_released(order.case_id)
    if report is not None:
        return evaluate(listing, report)
    if order is None:
        _alert_staff(listing.country, ("CM",), "listing_needs_check",
                     f"Listing {listing.reference} ({listing.origin}) needs a verification case.", obj=listing,
                     link=f"/listings/{listing.pk}")
    _tell_seller(listing, "listing_in_verification", f"Thank you. Listing {listing.reference} is being verified. "
                 "It goes live only if the report is green.")
    return listing


@transaction.atomic
def evaluate(listing, report, *, actor=None) -> Listing:
    """RUL-12: go live with the badge, or be rejected with the reasons. A report still in progress waits."""
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if listing.status != "in_verification" or report is None or report.status != "released":
        return listing
    blockers = publish_blockers(listing, report)
    if blockers:
        listing.status_reason = " ".join(b["message"] for b in blockers)
        listing.report = report if report.case.asset_id == listing.asset_id else listing.report
        listing.closed_at = _now()
        _move(listing, "rejected", actor=actor, event="listing.rejected", reason=listing.status_reason,
              extra_fields=["status_reason", "report", "closed_at"], blocking_reasons=blockers)
        _tell_seller(listing, "listing_rejected", f"Listing {listing.reference} cannot be published: "
                     f"{listing.status_reason} A failed check means no listing.")
        return listing
    from countries.selectors import config  # noqa: F401 - country time zone used below

    listing.report = report
    listing.checks_date = timezone.localtime(report.released_at).date()
    listing.badge_expires_at = report.released_at + timedelta(days=badge_validity_days(listing.country))
    listing.live_at, listing.status_reason = _now(), ""
    _move(listing, "live", actor=actor, event="listing.live",
          extra_fields=["report", "checks_date", "badge_expires_at", "live_at", "status_reason"],
          badge_expires_at=listing.badge_expires_at, checks_date=listing.checks_date)
    _link_report(listing, report, actor)
    _tell_seller(listing, "listing_live", f"Listing {listing.reference} is live with the Tenmina Verified badge "
                 f"until {timezone.localtime(listing.badge_expires_at):%d %B %Y}.")
    from geo.selectors import has_open_alert

    if has_open_alert(listing.asset_id):
        from geo.models import MonitoringAlert

        alert = MonitoringAlert.objects.filter(asset_id=listing.asset_id, status__in=["open", "under_review"]).first()
        suspend(listing, kind="monitoring_alert", source_id=alert.pk if alert else None,
                reason="Satellite monitoring raised an alert on this plot.")
    return listing


def _link_report(listing, report, actor=None):
    """RUL-14: buyers open the released version behind the badge."""
    if report.pdf_evidence_id:
        from evidence.services import link

        link(report.pdf_evidence, "listing", listing.pk, role="listing_report", by=actor)


@transaction.atomic
def on_report_released(payload: dict):
    from reports.models import Report

    report = Report.objects.filter(pk=payload.get("report_id")).select_related("case", "case__order").first()
    if report is None:
        return
    case = report.case
    waiting = Listing.objects.filter(status="in_verification", asset_id=case.asset_id)
    for listing in waiting:
        if (listing.verification_order_id and listing.verification_order_id == case.order_id) or \
                not report_reasons(listing, report):
            evaluate(listing, report)
    if payload.get("supersedes_id"):
        for listing in Listing.objects.filter(report_id=payload["supersedes_id"], status__in=PUBLIC_STATUSES +
                                              ["suspended"]):
            _corrected(listing, report)
    if (payload.get("verdict") == "red" and case.client_id and case.product_line in ("land", "building")
            and flags.enabled("listings.enabled", case.country)
            and Listing.objects.filter(country=case.country, status="live").exists()
            and not (case.order_id and case.order.organisation_id)):
        _notify(case.client, "listing_checked_plots_offer",
                "Your plot's report is red. Tenmina has checked plots from screened sellers, each with a green "
                "report. You can look at them, with no obligation.", subject="Checked plots you can look at",
                link="/listings", obj=case)


def _corrected(listing, report):
    """A correction supersedes the report behind a badge (FR-RPT-010): keep the badge only if it still passes."""
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if publish_blockers(listing, report):
        suspend(listing, kind="report_corrected", source_id=report.pk,
                reason="The report behind this listing was corrected and no longer passes.")
        return
    listing.report = report
    listing.checks_date = timezone.localtime(report.released_at).date()
    listing.badge_expires_at = report.released_at + timedelta(days=badge_validity_days(listing.country))
    listing.save(update_fields=["report", "checks_date", "badge_expires_at"])
    _link_report(listing, report)
    _audit(None, "listing.report_corrected", listing, {"report_id": str(report.pk)})


# --------------------------------------------------------------------------- withdrawal and re-verification

@transaction.atomic
def withdraw(listing, actor, reason="") -> Listing:
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if not (is_seller(actor, listing) or is_staff(actor, listing.country, "CM", "RV")):
        raise NotFound()
    if listing.status == "reserved":
        raise StateConflict("A buyer has reserved this listing. It can be withdrawn only after the reservation ends.")
    if listing.status not in ("draft", "in_verification", "live", "suspended", "expired"):
        raise StateConflict(f"A {listing.status} listing cannot be withdrawn.")
    listing.closed_at, listing.status_reason = _now(), (reason or "").strip()
    _move(listing, "withdrawn", actor=actor, event="listing.withdrawn", reason=listing.status_reason,
          extra_fields=["closed_at", "status_reason"])
    return listing


@transaction.atomic
def reverify(listing, actor, *, terms_version="", scope_version="") -> Listing:
    """Expired, In verification: the seller orders a new check (TC-STM-LST-09)."""
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    _on(listing.country, family=listing.origin in ("family", "stool"))
    if not is_seller(actor, listing):
        raise NotFound()
    if listing.status != "expired":
        raise StateConflict("Only an expired listing is sent for re-verification.")
    newer = find_report(listing)
    if newer is not None and newer.pk != listing.report_id and not publish_blockers(listing, newer):
        listing.verification_order = None
        _move(listing, "in_verification", actor=actor, event="listing.verification_requested",
              extra_fields=["verification_order"])
        return evaluate(listing, newer, actor=actor)
    listing.verification_order = _verification_order(listing, actor, terms_version, scope_version)
    _move(listing, "in_verification", actor=actor, event="listing.verification_requested",
          extra_fields=["verification_order"], order_id=listing.verification_order_id)
    return listing


# --------------------------------------------------------------------------- suspension (RUL-13, RUL-15, misconduct)

def _end_reservation(listing, reason, status="ended", *, actor=None, cancel_escrow=True):
    res = listing.reservations.filter(status="active").first()
    if res is None:
        return None
    res.ended_at, res.end_reason = _now(), reason
    state.transition(res, "listing_reservation", status, actor=actor, event="reservation.ended",
                     payload=_reservation_payload(res, end_reason=reason), extra_fields=["ended_at", "end_reason"])
    if cancel_escrow:
        _cancel_unfunded_escrow(res, reason)
    _notify(res.buyer, "reservation_ended", f"Your reservation of {listing.title} has ended: {reason}",
            subject=f"Reservation {res.reference} ended", obj=res, link=f"/reservations/{res.pk}")
    return res


def _cancel_unfunded_escrow(res, reason):
    """A proposed or agreed escrow with no money in it is cancelled; a funded one goes to staff (refund rules)."""
    e = res.escrow
    if e is None:
        return
    e.refresh_from_db()
    if e.status in ("proposed", "agreed") and not e.cancel_requested_at:
        from escrow import services as esc
        from escrow.common import staff_in

        cm = staff_in(e.country, "CM").first()
        if cm is None:
            return
        try:
            with transaction.atomic():
                esc.request_cancellation(e, cm, reason=f"Listing reservation ended: {reason}")
        except DomainError as exc:
            log.warning("escrow %s not cancelled: %s", e.pk, exc.detail)
    elif e.status not in ("released", "cancelled"):
        _alert_staff(res.country, ("CM",), "reservation_ended_funded",
                     f"Reservation {res.reference} ended ({reason}) but escrow {e.reference} holds money. "
                     "Decide the refund under the escrow rules.", obj=res)


def _first_open(listing):
    return listing.suspensions.filter(lifted_at__isnull=True).order_by("created_at").first()


@transaction.atomic
def suspend(listing, *, kind, reason, source_id=None, actor=None) -> Suspension | None:
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if listing.status not in ("live", "reserved", "suspended"):
        return None
    existing = listing.suspensions.filter(kind=kind, source_id=source_id, lifted_at__isnull=True).first()
    if existing:
        return existing
    prior = listing.status
    if listing.status == "suspended":
        first = _first_open(listing)
        prior = first.prior_status if first else "live"
    elif listing.status == "reserved" and kind != "dispute":
        _end_reservation(listing, {"monitoring_alert": "a monitoring alert was raised on the plot",
                                   "fresh_search_failed": "the fresh search found a problem",
                                   "misconduct": "the listing was suspended",
                                   "report_corrected": "the report was corrected"}.get(kind, reason), actor=actor)
        prior = "live"
    s = Suspension.objects.create(country=listing.country, listing=listing, kind=kind, source_id=source_id,
                                  reason=reason, prior_status=prior, created_by=actor)
    if listing.status != "suspended":
        listing.status_reason = reason
        _move(listing, "suspended", actor=actor, event="listing.suspended", reason=reason,
              extra_fields=["status_reason"], suspension_kind=kind, source_id=source_id)
    _tell_seller(listing, "listing_suspended", f"Listing {listing.reference} is suspended: {reason} "
                 "The badge is hidden until the issue is resolved.")
    if kind != "misconduct":
        _alert_staff(listing.country, ("CM", "RV"), "listing_suspended",
                     f"Listing {listing.reference} is suspended ({kind.replace('_', ' ')}): {reason}", obj=listing,
                     link=f"/listings/{listing.pk}")
    return s


def _restore(listing, actor=None, note=""):
    if listing.status != "suspended":
        return listing
    if not badge_valid(Listing(status="live", badge_expires_at=listing.badge_expires_at, report_id=listing.report_id)):
        listing.closed_at = None
        return _move(listing, "expired", actor=actor, event="listing.expired", reason="The badge expired while "
                     "the listing was suspended.")
    target = "reserved" if listing.reservations.filter(status="active").exists() else "live"
    listing.status_reason = ""
    _move(listing, target, actor=actor, event="listing.reinstated", reason=note, extra_fields=["status_reason"])
    _tell_seller(listing, "listing_reinstated", f"Listing {listing.reference} is live again.")
    return listing


@transaction.atomic
def lift(suspension, *, actor=None, note="") -> Listing:
    s = Suspension.objects.select_for_update().get(pk=suspension.pk)
    listing = Listing.objects.select_for_update().get(pk=s.listing_id)
    if s.lifted_at:
        return listing
    s.lifted_at, s.lifted_by, s.lift_note = _now(), actor, note or ""
    s.save(update_fields=["lifted_at", "lifted_by", "lift_note"])
    _audit(actor, "listing.suspension_lifted", listing, {"kind": s.kind, "source_id": str(s.source_id or "")})
    if not listing.suspensions.filter(lifted_at__isnull=True).exists():
        _restore(listing, actor, note)
    return listing


def lift_source(kind, source_id, *, note="", actor=None):
    for s in Suspension.objects.filter(kind=kind, source_id=source_id, lifted_at__isnull=True):
        lift(s, actor=actor, note=note)


@transaction.atomic
def staff_suspend(listing, actor, reason) -> Suspension:
    """Misconduct or another concern: a case manager or reviewer suspends with a reason."""
    if not is_staff(actor, listing.country, "CM", "RV"):
        raise Forbidden("Only a case manager or reviewer suspends a listing.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", extra={"errors": [{"pointer": "/reason", "message": "Required."}]})
    if listing.status not in ("live", "reserved", "suspended"):
        raise StateConflict(f"A {listing.status} listing cannot be suspended.")
    return suspend(listing, kind="misconduct", reason=reason.strip(), actor=actor)


@transaction.atomic
def reinstate(listing, actor, note) -> Listing:
    """TC-STM-LST-16: only a reviewer lifts a suspension by hand."""
    if not is_staff(actor, listing.country, "RV"):
        raise Forbidden("Only a reviewer can lift a suspension.")
    if not (note or "").strip():
        raise Invalid("Say how the issue was resolved.")
    if listing.status != "suspended":
        raise StateConflict("This listing is not suspended.")
    from geo.selectors import has_open_alert

    open_kinds = set(listing.suspensions.filter(lifted_at__isnull=True).values_list("kind", flat=True))
    if "monitoring_alert" in open_kinds and has_open_alert(listing.asset_id):
        raise RuleBlocked("Resolve the monitoring alert first.", code="publish-rule",
                          blocking_reasons=[{"rule": "RUL-13", "message": "A monitoring alert on the plot is open."}])
    if "dispute" in open_kinds:
        raise RuleBlocked("The dispute must close first.", code="publish-rule",
                          blocking_reasons=[{"rule": "RUL-15", "message": "A dispute on this listing is open."}])
    # The report's age matters only at publication; the badge expiry covers it afterwards (RUL-13).
    still = [b for b in publish_blockers(listing, listing.report) if "too old" not in b["message"]]
    if still:
        raise RuleBlocked("The report behind the listing no longer passes.", code="publish-rule",
                          blocking_reasons=still)
    for s in listing.suspensions.filter(lifted_at__isnull=True):
        lift(s, actor=actor, note=note.strip())
    listing.refresh_from_db()
    return listing


# --------------------------------------------------------------------------- removal (FR-LST-008)

@transaction.atomic
def remove(listing, actor, reason, *, scope="listing") -> Removal:
    if not is_staff(actor, listing.country, "RV"):
        raise Forbidden("Only a reviewer removes a listing or a seller.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", extra={"errors": [{"pointer": "/reason", "message": "Required."}]})
    if scope not in Removal.SCOPES:
        raise Invalid("Scope must be listing or seller.")
    reason = reason.strip()
    targets = [listing]
    if scope == "seller":
        qs = Listing.objects.filter(status__in=ACTIVE_STATUSES + ["rejected"])
        qs = qs.filter(organisation=listing.organisation) if listing.organisation_id else \
            qs.filter(submitted_by=listing.submitted_by)
        targets = list({x.pk: x for x in [listing, *qs]}.values())
    count = 0
    for x in targets:
        x = Listing.objects.select_for_update().get(pk=x.pk)
        if x.status in ("sold", "withdrawn", "removed"):
            continue
        if x.status == "reserved":
            _end_reservation(x, "the listing was removed by Tenmina", actor=actor)
        x.closed_at, x.status_reason = _now(), reason
        _move(x, "removed", actor=actor, event="listing.removed", reason=reason,
              extra_fields=["closed_at", "status_reason"], scope=scope)
        count += 1
    r = Removal.objects.create(country=listing.country, scope=scope, listing=listing,
                               organisation=listing.organisation if scope == "seller" else None,
                               person=listing.submitted_by if scope == "seller" else None, reason=reason,
                               removed_by=actor, listings_removed=count)
    _audit(actor, f"listing.removed_{scope}", listing, {"reason": reason, "listings": count})
    _tell_seller(listing, "listing_removed", f"Tenmina removed {'your listings' if scope == 'seller' else 'listing ' + listing.reference}"
                 f" for misconduct: {reason}")
    return r


# --------------------------------------------------------------------------- expiry (RUL-13, listings.expire_badges)

def expire_badges(now=None) -> int:
    now = now or _now()
    n = 0
    for listing in Listing.objects.filter(status__in=["live", "reserved", "suspended"], badge_expires_at__lte=now):
        with transaction.atomic():
            x = Listing.objects.select_for_update().get(pk=listing.pk)
            if x.status not in ("live", "reserved", "suspended"):
                continue
            if x.status == "reserved":
                _end_reservation(x, "the badge expired; the plot must be re-verified before you can buy it",
                                 status="ended", cancel_escrow=False)
            x.status_reason = "The badge validity ended. The seller can order re-verification."
            _move(x, "expired", event="listing.expired", reason=x.status_reason, extra_fields=["status_reason"])
            _tell_seller(x, "listing_expired", f"The badge on listing {x.reference} expired. Order re-verification "
                         "to list it again.", needs_action=True)
            n += 1
    return n


# --------------------------------------------------------------------------- enquiries (FR-LST-005)

@transaction.atomic
def enquire(buyer, *, message, listing=None, country=None, wanted_region="", wanted_locality="",
            budget=None) -> Enquiry:
    country = listing.country if listing is not None else country
    if country is None:
        raise Invalid("Choose a country.")
    _on(country)
    if not has_role(buyer, "CL"):
        raise Forbidden("Enquiries are for buyers with a client account.")
    if not (message or "").strip():
        raise Invalid("Write your question.", extra={"errors": [{"pointer": "/message", "message": "Required."}]})
    if listing is not None:
        if listing.status not in PUBLIC_STATUSES or not badge_valid(listing):
            raise StateConflict("This listing is not open for enquiries.")
        if is_seller(buyer, listing):
            raise Forbidden("You cannot enquire about your own listing.")
    amount, currency = (q(budget["amount"]), str(budget.get("currency") or country.currency).upper()) if budget \
        else (None, "")
    e = Enquiry.objects.create(country=country, reference=_reference(country, "ENQ"), listing=listing, buyer=buyer,
                               message=message.strip(), wanted_region=wanted_region or "",
                               wanted_locality=wanted_locality or "", budget_amount=amount, budget_currency=currency)
    _audit(buyer, "listing.enquiry_received", e, {"listing_id": str(listing.pk) if listing else None})
    publish("listing.enquiry_received", e.pk, {"enquiry_id": e.pk, "listing_id": listing.pk if listing else None,
                                               "buyer_id": buyer.pk, "country": country.code})
    _alert_staff(country, ("CM",), "listing_enquiry", f"Enquiry {e.reference}: {e.message[:200]}", obj=e,
                 link=f"/enquiries/{e.pk}")
    if listing is not None:
        _tell_seller(listing, "listing_enquiry_seller", f"A buyer asked about listing {listing.reference}: "
                     f"\"{e.message[:300]}\". Answer through Tenmina; the buyer's details stay private.")
    return e


@transaction.atomic
def answer_enquiry(enquiry, actor, answer) -> Enquiry:
    e = Enquiry.objects.select_for_update().get(pk=enquiry.pk)
    staff = is_staff(actor, e.country, "CM", "RV")
    seller = e.listing is not None and is_seller(actor, e.listing)
    if not (staff or seller):
        raise NotFound()
    if not (answer or "").strip():
        raise Invalid("Write the answer.")
    if e.status == "closed":
        raise StateConflict("This enquiry is closed.")
    if seller and not staff:
        e.seller_note = answer.strip()
    e.answer, e.answered_by, e.answered_at = answer.strip(), actor, _now()
    state.transition(e, "listing_enquiry", "answered", actor=actor, event="listing.enquiry_answered",
                     payload={"enquiry_id": e.pk, "listing_id": e.listing_id},
                     extra_fields=["answer", "answered_by", "answered_at", "seller_note"])
    if e.status == "answered":
        e.save(update_fields=["answer", "answered_by", "answered_at", "seller_note"])
    who = "the seller, through Tenmina" if seller and not staff else "Tenmina"
    _notify(e.buyer, "listing_enquiry_answered", f"{who.capitalize()} answered your enquiry {e.reference}.",
            obj=e, link=f"/enquiries/{e.pk}")
    return e


@transaction.atomic
def close_enquiry(enquiry, actor) -> Enquiry:
    e = Enquiry.objects.select_for_update().get(pk=enquiry.pk)
    if actor.pk != e.buyer_id and not is_staff(actor, e.country, "CM", "RV"):
        raise NotFound()
    if e.status == "closed":
        return e
    e.closed_at = _now()
    return state.transition(e, "listing_enquiry", "closed", actor=actor, extra_fields=["closed_at"],
                            payload={"enquiry_id": e.pk})


# --------------------------------------------------------------------------- reservations (FR-LST-005)

def _reservation_payload(res, **extra):
    l_ = res.listing
    return {"reservation_id": res.pk, "listing_id": l_.pk, "asset_id": l_.asset_id, "buyer_id": res.buyer_id,
            "client_id": res.buyer_id, "escrow_id": res.escrow_id, "organisation_id": l_.organisation_id,
            "report_id": l_.report_id, "country": res.country.code, **extra}


def _seller_payee(listing):
    from escrow.models import Payee

    if listing.organisation_id is None:
        return None
    return Payee.objects.filter(organisation_id=listing.organisation_id, kind__in=["seller", "developer"],
                                verification_status="verified").order_by("-created_at").first()


@transaction.atomic
def reserve(listing, buyer) -> Reservation:
    """Live to Reserved: a fresh search starts (CASE, reservation.created) and a purchase escrow is proposed."""
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    _on(listing.country)
    if not has_role(buyer, "CL"):
        raise Forbidden("Only a buyer with a client account can reserve.")
    if is_seller(buyer, listing):
        raise Forbidden("You cannot reserve your own listing.")
    if listing.status == "reserved" or listing.reservations.filter(status="active").exists():
        raise StateConflict("Another buyer has reserved this plot. You can send an enquiry and we will tell you if "
                            "it becomes free.", code="listing-reserved", extra={"enquire": f"/listings/{listing.pk}"
                                                                                         "/enquiries"})
    if listing.status != "live" or not badge_valid(listing):
        raise StateConflict("This listing cannot be reserved now.", code="listing-not-live",
                            extra={"listing_status": listing.status})
    days = int(_cfg(listing.country, "listings.reservation_days", DEFAULT_RESERVATION_DAYS))
    try:
        with transaction.atomic():
            res = Reservation.objects.create(country=listing.country, reference=_reference(listing.country, "RSV"),
                                             listing=listing, buyer=buyer, expires_at=_now() + timedelta(days=days))
    except IntegrityError:
        raise StateConflict("Another buyer reserved this plot a moment ago.", code="listing-reserved") from None
    from escrow import services as esc

    org = listing.organisation
    party = {"role": "developer" if org is not None and org.kind == "developer" else "seller",
             "person": listing.submitted_by, "organisation": org,
             "name": org.name if org else listing.submitted_by.full_name, "payee": _seller_payee(listing)}
    escrow = esc.create_escrow(buyer, kind="purchase", client=buyer, country=listing.country,
                               agreed_amount=listing.price_amount, currency=listing.price_currency,
                               title=f"Purchase: {listing.title}", report_id=listing.report_id,
                               asset_id=listing.asset_id, parties=[party])
    res.escrow = escrow
    res.save(update_fields=["escrow"])
    _move(listing, "reserved", actor=buyer, event="listing.reserved", reservation_id=res.pk, escrow_id=escrow.pk)
    publish("reservation.created", res.pk, _reservation_payload(res))
    from cases.models import Case

    fs = Case.objects.filter(product_line="fresh_search", origin="reservation", origin_ref=res.pk).first()
    if fs is not None:
        res.fresh_search_case_id = fs.pk
        res.save(update_fields=["fresh_search_case_id"])
    _audit(buyer, "listing.reserved", listing, {"reservation_id": str(res.pk), "escrow_id": str(escrow.pk)})
    _notify(buyer, "reservation_created", f"You reserved {listing.title} until "
            f"{timezone.localtime(res.expires_at):%d %B %Y}. A fresh search runs now. Read and accept the escrow "
            f"terms for {escrow.reference}.", subject=f"Reservation {res.reference}", obj=res,
            link=f"/escrows/{escrow.pk}", needs_action=True, category="money")
    _tell_seller(listing, "listing_reserved", f"Listing {listing.reference} is reserved by a buyer. Tenmina runs a "
                 f"fresh search; accept the escrow terms for {escrow.reference} when asked.")
    return res


def _back_to_live(listing, actor=None, reason=""):
    listing = Listing.objects.select_for_update().get(pk=listing.pk)
    if listing.status != "reserved":
        return listing
    if not badge_valid(listing):
        return _move(listing, "expired", actor=actor, event="listing.expired", reason="The badge expired.")
    return _move(listing, "live", actor=actor, event="listing.reinstated", reason=reason)


@transaction.atomic
def withdraw_reservation(res, buyer, reason="") -> Reservation:
    """TC-STM-LST-12, -13: the buyer withdraws only after the fresh search passed."""
    res = Reservation.objects.select_for_update().get(pk=res.pk)
    if buyer.pk != res.buyer_id:
        raise NotFound()
    if res.status != "active":
        raise StateConflict("This reservation has ended.")
    if res.fresh_search_status != "passed":
        raise StateConflict("You can withdraw once the fresh search result is in. If it fails, the reservation ends "
                            "by itself.", code="fresh-search-pending")
    if res.escrow_id and res.escrow.status not in ("proposed", "agreed", "cancelled"):
        raise StateConflict("Money is held for this purchase. Ask your case manager to cancel the escrow; the refund "
                            "goes back to where it came from.")
    _end_reservation(res.listing, reason or "you withdrew", status="withdrawn", actor=buyer)
    _back_to_live(res.listing, buyer, "The buyer withdrew.")
    res.refresh_from_db()
    return res


def lapse_reservations(now=None) -> int:
    """listings.lapse_reservations: a lapsed reservation with a passed fresh search frees the listing.
    One still waiting for its fresh search stays until the result; a funded escrow keeps it."""
    now = now or _now()
    n = 0
    for res in Reservation.objects.filter(status="active", expires_at__lte=now, fresh_search_status="passed"):
        with transaction.atomic():
            if res.escrow_id and res.escrow.status not in ("proposed", "agreed", "cancelled"):
                continue
            _end_reservation(res.listing, "the reservation period ended", status="lapsed")
            _back_to_live(res.listing, None, "The reservation lapsed.")
            n += 1
    return n


@transaction.atomic
def record_fresh_search_failure(res, actor, note) -> Reservation:
    """TC-E2E-J04-04: a fresh search that finds a new problem ends the reservation and suspends the listing."""
    res = Reservation.objects.select_for_update().get(pk=res.pk)
    if not is_staff(actor, res.country, "CM", "RV"):
        raise Forbidden("Only a case manager or reviewer records a fresh search result.")
    if not (note or "").strip():
        raise Invalid("Say what the fresh search found.")
    if res.status != "active":
        raise StateConflict("This reservation has ended.")
    res.fresh_search_status, res.fresh_search_note = "failed", note.strip()
    res.save(update_fields=["fresh_search_status", "fresh_search_note"])
    suspend(res.listing, kind="fresh_search_failed", source_id=res.pk, reason=f"Fresh search: {note.strip()}",
            actor=actor)
    res.refresh_from_db()
    return res


@transaction.atomic
def on_fresh_search_completed(payload: dict):
    from datetime import date

    res = None
    if payload.get("origin") == "reservation" and payload.get("origin_ref"):
        res = Reservation.objects.filter(pk=payload["origin_ref"]).first()
    if res is None and payload.get("asset_id"):
        res = Reservation.objects.filter(listing__asset_id=payload["asset_id"], status="active").first()
    if res is None or res.status != "active" or res.fresh_search_status == "failed":
        return
    d = payload.get("registry_result_date") or payload.get("site_check_date")
    res.fresh_search_status = "passed"
    res.fresh_search_date = date.fromisoformat(d[:10]) if isinstance(d, str) and d else d
    res.fresh_search_case_id = res.fresh_search_case_id or payload.get("case_id")
    res.save(update_fields=["fresh_search_status", "fresh_search_date", "fresh_search_case_id"])
    _audit(None, "listing.fresh_search_passed", res, {"case_id": str(payload.get("case_id") or "")})
    _notify(res.buyer, "reservation_fresh_search", f"The fresh search on {res.listing.title} is done. Your purchase "
            "can go ahead through the escrow.", obj=res, link=f"/reservations/{res.pk}")


@transaction.atomic
def on_release_confirmed(payload: dict):
    """FR-LST-007: Reserved (or Expired, TC-STM-LST-20) to Sold when the purchase escrow pays the seller."""
    eid = payload.get("escrow_id")
    if not eid:
        return
    res = Reservation.objects.filter(escrow_id=eid).order_by("-created_at").first()
    if res is None:
        return
    listing = Listing.objects.select_for_update().get(pk=res.listing_id)
    if listing.status not in ("reserved", "expired"):
        return
    if res.status == "active":
        res.ended_at, res.end_reason = _now(), "completed"
        state.transition(res, "listing_reservation", "completed", event="reservation.ended",
                         payload=_reservation_payload(res, end_reason="completed"),
                         extra_fields=["ended_at", "end_reason"])
    listing.sold_at = listing.closed_at = _now()
    _move(listing, "sold", event="listing.sold", extra_fields=["sold_at", "closed_at"],
          buyer_id=res.buyer_id, escrow_id=eid, client_id=res.buyer_id)
    _tell_seller(listing, "listing_sold", f"Listing {listing.reference} is sold. The bank paid the escrow.")


@transaction.atomic
def on_escrow_cancelled(payload: dict):
    eid = payload.get("escrow_id")
    res = Reservation.objects.filter(escrow_id=eid, status="active").first() if eid else None
    if res is None:
        return
    _end_reservation(res.listing, "the escrow was cancelled", cancel_escrow=False)
    if res.fresh_search_status != "failed":
        _back_to_live(res.listing, None, "The escrow was cancelled.")


# --------------------------------------------------------------------------- monitoring and disputes

def on_alert_raised(payload: dict):
    ids = [i for i in (payload.get("listing_ids") or []) if i]
    qs = Listing.objects.filter(status__in=["live", "reserved", "suspended"])
    qs = qs.filter(asset_id=payload.get("asset_id")) if payload.get("asset_id") else qs.filter(pk__in=ids)
    for listing in qs:
        suspend(listing, kind="monitoring_alert", source_id=payload.get("alert_id"),
                reason="Satellite monitoring saw a change on the plot. Tenmina is checking it.")


def on_alert_resolved(payload: dict):
    aid = payload.get("alert_id")
    if not aid:
        return
    if payload.get("resolution") == "change_confirmed":
        for s in Suspension.objects.filter(kind="monitoring_alert", source_id=aid, lifted_at__isnull=True):
            _alert_staff(s.country, ("RV",), "listing_alert_confirmed",
                         f"The change on the plot of listing {s.listing.reference} is confirmed. It stays suspended "
                         "until a reviewer decides or the seller orders re-verification.", obj=s.listing)
        return
    lift_source("monitoring_alert", aid, note=f"Monitoring alert resolved: {payload.get('resolution', '')}")


def on_dispute(payload: dict, opened: bool):
    lid = payload.get("listing_id")
    did = payload.get("dispute_id")
    if not lid or not did:
        return
    listing = Listing.objects.filter(pk=lid).first()
    if listing is None:
        return
    if opened:
        suspend(listing, kind="dispute", source_id=did, reason="A dispute was opened on this listing.")
    else:
        lift_source("dispute", did, note="The dispute closed.")


# --------------------------------------------------------------------------- established sellers

@transaction.atomic
def open_screening(actor, organisation) -> SellerScreening:
    if not is_staff(actor, organisation.country, "CM", "RV"):
        raise Forbidden("Only a case manager screens a seller.")
    if organisation.kind not in ("seller", "developer"):
        raise Invalid("Only seller and developer organisations are screened.")
    existing = SellerScreening.objects.filter(organisation=organisation).order_by("-created_at").first()
    if existing and existing.status == "in_progress":
        return existing
    if existing:
        existing.checks = {}
        existing.decided_by, existing.decided_at, existing.decision_note = None, None, ""
        return state.transition(existing, "seller_screening", "in_progress", actor=actor,
                                extra_fields=["checks", "decided_by", "decided_at", "decision_note"])
    s = SellerScreening.objects.create(country=organisation.country, organisation=organisation, opened_by=actor,
                                       checks={k: {"status": "pending"} for k in SellerScreening.CHECKS})
    _audit(actor, "seller_screening.opened", s, {"organisation_id": str(organisation.pk)})
    return s


@transaction.atomic
def record_screening_check(screening, actor, *, key, status, note="", evidence=None) -> SellerScreening:
    s = SellerScreening.objects.select_for_update().get(pk=screening.pk)
    if not is_staff(actor, s.country, "CM", "RV"):
        raise Forbidden()
    if s.status != "in_progress":
        raise StateConflict("This screening is decided.")
    if key not in SellerScreening.CHECKS:
        raise Invalid(f"Check must be one of {', '.join(SellerScreening.CHECKS)}.")
    if status not in ("passed", "failed", "not_applicable"):
        raise Invalid("Status must be passed, failed or not_applicable.")
    if status == "passed" and evidence is None:
        raise Invalid("Attach the evidence for a passed check.", code="evidence-required")
    if status == "not_applicable" and key != "agency_licence":
        raise Invalid("Only the agency licence can be not applicable (Act 1047, where it applies).")
    if evidence is not None:
        from evidence.services import link

        link(evidence, "seller_screening", s.pk, role=key, by=actor)
    checks = dict(s.checks or {})
    checks[key] = {"status": status, "note": note or "", "evidence_id": str(evidence.pk) if evidence else None,
                   "checked_by": str(actor.pk), "checked_at": _now().isoformat()}
    s.checks = checks
    s.save(update_fields=["checks"])
    _audit(actor, "seller_screening.check", s, {"key": key, "status": status})
    return s


@transaction.atomic
def decide_screening(screening, actor, *, outcome, note="") -> SellerScreening:
    s = SellerScreening.objects.select_for_update().get(pk=screening.pk)
    if not is_staff(actor, s.country, "RV"):
        raise Forbidden("Only a reviewer decides a screening.")
    if actor.pk == s.opened_by_id:
        raise DomainError("The person who ran the screening cannot decide it.", code="same-approver")
    if outcome not in ("established", "not_established"):
        raise Invalid("Outcome must be established or not_established.")
    if outcome == "established":
        missing = [k for k in SellerScreening.CHECKS
                   if (s.checks or {}).get(k, {}).get("status") not in ("passed", "not_applicable")]
        if missing:
            raise RuleBlocked("Every check must pass first.", code="screening-incomplete",
                              blocking_reasons=[{"rule": "DEC-2026-11-12", "message": f"Not passed: {k}"}
                                                for k in missing])
    elif not (note or "").strip():
        raise Invalid("Say why the seller is not established.")
    s.decided_by, s.decided_at, s.decision_note = actor, _now(), note or ""
    return state.transition(s, "seller_screening", outcome, actor=actor, event="seller_screening.decided",
                            payload={"organisation_id": s.organisation_id, "outcome": outcome},
                            extra_fields=["decided_by", "decided_at", "decision_note"])


def is_established(organisation_id) -> bool:
    if not organisation_id:
        return False
    s = SellerScreening.objects.filter(organisation_id=organisation_id).order_by("-created_at").first()
    return s is not None and s.status == "established"


def count_view(listing):
    Listing.objects.filter(pk=listing.pk).update(view_count=listing.view_count + 1)


__all__ = [n for n in dir() if not n.startswith("_")]
