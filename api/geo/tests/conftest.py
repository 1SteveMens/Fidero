"""GEO test helpers. Test shapes sit near Kumasi (about 6.7 N, 1.6 W), far
from the seeded sample layers near Accra, so each test controls its layers."""
import json
from decimal import Decimal

import pytest

from geo import services

LNG, LAT = -1.6000, 6.7000


def rect(minx, miny, maxx, maxy):
    return [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]


def square(dx=0.0, dy=0.0, size=0.0003):
    """A plot of about 33 m by 33 m, offset from the test origin in degrees."""
    return rect(LNG + dx, LAT + dy, LNG + dx + size, LAT + dy + size)


def fc(*rings, names=None):
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"name": (names or [f"F{i}" for i in range(len(rings))])[i]},
         "geometry": {"type": "Polygon", "coordinates": [r]}} for i, r in enumerate(rings)]}).encode()


@pytest.fixture
def make_layer(gh, people):
    def make(code, kind, *rings, buffer_m=None):
        layer = services.create_layer(actor=people["admin"], country=gh, code=code, name=code.replace("-", " "),
                                      kind=kind, buffer_m=buffer_m)
        if rings:
            services.load_layer_version(layer, actor=people["admin"], data=fc(*rings), filename=f"{code}.geojson",
                                        source="Test fixture")
            layer.refresh_from_db()
        return layer

    return make


@pytest.fixture
def make_asset(gh, people):
    def make(owner=None, ring=None, **kw):
        owner = owner or people["client"]
        kw.setdefault("locality", "Test locality")
        asset = services.create_asset(actor=owner, country=gh, owner=owner, **kw)
        if ring is not None:
            services.save_boundary(asset, actor=people["cm"], source="surveyor_coordinates", coordinates=ring)
            asset.refresh_from_db()
        return asset

    return make


@pytest.fixture
def clear_sky(monkeypatch):
    """No scene is ever too cloudy, so imagery tests are independent of the fake's cloud pattern."""
    monkeypatch.setitem(services.DEFAULTS, "geo.imagery_max_cloud_pct", Decimal("100"))


def topics(*names):
    from core.models import OutboxEvent

    return list(OutboxEvent.objects.filter(topic__in=names).order_by("created_at"))
