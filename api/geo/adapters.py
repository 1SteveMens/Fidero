"""GEO ports and adapters (ADR-10, 02 section 11: IF-04 to IF-06).

- `satellite` (ImagerySource, IF-05): finds the latest usable scene over a
  plot, draws the boundary on it and scores change between two scenes.
- `address_resolver` (AddressResolver, IF-06): turns a digital address such
  as a Ghana Post GPS code into a point.

The fakes are deterministic so the whole workflow runs offline and tests can
steer them through class attributes.
"""
import hashlib
import re
from datetime import date, timedelta


class ServiceUnavailable(Exception):
    """The integration cannot be reached. Callers fall back to the manual path."""


# --------------------------------------------------------------------------- satellite


class FakeSatellite:
    """Stands in for a public catalogue such as Sentinel-2 [TO VERIFY].

    Scenes are generated every 5 days with a cloud cover derived from the
    plot and the date. Tests steer it with:
      - AVAILABLE = False: the provider is down;
      - NO_IMAGERY: set of asset ids with no usable scene;
      - CHANGES: {asset_id: (built_up_delta, vegetation_delta)} applied to
        scenes after the first one fetched for that asset.
    """

    name = "fake-satellite"
    AVAILABLE = True
    NO_IMAGERY: set = set()
    CHANGES: dict = {}
    REVISIT_DAYS = 5
    RESOLUTION_M = 10

    def _h(self, *parts) -> int:
        return int(hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()[:8], 16)

    def latest_scene(self, *, asset_id, bbox, max_cloud=20.0, before=None):
        """Return the newest scene under `max_cloud` per cent cloud, or None.

        A cloudy scene is skipped and the next older one tried (IF-05)."""
        if not self.AVAILABLE:
            raise ServiceUnavailable("The imagery provider cannot be reached.")
        if str(asset_id) in {str(a) for a in self.NO_IMAGERY}:
            return None
        day = before or date.today()
        day = day - timedelta(days=day.toordinal() % self.REVISIT_DAYS)
        for _ in range(12):
            cloud = self._h("cloud", round(bbox[0], 3), round(bbox[1], 3), day.isoformat()) % 60
            if cloud <= max_cloud:
                return {
                    "provider": self.name,
                    "scene_id": f"FAKE-S2-{day:%Y%m%d}-{self._h(bbox, day) % 100000:05d}",
                    "captured_on": day,
                    "cloud_cover": float(cloud),
                    "resolution_m": float(self.RESOLUTION_M),
                }
            day -= timedelta(days=self.REVISIT_DAYS)
        return None

    def indices(self, *, asset_id, scene, apply_changes=False):
        """Built-up and vegetation index for the plot in a scene (0 to 1)."""
        base_b = (self._h("b", asset_id) % 30) / 100 + 0.05
        base_v = (self._h("v", asset_id) % 40) / 100 + 0.40
        if apply_changes:
            db, dv = self.CHANGES.get(str(asset_id), (0.0, 0.0))
            base_b, base_v = base_b + db, base_v + dv
        clamp = lambda x: max(0.0, min(1.0, x))  # noqa: E731
        return round(clamp(base_b), 4), round(clamp(base_v), 4)

    def render(self, *, scene, rings, bbox, label="") -> bytes:
        """An SVG image of the plot area with the boundary drawn and the image date."""
        minx, miny, maxx, maxy = bbox
        padx, pady = (maxx - minx) * 0.25 or 0.0005, (maxy - miny) * 0.25 or 0.0005
        minx, maxx, miny, maxy = minx - padx, maxx + padx, miny - pady, maxy + pady
        size = 512

        def xy(lng, lat):
            x = (lng - minx) / (maxx - minx) * size
            y = size - (lat - miny) / (maxy - miny) * size
            return f"{x:.1f},{y:.1f}"

        paths = "".join(
            f'<polygon points="{" ".join(xy(*pt[:2]) for pt in ring)}" fill="rgba(163,230,53,0.18)" '
            f'stroke="#a3e635" stroke-width="3"/>' for ring in rings)
        seed = self._h(scene["scene_id"]) % 360
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size + 40}" '
            f'viewBox="0 0 {size} {size + 40}">'
            f'<rect width="{size}" height="{size}" fill="hsl({seed},18%,32%)"/>'
            f'<rect x="40" y="60" width="140" height="90" fill="hsl({seed},10%,45%)"/>'
            f'<rect x="300" y="320" width="160" height="120" fill="hsl({(seed + 40) % 360},25%,28%)"/>'
            f"{paths}"
            f'<rect y="{size}" width="{size}" height="40" fill="#111"/>'
            f'<text x="10" y="{size + 25}" fill="#fff" font-family="sans-serif" font-size="14">'
            f'Image date {scene["captured_on"]:%d %b %Y} | {scene["provider"]} {scene["scene_id"]} | '
            f'{label}Sample imagery</text></svg>'
        )
        return svg.encode()


# --------------------------------------------------------------------------- digital addresses


class FakeAddressResolver:
    """Stands in for the Ghana Post GPS service [TO VERIFY].

    A code such as GA-183-8164 resolves to a fixed point inside a box for its
    region letter. Codes ending in 0000 are "not found". AVAILABLE = False
    makes the service unreachable."""

    name = "fake-ghana-post"
    AVAILABLE = True
    PATTERN = re.compile(r"^([A-Z]{2})-?(\d{3,4})-?(\d{4})$")
    # Rough boxes per first letter of the code (lng_min, lat_min, lng_max, lat_max). Sample data only.
    REGION_BOXES = {
        "G": (-0.35, 5.55, 0.05, 5.80),   # Greater Accra
        "A": (-1.75, 6.55, -1.45, 6.80),  # Ashanti
        "C": (-1.35, 5.10, -1.15, 5.25),  # Central
        "E": (-0.30, 6.05, -0.15, 6.15),  # Eastern
        "V": (0.40, 6.55, 0.55, 6.65),    # Volta
        "W": (-1.80, 4.88, -1.70, 4.95),  # Western
        "N": (-0.90, 9.35, -0.80, 9.45),  # Northern
    }

    def normalise(self, code: str) -> str | None:
        raw = re.sub(r"\s+", "", (code or "").upper())
        m = self.PATTERN.match(raw)
        if not m:
            return None
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    def resolve(self, code: str):
        """Return {"code", "lng", "lat", "accuracy_m"} or None when unknown."""
        if not self.AVAILABLE:
            raise ServiceUnavailable("The digital address service cannot be reached.")
        norm = self.normalise(code)
        if norm is None or norm.endswith("-0000"):
            return None
        box = self.REGION_BOXES.get(norm[0])
        if box is None:
            return None
        h = int(hashlib.sha256(norm.encode()).hexdigest()[:12], 16)
        fx, fy = (h % 10000) / 10000, ((h // 10000) % 10000) / 10000
        lng = box[0] + (box[2] - box[0]) * fx
        lat = box[1] + (box[3] - box[1]) * fy
        return {"code": norm, "lng": round(lng, 6), "lat": round(lat, 6), "accuracy_m": 5.0}
