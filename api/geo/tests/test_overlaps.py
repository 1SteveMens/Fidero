"""US-GEO-005, FR-GEO-005: new plots checked against previously verified plots. TC-GEO-005-01."""
from decimal import Decimal

import pytest

from core.errors import Invalid
from geo import services
from geo.models import OverlapFlag
from geo.tests.conftest import square, topics
from notifications.models import Message


@pytest.fixture
def pair(make_asset, people):
    a = make_asset(owner=people["seller"], ring=square(dx=0.05, size=0.0006), name="Verified plot")
    services.mark_verified(a.pk)
    b = make_asset(owner=people["client"], ring=square(dx=0.0503, dy=0.0003, size=0.0006), name="New plot")
    return a, b


def test_overlap_with_verified_plot_flagged_with_area(pair, people):
    """TC-GEO-005-01: overlap flagged with area, naming the other plot to authorised staff only."""
    a, b = pair
    flag = OverlapFlag.objects.get(asset=b)
    assert flag.other_asset_id == a.pk and flag.other_kind == "verified" and flag.status == "open"
    assert Decimal("900") < flag.overlap_area_sqm < Decimal("1200")  # a quarter of a 66 m square
    assert Decimal("0.2") < flag.overlap_share < Decimal("0.3")
    ev = topics("overlap.flagged")[-1]
    assert ev.payload["asset_id"] == str(b.pk) and ev.payload["other_asset_id"] == str(a.pk)
    staff_msg = Message.objects.filter(template="geo.overlap_flagged", person=people["cm"],
                                       subject_id=str(flag.pk)).first()
    assert staff_msg is not None and a.reference in staff_msg.body
    assert not Message.objects.filter(person=people["client"], subject_id=str(flag.pk)).exists()
    assert services.section7(b)["proposed_verdict"] == "amber"


def test_clients_never_see_who_owns_the_other_plot(pair, people, api):
    """US-GEO-005: the other case is named to authorised staff only."""
    a, b = pair
    client = api(people["client"])
    assert client.get(f"/v1/assets/{b.pk}/overlaps").status_code == 403
    assert client.get("/v1/overlap-flags").json()["items"] == []
    body = client.get(f"/v1/assets/{b.pk}/map").json()
    assert all(f["properties"]["kind"] != "overlap" for f in body["features"])
    r = api(people["cm"]).get(f"/v1/assets/{b.pk}/overlaps")
    assert r.status_code == 200 and r.json()[0]["other_asset"]["reference"] == a.reference
    assert r.json()[0]["other_asset"]["owner_name"] == people["seller"].full_name
    body = api(people["cm"]).get(f"/v1/assets/{b.pk}/map").json()
    assert any(f["properties"]["kind"] == "overlap" for f in body["features"])


def test_resolve_overlap(pair, people, api):
    """FR-GEO-005: confirm (section 7 red) or dismiss with a reason; a reason is required."""
    _, b = pair
    flag = OverlapFlag.objects.get(asset=b)
    with pytest.raises(Invalid):
        services.resolve_overlap(flag, actor=people["cm"], outcome="dismissed", note=" ")
    assert api(people["reviewer"]).post(f"/v1/overlap-flags/{flag.pk}/resolve",
                                        {"outcome": "confirmed", "note": "x"}, format="json").status_code == 403
    r = api(people["cm"]).post(f"/v1/overlap-flags/{flag.pk}/resolve",
                               {"outcome": "confirmed", "note": "Same land sold twice by the family."}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert services.section7(b)["proposed_verdict"] == "red"
    r = api(people["cm"]).post(f"/v1/overlap-flags/{flag.pk}/resolve",
                               {"outcome": "dismissed", "note": "x"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "state-conflict"


def test_dismissed_overlap_no_longer_counts(pair, people):
    """FR-GEO-005: a dismissed flag leaves section 7 to the overlay result."""
    _, b = pair
    flag = OverlapFlag.objects.get(asset=b)
    services.resolve_overlap(flag, actor=people["cm"], outcome="dismissed", note="Same plot registered twice.")
    assert services.section7(b)["proposed_verdict"] == "green"


def test_new_boundary_supersedes_old_flags(pair, people):
    """FR-GEO-001, 005: a corrected boundary closes the old flags and is checked afresh."""
    _, b = pair
    services.save_boundary(b, actor=people["cm"], source="surveyor_coordinates",
                           coordinates=square(dx=0.06, size=0.0006))
    assert OverlapFlag.objects.get(asset=b).status == "superseded"
    b.refresh_from_db()
    assert services.section7(b)["proposed_verdict"] == "green"


def test_no_flag_for_touching_plots(make_asset, people):
    """FR-GEO-005: neighbours that share only an edge are not overlaps."""
    make_asset(ring=square(dx=0.07))
    b = make_asset(ring=square(dx=0.0703))
    assert not OverlapFlag.objects.filter(asset=b).exists()


def test_overlap_queue_scoped(pair, people, api):
    """Staff queue lists flags; filtering by status works."""
    r = api(people["cm"]).get("/v1/overlap-flags?status=open")
    assert r.status_code == 200 and len(r.json()["items"]) >= 1
