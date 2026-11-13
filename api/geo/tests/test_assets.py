"""Assets, scoping and digital addresses. US-GEO-008 (FR-GEO-008, TC-GEO-008-01), plus the asset API
every story builds on."""
import pytest

from core.errors import FeatureOff
from geo import services
from geo.adapters import FakeAddressResolver
from geo.models import Asset
from geo.tests.conftest import square


def test_digital_address_resolves_for_confirmation(gh, people, api):
    """TC-GEO-008-01: a known address returns coordinates to confirm."""
    r = api(people["client"]).get("/v1/geo/ghana-post/GA-183-8164")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["status"] == "resolved" and body["code"] == "GA-183-8164"
    assert -0.35 <= body["location"]["lng"] <= 0.05 and 5.55 <= body["location"]["lat"] <= 5.80
    assert api(people["client"]).get("/v1/geo/ghana-post/GA1838164").json()["code"] == "GA-183-8164"
    assert api(people["client"]).get("/v1/geo/ghana-post/GA-183-0000").json()["status"] == "not_found"
    r = api(people["client"]).get("/v1/geo/ghana-post/hello")
    assert r.status_code == 422 and r.json()["code"] == "address-invalid"


def test_service_unavailable_saves_text_without_guessing(gh, people, api, monkeypatch):
    """US-GEO-008 AC2: service unavailable: address saved as text, no coordinates guessed."""
    monkeypatch.setattr(FakeAddressResolver, "AVAILABLE", False)
    r = api(people["client"]).get("/v1/geo/ghana-post/GA-183-8164")
    assert r.json()["status"] == "unavailable" and r.json()["location"] is None
    r = api(people["client"]).post("/v1/assets", {"locality": "East Legon", "ghana_post_gps": "ga-183-8164",
                                                  "type": "building"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["ghana_post_gps"] == "GA-183-8164" and r.json()["location"] is None
    assert r.json()["location_source"] == "none"


def test_confirmed_point_is_saved(gh, people, api):
    """US-GEO-008 AC1: the point the user confirmed is saved with its source."""
    loc = api(people["client"]).get("/v1/geo/ghana-post/GA-183-8164").json()["location"]
    r = api(people["client"]).post("/v1/assets", {"locality": "East Legon", "ghana_post_gps": "GA-183-8164",
                                                  "location": loc}, format="json")
    assert r.json()["location"] == loc and r.json()["location_source"] == "digital_address_confirmed"


def test_digital_address_flag_off(gh, people, settings):
    """06 2.6: geo.ghana_post_gps off: the lookup is not offered."""
    settings.TENMINA_FLAG_OVERRIDES = {"geo.ghana_post_gps": False}
    with pytest.raises(FeatureOff):
        services.resolve_digital_address(gh, "GA-183-8164")


def test_asset_scoping(gh, people, api, make_asset):
    """Clients see their own; staff see the country; professionals only what they are assigned."""
    mine = make_asset(owner=people["client"])
    other = make_asset(owner=people["client2"])
    ids = {a["id"] for a in api(people["client"]).get("/v1/assets?limit=100").json()["items"]}
    assert str(mine.pk) in ids and str(other.pk) not in ids
    assert api(people["client"]).get(f"/v1/assets/{other.pk}").status_code == 404
    assert api(people["cm"]).get(f"/v1/assets/{other.pk}").status_code == 200
    assert api(people["surveyor"]).get(f"/v1/assets/{other.pk}").status_code == 404
    r = api(people["cm"]).post(f"/v1/assets/{other.pk}/access-grants",
                               {"person_id": str(people["surveyor"].pk), "role": "SV"}, format="json")
    assert r.status_code == 201, r.content
    assert api(people["surveyor"]).get(f"/v1/assets/{other.pk}").status_code == 200
    r = api(people["cm"]).post(f"/v1/asset-access-grants/{r.json()['id']}/revoke")
    assert r.status_code == 200 and r.json()["revoked_at"]
    assert api(people["surveyor"]).get(f"/v1/assets/{other.pk}").status_code == 404
    r = api(people["cm"]).post(f"/v1/assets/{other.pk}/access-grants",
                               {"person_id": str(people["runner"].pk), "role": "SV"}, format="json")
    assert r.status_code == 422  # the runner is not a surveyor


def test_create_and_update_rules(gh, people, api):
    """Owners register their own property; staff register for a client; others cannot."""
    r = api(people["client"]).post("/v1/assets", {"locality": "Oyarifa", "owner_id": str(people["client2"].pk)},
                                   format="json")
    assert r.status_code == 403
    r = api(people["cm"]).post("/v1/assets", {"locality": "Oyarifa", "owner_id": str(people["client2"].pk),
                                              "type": "plot", "plot_number": "12"}, format="json")
    assert r.status_code == 201 and r.json()["owner"] == str(people["client2"].pk)
    assert r.json()["reference"].startswith("AST-GH-")
    aid = r.json()["id"]
    assert api(people["runner"]).post("/v1/assets", {"locality": "X"}, format="json").status_code == 403
    r = api(people["client2"]).patch(f"/v1/assets/{aid}", {"address": "Near the church"}, format="json")
    assert r.status_code == 200 and r.json()["address"] == "Near the church"
    assert api(people["client"]).patch(f"/v1/assets/{aid}", {"address": "x"}, format="json").status_code == 404
    r = api(people["client2"]).patch(f"/v1/assets/{aid}", {"location": {"lng": 5.6, "lat": -0.2}}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "geometry-outside-country"
    r = api(people["client2"]).post("/v1/assets", {"locality": " "}, format="json")
    assert r.status_code == 400


def test_disputed_flag_api(make_asset, people, api):
    """RUL-17 input: staff mark or clear the disputed flag with a reason; clients cannot."""
    a = make_asset()
    url = f"/v1/assets/{a.pk}/disputed-flag"
    assert api(people["client"]).post(url, {"disputed": True, "reason": "x"}, format="json").status_code == 403
    assert api(people["cm"]).post(url, {"disputed": True}, format="json").status_code == 422
    r = api(people["cm"]).post(url, {"disputed": True, "reason": "Family objection at site visit"}, format="json")
    assert r.status_code == 200 and r.json()["disputed_flag"] is True
    from geo.selectors import is_disputed

    assert is_disputed(a.pk)


def test_maps_and_point_lookup(gh, people, api, make_asset):
    """SCR-BO-07: map GeoJSON for the back office; PTR point lookup selector."""
    a = make_asset(ring=square(dx=0.2))
    b = a.current_boundary
    r = api(people["cm"]).get(f"/v1/geo/map?country=GH&bbox=-1.5,6.6,-1.3,6.8&layers=gh-sample-acquisitions")
    assert r.status_code == 200
    assert any(f["properties"].get("asset_id") == str(a.pk) for f in r.json()["features"])
    assert api(people["client"]).get("/v1/geo/map?country=GH&bbox=-1.5,6.6,-1.3,6.8").status_code == 403
    r = api(people["client"]).get(f"/v1/assets/{a.pk}/map")
    assert r.json()["features"][0]["properties"]["kind"] == "boundary"
    from geo.selectors import assets_at_point, distance_to_boundary_m

    c = b.centroid
    assert list(assets_at_point(gh, c.x, c.y)) == [a]
    assert distance_to_boundary_m(a.pk, c.x, c.y) == 0
    assert distance_to_boundary_m(a.pk, c.x, c.y + 0.01) > 1000


def test_seeded_sample_layers_are_labelled(seeded, people, api):
    """Seed: sample layers are marked as fictional sample data."""
    items = api(people["cm"]).get("/v1/admin/overlay-layers?country=GH&limit=100").json()["items"]
    sample = [x for x in items if x["code"].startswith("gh-sample-")]
    assert len(sample) == 5 and all(x["is_sample"] for x in sample)
    assert Asset.objects.filter(locality__endswith="(sample)").count() >= 6


def test_create_is_idempotent(gh, people, api):
    """02 7.1: the same Idempotency-Key and body returns the first response."""
    c = api(people["client"])
    body = {"locality": "Oyarifa", "plot_number": "77"}
    r1 = c.post("/v1/assets", body, format="json", HTTP_IDEMPOTENCY_KEY="k-geo-1")
    r2 = c.post("/v1/assets", body, format="json", HTTP_IDEMPOTENCY_KEY="k-geo-1")
    assert r1.status_code == 201 and r2.json()["id"] == r1.json()["id"]
    assert Asset.objects.filter(plot_number="77").count() == 1


def test_boundary_event_handler_is_idempotent(make_asset):
    """Handlers are idempotent: re-delivering asset.boundary_saved adds no second run or flag."""
    from core.events import dispatch
    from core.models import OutboxEvent
    from geo.models import OverlayRun

    asset = make_asset(ring=square(dx=0.4))
    ev = OutboxEvent.objects.filter(topic="asset.boundary_saved", aggregate_id=asset.pk).get()
    dispatch(ev)
    assert OverlayRun.objects.filter(asset=asset).count() == 1
    assert OverlayRun.objects.get(asset=asset).status == "completed"


def test_country_extent_api(gh, people, api):
    """Country is configuration: the land area is loaded by an administrator."""
    r = api(people["cm"]).get("/v1/admin/geo/country-extents/GH")
    assert r.status_code == 200 and r.json()["geometry"]["type"] == "MultiPolygon"
    body = {"geojson": {"type": "Polygon", "coordinates": [[[-3, 4], [2, 4], [2, 12], [-3, 12], [-3, 4]]]},
            "label": "Wider box"}
    assert api(people["cm"]).put("/v1/admin/geo/country-extents/GH", body, format="json").status_code == 403
    r = api(people["admin"]).put("/v1/admin/geo/country-extents/GH", body, format="json")
    assert r.status_code == 200 and r.json()["label"] == "Wider box"
