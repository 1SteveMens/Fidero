"""GEO Geospatial: the public interface other modules may call.

Assets and boundaries (FR-GEO-001), overlay checks and the proposed section 7
verdict (FR-GEO-002, 003), overlay layers (FR-GEO-004), overlaps with other
plots (FR-GEO-005), satellite images (FR-GEO-006), monitoring (FR-GEO-007)
and digital addresses such as Ghana Post GPS (FR-GEO-008).
"""
import hashlib
import logging
import time
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import Max, Q
from django.utils import timezone

from administration import flags
from audit.services import record
from core import state
from core.adapters import get_adapter
from core.errors import DomainError, Forbidden, Invalid, StateConflict
from core.events import publish
from core.ids import human_ref
from countries.selectors import config as country_config

from . import geometry as G
from .adapters import ServiceUnavailable
from .models import (SQM_PER_ACRE, Asset, AssetAccess, BoundaryVersion, CountryExtent, MonitoringAlert,
                     MonitoringEnrolment, OverlapFlag, OverlayFeature, OverlayLayer, OverlayLayerVersion,
                     OverlayResult, OverlayRun, SatelliteImage)

log = logging.getLogger(__name__)

SATELLITE_FLAG = "geo.satellite_monitoring"
ADDRESS_FLAG = "geo.ghana_post_gps"

# Working assumptions used only when neither an administrator setting nor the
# country configuration gives a value. Every one is [TO VERIFY].
DEFAULTS = {
    "geo.buffer_m": Decimal("50"),               # near = within 50 m of a layer feature [TO VERIFY]
    "geo.overlap_min_sqm": Decimal("1"),         # ignore slivers under 1 m2 from digitising [TO VERIFY]
    "geo.min_plot_sqm": Decimal("20"),           # smaller than this is almost certainly a mistake [TO VERIFY]
    "geo.max_plot_sqm": Decimal("5000000"),      # 500 hectares [TO VERIFY]
    "geo.imagery_max_cloud_pct": Decimal("20"),  # IF-05: skip cloudier scenes [TO VERIFY]
    "geo.monitoring_change_threshold": Decimal("0.15"),  # change score that raises an alert [TO VERIFY]
}


def _adapter(port):
    defaults = {"satellite": "geo.adapters.FakeSatellite", "address_resolver": "geo.adapters.FakeAddressResolver"}
    return get_adapter(port, default=defaults[port])


def setting(key: str, country, default=None):
    """Configurable value (FR-ADM-005): administrator setting, then country configuration, then default."""
    try:
        from administration import selectors as adm

        getter = getattr(adm, "setting", None)
        if getter is not None:
            value = getter(key, country)
            if value not in (None, ""):
                return value
    except Exception:  # noqa: BLE001 - the ADM settings store may not exist yet
        pass
    value = country_config(country, key, None)
    if value is not None:
        return value
    return default if default is not None else DEFAULTS.get(key)


def _dec(value, places="0.01"):
    return Decimal(str(value)).quantize(Decimal(places))


def staff_to_alert(country, roles=("CM",)):
    from accounts.models import Person

    return list(Person.objects.filter(
        Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
        role_grants__role__in=roles, role_grants__revoked_at__isnull=True, is_active=True).distinct())


def _notify_staff(country, template, *, subject, body, obj, link=""):
    from notifications.services import notify

    for person in staff_to_alert(country):
        notify(person, template, subject=subject, body=body, link=link, channels=("in_app", "email"),
               needs_action=False, subject_obj=obj)


# --------------------------------------------------------------------------- assets


def _next_reference(country):
    year = timezone.now().year
    prefix = f"AST-{country.code}-{year}-"
    with connection.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(7312)")
    last = (Asset.objects.filter(reference__startswith=prefix).order_by("-reference")
            .values_list("reference", flat=True).first())
    n = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    return human_ref("AST", country.code, year, n)


def _point(location):
    from django.contrib.gis.geos import Point

    if location in (None, {}, ""):
        return None
    try:
        lng, lat = float(location["lng"]), float(location["lat"])
    except (KeyError, TypeError, ValueError):
        raise Invalid('Give the location as {"lng": -0.18, "lat": 5.6}.')
    if not (-180 <= lng <= 180 and -90 <= lat <= 90):
        raise Invalid("The location is not a valid longitude and latitude.", code="projection-invalid")
    return Point(lng, lat, srid=4326)


def _check_in_extent(country, geom):
    """Refuse coordinates outside the country's land area (when one is loaded).
    Coordinates that fit once latitude and longitude are swapped get their own message."""
    ext = CountryExtent.objects.filter(country=country).first()
    if ext is None or ext.geom.intersects(geom):
        return
    from django.contrib.gis.geos import GEOSGeometry

    with connection.cursor() as cur:
        cur.execute("SELECT ST_AsEWKT(ST_FlipCoordinates(ST_GeomFromEWKT(%s)))", [geom.ewkt])
        swapped = GEOSGeometry(cur.fetchone()[0])
    if ext.geom.intersects(swapped):
        raise Invalid("The coordinates look swapped. Give longitude first, then latitude "
                      "(or easting, then northing).", code="geometry-outside-country")
    raise Invalid(f"These coordinates are outside {country.name}. Check the coordinate system and the values.",
                  code="geometry-outside-country")


def create_asset(*, actor, country, type="plot", locality, owner=None, name="", region="", district="",
                 address="", plot_number="", site_plan_ref="", ghana_post_gps="", location=None) -> Asset:
    """Register a plot, building, off-plan unit or managed property.

    FR-GEO-008: a digital address is always saved as text. Coordinates are
    saved only when the caller confirmed them; none are ever guessed."""
    flags.read_only_guard()
    if type not in Asset.TYPES:
        raise Invalid(f"Type must be one of {', '.join(Asset.TYPES)}.")
    if not (locality or "").strip():
        raise Invalid("Give the locality (town or area) of the property.")
    point = _point(location)
    if point is not None:
        _check_in_extent(country, point)
    code = ghana_post_gps.strip().upper() if ghana_post_gps else ""
    with transaction.atomic():
        asset = Asset.objects.create(
            country=country, reference=_next_reference(country), type=type, name=name, owner=owner,
            region=region, district=district, locality=locality.strip(), address=address, plot_number=plot_number,
            site_plan_ref=site_plan_ref, ghana_post_gps=code, location=point,
            location_source=("digital_address_confirmed" if point is not None and code else
                             "manual" if point is not None else "none"),
            created_by=actor)
        record(actor=actor, action="asset.created", entity="asset", entity_id=asset.pk, country=country,
               data={"reference": asset.reference, "type": type, "owner_id": owner.pk if owner else None})
        publish("asset.created", asset.pk, {"asset_id": asset.pk, "country": country.code, "type": type,
                                            "owner_id": owner.pk if owner else None})
    return asset


EDITABLE = {"name", "region", "district", "locality", "address", "plot_number", "site_plan_ref", "ghana_post_gps"}


def update_asset(asset: Asset, *, actor, location=..., **fields) -> Asset:
    flags.read_only_guard()
    unknown = set(fields) - EDITABLE
    if unknown:
        raise Invalid(f"These fields cannot be changed here: {', '.join(sorted(unknown))}.")
    changed = {}
    for k, v in fields.items():
        v = (v or "").strip()
        if k == "ghana_post_gps":
            v = v.upper()
        if k == "locality" and not v:
            raise Invalid("Give the locality (town or area) of the property.")
        if getattr(asset, k) != v:
            changed[k] = v
            setattr(asset, k, v)
    if location is not ...:
        point = _point(location)
        if point is not None:
            _check_in_extent(asset.country, point)
        asset.location = point
        asset.location_source = ("none" if point is None else
                                 "digital_address_confirmed" if asset.ghana_post_gps else "manual")
        changed["location"] = location
    if not changed:
        return asset
    asset.save()
    record(actor=actor, action="asset.updated", entity="asset", entity_id=asset.pk, country=asset.country,
           data=changed)
    return asset


def set_disputed(asset: Asset, *, actor, disputed: bool, reason="") -> Asset:
    """RUL-17 input: field visits to a disputed plot need a risk screen and two people."""
    if disputed and not reason.strip():
        raise Invalid("Say why the plot is disputed.")
    asset.disputed_flag = bool(disputed)
    asset.disputed_reason = reason.strip() if disputed else ""
    asset.save(update_fields=["disputed_flag", "disputed_reason"])
    record(actor=actor, action="asset.disputed_flag", entity="asset", entity_id=asset.pk, country=asset.country,
           data={"disputed": asset.disputed_flag, "reason": asset.disputed_reason})
    publish("asset.dispute_flag_changed", asset.pk, {"asset_id": asset.pk, "disputed": asset.disputed_flag})
    return asset


def mark_verified(asset_id, *, at=None, actor=None):
    """Called by RPT (or its report.released event) when a report on this plot is released.
    Verified plots are what new plots are checked against first (FR-GEO-005)."""
    asset = Asset.objects.filter(pk=asset_id).first()
    if asset is None or asset.verified_at:
        return asset
    asset.verified_at = at or timezone.now()
    asset.save(update_fields=["verified_at"])
    record(actor=actor, action="asset.verified", entity="asset", entity_id=asset.pk, country=asset.country,
           data={"verified_at": asset.verified_at})
    return asset


def grant_access(asset: Asset, person, *, role, actor=None, case_id=None, expires_at=None) -> AssetAccess:
    """Give an assigned professional access to the asset (SV asg, LW asg)."""
    if role not in AssetAccess.ROLES:
        raise Invalid(f"Role must be one of {', '.join(AssetAccess.ROLES)}.")
    if not person.has_tenmina_role(role, country=asset.country):
        raise Invalid("This person does not hold that role in this country.")
    existing = AssetAccess.objects.filter(asset=asset, person=person, role=role, revoked_at__isnull=True,
                                          case_id=case_id).first()
    if existing:
        return existing
    grant = AssetAccess.objects.create(asset=asset, country=asset.country, person=person, role=role,
                                       case_id=case_id, granted_by=actor, expires_at=expires_at)
    record(actor=actor, action="asset.access_granted", entity="asset", entity_id=asset.pk, country=asset.country,
           data={"person_id": person.pk, "role": role, "case_id": case_id})
    return grant


def revoke_access(grant: AssetAccess, *, actor=None) -> AssetAccess:
    if grant.revoked_at is None:
        grant.revoked_at = timezone.now()
        grant.save(update_fields=["revoked_at"])
        record(actor=actor, action="asset.access_revoked", entity="asset", entity_id=grant.asset_id,
               country=grant.country, data={"person_id": grant.person_id, "role": grant.role})
    return grant


def revoke_case_access(case_id, *, actor=None):
    for g in AssetAccess.objects.filter(case_id=case_id, revoked_at__isnull=True):
        revoke_access(g, actor=actor)


def set_country_extent(country, *, actor, geojson, label="") -> CountryExtent:
    mp, _ = G.boundary_from_geojson(geojson)
    ext, _ = CountryExtent.objects.update_or_create(country=country, defaults={
        "geom": mp, "label": label, "loaded_by": actor})
    record(actor=actor, action="geo.country_extent_set", entity="country", entity_id=country.pk, country=country,
           data={"label": label})
    return ext


# --------------------------------------------------------------------------- boundaries (FR-GEO-001)


def parse_boundary(*, source, coordinates=None, geojson=None, points=None, srid=4326):
    """Return (MultiPolygon in WGS 84, input srid). Raises Invalid with a plain message."""
    srid = G.check_srid(srid or 4326)
    given = [x for x in (coordinates, geojson, points) if x not in (None, "", [])]
    if len(given) != 1:
        raise Invalid("Give exactly one of coordinates, geojson or points.")
    if coordinates not in (None, "", []):
        return G.polygon_from_points(coordinates, srid), srid
    if points not in (None, "", []):
        # Drawn on a map: longitude and latitude, the ring is closed for the user.
        return G.polygon_from_points(points, 4326, close=True), 4326
    return G.boundary_from_geojson(geojson, srid)


def _measure(geom):
    with connection.cursor() as cur:
        cur.execute(
            "SELECT ST_Area(g::geography), ST_Perimeter(g::geography), ST_AsEWKT(ST_PointOnSurface(g)) "
            "FROM (SELECT ST_GeomFromEWKT(%s) AS g) s", [geom.ewkt])
        area, perim, centroid = cur.fetchone()
    from django.contrib.gis.geos import GEOSGeometry

    return Decimal(str(area)), Decimal(str(perim)), GEOSGeometry(centroid)


def save_boundary(asset: Asset, *, actor, source, coordinates=None, geojson=None, points=None, srid=4326,
                  evidence=None, note="") -> BoundaryVersion:
    """Save a new boundary version (never edits an old one), then publish
    asset.boundary_saved so the overlay and overlap checks run (FR-GEO-002, 005)."""
    flags.read_only_guard()
    if source not in BoundaryVersion.SOURCES:
        raise Invalid(f"Source must be one of {', '.join(BoundaryVersion.SOURCES)}.")
    if asset.type == "offplan_unit" and source == "records_programme":
        raise Invalid("Off-plan units take the boundary of the development plot.")
    geom, in_srid = parse_boundary(source=source, coordinates=coordinates, geojson=geojson, points=points, srid=srid)
    _check_in_extent(asset.country, geom)
    area, perimeter, centroid = _measure(geom)
    lo = Decimal(str(setting("geo.min_plot_sqm", asset.country)))
    hi = Decimal(str(setting("geo.max_plot_sqm", asset.country)))
    if area < lo:
        raise Invalid(f"The boundary encloses only {area:.0f} m2. Check the units and the coordinate system.",
                      code="geometry-implausible")
    if area > hi:
        raise Invalid(f"The boundary encloses {area / 10000:.1f} hectares, more than the {hi / 10000:.0f} hectares "
                      "allowed for one plot. Check the units and the coordinate system.", code="geometry-implausible")
    if evidence is not None and evidence.country_id != asset.country_id:
        raise Invalid("The evidence belongs to another country.")
    with transaction.atomic():
        asset = Asset.objects.select_for_update().get(pk=asset.pk)
        n = (asset.boundaries.aggregate(m=Max("version"))["m"] or 0) + 1
        bv = BoundaryVersion.objects.create(
            asset=asset, country=asset.country, version=n, geom=geom, source=source, input_srid=in_srid,
            area_sqm=_dec(area), area_acres=_dec(area / Decimal(str(SQM_PER_ACRE)), "0.0001"),
            perimeter_m=_dec(perimeter), centroid=centroid, point_count=geom.num_coords, evidence=evidence,
            note=note, captured_by=actor)
        previous = asset.current_boundary_id
        asset.current_boundary = bv
        fields = ["current_boundary"]
        if asset.location is None or asset.location_source in ("none", "boundary"):
            asset.location, asset.location_source = centroid, "boundary"
            fields += ["location", "location_source"]
        asset.save(update_fields=fields)
        if evidence is not None:
            from evidence.services import link

            link(evidence, "geo_boundary", bv.pk, role="boundary_source", by=actor)
        for flag in OverlapFlag.objects.filter(asset=asset, status__in=["open", "confirmed"]).exclude(boundary=bv):
            state.transition(flag, "overlap_flag", "superseded", actor=actor, event="overlap.superseded",
                             payload={"asset_id": asset.pk, "new_boundary_id": bv.pk})
        run = OverlayRun.objects.create(asset=asset, country=asset.country, boundary=bv, trigger="boundary_saved",
                                        requested_by=actor)
        record(actor=actor, action="asset.boundary_saved", entity="asset", entity_id=asset.pk, country=asset.country,
               data={"boundary_id": bv.pk, "version": n, "source": source, "input_srid": in_srid,
                     "area_sqm": bv.area_sqm, "previous_boundary_id": previous})
        publish("asset.boundary_saved", asset.pk, {
            "asset_id": asset.pk, "boundary_id": bv.pk, "version": n, "source": source, "run_id": run.pk,
            "area_sqm": bv.area_sqm, "country": asset.country.code})
    return bv


# --------------------------------------------------------------------------- overlay checks (FR-GEO-002, 003)


def layer_buffer(layer: OverlayLayer) -> Decimal:
    if layer.buffer_m is not None:
        return Decimal(layer.buffer_m)
    by_kind = setting(f"geo.buffer_m.{layer.kind}", layer.country, None)
    if isinstance(by_kind, (int, float, str, Decimal)) and str(by_kind) not in ("",):
        try:
            return Decimal(str(by_kind))
        except Exception:  # noqa: BLE001
            pass
    return Decimal(str(setting("geo.buffer_m", layer.country)))


def classify(intersection_sqm, distance_m, buffer_m) -> str:
    """Inside when the plot shares area with a feature; near when within the
    buffer (the boundary distance counts as near); else clear (TC-GEO-003-02)."""
    if intersection_sqm is not None and Decimal(str(intersection_sqm)) > Decimal("0.01"):
        return "inside"
    if distance_m is not None and _dec(distance_m) <= _dec(buffer_m):
        return "near"
    return "clear"


def _layer_check(boundary: BoundaryVersion, version: OverlayLayerVersion, buffer_m: Decimal) -> dict:
    sql = """
        WITH b AS (SELECT geom FROM geo_boundary_version WHERE id = %s)
        SELECT f.id, f.name,
               ST_Area(ST_Intersection(f.geom, b.geom)::geography) AS inter,
               ST_Distance(f.geom::geography, b.geom::geography) AS dist
          FROM geo_overlay_feature f, b
         WHERE f.layer_version_id = %s
           AND ST_DWithin(f.geom::geography, b.geom::geography, %s)
         ORDER BY dist, inter DESC
    """
    with connection.cursor() as cur:
        cur.execute(sql, [boundary.pk, version.pk, float(buffer_m) + 1.0])
        rows = cur.fetchall()
    if not rows:
        return {"outcome": "clear", "distance_m": None, "affected_area_sqm": Decimal("0"),
                "affected_share": Decimal("0"), "feature_ids": [], "feature_names": []}
    inside = [r for r in rows if classify(r[2], r[3], buffer_m) == "inside"]
    if inside:
        ids = [r[0] for r in inside]
        with connection.cursor() as cur:
            cur.execute(
                "SELECT ST_Area(ST_Intersection(b.geom, ST_Union(f.geom))::geography) "
                "FROM geo_overlay_feature f, geo_boundary_version b WHERE b.id = %s AND f.id = ANY(%s) "
                "GROUP BY b.geom", [boundary.pk, ids])
            area = Decimal(str(cur.fetchone()[0]))
        share = min(Decimal("1"), area / Decimal(boundary.area_sqm)) if boundary.area_sqm else Decimal("0")
        return {"outcome": "inside", "distance_m": Decimal("0"), "affected_area_sqm": _dec(area),
                "affected_share": _dec(share, "0.0001"), "feature_ids": ids, "feature_names": [r[1] for r in inside]}
    nearest = rows[0]
    outcome = classify(None, nearest[3], buffer_m)
    near_rows = [r for r in rows if classify(None, r[3], buffer_m) == "near"]
    return {"outcome": outcome, "distance_m": _dec(nearest[3]), "affected_area_sqm": Decimal("0"),
            "affected_share": Decimal("0"), "feature_ids": [r[0] for r in near_rows],
            "feature_names": [r[1] for r in near_rows]}


def expected_layers(country):
    """Every layer the country says a plot must be checked against: active, or created but not yet loaded."""
    return list(OverlayLayer.objects.filter(country=country, status__in=["active", "draft"])
                .select_related("current_version").order_by("code"))


def _layer_failure_hook(layer, version):
    """Tests replace this to simulate a worker failure on one layer (TC-GEO-002-02)."""


def evaluate_run(run: OverlayRun) -> str:
    """Compute every layer result of a pending run and fill its fields. Returns the
    status the run should move to; the caller saves it (run_overlays, or a seed)."""
    started = time.monotonic()
    run.started_at = timezone.now()
    items = []
    for layer in expected_layers(run.country):
        version = layer.current_version
        base = {"layer_id": str(layer.pk), "layer_code": layer.code, "layer_name": layer.name,
                "layer_kind": layer.kind, "is_sample": layer.is_sample}
        if version is None:
            items.append({**base, "status": "missing", "message": "This layer has no data loaded yet."})
            continue
        base.update(layer_version_id=str(version.pk), layer_version=version.version)
        existing = OverlayResult.objects.filter(boundary=run.boundary, layer_version=version).first()
        if existing is not None:
            items.append({**base, "status": "checked", "result_id": str(existing.pk), "outcome": existing.outcome,
                          "reused": True})
            continue
        buf = layer_buffer(layer)
        try:
            with transaction.atomic():
                _layer_failure_hook(layer, version)
                r = _layer_check(run.boundary, version, buf)
                res = OverlayResult.objects.create(
                    country=run.country, boundary=run.boundary, layer_version=version, run=run, buffer_m=buf, **r)
            items.append({**base, "status": "checked", "result_id": str(res.pk), "outcome": res.outcome})
        except Exception as exc:  # noqa: BLE001 - one layer failing must not lose the others
            log.exception("overlay check failed for layer %s", layer.code)
            items.append({**base, "status": "failed", "message": f"The check could not run: {exc}"})
    run.items = items
    run.layers_expected = len(items)
    run.layers_checked = sum(1 for i in items if i["status"] == "checked")
    verdict, reasons = overlay_verdict(run)
    run.proposed_verdict, run.verdict_reasons = verdict, reasons
    run.completed_at = timezone.now()
    run.duration_ms = int((time.monotonic() - started) * 1000)
    to = "completed" if run.layers_checked == run.layers_expected else "incomplete"
    if not items:
        to = "incomplete"
        run.error = "No overlay layers are configured for this country."
    return to


def run_overlays(run: OverlayRun) -> OverlayRun:
    """Check the run's boundary against every expected layer. A missing layer or a
    failure marks the run incomplete, alerts case managers, and keeps the
    proposed verdict from being green (TC-GEO-002-02)."""
    run = OverlayRun.objects.select_related("boundary", "asset", "country").get(pk=run.pk)
    if run.status != "pending":
        return run
    to = evaluate_run(run)
    state.transition(run, "overlay_run", to, event="overlay_run.status_changed",
                     extra_fields=["items", "layers_expected", "layers_checked", "proposed_verdict",
                                   "verdict_reasons", "started_at", "completed_at", "duration_ms", "error"],
                     payload={"asset_id": run.asset_id})
    _apply_dispute_layer(run)
    s7 = section7(run.asset)
    publish("overlay.completed", run.asset_id, {
        "asset_id": run.asset_id, "boundary_id": run.boundary_id, "run_id": run.pk, "status": run.status,
        "overlay_verdict": run.proposed_verdict, "proposed_verdict": s7["proposed_verdict"],
        "layers_checked": run.layers_checked, "layers_expected": run.layers_expected,
        "duration_ms": run.duration_ms, "country": run.country.code})
    if run.status != "completed":
        _notify_staff(run.country, "geo.overlay_incomplete", obj=run,
                      subject=f"Overlay check incomplete for {run.asset.reference}",
                      body=f"{run.layers_expected - run.layers_checked} layer(s) could not be checked for "
                           f"{run.asset.reference}. Section 7 cannot be green until they are. "
                           f"{run.error}".strip(),
                      link=f"/assets/{run.asset_id}/overlay-results")
    return run


def _apply_dispute_layer(run):
    """A plot inside a known dispute area is flagged disputed (RUL-17)."""
    hits = [i for i in run.items if i.get("layer_kind") == "known_dispute" and i.get("outcome") == "inside"]
    if hits and not run.asset.disputed_flag:
        set_disputed(run.asset, actor=None, disputed=True,
                     reason=f"Inside known dispute area: {', '.join(h['layer_name'] for h in hits)}")


def overlay_verdict(run: OverlayRun):
    """Red if any layer flags inside; amber if any is near, missing or failed; else green."""
    reasons = []
    results = {str(r.pk): r for r in OverlayResult.objects.filter(
        pk__in=[i["result_id"] for i in run.items if i.get("result_id")]).select_related("layer_version__layer")}
    colour = "green"
    for item in run.items:
        if item["status"] != "checked":
            colour = "red" if colour == "red" else "amber"
            reasons.append({"verdict": "amber", "layer": item["layer_name"],
                            "message": f"{item['layer_name']}: not checked. {item.get('message', '')}".strip()})
            continue
        r = results.get(item["result_id"])
        if r is None:
            continue
        if r.outcome == "inside":
            colour = "red"
            pct = (r.affected_share * 100).quantize(Decimal("0.1"))
            reasons.append({"verdict": "red", "layer": item["layer_name"],
                            "message": f"Inside {item['layer_name']}: {pct}% of the plot "
                                       f"({r.affected_area_sqm} m2) is affected."})
        elif r.outcome == "near":
            if colour == "green":
                colour = "amber"
            reasons.append({"verdict": "amber", "layer": item["layer_name"],
                            "message": f"Near {item['layer_name']}: {r.distance_m} m away, within the "
                                       f"{r.buffer_m} m buffer."})
    if not run.items:
        colour = "amber"
        reasons.append({"verdict": "amber", "layer": "", "message": "No overlay layers are configured."})
    return colour, reasons


def recheck(asset: Asset, *, actor, trigger="recheck") -> OverlayRun:
    """Re-run the checks on the current boundary, e.g. after a layer update.
    New results sit next to the old ones (US-GEO-002 AC3)."""
    if asset.current_boundary_id is None:
        raise StateConflict("Save the plot boundary before running overlay checks.")
    run = OverlayRun.objects.create(asset=asset, country=asset.country, boundary_id=asset.current_boundary_id,
                                    trigger=trigger, requested_by=actor)
    record(actor=actor, action="overlay.recheck_requested", entity="asset", entity_id=asset.pk,
           country=asset.country, data={"run_id": run.pk, "trigger": trigger})
    return run_overlays(run)


# --------------------------------------------------------------------------- overlaps (FR-GEO-005)


def find_overlaps(boundary: BoundaryVersion) -> list[OverlapFlag]:
    """Store a flag for every other plot whose current boundary overlaps this one by more
    than the minimum area. Returns only the flags created now."""
    asset = boundary.asset
    min_sqm = float(setting("geo.overlap_min_sqm", asset.country))
    sql = """
        WITH b AS (SELECT geom FROM geo_boundary_version WHERE id = %s)
        SELECT a.id, o.id,
               ST_Area(ST_Intersection(o.geom, b.geom)::geography) AS inter,
               ST_Area(o.geom::geography) AS other_area
          FROM geo_asset a JOIN geo_boundary_version o ON o.id = a.current_boundary_id, b
         WHERE a.country_id = %s AND a.id <> %s AND ST_Intersects(o.geom, b.geom)
    """
    with connection.cursor() as cur:
        cur.execute(sql, [boundary.pk, asset.country_id, asset.pk])
        rows = [r for r in cur.fetchall() if r[2] >= min_sqm]
    flags_out = []
    others = {a.pk: a for a in Asset.objects.filter(pk__in=[r[0] for r in rows])}
    for other_id, other_bid, inter, other_area in rows:
        other = others[other_id]
        kind = "verified" if other.verified_at else "listed" if other.listed_at else "registered"
        flag, created = OverlapFlag.objects.get_or_create(
            boundary=boundary, other_boundary_id=other_bid, defaults=dict(
                asset=asset, country=asset.country, other_asset=other, other_kind=kind,
                overlap_area_sqm=_dec(inter),
                overlap_share=_dec(min(1, Decimal(str(inter)) / boundary.area_sqm), "0.0001"),
                other_overlap_share=_dec(min(1, inter / other_area) if other_area else 0, "0.0001")))
        if created:
            flags_out.append(flag)
    return flags_out


def check_overlaps(boundary: BoundaryVersion) -> list[OverlapFlag]:
    """FR-GEO-005: compare a new boundary with every other plot's current boundary in the
    country, publish overlap.flagged and alert staff (never the client)."""
    asset = boundary.asset
    flags_out = find_overlaps(boundary)
    for flag in flags_out:
        other, kind = flag.other_asset, flag.other_kind
        record(action="overlap.flagged", entity="asset", entity_id=asset.pk, country=asset.country,
               data={"flag_id": flag.pk, "other_asset_id": other.pk, "area_sqm": flag.overlap_area_sqm,
                     "other_kind": kind})
        publish("overlap.flagged", asset.pk, {
            "flag_id": flag.pk, "asset_id": asset.pk, "boundary_id": boundary.pk, "other_asset_id": other.pk,
            "other_kind": kind, "overlap_area_sqm": flag.overlap_area_sqm, "overlap_share": flag.overlap_share,
            "country": asset.country.code})
        # Staff only: the client is never told who owns the other plot (US-GEO-005).
        _notify_staff(asset.country, "geo.overlap_flagged", obj=flag,
                      subject=f"Overlap found on {asset.reference}",
                      body=f"{asset.reference} overlaps {kind} plot {other.reference} by "
                           f"{flag.overlap_area_sqm} m2 ({(flag.overlap_share * 100).quantize(Decimal('0.1'))}% "
                           "of the new plot). Check for a double sale before going on.",
                      link=f"/assets/{asset.pk}/overlaps")
    return flags_out


def resolve_overlap(flag: OverlapFlag, *, actor, outcome, note) -> OverlapFlag:
    """A case manager confirms a real overlap (it stays on section 7 as red) or
    dismisses it with a reason, e.g. the same plot registered twice."""
    if outcome not in ("confirmed", "dismissed"):
        raise Invalid("Outcome must be confirmed or dismissed.")
    if not (note or "").strip():
        raise Invalid("Give the reason for your decision.")
    flag.resolution, flag.resolution_note = outcome, note.strip()
    flag.resolved_by, flag.resolved_at = actor, timezone.now()
    state.transition(flag, "overlap_flag", outcome, actor=actor, event=f"overlap.{outcome}",
                     extra_fields=["resolution", "resolution_note", "resolved_by", "resolved_at"],
                     payload={"asset_id": flag.asset_id, "other_asset_id": flag.other_asset_id})
    return flag


# --------------------------------------------------------------------------- section 7 (FR-GEO-003)


def section7(asset: Asset) -> dict:
    """The proposed section 7 verdict for the current boundary: the latest
    overlay run plus overlap flags. Confirmed overlaps are red; open ones amber."""
    if asset.current_boundary_id is None:
        return {"proposed_verdict": None, "status": "no_boundary", "run": None, "reasons": [
            {"verdict": "amber", "layer": "", "message": "No plot boundary has been saved yet."}]}
    run = (OverlayRun.objects.filter(boundary_id=asset.current_boundary_id).order_by("-created_at").first())
    if run is None or run.status == "pending":
        return {"proposed_verdict": "amber", "status": "pending", "run": run, "reasons": [
            {"verdict": "amber", "layer": "", "message": "The overlay check has not finished."}]}
    colour, reasons = run.proposed_verdict or "amber", list(run.verdict_reasons)
    for f in OverlapFlag.objects.filter(boundary_id=asset.current_boundary_id, status__in=["open", "confirmed"]):
        if f.status == "confirmed":
            colour = "red"
            reasons.append({"verdict": "red", "layer": "overlap",
                            "message": f"Confirmed overlap of {f.overlap_area_sqm} m2 with another plot."})
        else:
            colour = "red" if colour == "red" else "amber"
            reasons.append({"verdict": "amber", "layer": "overlap",
                            "message": f"Possible overlap of {f.overlap_area_sqm} m2 with another plot, "
                                       "not yet reviewed."})
    if run.status != "completed" and colour == "green":
        colour = "amber"
    return {"proposed_verdict": colour, "status": run.status, "run": run, "reasons": reasons}


# --------------------------------------------------------------------------- overlay layers (FR-GEO-004)


def create_layer(*, actor, country, code, name, kind, description="", buffer_m=None, is_sample=False) -> OverlayLayer:
    flags.read_only_guard()
    if kind not in OverlayLayer.KINDS:
        raise Invalid(f"Kind must be one of {', '.join(OverlayLayer.KINDS)}.")
    if OverlayLayer.objects.filter(country=country, code=code).exists():
        raise DomainError("A layer with this code already exists in this country.", code="state-conflict")
    layer = OverlayLayer.objects.create(country=country, code=code, name=name, kind=kind, description=description,
                                        buffer_m=buffer_m, is_sample=is_sample, created_by=actor)
    record(actor=actor, action="overlay_layer.created", entity="overlay_layer", entity_id=layer.pk, country=country,
           data={"code": code, "kind": kind, "buffer_m": buffer_m, "is_sample": is_sample})
    return layer


def update_layer(layer: OverlayLayer, *, actor, **fields) -> OverlayLayer:
    allowed = {"name", "description", "buffer_m"}
    if set(fields) - allowed:
        raise Invalid("Only the name, description and buffer can be changed. Load a new version for new shapes.")
    for k, v in fields.items():
        setattr(layer, k, v)
    layer.save()
    record(actor=actor, action="overlay_layer.updated", entity="overlay_layer", entity_id=layer.pk,
           country=layer.country, data=fields)
    return layer


def set_layer_status(layer: OverlayLayer, *, actor, status, reason=""):
    if status == "active" and layer.current_version_id is None:
        raise StateConflict("Load a version of this layer before switching it on.")
    return state.transition(layer, "overlay_layer", status, actor=actor, reason=reason,
                            event="overlay_layer.status_changed")


def load_layer_version(layer: OverlayLayer, *, actor, data: bytes, filename="layer.geojson", source,
                       valid_from=None, srid=4326, note="") -> OverlayLayerVersion:
    """Validate the whole file first; on any error nothing is stored and the active
    version stays as it was (TC-GEO-004-02). The file is kept write-once as evidence."""
    flags.read_only_guard()
    if not (source or "").strip():
        raise Invalid("Say where the map comes from (the source), e.g. the agency and sheet.")
    if not filename.lower().endswith((".geojson", ".json")):
        raise Invalid("Upload the layer as GeoJSON (.geojson). Convert Shapefile or GeoPackage files first.",
                      code="layer-file-invalid")
    srid = G.check_srid(srid or 4326)
    features, used_srid = G.layer_features(data, srid)
    digest = hashlib.sha256(data).hexdigest()
    with transaction.atomic():
        layer = OverlayLayer.objects.select_for_update().get(pk=layer.pk)
        if layer.current_version_id and layer.current_version.sha256 == digest:
            raise DomainError("This file is the same as the active version.", code="state-conflict")
        from evidence.services import store, link

        ev = store(data=data, country=layer.country, uploaded_by=actor, content_type="application/geo+json",
                   original_name=filename, source="upload", description=f"Overlay layer {layer.code}")
        n = (layer.versions.aggregate(m=Max("version"))["m"] or 0) + 1
        v = OverlayLayerVersion.objects.create(
            layer=layer, country=layer.country, version=n, source=source.strip(), input_srid=used_srid,
            valid_from=valid_from, feature_count=len(features), sha256=digest, evidence=ev, note=note,
            loaded_by=actor)
        OverlayFeature.objects.bulk_create([
            OverlayFeature(layer_version=v, name=name, properties=props, geom=geom) for name, props, geom in features])
        link(ev, "geo_overlay_layer_version", v.pk, role="layer_file", by=actor)
        old = layer.current_version
        if old is not None:
            state.transition(old, "overlay_layer_version", "superseded", actor=actor,
                             payload={"layer_id": layer.pk, "by_version": n})
        layer.current_version = v
        layer.save(update_fields=["current_version"])
        if layer.status == "draft":
            state.transition(layer, "overlay_layer", "active", actor=actor, event="overlay_layer.status_changed")
        record(actor=actor, action="overlay_layer.version_loaded", entity="overlay_layer", entity_id=layer.pk,
               country=layer.country, data={"version": n, "features": len(features), "sha256": digest,
                                            "source": source, "previous_version": old.version if old else None})
        publish("overlay_layer.version_loaded", layer.pk, {"layer_id": layer.pk, "layer_version_id": v.pk,
                                                           "version": n, "country": layer.country.code})
    return v


def recheck_layer(layer: OverlayLayer, *, actor, asset_ids=None) -> list[OverlayRun]:
    """Re-check plots against the latest layers. Default: every plot with a boundary
    that is not yet verified (released reports keep their results)."""
    qs = Asset.objects.filter(country=layer.country, current_boundary__isnull=False)
    if asset_ids:
        qs = qs.filter(pk__in=asset_ids)
    else:
        qs = qs.filter(verified_at__isnull=True)
    return [recheck(a, actor=actor, trigger="layer_updated") for a in qs.order_by("created_at")]


# --------------------------------------------------------------------------- satellite images (FR-GEO-006)


def _rings(geom):
    return [list(ring.coords) for poly in geom for ring in poly]


def _bbox(asset):
    if asset.current_boundary_id:
        return asset.current_boundary.geom.extent
    if asset.location is not None:
        x, y = asset.location.x, asset.location.y
        return (x - 0.0005, y - 0.0005, x + 0.0005, y + 0.0005)
    return None


def _unavailable(asset, *, purpose, reason, actor=None, report_id=None):
    img = SatelliteImage.objects.create(asset=asset, country=asset.country, boundary=asset.current_boundary,
                                        purpose=purpose, status="unavailable", provider="-", gap_reason=reason,
                                        report_id=report_id, requested_by=actor)
    record(actor=actor, action="satellite_image.unavailable", entity="asset", entity_id=asset.pk,
           country=asset.country, data={"reason": reason, "purpose": purpose})
    return img


def fetch_image(asset: Asset, *, actor=None, purpose="on_request", report_id=None, before=None,
                apply_changes=None) -> SatelliteImage:
    """Fetch the newest usable scene, draw the boundary and store it as evidence."""
    if not flags.enabled(SATELLITE_FLAG, asset.country):
        return _unavailable(asset, purpose=purpose, actor=actor, report_id=report_id,
                            reason="Satellite imagery is not switched on in this country yet.")
    bbox = _bbox(asset)
    if bbox is None:
        return _unavailable(asset, purpose=purpose, actor=actor, report_id=report_id,
                            reason="No boundary or location is saved for this property.")
    sat = _adapter("satellite")
    max_cloud = float(setting("geo.imagery_max_cloud_pct", asset.country))
    try:
        scene = sat.latest_scene(asset_id=asset.pk, bbox=bbox, max_cloud=max_cloud, before=before)
    except ServiceUnavailable as exc:
        return _unavailable(asset, purpose=purpose, actor=actor, report_id=report_id,
                            reason=f"The imagery provider could not be reached: {exc}")
    if scene is None:
        return _unavailable(asset, purpose=purpose, actor=actor, report_id=report_id,
                            reason=f"No clear image (under {max_cloud:.0f}% cloud) of this plot was found.")
    if apply_changes is None:
        apply_changes = SatelliteImage.objects.filter(asset=asset, status="available").exists()
    built, veg = sat.indices(asset_id=asset.pk, scene=scene, apply_changes=apply_changes)
    rings = _rings(asset.current_boundary.geom) if asset.current_boundary_id else []
    svg = sat.render(scene=scene, rings=rings, bbox=bbox, label=f"{asset.reference} | ")
    from evidence.services import link, store

    with transaction.atomic():
        ev = store(data=svg, country=asset.country, uploaded_by=actor, content_type="image/svg+xml",
                   original_name=f"{asset.reference}-{scene['captured_on']:%Y%m%d}.svg", source="provider",
                   description=f"Satellite image of {asset.reference}, {scene['captured_on']:%d %b %Y}")
        img = SatelliteImage.objects.create(
            asset=asset, country=asset.country, boundary=asset.current_boundary, purpose=purpose, status="available",
            provider=scene["provider"], scene_id=scene["scene_id"], captured_on=scene["captured_on"],
            cloud_cover=_dec(scene["cloud_cover"]), resolution_m=_dec(scene["resolution_m"]),
            built_up_index=_dec(built, "0.0001"), vegetation_index=_dec(veg, "0.0001"), evidence=ev,
            report_id=report_id, requested_by=actor)
        link(ev, "asset", asset.pk, role="satellite_image", by=actor)
        if report_id:
            link(ev, "report", report_id, role="satellite_image", by=actor)
        record(actor=actor, action="satellite_image.fetched", entity="asset", entity_id=asset.pk,
               country=asset.country, data={"image_id": img.pk, "scene_id": img.scene_id,
                                            "captured_on": img.captured_on, "purpose": purpose})
    return img


def image_for_report(asset_id, *, report_id=None, actor=None) -> dict:
    """For RPT: the image with boundary and date for section 4, or the gap text (US-GEO-006)."""
    asset = Asset.objects.select_related("current_boundary", "country").get(pk=asset_id)
    if asset.current_boundary_id is None:
        img = _unavailable(asset, purpose="report", actor=actor, report_id=report_id,
                           reason="No plot boundary was saved, so no image with the boundary can be shown.")
    else:
        img = fetch_image(asset, actor=actor, purpose="report", report_id=report_id)
    if img.status == "available":
        return {"available": True, "image_id": img.pk, "evidence_id": img.evidence_id,
                "captured_on": img.captured_on, "provider": img.provider, "scene_id": img.scene_id,
                "section_4_text": f"Satellite image dated {img.captured_on:%d %B %Y} ({img.provider}), "
                                  "with the surveyed boundary drawn.", "gap": ""}
    gap = f"No satellite image is included. {img.gap_reason}"
    return {"available": False, "image_id": img.pk, "evidence_id": None, "captured_on": None, "provider": "",
            "scene_id": "", "section_4_text": gap, "gap": gap}


# --------------------------------------------------------------------------- monitoring (FR-GEO-007, RUL-13)


def enrol(asset: Asset, *, reason, source_id=None, actor=None, baseline_before=None) -> MonitoringEnrolment:
    """Start watching a plot. Idempotent per asset, reason and source."""
    if reason not in MonitoringEnrolment.REASONS:
        raise Invalid(f"Reason must be one of {', '.join(MonitoringEnrolment.REASONS)}.")
    existing = MonitoringEnrolment.objects.filter(asset=asset, reason=reason, source_id=source_id,
                                                  status="active").first()
    if existing:
        return existing
    with transaction.atomic():
        e = MonitoringEnrolment.objects.create(asset=asset, country=asset.country, reason=reason,
                                               source_id=source_id, enrolled_by=actor)
        if flags.enabled(SATELLITE_FLAG, asset.country):
            base = fetch_image(asset, actor=actor, purpose="monitoring", apply_changes=False,
                               before=baseline_before)
            if base.status == "available":
                e.baseline_image = base
                e.save(update_fields=["baseline_image"])
        record(actor=actor, action="monitoring.enrolled", entity="asset", entity_id=asset.pk, country=asset.country,
               data={"enrolment_id": e.pk, "reason": reason, "source_id": source_id})
        publish("monitoring.enrolled", asset.pk, {"asset_id": asset.pk, "enrolment_id": e.pk, "reason": reason,
                                                  "source_id": source_id})
    return e


def end_enrolment(e: MonitoringEnrolment, *, actor=None, reason="") -> MonitoringEnrolment:
    e.ended_at, e.ended_reason = timezone.now(), reason
    return state.transition(e, "monitoring_enrolment", "ended", actor=actor, reason=reason,
                            event="monitoring.ended", extra_fields=["ended_at", "ended_reason"],
                            payload={"asset_id": e.asset_id})


def end_for_source(source_id, *, reason="", actor=None):
    for e in MonitoringEnrolment.objects.filter(source_id=source_id, status="active"):
        end_enrolment(e, actor=actor, reason=reason)


def change_between(prev: SatelliteImage, new: SatelliteImage):
    """Change score and kind between two images of the same plot."""
    db = Decimal(new.built_up_index or 0) - Decimal(prev.built_up_index or 0)
    dv = Decimal(new.vegetation_index or 0) - Decimal(prev.vegetation_index or 0)
    score = max(abs(db), abs(dv))
    if db > 0 and db >= -dv:
        kind = "new_structure"
    elif dv < 0:
        kind = "clearing"
    else:
        kind = "other"
    return _dec(score, "0.0001"), kind


def check_enrolment(e: MonitoringEnrolment, *, before=None, actor=None):
    """Compare the newest scene with the baseline. Returns the alert raised, or None."""
    asset = e.asset
    e.last_checked_at = timezone.now()
    e.save(update_fields=["last_checked_at"])
    if e.baseline_image is None:
        base = fetch_image(asset, actor=actor, purpose="monitoring", before=before, apply_changes=False)
        if base.status == "available":
            e.baseline_image = base
            e.save(update_fields=["baseline_image"])
        return None
    sat = _adapter("satellite")
    bbox = _bbox(asset)
    try:
        scene = sat.latest_scene(asset_id=asset.pk, bbox=bbox,
                                 max_cloud=float(setting("geo.imagery_max_cloud_pct", asset.country)), before=before)
    except ServiceUnavailable:
        return None
    if scene is None or scene["scene_id"] == e.baseline_image.scene_id or (
            e.baseline_image.captured_on and scene["captured_on"] <= e.baseline_image.captured_on):
        return None  # no newer imagery yet
    if MonitoringAlert.objects.filter(asset=asset, status__in=["open", "under_review"],
                                      new_image__scene_id=scene["scene_id"]).exists():
        return None
    new = fetch_image(asset, actor=actor, purpose="monitoring", before=before, apply_changes=True)
    if new.status != "available":
        return None
    score, kind = change_between(e.baseline_image, new)
    threshold = Decimal(str(setting("geo.monitoring_change_threshold", asset.country)))
    if score < threshold:
        e.baseline_image = new
        e.save(update_fields=["baseline_image"])
        return None
    return raise_alert(e, e.baseline_image, new, score=score, kind=kind, threshold=threshold)


def raise_alert(e, prev, new, *, score, kind, threshold) -> MonitoringAlert:
    asset = e.asset
    with transaction.atomic():
        alert = MonitoringAlert.objects.create(
            asset=asset, country=asset.country, enrolment=e, previous_image=prev, new_image=new,
            previous_date=prev.captured_on, new_date=new.captured_on, change_score=score, threshold=threshold,
            change_kind=kind)
        sources = MonitoringEnrolment.objects.filter(asset=asset, status="active")
        payload = {
            "alert_id": alert.pk, "asset_id": asset.pk, "change_kind": kind, "change_score": str(score),
            "previous_date": prev.captured_on, "new_date": new.captured_on, "country": asset.country.code,
            "listing_ids": [s.source_id for s in sources if s.reason == "listing" and s.source_id],
            "project_ids": [s.source_id for s in sources if s.reason == "project" and s.source_id]}
        record(action="monitoring.alert_raised", entity="monitoring_alert", entity_id=alert.pk,
               country=asset.country, data=payload)
        publish("monitoring.alert_raised", alert.pk, payload)
    words = {"new_structure": "new building work", "clearing": "land clearing", "other": "a change"}[kind]
    _notify_staff(asset.country, "geo.monitoring_alert", obj=alert,
                  subject=f"Monitoring alert on {asset.reference}",
                  body=f"Satellite images of {asset.reference} from {prev.captured_on:%d %b %Y} and "
                       f"{new.captured_on:%d %b %Y} show {words} (score {score}). Check it and resolve the alert.",
                  link=f"/monitoring-alerts/{alert.pk}")
    if asset.owner_id:
        from notifications.services import notify

        notify(asset.owner, "geo.monitoring_alert_client", subject=f"We saw a change on {asset.name or asset.reference}",
               body=f"New satellite images show {words} on your property. A case manager is checking it. "
                    "We will tell you what we find.", link=f"/assets/{asset.pk}", needs_action=False,
               subject_obj=alert)
    return alert


def run_monitoring(*, country=None, before=None, asset_ids=None, actor=None) -> dict:
    """The weekly schedule (geo.monitor_changes in 02 7.12). Returns a summary."""
    qs = MonitoringEnrolment.objects.filter(status="active").select_related("asset", "asset__country",
                                                                            "baseline_image")
    if country is not None:
        qs = qs.filter(country=country)
    if asset_ids:
        qs = qs.filter(asset_id__in=asset_ids)
    summary = {"checked": 0, "alerts": 0, "skipped_flag_off": 0, "alert_ids": []}
    seen = set()
    for e in qs.order_by("created_at"):
        if e.asset_id in seen:
            continue  # one check per plot even when several reasons watch it
        seen.add(e.asset_id)
        if not flags.enabled(SATELLITE_FLAG, e.country):
            summary["skipped_flag_off"] += 1
            continue
        alert = check_enrolment(e, before=before, actor=actor)
        summary["checked"] += 1
        if alert is not None:
            summary["alerts"] += 1
            summary["alert_ids"].append(str(alert.pk))
    return summary


def take_alert(alert: MonitoringAlert, *, actor) -> MonitoringAlert:
    alert.assigned_to = actor
    return state.transition(alert, "monitoring_alert", "under_review", actor=actor, extra_fields=["assigned_to"],
                            payload={"asset_id": alert.asset_id})


def resolve_alert(alert: MonitoringAlert, *, actor, resolution, note, evidence=None) -> MonitoringAlert:
    """Close an alert with what was found. Only then can a suspended listing go live again (RUL-13)."""
    if resolution not in MonitoringAlert.RESOLUTIONS:
        raise Invalid(f"Resolution must be one of {', '.join(MonitoringAlert.RESOLUTIONS)}.")
    if not (note or "").strip():
        raise Invalid("Say what was found.")
    if resolution == "change_confirmed" and evidence is None:
        raise Invalid("Attach the site photo or report that confirms the change.", code="evidence-required")
    if evidence is not None and evidence.country_id != alert.country_id:
        raise Forbidden("The evidence belongs to another country.")
    with transaction.atomic():
        alert.resolution, alert.resolution_note = resolution, note.strip()
        alert.resolution_evidence = evidence
        alert.resolved_by, alert.resolved_at = actor, timezone.now()
        state.transition(alert, "monitoring_alert", "resolved", actor=actor, extra_fields=["resolution", "resolution_note", "resolution_evidence", "resolved_by",
                                       "resolved_at"], payload={"asset_id": alert.asset_id})
        if evidence is not None:
            from evidence.services import link

            link(evidence, "monitoring_alert", alert.pk, role="resolution", by=actor)
        if alert.enrolment_id and alert.enrolment.status == "active":
            alert.enrolment.baseline_image = alert.new_image  # compare future images with the new state
            alert.enrolment.save(update_fields=["baseline_image"])
        still_open = MonitoringAlert.objects.filter(asset=alert.asset, status__in=["open", "under_review"]).count()
        payload = {"alert_id": alert.pk, "asset_id": alert.asset_id, "resolution": resolution,
                   "open_alerts_on_asset": still_open, "country": alert.country.code}
        publish("monitoring.alert_resolved", alert.pk, payload)
    return alert


# --------------------------------------------------------------------------- digital addresses (FR-GEO-008)


def resolve_digital_address(country, code: str) -> dict:
    """Address to coordinates where the service allows. Never guesses: when the
    service is down the caller saves the address as text only (US-GEO-008)."""
    flags.require(ADDRESS_FLAG, country)
    resolver = _adapter("address_resolver")
    norm = resolver.normalise(code)
    if norm is None:
        raise Invalid("This is not a valid digital address. It looks like GA-183-8164.", code="address-invalid")
    try:
        hit = resolver.resolve(norm)
    except ServiceUnavailable:
        return {"status": "unavailable", "code": norm, "location": None, "accuracy_m": None,
                "message": "The address service is not available now. Save the address as text; "
                           "no coordinates will be guessed."}
    if hit is None:
        return {"status": "not_found", "code": norm, "location": None, "accuracy_m": None,
                "message": "The address service does not know this address. Check it, or save it as text."}
    return {"status": "resolved", "code": hit["code"], "location": {"lng": hit["lng"], "lat": hit["lat"]},
            "accuracy_m": hit["accuracy_m"], "message": "Check the point on the map and confirm it is right."}
