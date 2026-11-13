"""US-GEO-002, 003, 004 (FR-GEO-002, 003, 004): overlay checks, inside/near/clear, the proposed
section 7 verdict, and versioned layers. TC-GEO-002-01/02, TC-GEO-003-01/02, TC-GEO-004-01/02."""
import json
import random
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, InternalError, transaction

from core.errors import Invalid
from geo import services
from geo.models import OverlayLayerVersion, OverlayResult, OverlayRun
from geo.tests.conftest import LAT, LNG, fc, rect, square, topics
from notifications.models import Message

ROAD = rect(LNG - 0.01, LAT - 0.0004, LNG + 0.01, LAT)  # a 44 m wide strip just south of the test origin


def test_result_per_layer_with_version(make_layer, make_asset):
    """TC-GEO-002-01: on save, one result per layer, each with its layer version; within 30 s."""
    acq = make_layer("t-acq", "government_acquisition", square(dx=0.01))
    road = make_layer("t-road", "road_reserve", ROAD)
    asset = make_asset(ring=square(dy=0.002))
    s7 = services.section7(asset)
    run = s7["run"]
    assert run.status == "completed" and run.duration_ms < 30000
    by_code = {i["layer_code"]: i for i in run.items}
    assert by_code["t-acq"]["layer_version"] == 1 and by_code["t-road"]["layer_version"] == 1
    res = OverlayResult.objects.filter(boundary=asset.current_boundary)
    assert {r.layer_version.layer_id for r in res} >= {acq.pk, road.pk}
    ev = topics("overlay.completed")[-1]
    assert ev.payload["asset_id"] == str(asset.pk) and ev.payload["proposed_verdict"] == "green"


def test_inside_near_clear_and_verdict(make_layer, make_asset):
    """TC-GEO-003-01: correct flag per plot; section 7 proposed red, amber, green."""
    make_layer("t-acq", "government_acquisition", rect(LNG + 0.005, LAT + 0.005, LNG + 0.006, LAT + 0.006))
    make_layer("t-road", "road_reserve", ROAD)
    inside = make_asset(ring=square(dx=0.0052, dy=0.0052))
    near = make_asset(ring=square(dy=0.0004))           # 44 m north of the road strip
    clear = make_asset(ring=square(dx=-0.003, dy=0.002))
    assert services.section7(inside)["proposed_verdict"] == "red"
    assert services.section7(near)["proposed_verdict"] == "amber"
    assert services.section7(clear)["proposed_verdict"] == "green"
    r = OverlayResult.objects.get(boundary=inside.current_boundary, layer_version__layer__code="t-acq")
    assert r.outcome == "inside" and r.affected_share == Decimal("1.0000")
    r = OverlayResult.objects.get(boundary=near.current_boundary, layer_version__layer__code="t-road")
    assert r.outcome == "near" and Decimal("40") < r.distance_m < Decimal("50") and r.buffer_m == Decimal("50")
    reasons = services.section7(near)["reasons"]
    assert any("Near" in x["message"] and "m away" in x["message"] for x in reasons)


def test_partial_overlap_share(make_layer, make_asset):
    """FR-GEO-002: the share of the plot affected is reported."""
    make_layer("t-acq", "government_acquisition", rect(LNG, LAT + 0.01, LNG + 0.00015, LAT + 0.0105))
    asset = make_asset(ring=square(dy=0.01))
    r = OverlayResult.objects.get(boundary=asset.current_boundary, layer_version__layer__code="t-acq")
    assert r.outcome == "inside" and Decimal("0.45") < r.affected_share < Decimal("0.55")


def test_buffer_boundary_property():
    """TC-GEO-003-02: exactly on the buffer is near; 1 m outside is clear (property test on distances)."""
    rng = random.Random(7)
    for _ in range(500):
        buf = Decimal(rng.randint(1, 500))
        assert services.classify(0, buf, buf) == "near"
        assert services.classify(0, buf + 1, buf) == "clear"
        d = Decimal(str(rng.uniform(0, float(buf))))
        assert services.classify(0, d, buf) == "near"
        assert services.classify(rng.uniform(0.02, 1000), 0, buf) == "inside"


def test_layer_buffer_is_configurable(make_layer, make_asset):
    """FR-GEO-003: the buffer per layer overrides the setting; a smaller buffer makes the plot clear."""
    make_layer("t-road", "road_reserve", ROAD, buffer_m=Decimal("20"))
    asset = make_asset(ring=square(dy=0.0004))
    r = OverlayResult.objects.get(boundary=asset.current_boundary, layer_version__layer__code="t-road")
    assert r.outcome == "clear" and r.buffer_m == Decimal("20.00")


def test_missing_layer_makes_run_incomplete(make_layer, make_asset):
    """TC-GEO-002-02: a layer with no data marks the result incomplete, alerts the case manager,
    and section 7 cannot be green."""
    make_layer("t-flood", "flood_zone")  # created, never loaded
    asset = make_asset(ring=square(dx=0.02))
    s7 = services.section7(asset)
    assert s7["status"] == "incomplete" and s7["proposed_verdict"] == "amber"
    assert any(i["status"] == "missing" for i in s7["run"].items)
    assert Message.objects.filter(template="geo.overlay_incomplete", person__email="cm@tenmina.test").exists()


def test_worker_failure_on_one_layer(make_layer, make_asset, monkeypatch):
    """TC-GEO-002-02: one layer failing keeps the other results and the run is incomplete."""
    make_layer("t-road", "road_reserve", ROAD)

    def boom(layer, version):
        if layer.code == "t-road":
            raise RuntimeError("worker lost")

    monkeypatch.setattr(services, "_layer_failure_hook", boom)
    asset = make_asset(ring=square(dx=0.02))
    run = services.section7(asset)["run"]
    assert run.status == "incomplete"
    failed = [i for i in run.items if i["status"] == "failed"]
    assert [i["layer_code"] for i in failed] == ["t-road"]
    assert run.layers_checked == run.layers_expected - 1
    assert services.section7(asset)["proposed_verdict"] != "green"


def test_database_refuses_green_incomplete_run(make_asset, make_layer):
    """dbsql: an incomplete run cannot carry a green verdict."""
    make_layer("t-flood", "flood_zone")
    asset = make_asset(ring=square(dx=0.02))
    run = OverlayRun.objects.filter(asset=asset).latest("created_at")
    with pytest.raises((IntegrityError, InternalError)), transaction.atomic():
        OverlayRun.objects.filter(pk=run.pk).update(proposed_verdict="green")


def test_known_dispute_layer_sets_disputed_flag(make_layer, make_asset):
    """RUL-17 input: a plot inside a known dispute area is flagged disputed."""
    make_layer("t-dispute", "known_dispute", rect(LNG + 0.03, LAT, LNG + 0.031, LAT + 0.001))
    asset = make_asset(ring=square(dx=0.0302, dy=0.0002))
    asset.refresh_from_db()
    assert asset.disputed_flag and "dispute" in asset.disputed_reason


def test_new_layer_version_keeps_old_and_recheck_stores_next_to_old(make_layer, make_asset, people):
    """TC-GEO-004-01 and US-GEO-002 AC3: v2 active, v1 kept, past results still show v1;
    a re-check stores the new result next to the old one."""
    layer = make_layer("t-acq", "government_acquisition", rect(LNG + 0.05, LAT, LNG + 0.051, LAT + 0.001))
    asset = make_asset(ring=square(dx=0.0502, dy=0.0002))
    old = OverlayResult.objects.get(boundary=asset.current_boundary, layer_version__layer=layer)
    assert old.outcome == "inside" and old.layer_version.version == 1
    v2 = services.load_layer_version(layer, actor=people["admin"], source="Revised sheet",
                                     data=fc(rect(LNG + 0.06, LAT, LNG + 0.061, LAT + 0.001)),
                                     filename="acq-v2.geojson")
    layer.refresh_from_db()
    v1 = OverlayLayerVersion.objects.get(layer=layer, version=1)
    assert layer.current_version_id == v2.pk and v2.status == "active" and v1.status == "superseded"
    assert v1.features.count() == 1
    services.recheck(asset, actor=people["cm"])
    results = OverlayResult.objects.filter(boundary=asset.current_boundary, layer_version__layer=layer)
    assert {(r.layer_version.version, r.outcome) for r in results} == {(1, "inside"), (2, "clear")}
    assert services.section7(asset)["proposed_verdict"] == "green"
    with pytest.raises((IntegrityError, InternalError, Exception)), transaction.atomic():
        OverlayLayerVersion.objects.filter(pk=v1.pk).update(sha256="0" * 64)


@pytest.mark.parametrize("data,code", [
    (b"{not json", "layer-file-invalid"),
    (json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "urn:x:custom"}},
                 "features": []}).encode(), "projection-invalid"),
    (json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
               "geometry": {"type": "Point", "coordinates": [LNG, LAT]}}]}).encode(), "layer-file-invalid"),
    (fc([[LNG, LAT], [LNG + 1, LAT + 1], [LNG + 1, LAT], [LNG, LAT + 1], [LNG, LAT]]), "layer-file-invalid"),
    (fc(rect(350000, 740000, 351000, 741000)), "layer-file-invalid"),
])
def test_bad_layer_file_rejected_active_unchanged(make_layer, people, data, code):
    """TC-GEO-004-02: corrupt file or wrong projection is rejected with the reason; the active
    version is unchanged."""
    layer = make_layer("t-acq", "government_acquisition", square(dx=0.1))
    active = layer.current_version_id
    with pytest.raises(Invalid) as exc:
        services.load_layer_version(layer, actor=people["admin"], data=data, filename="bad.geojson",
                                    source="Bad file")
    assert exc.value.code == code and exc.value.detail
    layer.refresh_from_db()
    assert layer.current_version_id == active and layer.versions.count() == 1


def test_layer_admin_api(gh, people, api, make_asset):
    """US-GEO-004 API journey: administrator creates, uploads v1 and v2 (multipart), lists versions and
    features; a case manager cannot upload; a bad file returns the reasons."""
    adm, cm = api(people["admin"]), api(people["cm"])
    r = adm.post("/v1/admin/overlay-layers", {"country": "GH", "code": "t-wetland", "name": "Wetlands",
                                              "kind": "wetland", "buffer_m": "30.00"}, format="json")
    assert r.status_code == 201, r.content
    lid = r.json()["id"]
    assert r.json()["status"] == "draft" and r.json()["effective_buffer_m"] == "30.00"
    up = SimpleUploadedFile("wet.geojson", fc(square(dx=0.2)), content_type="application/geo+json")
    r = cm.post(f"/v1/admin/overlay-layers/{lid}/versions", {"file": up, "source": "x"}, format="multipart")
    assert r.status_code == 403
    up = SimpleUploadedFile("wet.geojson", fc(square(dx=0.2)), content_type="application/geo+json")
    r = adm.post(f"/v1/admin/overlay-layers/{lid}/versions", {"file": up, "source": "Water Resources Commission "
                                                                                    "[TO VERIFY]"},
                 format="multipart")
    assert r.status_code == 201, r.content
    assert r.json()["version"] == 1 and r.json()["feature_count"] == 1 and len(r.json()["sha256"]) == 64
    r = adm.post(f"/v1/admin/overlay-layers/{lid}/versions",
                 {"geojson": json.loads(fc(square(dx=0.3))), "source": "Revised", "recheck": True}, format="json")
    assert r.status_code == 201 and r.json()["version"] == 2
    r = adm.post(f"/v1/admin/overlay-layers/{lid}/versions", {"geojson": {"type": "FeatureCollection",
                                                                          "features": []}, "source": "x"},
                 format="json")
    assert r.status_code == 422 and r.json()["code"] == "layer-file-invalid"
    r = cm.get(f"/v1/admin/overlay-layers/{lid}/versions")
    assert [v["version"] for v in r.json()] == [2, 1] and r.json()[1]["status"] == "superseded"
    r = cm.get(f"/v1/admin/overlay-layers/{lid}/features?version=1")
    assert r.json()["type"] == "FeatureCollection" and len(r.json()["features"]) == 1
    r = cm.get("/v1/admin/overlay-layers?country=GH")
    assert any(x["code"] == "t-wetland" for x in r.json()["items"])
    assert api(people["client"]).get("/v1/admin/overlay-layers").json()["items"] == []
    r = adm.post(f"/v1/admin/overlay-layers/{lid}/status", {"status": "retired", "reason": "Replaced"},
                 format="json")
    assert r.status_code == 200 and r.json()["status"] == "retired"
    asset = make_asset(ring=square(dx=0.3))
    codes = [i["layer_code"] for i in services.section7(asset)["run"].items]
    assert "t-wetland" not in codes  # retired layers are not checked


def test_overlay_results_api_roles(make_layer, make_asset, people, api):
    """02 7.4 GET /v1/assets/{id}/overlay-results: CM, RV, LW assigned; not the client; re-run by CM."""
    make_layer("t-road", "road_reserve", ROAD)
    asset = make_asset(ring=square(dy=0.0004))
    url = f"/v1/assets/{asset.pk}/overlay-results"
    r = api(people["reviewer"]).get(url)
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["proposed_verdict"] == "amber" and body["run"]["status"] == "completed"
    assert any(x["layer_code"] == "t-road" and x["outcome"] == "near" for x in body["run"]["results"])
    assert api(people["client"]).get(url).status_code == 403
    assert api(people["lawyer"]).get(url).status_code == 404
    services.grant_access(asset, people["lawyer"], role="LW", actor=people["cm"])
    assert api(people["lawyer"]).get(url).status_code == 200
    r = api(people["cm"]).post(f"/v1/assets/{asset.pk}/overlay-checks")
    assert r.status_code == 201 and len(r.json()["history"]) == 1
    assert api(people["reviewer"]).post(f"/v1/assets/{asset.pk}/overlay-checks").status_code == 403
