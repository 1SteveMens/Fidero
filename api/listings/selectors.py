"""LST read-only queries other modules may use.

- public_listings(at)                 live listings with a valid badge (RUL-13 at read time)
- search(params, at)                  FR-LST-004 filters
- point_of(listing)                   map position: the plot's confirmed point or its boundary centre
- visible_listings(user)              what a seller, buyer or staff member may open
- listing_for_asset(asset_id)         the active listing on a plot, if any
- active_reservation(listing)
"""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, Q
from django.utils import timezone

from core.permissions import has_role

from .models import ACTIVE_STATUSES, PUBLIC_STATUSES, Enquiry, Listing, Reservation

SORTS = {"price": "price_amount", "-price": "-price_amount", "newest": "-live_at", "verified": "-checks_date",
         "size": "size_sqm", "-size": "-size_sqm"}


def public_listings(at=None):
    at = at or timezone.now()
    return Listing.objects.filter(status="live", badge_expires_at__gt=at, report__isnull=False).select_related(
        "asset", "organisation", "country", "report")


def _dec(v):
    try:
        return Decimal(str(v))
    except (InvalidOperation, TypeError):
        return None


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def search(params, at=None, qs=None):
    """Filters: country, region, district, locality, kind, min_price, max_price, currency, min_size, max_size,
    verified_since, q (full text), organisation_id, bbox (min_lng,min_lat,max_lng,max_lat), sort."""
    qs = public_listings(at) if qs is None else qs
    g = params.get
    if g("country"):
        qs = qs.filter(country__code=str(g("country")).upper())
    for f in ("region", "district", "locality"):
        if g(f):
            qs = qs.filter(**{f"{f}__icontains": g(f)})
    if g("kind"):
        qs = qs.filter(kind__in=str(g("kind")).split(","))
    if g("currency"):
        qs = qs.filter(price_currency=str(g("currency")).upper())
    for key, lookup in (("min_price", "price_amount__gte"), ("max_price", "price_amount__lte"),
                        ("min_size", "size_sqm__gte"), ("max_size", "size_sqm__lte")):
        v = _dec(g(key)) if g(key) not in (None, "") else None
        if v is not None:
            qs = qs.filter(**{lookup: v})
    if g("verified_since"):
        d = _date(g("verified_since"))
        if d:
            qs = qs.filter(checks_date__gte=d)
    if g("organisation_id"):
        qs = qs.filter(organisation_id=g("organisation_id"))
    if g("bbox"):
        try:
            x1, y1, x2, y2 = [float(x) for x in str(g("bbox")).split(",")]
            from django.contrib.gis.geos import Polygon

            box = Polygon.from_bbox((x1, y1, x2, y2))
            box.srid = 4326
            qs = qs.filter(Q(asset__location__within=box) | Q(asset__current_boundary__geom__intersects=box))
        except (ValueError, TypeError):
            pass
    if g("q"):
        query = SearchQuery(str(g("q")), search_type="websearch")
        qs = qs.filter(search_doc=query).annotate(rank=SearchRank(F("search_doc"), query)).order_by("-rank")
        return qs
    return qs.order_by(SORTS.get(g("sort") or "", "-live_at"), "pk")


def point_of(listing):
    """(lng, lat) for the map, or None. Coordinates are never guessed (FR-GEO-008)."""
    a = listing.asset
    if a.location is not None:
        return float(a.location.x), float(a.location.y)
    b = a.current_boundary
    if b is not None and getattr(b, "geom", None) is not None:
        c = b.geom.centroid
        return float(c.x), float(c.y)
    return None


def boundary_geojson(listing):
    b = listing.asset.current_boundary
    if b is None or getattr(b, "geom", None) is None:
        return None
    from geo.geometry import as_geojson

    return as_geojson(b.geom)


def visible_listings(user):
    """Public listings for everyone; sellers see their organisation's; staff see their countries'."""
    if user is None or not user.is_authenticated:
        return Listing.objects.filter(status__in=PUBLIC_STATUSES + ["sold"])
    q_ = Q(status__in=PUBLIC_STATUSES + ["sold"]) | Q(submitted_by=user) | Q(
        organisation__memberships__person=user, organisation__memberships__status="active")
    q_ |= Q(reservations__buyer=user)
    if has_role(user, "CM", "RV", "AD"):
        from accounts.selectors import staff_country_codes

        codes = staff_country_codes(user)
        if codes is None:
            return Listing.objects.all()
        q_ |= Q(country__code__in=list(codes))
    return Listing.objects.filter(q_).distinct()


def listing_for_asset(asset_id):
    return Listing.objects.filter(asset_id=asset_id, status__in=ACTIVE_STATUSES).first()


def active_reservation(listing):
    return listing.reservations.filter(status="active").first()


def reservations_for(user):
    q_ = Q(buyer=user) | Q(listing__submitted_by=user) | Q(listing__organisation__memberships__person=user,
                                                           listing__organisation__memberships__status="active")
    if has_role(user, "CM", "RV", "AD"):
        from accounts.selectors import staff_country_codes

        codes = staff_country_codes(user)
        if codes is None:
            return Reservation.objects.all()
        q_ |= Q(country__code__in=list(codes))
    return Reservation.objects.filter(q_).distinct()


def enquiries_for(user):
    q_ = Q(buyer=user) | Q(listing__submitted_by=user) | Q(listing__organisation__memberships__person=user,
                                                           listing__organisation__memberships__status="active")
    if has_role(user, "CM", "RV", "AD"):
        from accounts.selectors import staff_country_codes

        codes = staff_country_codes(user)
        if codes is None:
            return Enquiry.objects.all()
        q_ |= Q(country__code__in=list(codes))
    return Enquiry.objects.filter(q_).distinct()


def is_party(person, listing) -> bool:
    """For DSP: the seller side, or the buyer holding a reservation (active or ended with an escrow)."""
    from .services import is_seller

    if is_seller(person, listing):
        return True
    return listing.reservations.filter(buyer=person).exists()
