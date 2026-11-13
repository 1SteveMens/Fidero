"""US-GEO-001, FR-GEO-001: plot boundaries as polygons. TC-GEO-001-01, TC-GEO-001-02."""
from decimal import Decimal

import pytest
from django.db import IntegrityError, InternalError, connection, transaction

from core.errors import Invalid
from geo import services
from geo.models import Asset, BoundaryVersion
from geo.tests.conftest import LAT, LNG, rect, square, topics


def test_surveyor_coordinates_saved_as_valid_polygon(make_asset, people):
    """TC-GEO-001-01: a valid polygon is stored in SRID 4326 with area in m2 and acres."""
    asset = make_asset()
    bv = services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates", coordinates=square())
    assert bv.geom.srid == 4326 and bv.geom.valid
    assert bv.version == 1 and bv.source == "surveyor_coordinates"
    assert Decimal("1000") < bv.area_sqm < Decimal("1300")  # about 33 m x 33 m
    assert abs(bv.area_acres - bv.area_sqm / Decimal("4046.8564224")) < Decimal("0.001")
    asset.refresh_from_db()
    assert asset.current_boundary_id == bv.pk
    assert asset.location_source == "boundary" and asset.location is not None
    ev = topics("asset.boundary_saved")[-1]
    assert ev.payload["boundary_id"] == str(bv.pk)


def test_new_version_never_edits_the_old(make_asset, people):
    """FR-GEO-001: a new boundary is a new version; the old one is kept."""
    asset = make_asset(ring=square())
    v1 = asset.current_boundary
    v2 = services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates",
                                coordinates=square(size=0.0004))
    asset.refresh_from_db()
    assert v2.version == 2 and asset.current_boundary_id == v2.pk
    assert BoundaryVersion.objects.filter(pk=v1.pk).exists()
    with pytest.raises((IntegrityError, InternalError, Exception)), transaction.atomic():
        BoundaryVersion.objects.filter(pk=v1.pk).update(note="edited")


@pytest.mark.parametrize("coords,code", [
    ([[LNG, LAT], [LNG + 0.0003, LAT + 0.0003], [LNG + 0.0003, LAT], [LNG, LAT + 0.0003], [LNG, LAT]],
     "geometry-self-intersecting"),
    ([[LNG, LAT], [LNG + 0.0003, LAT], [LNG + 0.0003, LAT + 0.0003], [LNG, LAT + 0.0003]], "geometry-unclosed"),
    ([[LNG, LAT], [LNG + 0.0003, LAT], [LNG, LAT]], "geometry-invalid"),
    ([[LAT, LNG], [LAT + 0.0003, LNG], [LAT + 0.0003, LNG + 0.0003], [LAT, LNG + 0.0003], [LAT, LNG]],
     "geometry-outside-country"),
])
def test_invalid_coordinates_rejected_and_nothing_saved(make_asset, people, coords, code):
    """TC-GEO-001-02: self-intersecting, open ring, under 3 points, wrong coordinate order."""
    asset = make_asset()
    before = BoundaryVersion.objects.count()
    with pytest.raises(Invalid) as exc:
        services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates", coordinates=coords)
    assert exc.value.code == code
    assert BoundaryVersion.objects.count() == before
    asset.refresh_from_db()
    assert asset.current_boundary_id is None


def test_swapped_coordinates_get_a_plain_message(make_asset, people):
    """TC-GEO-001-02: wrong coordinate order is named as such."""
    asset = make_asset()
    swapped = [[y, x] for x, y in square()]
    with pytest.raises(Invalid) as exc:
        services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates", coordinates=swapped)
    assert "swapped" in exc.value.detail


def test_projected_coordinates_are_transformed(make_asset, people):
    """FR-GEO-001: surveyor coordinates in the Ghana Metre Grid (EPSG:25000) are stored in WGS 84."""
    asset = make_asset()
    with connection.cursor() as cur:
        cur.execute("SELECT ST_X(p), ST_Y(p) FROM (SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), "
                    "25000) p) s", [LNG, LAT])
        x, y = cur.fetchone()
    ring = rect(x, y, x + 30, y + 30)
    bv = services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates", coordinates=ring,
                                srid=25000)
    assert bv.input_srid == 25000 and bv.geom.srid == 4326
    assert Decimal("850") < bv.area_sqm < Decimal("950")  # 30 m x 30 m
    assert abs(bv.centroid.x - LNG) < 0.001 and abs(bv.centroid.y - LAT) < 0.001


def test_projected_values_without_a_system_are_refused(make_asset, people):
    """TC-GEO-001-02: metres given as degrees are refused with a plain message."""
    asset = make_asset()
    with pytest.raises(Invalid) as exc:
        services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates",
                               coordinates=rect(350000, 740000, 350030, 740030))
    assert exc.value.code == "projection-invalid"


def test_implausible_area_refused(make_asset, people):
    """FR-GEO-001: a tiny shape is almost always a unit mistake."""
    asset = make_asset()
    with pytest.raises(Invalid) as exc:
        services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates",
                               coordinates=square(size=0.00001))
    assert exc.value.code == "geometry-implausible"


def test_geojson_and_drawn_points(make_asset, people):
    """FR-GEO-001: GeoJSON upload and points drawn on a map (closed for the user)."""
    asset = make_asset()
    feature = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [square()]}}
    bv = services.save_boundary(asset, actor=people["cm"], source="geojson_upload", geojson=feature)
    assert bv.version == 1
    pts = [{"lng": x, "lat": y} for x, y in square(dx=0.001)[:-1]]
    bv2 = services.save_boundary(asset, actor=people["client"], source="drawn", points=pts)
    assert bv2.version == 2 and bv2.geom.valid
    with pytest.raises(Invalid):
        services.save_boundary(asset, actor=people["cm"], source="geojson_upload",
                               geojson={"type": "Point", "coordinates": [LNG, LAT]})


def test_database_refuses_foreign_boundary(make_asset):
    """dbsql: an asset can only use one of its own boundary versions."""
    a = make_asset(ring=square())
    b = make_asset(ring=square(dx=0.002))
    with pytest.raises(IntegrityError), transaction.atomic():
        Asset.objects.filter(pk=a.pk).update(current_boundary=b.current_boundary_id)


def test_boundary_api_roles(make_asset, people, api):
    """02 7.4 PUT /v1/assets/{id}/boundary: SV assigned, CM; the owner may only draw; others get 404 or 403."""
    asset = make_asset()
    url = f"/v1/assets/{asset.pk}/boundary"
    body = {"source": "surveyor_coordinates", "coordinates": square()}
    assert api(people["surveyor"]).put(url, body, format="json").status_code == 404  # not assigned: cannot see it
    services.grant_access(asset, people["surveyor"], role="SV", actor=people["cm"])
    r = api(people["surveyor"]).put(url, body, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["version"] == 1 and r.json()["geometry"]["type"] == "MultiPolygon"
    assert api(people["client"]).put(url, body, format="json").status_code == 403
    pts = [{"lng": x, "lat": y} for x, y in square()[:-1]]
    r = api(people["client"]).put(url, {"source": "drawn", "points": pts}, format="json")
    assert r.status_code == 201, r.content
    assert api(people["client2"]).put(url, body, format="json").status_code == 404
    bad = api(people["cm"]).put(url, {"source": "surveyor_coordinates", "coordinates": square()[:-1]}, format="json")
    assert bad.status_code == 422 and bad.json()["code"] == "geometry-unclosed"
    r = api(people["client"]).get(url)
    assert r.status_code == 200 and r.json()["type"] == "Feature" and r.json()["properties"]["version"] == 2
    r = api(people["cm"]).get(f"/v1/assets/{asset.pk}/boundaries")
    assert [b["version"] for b in r.json()] == [2, 1]


def test_read_only_mode_blocks_boundary_saves(make_asset, people, settings):
    """06 2.6: maintenance.read_only pauses every write."""
    asset = make_asset()
    settings.TENMINA_FLAG_OVERRIDES = {"maintenance.read_only": True}
    from core.errors import DomainError

    with pytest.raises(DomainError) as exc:
        services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates", coordinates=square())
    assert exc.value.code == "maintenance-read-only"
