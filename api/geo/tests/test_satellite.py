"""US-GEO-006, FR-GEO-006: a satellite image of the plot with the boundary drawn. TC-GEO-006-01."""
import hashlib
import uuid

from evidence.models import EvidenceLink
from evidence.services import verify
from geo import services
from geo.adapters import FakeSatellite
from geo.models import SatelliteImage
from geo.tests.conftest import square


def test_report_gets_image_with_boundary_and_date(make_asset, people, clear_sky):
    """TC-GEO-006-01: image with boundary in section 4, with the image date; stored as evidence."""
    asset = make_asset(ring=square())
    report_id = uuid.uuid4()
    out = services.image_for_report(asset.pk, report_id=report_id, actor=people["cm"])
    assert out["available"] and out["captured_on"] is not None
    assert "Satellite image dated" in out["section_4_text"]
    img = SatelliteImage.objects.get(pk=out["image_id"])
    assert img.boundary_id == asset.current_boundary_id and img.purpose == "report"
    assert verify(img.evidence)
    assert EvidenceLink.objects.filter(evidence=img.evidence, subject_type="report", subject_id=report_id).exists()
    from core.adapters import get_adapter

    svg = get_adapter("evidence_store").get(img.evidence.storage_key)
    assert b"<polygon" in svg and b"Image date" in svg
    assert hashlib.sha256(svg).hexdigest() == img.evidence.sha256


def test_no_image_states_the_gap(make_asset, people, monkeypatch, clear_sky):
    """US-GEO-006 AC2: no image available, the gap is stated for section 4."""
    asset = make_asset(ring=square())
    monkeypatch.setattr(FakeSatellite, "NO_IMAGERY", {str(asset.pk)})
    out = services.image_for_report(asset.pk)
    assert not out["available"] and out["gap"].startswith("No satellite image is included.")
    assert SatelliteImage.objects.get(pk=out["image_id"]).status == "unavailable"


def test_provider_down_or_flag_off_states_the_gap(make_asset, people, monkeypatch, settings):
    """IF-05: the provider down or imagery switched off in the country: the report continues with a gap."""
    asset = make_asset(ring=square())
    monkeypatch.setattr(FakeSatellite, "AVAILABLE", False)
    assert "could not be reached" in services.image_for_report(asset.pk)["gap"]
    monkeypatch.setattr(FakeSatellite, "AVAILABLE", True)
    settings.TENMINA_FLAG_OVERRIDES = {"geo.satellite_monitoring": False}
    assert "not switched on" in services.image_for_report(asset.pk)["gap"]


def test_no_boundary_states_the_gap(make_asset):
    """US-GEO-006: without a saved polygon there is no image with a boundary."""
    asset = make_asset()
    out = services.image_for_report(asset.pk)
    assert not out["available"] and "boundary" in out["gap"]


def test_satellite_api(make_asset, people, api, clear_sky):
    """02 7.4 GET /v1/assets/{id}/satellite-image: CM, client own; another client cannot."""
    asset = make_asset(ring=square())
    cm = api(people["cm"])
    assert api(people["client"]).post(f"/v1/assets/{asset.pk}/satellite-images", {}, format="json").status_code == 403
    r = cm.post(f"/v1/assets/{asset.pk}/satellite-images", {"purpose": "on_request"}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "available"
    r = api(people["client"]).get(f"/v1/assets/{asset.pk}/satellite-image")
    assert r.status_code == 200 and r.json()["captured_on"]
    content = api(people["client"]).get(r.json()["content_url"])
    assert content.status_code == 200 and content["Content-Type"] == "image/svg+xml"
    assert api(people["client2"]).get(f"/v1/assets/{asset.pk}/satellite-image").status_code == 404
    assert api(people["client2"]).get(r.json()["content_url"]).status_code == 404
    r = cm.post(f"/v1/assets/{asset.pk}/report-image", {"report_id": str(uuid.uuid4())}, format="json")
    assert r.status_code == 201 and r.json()["available"] is True
