"""Server verification and fraud checks (FR-MOB-011, 02 section 8.7).

Thresholds are working assumptions, read per country from the published
country configuration under `mobile.*` (adm_setting in 02 6.8).
"""
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

DEFAULTS = {
    "plot_buffer_m": 50,  # 8.7 position
    "max_accuracy_m": 50,
    "device_time_gap_s": 300,  # device clock ahead of the server by more than this
    "max_capture_age_days": 7,  # captured more than this before upload
    "checkin_radius_m": 100,  # ADR-19
    "checkin_max_accuracy_m": 100,
    "checkin_time_gap_s": 3600,  # check-in uploaded this long after it happened (offline)
    "checkout_min_minutes": 15,
    "checkout_missing_hours": 12,  # a check-in with no check-out after this is reported
    "exif_time_tolerance_s": 120,
    "phash_max_distance": 4,
}


def setting(country, key):
    from countries.selectors import config

    default = DEFAULTS[key]
    try:
        value = config(country, f"mobile.{key}", default) if country is not None else default
    except Exception:  # noqa: BLE001
        value = default
    return type(default)(value)


R = 6371008.8


def haversine(lat1, lng1, lat2, lng2) -> float:
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lng2) - float(lng1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def _inside(lat, lng, poly) -> bool:
    x, y, inside = float(lng), float(lat), False
    n = len(poly)
    for i in range(n):
        y1, x1 = float(poly[i][0]), float(poly[i][1])
        y2, x2 = float(poly[(i + 1) % n][0]), float(poly[(i + 1) % n][1])
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def distance_to_polygon(lat, lng, poly) -> float:
    """0 inside the boundary, else metres to the nearest edge (local flat projection)."""
    if _inside(lat, lng, poly):
        return 0.0
    lat0 = math.radians(float(lat))

    def xy(p):
        return (math.radians(float(p[1]) - float(lng)) * R * math.cos(lat0), math.radians(float(p[0]) - float(lat)) * R)

    best = float("inf")
    pts = [xy(p) for p in poly]
    for i in range(len(pts)):
        (ax, ay), (bx, by) = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def distance_to_site(lat, lng, item) -> float | None:
    if item is None or lat is None or lng is None:
        return None
    if item.boundary and len(item.boundary) >= 3:
        return distance_to_polygon(lat, lng, item.boundary)
    if item.point:
        return haversine(lat, lng, item.point[0], item.point[1])
    return None


def registered_point(item):
    if item.point:
        return float(item.point[0]), float(item.point[1])
    if item.boundary and len(item.boundary) >= 3:
        return (sum(float(p[0]) for p in item.boundary) / len(item.boundary),
                sum(float(p[1]) for p in item.boundary) / len(item.boundary))
    return None


def _project_of(ev) -> str:
    m = getattr(ev, "manifest", None) if hasattr(ev, "manifest") else None
    if m is not None:
        return m.project_key or f"{m.subject_type}:{m.subject_id}"
    return f"{ev.owner_type}:{ev.owner_id}"


def device_flags(device) -> list:
    out = []
    if device.key_security == "software":
        out.append(("software_key", {"key_security": "software"}))
    if device.integrity_status == "failed":
        out.append(("integrity_failed", {"verdict": device.integrity_verdict}))
    return out


def evidence_flags(manifest, evidence, item, device) -> list:
    """Flags for a stored evidence item. Returns [(kind, detail)]."""
    from evidence.models import Evidence
    from evidence.services import phash_distance

    country = manifest.country
    out = device_flags(device)
    cam = (manifest.manifest or {}).get("camera") or {}
    if cam.get("emulator"):
        out.append(("emulator", {"model": cam.get("model", "")}))
    if manifest.unassigned_capture:
        out.append(("unassigned_capture", {"subject_type": manifest.subject_type,
                                           "subject_id": str(manifest.subject_id)}))
    # Position
    if manifest.latitude is None:
        out.append(("outside_buffer", {"reason": "no_position"}))
    else:
        buffer_m = item.buffer_m if item and item.buffer_m is not None else setting(country, "plot_buffer_m")
        dist = distance_to_site(manifest.latitude, manifest.longitude, item)
        if dist is not None and dist > buffer_m:
            out.append(("outside_buffer", {"reason": "distance", "distance_m": round(dist, 1),
                                           "buffer_m": buffer_m}))
        max_acc = setting(country, "max_accuracy_m")
        if manifest.accuracy_m is not None and float(manifest.accuracy_m) > max_acc:
            out.append(("outside_buffer", {"reason": "accuracy", "accuracy_m": float(manifest.accuracy_m),
                                           "max_accuracy_m": max_acc}))
        if manifest.location_mock:
            out.append(("outside_buffer", {"reason": "mock"}))
    # Time
    gap_s = setting(country, "device_time_gap_s")
    if manifest.corrected_capture_at > manifest.received_at + timedelta(seconds=gap_s):
        out.append(("time_gap", {"reason": "device_clock_ahead", "seconds": int(
            (manifest.corrected_capture_at - manifest.received_at).total_seconds())}))
    age_days = setting(country, "max_capture_age_days")
    if manifest.received_at - manifest.corrected_capture_at > timedelta(days=age_days):
        out.append(("time_gap", {"reason": "captured_long_before_upload", "days": (
            manifest.received_at - manifest.corrected_capture_at).days}))
    # Order
    if item is not None and item.previous_pass_at and manifest.corrected_capture_at < item.previous_pass_at:
        out.append(("before_previous_pass", {"previous_pass_at": item.previous_pass_at.isoformat(),
                                             "captured_at": manifest.corrected_capture_at.isoformat()}))
    # Duplicate: same hash, or a near-identical image, on another project
    project = manifest.project_key or f"{manifest.subject_type}:{manifest.subject_id}"
    others = Evidence.objects.filter(sha256=evidence.sha256).exclude(pk=evidence.pk)
    for o in others.select_related("manifest")[:20]:
        if _project_of(o) != project:
            out.append(("duplicate_hash", {"match": "exact", "other_evidence_id": str(o.pk)}))
            break
    else:
        if evidence.phash:
            limit = setting(country, "phash_max_distance")
            cands = Evidence.objects.filter(country=country).exclude(phash="").exclude(pk=evidence.pk) \
                .exclude(sha256=evidence.sha256).order_by("-received_at").select_related("manifest")[:500]
            for o in cands:
                if _project_of(o) != project and phash_distance(evidence.phash, o.phash) <= limit:
                    out.append(("duplicate_hash", {"match": "near", "other_evidence_id": str(o.pk)}))
                    break
    # Metadata
    meta = evidence.metadata or {}
    expected_model = (cam.get("model") or device.model or "").strip().lower()
    exif_model = (meta.get("exif_model") or "").strip().lower()
    if exif_model and expected_model and exif_model != expected_model:
        out.append(("metadata_mismatch", {"field": "model", "exif": meta.get("exif_model"),
                                          "device": cam.get("model") or device.model}))
    if meta.get("exif_datetime"):
        try:
            tz = ZoneInfo(country.timezone)
            exif_dt = datetime.strptime(meta["exif_datetime"], "%Y:%m:%d %H:%M:%S").replace(tzinfo=tz)
            diff = abs((exif_dt - manifest.captured_at_device).total_seconds())
            tol = setting(country, "exif_time_tolerance_s")
            if diff > tol:
                out.append(("metadata_mismatch", {"field": "time", "exif": meta["exif_datetime"],
                                                  "seconds": int(diff)}))
        except (ValueError, KeyError):
            out.append(("metadata_mismatch", {"field": "time", "exif": meta.get("exif_datetime")}))
    return out
