"""GEO API serializers. Geometry is GeoJSON in WGS 84 (longitude, latitude)."""
import json

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (Asset, AssetAccess, BoundaryVersion, MonitoringAlert, MonitoringEnrolment, OverlapFlag,
                     OverlayLayer, OverlayLayerVersion, OverlayResult, OverlayRun, SatelliteImage)

GEOMETRY_SCHEMA = {
    "type": "object",
    "description": "GeoJSON geometry in WGS 84 (EPSG:4326), longitude first.",
    "properties": {"type": {"type": "string", "example": "MultiPolygon"},
                   "coordinates": {"type": "array", "items": {}}},
    "required": ["type", "coordinates"],
}
LNGLAT_SCHEMA = {
    "type": "object",
    "properties": {"lng": {"type": "number", "example": -0.187}, "lat": {"type": "number", "example": 5.603}},
    "required": ["lng", "lat"],
}


@extend_schema_field(GEOMETRY_SCHEMA)
class GeometryField(serializers.Field):
    def __init__(self, **kw):
        kw.setdefault("read_only", True)
        super().__init__(**kw)

    def to_representation(self, geom):
        return json.loads(geom.geojson) if geom is not None else None


@extend_schema_field(LNGLAT_SCHEMA)
class LngLatField(serializers.Field):
    def to_representation(self, point):
        if point is None:
            return None
        if isinstance(point, dict):
            return {"lng": float(point["lng"]), "lat": float(point["lat"])}
        return {"lng": round(point.x, 7), "lat": round(point.y, 7)}

    def to_internal_value(self, data):
        if not isinstance(data, dict) or "lng" not in data or "lat" not in data:
            raise serializers.ValidationError('Use {"lng": -0.187, "lat": 5.603}.')
        try:
            return {"lng": float(data["lng"]), "lat": float(data["lat"])}
        except (TypeError, ValueError):
            raise serializers.ValidationError("lng and lat must be numbers.")


# --------------------------------------------------------------------------- assets


class BoundarySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = BoundaryVersion
        fields = ["id", "version", "source", "area_sqm", "area_acres", "perimeter_m", "created_at"]


class AssetSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    owner_name = serializers.SerializerMethodField()
    location = LngLatField(read_only=True)
    current_boundary = BoundarySummarySerializer(read_only=True)
    monitoring_active = serializers.SerializerMethodField()
    open_alerts = serializers.SerializerMethodField()

    class Meta:
        model = Asset
        fields = ["id", "reference", "type", "name", "country", "owner", "owner_name", "region", "district",
                  "locality", "address", "plot_number", "site_plan_ref", "ghana_post_gps", "location",
                  "location_source", "current_boundary", "disputed_flag", "disputed_reason", "verified_at",
                  "listed_at", "monitoring_active", "open_alerts", "created_at", "updated_at", "row_version"]
        read_only_fields = fields

    def get_owner_name(self, obj) -> str:
        return obj.owner.full_name if obj.owner_id else ""

    def get_monitoring_active(self, obj) -> bool:
        return obj.enrolments.filter(status="active").exists()

    def get_open_alerts(self, obj) -> int:
        return obj.monitoring_alerts.filter(status__in=["open", "under_review"]).count()


class AssetCreateSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2, required=False,
                                    help_text="ISO code. Defaults to your home country.")
    owner_id = serializers.UUIDField(required=False, help_text="Staff only: the client who owns the property.")
    type = serializers.ChoiceField(choices=Asset.TYPES, default="plot")
    name = serializers.CharField(required=False, allow_blank=True, default="")
    region = serializers.CharField(required=False, allow_blank=True, default="")
    district = serializers.CharField(required=False, allow_blank=True, default="")
    locality = serializers.CharField()
    address = serializers.CharField(required=False, allow_blank=True, default="")
    plot_number = serializers.CharField(required=False, allow_blank=True, default="")
    site_plan_ref = serializers.CharField(required=False, allow_blank=True, default="")
    ghana_post_gps = serializers.CharField(required=False, allow_blank=True, default="",
                                           help_text="Digital address, saved as text.")
    location = LngLatField(required=False, allow_null=True,
                           help_text="Only a point the user confirmed. Never guessed.")


class AssetUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False, allow_blank=True)
    region = serializers.CharField(required=False, allow_blank=True)
    district = serializers.CharField(required=False, allow_blank=True)
    locality = serializers.CharField(required=False)
    address = serializers.CharField(required=False, allow_blank=True)
    plot_number = serializers.CharField(required=False, allow_blank=True)
    site_plan_ref = serializers.CharField(required=False, allow_blank=True)
    ghana_post_gps = serializers.CharField(required=False, allow_blank=True)
    location = LngLatField(required=False, allow_null=True)


class DisputedFlagSerializer(serializers.Serializer):
    disputed = serializers.BooleanField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class AssetAccessGrantSerializer(serializers.ModelSerializer):
    person_name = serializers.CharField(source="person.full_name", read_only=True)

    class Meta:
        model = AssetAccess
        fields = ["id", "asset", "person", "person_name", "role", "case_id", "granted_by", "expires_at",
                  "revoked_at", "created_at"]
        read_only_fields = fields


class AssetAccessGrantCreateSerializer(serializers.Serializer):
    person_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=AssetAccess.ROLES)
    case_id = serializers.UUIDField(required=False, allow_null=True)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


# --------------------------------------------------------------------------- boundaries


class BoundaryInputSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=BoundaryVersion.SOURCES)
    coordinates = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=3),
        required=False, help_text="Surveyor corner points as [x, y], closed (last point = first).")
    srid = serializers.IntegerField(required=False, default=4326,
                                    help_text="EPSG code of the coordinates, e.g. 4326, 2136 or 25000.")
    geojson = serializers.JSONField(required=False, help_text="A GeoJSON Polygon, MultiPolygon, Feature or "
                                                              "FeatureCollection.")
    points = serializers.ListField(child=LngLatField(), required=False,
                                   help_text="Points drawn on a map; the ring is closed for you.")
    evidence_id = serializers.UUIDField(required=False, allow_null=True,
                                        help_text="The surveyor's file or site plan in the evidence store.")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class BoundaryVersionSerializer(serializers.ModelSerializer):
    centroid = LngLatField(read_only=True)
    geometry = GeometryField(source="geom")
    captured_by_name = serializers.CharField(source="captured_by.full_name", read_only=True)
    is_current = serializers.SerializerMethodField()

    class Meta:
        model = BoundaryVersion
        fields = ["id", "asset", "version", "source", "input_srid", "area_sqm", "area_acres", "perimeter_m",
                  "centroid", "point_count", "evidence", "note", "captured_by", "captured_by_name", "is_current",
                  "geometry", "created_at"]
        read_only_fields = fields

    def get_is_current(self, obj) -> bool:
        return obj.asset.current_boundary_id == obj.pk


class GeoFeatureSerializer(serializers.Serializer):
    type = serializers.CharField(default="Feature")
    id = serializers.CharField(required=False)
    geometry = serializers.JSONField()
    properties = serializers.JSONField()


class GeoFeatureCollectionSerializer(serializers.Serializer):
    type = serializers.CharField(default="FeatureCollection")
    features = GeoFeatureSerializer(many=True)


# --------------------------------------------------------------------------- overlay


class LayerVersionSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = OverlayLayerVersion
        fields = ["id", "version", "status", "source", "valid_from", "feature_count", "created_at"]


class OverlayResultSerializer(serializers.ModelSerializer):
    layer_id = serializers.UUIDField(source="layer_version.layer_id", read_only=True)
    layer_code = serializers.CharField(source="layer_version.layer.code", read_only=True)
    layer_name = serializers.CharField(source="layer_version.layer.name", read_only=True)
    layer_kind = serializers.CharField(source="layer_version.layer.kind", read_only=True)
    is_sample = serializers.BooleanField(source="layer_version.layer.is_sample", read_only=True)
    layer_version = LayerVersionSummarySerializer(read_only=True)

    class Meta:
        model = OverlayResult
        fields = ["id", "boundary", "run", "layer_id", "layer_code", "layer_name", "layer_kind", "is_sample",
                  "layer_version", "outcome", "distance_m", "buffer_m", "affected_area_sqm", "affected_share",
                  "feature_names", "computed_at"]
        read_only_fields = fields


class OverlayRunItemSerializer(serializers.Serializer):
    layer_id = serializers.UUIDField()
    layer_code = serializers.CharField()
    layer_name = serializers.CharField()
    layer_kind = serializers.CharField()
    is_sample = serializers.BooleanField()
    layer_version_id = serializers.UUIDField(required=False)
    layer_version = serializers.IntegerField(required=False)
    status = serializers.ChoiceField(choices=["checked", "missing", "failed"])
    outcome = serializers.ChoiceField(choices=OverlayResult.OUTCOMES, required=False)
    result_id = serializers.UUIDField(required=False)
    reused = serializers.BooleanField(required=False)
    message = serializers.CharField(required=False)


class VerdictReasonSerializer(serializers.Serializer):
    verdict = serializers.ChoiceField(choices=["red", "amber", "green"])
    layer = serializers.CharField(allow_blank=True)
    message = serializers.CharField()


class OverlayRunSerializer(serializers.ModelSerializer):
    boundary_version = serializers.IntegerField(source="boundary.version", read_only=True)
    items = OverlayRunItemSerializer(many=True, read_only=True)
    verdict_reasons = VerdictReasonSerializer(many=True, read_only=True)
    results = OverlayResultSerializer(many=True, read_only=True, source="result_list")

    class Meta:
        model = OverlayRun
        fields = ["id", "asset", "boundary", "boundary_version", "status", "trigger", "proposed_verdict",
                  "verdict_reasons", "layers_expected", "layers_checked", "items", "results", "started_at",
                  "completed_at", "duration_ms", "error", "created_at"]
        read_only_fields = fields


class Section7Serializer(serializers.Serializer):
    asset_id = serializers.UUIDField()
    boundary_id = serializers.UUIDField(allow_null=True)
    proposed_verdict = serializers.ChoiceField(choices=["red", "amber", "green"], allow_null=True,
                                               help_text="Proposed for report section 7; the lawyer decides.")
    status = serializers.CharField(help_text="completed, incomplete, failed, pending or no_boundary")
    reasons = VerdictReasonSerializer(many=True)
    run = OverlayRunSerializer(allow_null=True)
    history = OverlayRunSerializer(many=True, help_text="Earlier runs, newest first, with their layer versions.")


class OverlapOtherSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    reference = serializers.CharField()
    locality = serializers.CharField()
    plot_number = serializers.CharField()
    owner_name = serializers.CharField()
    verified_at = serializers.DateTimeField(allow_null=True)
    listed_at = serializers.DateTimeField(allow_null=True)


class OverlapFlagSerializer(serializers.ModelSerializer):
    asset_reference = serializers.CharField(source="asset.reference", read_only=True)
    other_asset = serializers.SerializerMethodField()
    resolved_by_name = serializers.SerializerMethodField()

    class Meta:
        model = OverlapFlag
        fields = ["id", "asset", "asset_reference", "boundary", "other_asset", "other_boundary", "other_kind",
                  "overlap_area_sqm", "overlap_share", "other_overlap_share", "status", "resolution",
                  "resolution_note", "resolved_by", "resolved_by_name", "resolved_at", "created_at"]
        read_only_fields = fields

    @extend_schema_field(OverlapOtherSerializer)
    def get_other_asset(self, obj):
        o = obj.other_asset
        return {"id": o.pk, "reference": o.reference, "locality": o.locality, "plot_number": o.plot_number,
                "owner_name": o.owner.full_name if o.owner_id else "", "verified_at": o.verified_at,
                "listed_at": o.listed_at}

    def get_resolved_by_name(self, obj) -> str:
        return obj.resolved_by.full_name if obj.resolved_by_id else ""


class OverlapResolveSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["confirmed", "dismissed"])
    note = serializers.CharField()


# --------------------------------------------------------------------------- satellite


class SatelliteImageSerializer(serializers.ModelSerializer):
    content_url = serializers.SerializerMethodField()

    class Meta:
        model = SatelliteImage
        fields = ["id", "asset", "boundary", "purpose", "status", "provider", "scene_id", "captured_on",
                  "cloud_cover", "resolution_m", "built_up_index", "vegetation_index", "evidence", "gap_reason",
                  "report_id", "content_url", "created_at"]
        read_only_fields = fields

    def get_content_url(self, obj) -> str | None:
        return f"/v1/satellite-images/{obj.pk}/content" if obj.evidence_id else None


class SatelliteFetchSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=SatelliteImage.PURPOSES, default="on_request")
    report_id = serializers.UUIDField(required=False, allow_null=True)


class ReportImageSerializer(serializers.Serializer):
    available = serializers.BooleanField()
    image_id = serializers.UUIDField()
    evidence_id = serializers.UUIDField(allow_null=True)
    captured_on = serializers.DateField(allow_null=True)
    provider = serializers.CharField(allow_blank=True)
    scene_id = serializers.CharField(allow_blank=True)
    section_4_text = serializers.CharField()
    gap = serializers.CharField(allow_blank=True)


# --------------------------------------------------------------------------- layers


class OverlayLayerSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    current_version = LayerVersionSummarySerializer(read_only=True)
    effective_buffer_m = serializers.SerializerMethodField()

    class Meta:
        model = OverlayLayer
        fields = ["id", "country", "code", "name", "kind", "description", "buffer_m", "effective_buffer_m",
                  "status", "is_sample", "current_version", "created_at", "updated_at"]
        read_only_fields = fields

    def get_effective_buffer_m(self, obj) -> str:
        from .services import layer_buffer

        return f"{layer_buffer(obj):.2f}"


class OverlayLayerCreateSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    code = serializers.SlugField(max_length=64)
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=OverlayLayer.KINDS)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    buffer_m = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True,
                                        min_value=0, help_text="Leave empty to use the country setting.")
    is_sample = serializers.BooleanField(required=False, default=False)


class OverlayLayerUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    buffer_m = serializers.DecimalField(max_digits=10, decimal_places=2, required=False, allow_null=True,
                                        min_value=0)


class LayerStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["active", "retired"])
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class OverlayLayerVersionSerializer(serializers.ModelSerializer):
    loaded_by_name = serializers.CharField(source="loaded_by.full_name", read_only=True)

    class Meta:
        model = OverlayLayerVersion
        fields = ["id", "layer", "version", "status", "source", "source_format", "input_srid", "valid_from",
                  "feature_count", "sha256", "evidence", "note", "loaded_by", "loaded_by_name", "created_at"]
        read_only_fields = fields


class LayerUploadSerializer(serializers.Serializer):
    file = serializers.FileField(required=False, help_text="GeoJSON FeatureCollection of polygons.")
    geojson = serializers.JSONField(required=False, help_text="The same, sent inline as JSON.")
    source = serializers.CharField(help_text="Who published the map and which edition.")
    valid_from = serializers.DateField(required=False, allow_null=True)
    srid = serializers.IntegerField(required=False, default=4326)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    recheck = serializers.BooleanField(required=False, default=False,
                                       help_text="Re-check unverified plots against the new version now.")


class OverlayRecheckSerializer(serializers.Serializer):
    asset_ids = serializers.ListField(child=serializers.UUIDField(), required=False)


class OverlayRecheckResultSerializer(serializers.Serializer):
    runs = OverlayRunSerializer(many=True)


class CountryExtentInputSerializer(serializers.Serializer):
    geojson = serializers.JSONField()
    label = serializers.CharField(required=False, allow_blank=True, default="")


class CountryExtentSerializer(serializers.Serializer):
    country = serializers.CharField()
    label = serializers.CharField()
    geometry = GeometryField()
    updated_at = serializers.DateTimeField()


# --------------------------------------------------------------------------- monitoring


class MonitoringEnrolmentSerializer(serializers.ModelSerializer):
    asset_reference = serializers.CharField(source="asset.reference", read_only=True)
    baseline_date = serializers.DateField(source="baseline_image.captured_on", read_only=True, allow_null=True)

    class Meta:
        model = MonitoringEnrolment
        fields = ["id", "asset", "asset_reference", "reason", "source_id", "status", "baseline_image",
                  "baseline_date", "last_checked_at", "ended_at", "ended_reason", "enrolled_by", "created_at"]
        read_only_fields = fields


class MonitoringEnrolSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=["manual"], default="manual")


class EndEnrolmentSerializer(serializers.Serializer):
    reason = serializers.CharField()


class MonitoringAlertSerializer(serializers.ModelSerializer):
    asset_reference = serializers.CharField(source="asset.reference", read_only=True)
    previous_image = SatelliteImageSerializer(read_only=True)
    new_image = SatelliteImageSerializer(read_only=True)
    assigned_to_name = serializers.SerializerMethodField()

    class Meta:
        model = MonitoringAlert
        fields = ["id", "asset", "asset_reference", "enrolment", "previous_image", "new_image", "previous_date",
                  "new_date", "change_score", "threshold", "change_kind", "status", "assigned_to",
                  "assigned_to_name", "resolution", "resolution_note", "resolution_evidence", "resolved_by",
                  "resolved_at", "created_at"]
        read_only_fields = fields

    def get_assigned_to_name(self, obj) -> str:
        return obj.assigned_to.full_name if obj.assigned_to_id else ""


class AlertResolveSerializer(serializers.Serializer):
    resolution = serializers.ChoiceField(choices=MonitoringAlert.RESOLUTIONS)
    note = serializers.CharField()
    evidence_id = serializers.UUIDField(required=False, allow_null=True)


class MonitoringRunInputSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2, required=False)
    asset_ids = serializers.ListField(child=serializers.UUIDField(), required=False)
    before = serializers.DateField(required=False, allow_null=True,
                                   help_text="Use imagery up to this date (testing and back-fills).")


class MonitoringRunResultSerializer(serializers.Serializer):
    checked = serializers.IntegerField()
    alerts = serializers.IntegerField()
    skipped_flag_off = serializers.IntegerField()
    alert_ids = serializers.ListField(child=serializers.UUIDField())


# --------------------------------------------------------------------------- digital address


class DigitalAddressSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["resolved", "not_found", "unavailable"])
    code = serializers.CharField()
    location = LngLatField(allow_null=True)
    accuracy_m = serializers.FloatField(allow_null=True)
    message = serializers.CharField()

