"""US-GEO-007, FR-GEO-007, RUL-13: monitoring of listed and active plots. TC-GEO-007-01."""
import uuid
from datetime import date

import pytest

from core.errors import Invalid
from core.events import publish
from geo import services
from geo.adapters import FakeSatellite
from geo.models import MonitoringAlert, MonitoringEnrolment
from geo.tests.conftest import square, topics
from notifications.models import Message

BASE = date(2026, 1, 15)
LATER = date(2026, 6, 15)


@pytest.fixture
def watched(make_asset, people, clear_sky):
    asset = make_asset(ring=square(dx=0.08))
    listing_id = uuid.uuid4()
    publish("listing.live", listing_id, {"listing_id": listing_id, "asset_id": asset.pk})
    e = MonitoringEnrolment.objects.get(asset=asset, reason="listing")
    # Re-take the baseline at a known older date so later imagery is newer.
    e.baseline_image = services.fetch_image(asset, purpose="monitoring", before=BASE, apply_changes=False)
    e.save(update_fields=["baseline_image"])
    return asset, listing_id, e


def test_listing_live_enrols_and_is_idempotent(watched):
    """05 5.5: listing live, monitoring enrolled; a repeated event does not enrol twice."""
    asset, listing_id, e = watched
    asset.refresh_from_db()
    assert asset.listed_at is not None and e.status == "active" and e.source_id == listing_id
    publish("listing.live", listing_id, {"listing_id": listing_id, "asset_id": asset.pk})
    assert MonitoringEnrolment.objects.filter(asset=asset, status="active").count() == 1


def test_project_started_enrols(make_asset, clear_sky):
    """02 4.2: project.started starts monitoring the project's plot; project.completed ends it."""
    asset = make_asset(ring=square(dx=0.09))
    pid = uuid.uuid4()
    publish("project.started", pid, {"project_id": pid, "asset_id": asset.pk})
    e = MonitoringEnrolment.objects.get(asset=asset, reason="project")
    assert e.source_id == pid and e.baseline_image is not None
    publish("project.completed", pid, {"project_id": pid, "asset_id": asset.pk})
    e.refresh_from_db()
    assert e.status == "ended"


def test_change_above_threshold_raises_alert(watched, people, monkeypatch):
    """TC-GEO-007-01: new imagery shows a new structure above the threshold: alert raised for a case
    manager, published with the listing so LST suspends it (RUL-13)."""
    asset, listing_id, e = watched
    monkeypatch.setitem(FakeSatellite.CHANGES, str(asset.pk), (0.35, -0.10))
    out = services.run_monitoring(before=LATER, asset_ids=[asset.pk])
    assert out["alerts"] == 1
    alert = MonitoringAlert.objects.get(asset=asset)
    assert alert.status == "open" and alert.change_kind == "new_structure" and alert.change_score >= alert.threshold
    assert alert.new_date > alert.previous_date
    ev = topics("monitoring.alert_raised")[-1]
    assert ev.payload["asset_id"] == str(asset.pk) and ev.payload["listing_ids"] == [str(listing_id)]
    assert Message.objects.filter(template="geo.monitoring_alert", person=people["cm"]).exists()
    client_msg = Message.objects.filter(template="geo.monitoring_alert_client", person=asset.owner).first()
    assert client_msg is not None and client_msg.needs_action is False
    from geo.selectors import has_open_alert

    assert has_open_alert(asset.pk)
    again = services.run_monitoring(before=LATER, asset_ids=[asset.pk])
    assert again["alerts"] == 0  # the same scene does not raise a second alert


def test_clearing_detected(watched, monkeypatch):
    """FR-GEO-007: clearing appears as vegetation loss."""
    asset, _, _ = watched
    monkeypatch.setitem(FakeSatellite.CHANGES, str(asset.pk), (0.0, -0.40))
    services.run_monitoring(before=LATER, asset_ids=[asset.pk])
    assert MonitoringAlert.objects.get(asset=asset).change_kind == "clearing"


def test_small_change_no_alert_and_baseline_moves(watched, monkeypatch):
    """FR-GEO-007: below the threshold, no alert; the newer image becomes the baseline."""
    asset, _, e = watched
    monkeypatch.setitem(FakeSatellite.CHANGES, str(asset.pk), (0.02, -0.01))
    out = services.run_monitoring(before=LATER, asset_ids=[asset.pk])
    assert out == {"checked": 1, "alerts": 0, "skipped_flag_off": 0, "alert_ids": []}
    e.refresh_from_db()
    assert e.baseline_image.captured_on > BASE


def test_flag_off_skips_monitoring(watched, settings, monkeypatch):
    """06 2.6: geo.satellite_monitoring off means no imagery calls and no alerts."""
    asset, _, _ = watched
    monkeypatch.setitem(FakeSatellite.CHANGES, str(asset.pk), (0.5, -0.5))
    settings.TENMINA_FLAG_OVERRIDES = {"geo.satellite_monitoring": False}
    out = services.run_monitoring(before=LATER, asset_ids=[asset.pk])
    assert out["skipped_flag_off"] == 1 and not MonitoringAlert.objects.filter(asset=asset).exists()


def test_resolve_rules(watched, people, monkeypatch):
    """RUL-13: an alert closes only with what was found; a confirmed change needs evidence."""
    asset, _, e = watched
    monkeypatch.setitem(FakeSatellite.CHANGES, str(asset.pk), (0.35, -0.10))
    services.run_monitoring(before=LATER, asset_ids=[asset.pk])
    alert = MonitoringAlert.objects.get(asset=asset)
    with pytest.raises(Invalid):
        services.resolve_alert(alert, actor=people["cm"], resolution="no_change", note="")
    with pytest.raises(Invalid) as exc:
        services.resolve_alert(alert, actor=people["cm"], resolution="change_confirmed", note="Built")
    assert exc.value.code == "evidence-required"
    services.resolve_alert(alert, actor=people["cm"], resolution="no_change", note="Shadow from a cloud edge.")
    ev = topics("monitoring.alert_resolved")[-1]
    assert ev.payload["alert_id"] == str(alert.pk) and ev.payload["open_alerts_on_asset"] == 0
    e.refresh_from_db()
    assert e.baseline_image_id == alert.new_image_id


def test_monitoring_api_journey(watched, people, api, monkeypatch):
    """US-GEO-007 API journey: run, list, review, resolve with evidence; owner sees, others do not."""
    asset, _, _ = watched
    monkeypatch.setitem(FakeSatellite.CHANGES, str(asset.pk), (0.35, -0.10))
    cm = api(people["cm"])
    assert api(people["client"]).post("/v1/monitoring/runs", {"country": "GH"}, format="json").status_code == 403
    r = cm.post("/v1/monitoring/runs", {"country": "GH", "asset_ids": [str(asset.pk)], "before": str(LATER)},
                format="json")
    assert r.status_code == 201 and r.json()["alerts"] == 1, r.content
    aid = r.json()["alert_ids"][0]
    assert api(people["client"]).get(f"/v1/monitoring-alerts/{aid}").status_code == 200
    assert api(people["client2"]).get(f"/v1/monitoring-alerts/{aid}").status_code == 404
    r = cm.post(f"/v1/monitoring-alerts/{aid}/review")
    assert r.status_code == 200 and r.json()["status"] == "under_review"
    assert api(people["client"]).post(f"/v1/monitoring-alerts/{aid}/resolve", {}, format="json").status_code == 403
    from evidence.services import store

    ev = store(data=b"site photo", country=asset.country, uploaded_by=people["cm"], content_type="image/jpeg")
    r = cm.post(f"/v1/monitoring-alerts/{aid}/resolve", {"resolution": "change_confirmed",
                                                         "note": "A block wall was built.",
                                                         "evidence_id": str(ev.pk)}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "resolved", r.content
    r = cm.get("/v1/monitoring/enrolments?status=active")
    assert any(x["asset"] == str(asset.pk) for x in r.json()["items"])
    r = cm.get(f"/v1/assets/{asset.pk}/monitoring")
    assert r.json()[0]["reason"] == "listing"


def test_manual_enrol_and_end(make_asset, people, api, clear_sky):
    """FR-GEO-007: a case manager can watch a plot and stop watching it with a reason."""
    asset = make_asset(ring=square(dx=0.095))
    r = api(people["cm"]).post(f"/v1/assets/{asset.pk}/monitoring", {"reason": "manual"}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "active"
    eid = r.json()["id"]
    r = api(people["cm"]).post(f"/v1/monitoring/enrolments/{eid}/end", {"reason": "Client asked"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "ended"


def test_listing_sold_ends_monitoring(watched):
    """05 5.5: a sold listing is no longer watched."""
    asset, listing_id, e = watched
    publish("listing.sold", listing_id, {"listing_id": listing_id, "asset_id": asset.pk})
    e.refresh_from_db()
    assert e.status == "ended"
