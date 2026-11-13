"""GEO Geospatial: read-only queries other modules may use."""
from django.db.models import Q
from django.utils import timezone

from core.permissions import PROFESSIONAL_ROLES, STAFF_ROLES, has_role

from .models import Asset, AssetAccess, MonitoringAlert, OverlapFlag


def role_countries(user, roles):
    """None when the user holds one of `roles` in every country, else the set of country ids."""
    grants = user.role_grants.filter(role__in=roles, revoked_at__isnull=True).values_list("country_id", flat=True)
    ids = set(grants)
    if None in ids:
        return None
    return ids


def in_country(qs, user, roles, field="country_id"):
    countries = role_countries(user, roles)
    if countries is None:
        return qs
    return qs.filter(**{f"{field}__in": countries})


def active_grants(user):
    now = timezone.now()
    return AssetAccess.objects.filter(person=user, revoked_at__isnull=True).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def visible_assets(user):
    """Clients and owners see their own; staff their countries; professionals what they are assigned."""
    if not user or not user.is_authenticated:
        return Asset.objects.none()
    q = Q(owner=user)
    if has_role(user, *STAFF_ROLES):
        countries = role_countries(user, STAFF_ROLES)
        if countries is None:
            return Asset.objects.all()
        q |= Q(country_id__in=countries)
    if has_role(user, *PROFESSIONAL_ROLES):
        q |= Q(pk__in=active_grants(user).values("asset_id"))
    return Asset.objects.filter(q)


def is_staff_for(user, asset, *roles) -> bool:
    return has_role(user, *(roles or tuple(STAFF_ROLES)), country=asset.country)


def is_assigned(user, asset, *roles) -> bool:
    qs = active_grants(user).filter(asset=asset)
    if roles:
        qs = qs.filter(role__in=roles)
    return qs.exists()


def is_owner(user, asset) -> bool:
    return asset.owner_id is not None and asset.owner_id == user.pk


def section7(asset_id) -> dict:
    """For RPT: the proposed section 7 verdict with reasons and the run it came from."""
    from .services import section7 as _s7

    return _s7(Asset.objects.get(pk=asset_id))


def is_disputed(asset_id) -> bool:
    """For CASE (RUL-17)."""
    return Asset.objects.filter(pk=asset_id, disputed_flag=True).exists()


def has_open_alert(asset_id) -> bool:
    """For LST (RUL-13): an unresolved monitoring alert hides the badge."""
    return MonitoringAlert.objects.filter(asset_id=asset_id, status__in=["open", "under_review"]).exists()


def open_overlaps(asset_id):
    return OverlapFlag.objects.filter(asset_id=asset_id, status__in=["open", "confirmed"])


def assets_at_point(country, lng, lat):
    """For PTR (US-PTR-001): assets whose current boundary contains the point (02 7.8).
    The caller returns 'ambiguous' when more than one matches."""
    from django.contrib.gis.geos import Point

    pt = Point(float(lng), float(lat), srid=4326)
    return Asset.objects.filter(country=country, current_boundary__geom__intersects=pt)


def distance_to_boundary_m(asset_id, lng, lat):
    """For MOB (FR-MOB-003): metres from a captured point to the plot boundary (0 inside), or None."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(
            "SELECT ST_Distance(b.geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) "
            "FROM geo_asset a JOIN geo_boundary_version b ON b.id = a.current_boundary_id WHERE a.id = %s",
            [float(lng), float(lat), str(asset_id)])
        row = cur.fetchone()
    return None if row is None else round(float(row[0]), 2)
