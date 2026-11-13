"""Parsing and validating geometry from surveyors, uploads and drawn points.

Every error is a plain sentence a surveyor or administrator can act on
(TC-GEO-001-02, TC-GEO-004-02). Nothing is saved when parsing fails.
"""
import json

from django.contrib.gis.gdal import SpatialReference
from django.contrib.gis.gdal.error import GDALException
from django.contrib.gis.geos import GEOSGeometry, LinearRing, MultiPolygon, Polygon
from django.contrib.gis.geos.error import GEOSException

from core.errors import Invalid

WGS84 = 4326
_CRS84 = {"urn:ogc:def:crs:OGC:1.3:CRS84", "urn:ogc:def:crs:OGC::CRS84", "EPSG:4326", "urn:ogc:def:crs:EPSG::4326"}


def bad(message, code="geometry-invalid", **extra):
    return Invalid(message, code=code, extra=extra)


def check_srid(srid) -> int:
    try:
        srid = int(srid)
        SpatialReference(srid)
    except (TypeError, ValueError, GDALException):
        raise bad(f"The coordinate system EPSG:{srid} is not known. Use a valid EPSG code.", code="projection-invalid")
    return srid


def _pairs(points, label="coordinates"):
    if not isinstance(points, (list, tuple)):
        raise bad(f"The {label} must be a list of [x, y] pairs.")
    out = []
    for i, p in enumerate(points):
        if isinstance(p, dict):
            p = [p.get("lng", p.get("x", p.get("easting"))), p.get("lat", p.get("y", p.get("northing")))]
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise bad(f"Point {i + 1} is not an [x, y] pair.", pointer=f"/{label}/{i}")
        try:
            out.append((float(p[0]), float(p[1])))
        except (TypeError, ValueError):
            raise bad(f"Point {i + 1} has a value that is not a number.", pointer=f"/{label}/{i}")
    return out


def ring_from_points(points, *, close=False, label="coordinates"):
    pts = _pairs(points, label)
    if close and pts and pts[0] != pts[-1]:
        pts.append(pts[0])
    distinct = {p for p in pts}
    if len(distinct) < 3:
        raise bad("A boundary needs at least 3 different corner points.")
    if pts[0] != pts[-1]:
        raise bad("The boundary is not closed. The last point must be the same as the first.",
                  code="geometry-unclosed")
    if len(pts) < 4:
        raise bad("A boundary needs at least 3 different corner points.")
    return pts


def _ensure_lonlat(geom, srid):
    if srid != WGS84:
        return
    for x, y in _coords(geom):
        if not (-180 <= x <= 180 and -90 <= y <= 90):
            raise bad("These coordinates are not longitude and latitude. Give the coordinate system "
                      "(EPSG code) they were measured in.", code="projection-invalid")


def _coords(geom):
    if isinstance(geom, MultiPolygon):
        for poly in geom:
            yield from _coords(poly)
    elif isinstance(geom, Polygon):
        for ring in geom:
            yield from ring.coords


def to_multipolygon(geom, srid=WGS84, *, what="The boundary"):
    """Validate, transform to WGS 84 and return a MultiPolygon."""
    if geom.geom_type == "Polygon":
        geom = MultiPolygon(geom, srid=geom.srid)
    if geom.geom_type != "MultiPolygon":
        raise bad(f"{what} must be a polygon, not a {geom.geom_type}.")
    if geom.empty:
        raise bad(f"{what} is empty.")
    geom.srid = srid
    _ensure_lonlat(geom, srid)
    if not geom.valid:
        reason = geom.valid_reason
        if "Self-intersection" in reason or "Ring Self-intersection" in reason:
            raise bad(f"{what} crosses itself. Check the order of the corner points. ({reason})",
                      code="geometry-self-intersecting")
        raise bad(f"{what} is not a valid shape: {reason}.")
    if srid != WGS84:
        try:
            geom.transform(WGS84)
        except (GDALException, GEOSException):
            raise bad("The coordinates could not be converted to longitude and latitude.", code="projection-invalid")
        _ensure_lonlat(geom, WGS84)
    return geom


def polygon_from_points(points, srid=WGS84, *, close=False):
    shell = ring_from_points(points, close=close)
    try:
        poly = Polygon(LinearRing(shell), srid=srid)
    except (GEOSException, ValueError, TypeError) as exc:
        raise bad(f"The points do not make a polygon: {exc}.")
    return to_multipolygon(poly, srid)


def _crs_srid(obj, default):
    crs = obj.get("crs") if isinstance(obj, dict) else None
    if not crs:
        return default
    name = (crs.get("properties") or {}).get("name", "") if isinstance(crs, dict) else ""
    if name in _CRS84:
        return WGS84
    if "EPSG" in name:
        try:
            return check_srid(name.replace("::", ":").split(":")[-1])
        except Invalid:
            raise
    raise bad(f"The file uses a coordinate system that is not supported ({name or 'unnamed'}). "
              "Save it as WGS 84 (EPSG:4326).", code="projection-invalid")


def load_json(data):
    if isinstance(data, (bytes, bytearray)):
        try:
            data = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise bad("The file is not a GeoJSON text file.", code="layer-file-invalid")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            raise bad(f"The file is not valid GeoJSON: {exc.msg} at line {exc.lineno}.", code="layer-file-invalid")
    if not isinstance(data, dict) or "type" not in data:
        raise bad("The file is not GeoJSON: it has no 'type'.", code="layer-file-invalid")
    return data


def geometry_from_geojson(obj, srid=WGS84, *, what="The boundary"):
    try:
        g = GEOSGeometry(json.dumps(obj))
    except (GEOSException, GDALException, ValueError, TypeError) as exc:
        raise bad(f"{what} geometry cannot be read: {exc}.")
    return to_multipolygon(g, srid, what=what)


def boundary_from_geojson(data, srid=WGS84):
    """A Polygon, MultiPolygon, Feature or FeatureCollection of polygons, as one MultiPolygon."""
    obj = load_json(data)
    srid = _crs_srid(obj, srid)
    kind = obj.get("type")
    if kind == "FeatureCollection":
        geoms = [f.get("geometry") for f in obj.get("features") or []]
    elif kind == "Feature":
        geoms = [obj.get("geometry")]
    else:
        geoms = [obj]
    geoms = [g for g in geoms if g]
    if not geoms:
        raise bad("The file has no polygon in it.")
    polys = []
    for g in geoms:
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            raise bad(f"The boundary must be a polygon, not a {g.get('type')}.")
        for ring_set in ([g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]):
            for ring in ring_set:
                ring_from_points(ring)  # closed, at least 3 points
        polys.extend(geometry_from_geojson(g, srid))
    mp = MultiPolygon(*polys, srid=WGS84)
    if not mp.valid:
        raise bad("The polygons in the file overlap each other. Upload one plot boundary.",
                  code="geometry-self-intersecting")
    return mp, srid


def layer_features(data, srid=WGS84):
    """Parse a layer file. Returns ([(name, properties, MultiPolygon)], srid). Rejects the whole
    file with the reasons when any feature is bad (TC-GEO-004-02)."""
    obj = load_json(data)
    srid = _crs_srid(obj, srid)
    if obj.get("type") != "FeatureCollection":
        raise bad("A layer file must be a GeoJSON FeatureCollection.", code="layer-file-invalid")
    feats = obj.get("features") or []
    if not feats:
        raise bad("The layer file has no features.", code="layer-file-invalid")
    out, problems = [], []
    for i, f in enumerate(feats):
        g = (f or {}).get("geometry")
        props = (f or {}).get("properties") or {}
        name = str(props.get("name") or props.get("NAME") or f"Feature {i + 1}")
        if not g:
            problems.append({"feature": i + 1, "message": "Feature has no geometry."})
            continue
        if g.get("type") not in ("Polygon", "MultiPolygon"):
            problems.append({"feature": i + 1, "message": f"Feature is a {g.get('type')}; only polygons are allowed."})
            continue
        try:
            out.append((name, props, geometry_from_geojson(g, srid, what=f"Feature {i + 1}")))
        except Invalid as exc:
            problems.append({"feature": i + 1, "message": exc.detail})
    if problems:
        raise Invalid(f"The layer file was rejected: {len(problems)} feature(s) are not valid. "
                      "Nothing was loaded and the active version is unchanged.",
                      code="layer-file-invalid", extra={"problems": problems[:50]})
    return out, srid


def as_geojson(geom) -> dict:
    return json.loads(geom.geojson) if geom is not None else None
