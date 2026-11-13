"""GEO demo data. ALL SHAPES ARE FICTIONAL SAMPLE DATA near Accra, not real maps.

Layers: a government acquisition, a forest reserve, a road reserve, a
waterway and a known dispute area, each one simple rectangle. Plots show
every outcome: clear (green), inside an acquisition (red), near a road
reserve (amber), overlapping a verified plot (amber, overlap flag), inside a
dispute area (red, disputed), plus a house and a managed property, and
monitoring with one open and one resolved alert.

Like the other seeds, rows are written directly: they are not audit entries
and publish no events. The checks themselves run the same service code.
"""
import hashlib
import json
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

SAMPLE = "Sample data for demonstration. Not a real map."


def _rect(minx, miny, maxx, maxy):
    return [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]


def _fc(name, ring):
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": name, "note": SAMPLE},
         "geometry": {"type": "Polygon", "coordinates": [ring]}}]}).encode()


LAYERS = [
    ("gh-sample-acquisitions", "Government acquisitions (sample)", "government_acquisition",
     "Sample Acquisition Area A", _rect(-0.160, 5.760, -0.150, 5.768)),
    ("gh-sample-forest", "Forest reserves (sample)", "forest_reserve",
     "Sample Forest Reserve", _rect(-0.140, 5.770, -0.130, 5.780)),
    ("gh-sample-road-reserve", "Road reserves (sample)", "road_reserve",
     "Sample Ring Road reserve", _rect(-0.170, 5.7500, -0.120, 5.7504)),
    ("gh-sample-waterways", "Waterways and wetlands (sample)", "waterway",
     "Sample Stream", _rect(-0.1450, 5.740, -0.1447, 5.765)),
    ("gh-sample-disputes", "Known dispute areas (sample)", "known_dispute",
     "Sample disputed family land", _rect(-0.125, 5.755, -0.120, 5.760)),
]

# key, owner key, type, name, locality, plot number, ghana post gps, ring or None, location
PLOTS = [
    ("clear", "client", "plot", "Plot at Sample Hills", "Oyarifa (sample)", "SMP-001", "GA-492-1150",
     _rect(-0.1350, 5.7600, -0.1347, 5.7603), None),
    ("acquired", "client", "plot", "Plot near the acquisition", "Adenta (sample)", "SMP-002", "",
     _rect(-0.1550, 5.7640, -0.1547, 5.7643), None),
    ("near_road", "client2", "plot", "Roadside plot", "Ashaley Botwe (sample)", "SMP-003", "",
     _rect(-0.1380, 5.7508, -0.1377, 5.7511), None),
    ("verified", "seller", "plot", "Ato Estates plot 14", "Oyarifa (sample)", "SMP-014", "",
     _rect(-0.1320, 5.7620, -0.1314, 5.7626), None),
    ("overlapping", "client2", "plot", "Plot offered by a family", "Oyarifa (sample)", "SMP-015", "",
     _rect(-0.1317, 5.7623, -0.1311, 5.7629), None),
    ("disputed", "seller", "plot", "Ato Estates plot 31", "Kweiman (sample)", "SMP-031", "",
     _rect(-0.1230, 5.7570, -0.1227, 5.7573), None),
    ("house", "client", "building", "Family house", "East Legon (sample)", "", "GA-183-8164", None,
     {"lng": -0.1520, "lat": 5.6350}),
    ("managed", "client2", "managed_property", "Rental flat", "Spintex (sample)", "", "", None,
     {"lng": -0.1050, "lat": 5.6400}),
]

GHANA_BOX = _rect(-3.30, 4.70, 1.20, 11.20)  # approximate bounding box [TO VERIFY]
LISTING_ID = "0192f3c1-0000-7000-8000-00000000a001"  # sample listing id until LST seeds its own
PROJECT_ID = "0192f3c1-0000-7000-8000-00000000b001"  # sample project id until BLD seeds its own


def _evidence(data, country, *, by, content_type, name, source, description):
    """Write-once evidence for seed rows, stored the same way as evidence.services.store."""
    from core.adapters import get_adapter
    from core.ids import uuid7
    from evidence.models import Evidence

    eid = uuid7()
    key = f"{country.code}/{timezone.now():%Y/%m}/{eid}"
    get_adapter("evidence_store").put(key, data)
    return Evidence.objects.create(id=eid, country=country, sha256=hashlib.sha256(data).hexdigest(),
                                   size_bytes=len(data), content_type=content_type, original_name=name,
                                   storage_key=key, source=source, uploaded_by=by, scan_status="clean",
                                   description=description)


def _layer(gh, admin, code, name, kind, feature, ring):
    from . import geometry as G
    from .models import OverlayFeature, OverlayLayer, OverlayLayerVersion

    layer, _ = OverlayLayer.objects.get_or_create(country=gh, code=code, defaults=dict(
        name=name, kind=kind, description=SAMPLE, is_sample=True, status="active", created_by=admin))
    if layer.current_version_id is None:
        data = _fc(feature, ring)
        features, srid = G.layer_features(data)
        ev = _evidence(data, gh, by=admin, content_type="application/geo+json", name=f"{code}.geojson",
                       source="upload", description=f"Overlay layer {code} (sample)")
        v = OverlayLayerVersion.objects.create(
            layer=layer, country=gh, version=1, source="Tenmina sample data, drawn for demonstration [not a real map]",
            input_srid=srid, valid_from=date(2026, 1, 1), feature_count=len(features),
            sha256=hashlib.sha256(data).hexdigest(), evidence=ev, note=SAMPLE, loaded_by=admin)
        OverlayFeature.objects.bulk_create([OverlayFeature(layer_version=v, name=n, properties=p, geom=g)
                                            for n, p, g in features])
        layer.current_version = v
        layer.save(update_fields=["current_version"])
    return layer


def _asset(gh, people, owner_key, typ, name, locality, plot_no, gps, loc):
    from django.contrib.gis.geos import Point

    from . import services
    from .models import Asset

    owner = people[owner_key]
    asset = Asset.objects.filter(country=gh, name=name, owner=owner).first()
    if asset is None:
        point = Point(loc["lng"], loc["lat"], srid=4326) if loc else None
        asset = Asset.objects.create(
            country=gh, reference=services._next_reference(gh), type=typ, name=name, owner=owner,
            region="Greater Accra", locality=locality, plot_number=plot_no, ghana_post_gps=gps, location=point,
            location_source=("digital_address_confirmed" if point and gps else "manual" if point else "none"),
            created_by=owner)
    return asset


def _boundary(asset, ring, surveyor, cm):
    """A surveyed boundary, its overlap flags and overlay checks, without events."""
    from . import services
    from .models import AssetAccess, BoundaryVersion, OverlayRun

    AssetAccess.objects.get_or_create(asset=asset, person=surveyor, role="SV", revoked_at=None,
                                      defaults={"country": asset.country, "granted_by": cm})
    geom, srid = services.parse_boundary(source="surveyor_coordinates", coordinates=ring)
    area, perimeter, centroid = services._measure(geom)
    bv = BoundaryVersion.objects.create(
        asset=asset, country=asset.country, version=1, geom=geom, source="surveyor_coordinates", input_srid=srid,
        area_sqm=services._dec(area), area_acres=services._dec(area / Decimal("4046.8564224"), "0.0001"),
        perimeter_m=services._dec(perimeter), centroid=centroid, point_count=geom.num_coords,
        note="Sample survey [not a real plot]", captured_by=surveyor)
    asset.current_boundary = bv
    if asset.location is None:
        asset.location, asset.location_source = centroid, "boundary"
    asset.save()
    services.find_overlaps(bv)
    run = OverlayRun.objects.create(asset=asset, country=asset.country, boundary=bv, trigger="boundary_saved",
                                    requested_by=surveyor)
    run.status = services.evaluate_run(run)
    run.save()
    hits = [i["layer_name"] for i in run.items
            if i.get("layer_kind") == "known_dispute" and i.get("outcome") == "inside"]
    if hits:
        asset.disputed_flag, asset.disputed_reason = True, f"Inside known dispute area: {', '.join(hits)}"
        asset.save(update_fields=["disputed_flag", "disputed_reason"])


def _image(asset, *, purpose, before, by, changes=None):
    from . import services
    from .adapters import FakeSatellite
    from .models import SatelliteImage

    sat = services._adapter("satellite")
    # Sample imagery: any cloud cover, so the demo always has images on fixed dates.
    scene = sat.latest_scene(asset_id=asset.pk, bbox=services._bbox(asset), max_cloud=100.0, before=before)
    if scene is None:
        return None
    if changes:
        FakeSatellite.CHANGES[str(asset.pk)] = changes
    try:
        built, veg = sat.indices(asset_id=asset.pk, scene=scene, apply_changes=bool(changes))
    finally:
        FakeSatellite.CHANGES.pop(str(asset.pk), None)
    svg = sat.render(scene=scene, rings=services._rings(asset.current_boundary.geom), bbox=services._bbox(asset),
                     label=f"{asset.reference} | ")
    ev = _evidence(svg, asset.country, by=by, content_type="image/svg+xml",
                   name=f"{asset.reference}-{scene['captured_on']:%Y%m%d}.svg", source="provider",
                   description=f"Satellite image of {asset.reference} (sample)")
    return SatelliteImage.objects.create(
        asset=asset, country=asset.country, boundary=asset.current_boundary, purpose=purpose, status="available",
        provider=scene["provider"], scene_id=scene["scene_id"], captured_on=scene["captured_on"],
        cloud_cover=services._dec(scene["cloud_cover"]), resolution_m=services._dec(scene["resolution_m"]),
        built_up_index=services._dec(built, "0.0001"), vegetation_index=services._dec(veg, "0.0001"), evidence=ev,
        requested_by=by)


def _watch(asset, *, reason, source_id, cm, change, resolved):
    from . import services
    from .models import MonitoringAlert, MonitoringEnrolment

    e, _ = MonitoringEnrolment.objects.get_or_create(
        asset=asset, reason=reason, source_id=source_id, status="active",
        defaults={"country": asset.country, "enrolled_by": cm})
    if MonitoringAlert.objects.filter(asset=asset).exists():
        return
    today = date.today()
    base = _image(asset, purpose="monitoring", before=today - timedelta(days=45), by=cm)
    new = _image(asset, purpose="monitoring", before=today, by=cm, changes=change)
    if base is None or new is None or base.scene_id == new.scene_id:
        return
    score, kind = services.change_between(base, new)
    alert = MonitoringAlert(
        asset=asset, country=asset.country, enrolment=e, previous_image=base, new_image=new,
        previous_date=base.captured_on, new_date=new.captured_on, change_score=score,
        threshold=Decimal(str(services.setting("geo.monitoring_change_threshold", asset.country))),
        change_kind=kind, assigned_to=cm)
    if resolved:
        alert.status, alert.resolution, alert.resolved_by, alert.resolved_at = (
            "resolved", "change_explained", cm, timezone.now())
        alert.resolution_note = "The contractor started the foundation as planned. Matches milestone 1."
        e.baseline_image = new
    else:
        e.baseline_image = base
    alert.save()
    e.last_checked_at = timezone.now()
    e.save(update_fields=["baseline_image", "last_checked_at"])


def run(ctx):
    from django.contrib.gis.geos import MultiPolygon, Polygon

    from administration import flags
    from countries.models import Country

    from . import services
    from .models import CountryExtent

    gh = ctx.get("gh") or Country.objects.get(code="GH")
    people = ctx["people"]
    admin, surveyor, cm = people["admin"], people["surveyor"], people["cm"]

    CountryExtent.objects.get_or_create(country=gh, defaults={
        "geom": MultiPolygon(Polygon(GHANA_BOX), srid=4326), "loaded_by": admin,
        "label": "Ghana, approximate bounding box [TO VERIFY]"})

    layers = {code: _layer(gh, admin, code, name, kind, feature, ring)
              for code, name, kind, feature, ring in LAYERS}

    assets = {}
    for key, owner_key, typ, name, locality, plot_no, gps, ring, loc in PLOTS:
        asset = _asset(gh, people, owner_key, typ, name, locality, plot_no, gps, loc)
        if key == "verified" and not asset.verified_at:
            asset.verified_at = timezone.now() - timedelta(days=200)
            asset.save(update_fields=["verified_at"])
        if ring and asset.current_boundary_id is None:
            _boundary(asset, ring, surveyor, cm)
            asset.refresh_from_db()
        assets[key] = asset

    if flags.enabled(services.SATELLITE_FLAG, gh):
        if not assets["clear"].satellite_images.filter(purpose="report").exists():
            _image(assets["clear"], purpose="report", before=None, by=cm)
        _watch(assets["verified"], reason="listing", source_id=LISTING_ID, cm=cm, change=(0.30, -0.25),
               resolved=False)
        _watch(assets["near_road"], reason="project", source_id=PROJECT_ID, cm=cm, change=(0.20, -0.05),
               resolved=True)
    ctx["geo"] = {"assets": assets, "layers": layers}
