"""GEO Geospatial checks and monitoring (FR-GEO-001 to 008, document 02 sections 6.4 and 6.8).

Geometry is stored in WGS 84 (SRID 4326). Areas and distances are always
computed on the geography type, so they are in metres and square metres.

Append-only tables (enforced again in dbsql.py): boundary versions, overlay
features, overlay results and satellite images. A boundary is never edited:
a new version is added and the asset points at it.
"""
from django.conf import settings
from django.contrib.gis.db import models as gis
from django.db import models

from core import state
from core.models import BaseModel, CountryScopedModel

SQM_PER_ACRE = 4046.8564224


class Asset(CountryScopedModel):
    """A plot of land, a house or building, an off-plan unit or a managed property."""

    TYPES = ["plot", "building", "offplan_unit", "managed_property"]
    LOCATION_SOURCES = ["none", "digital_address_confirmed", "manual", "boundary"]

    reference = models.TextField(unique=True)
    type = models.TextField(choices=[(t, t) for t in TYPES], default="plot")
    name = models.TextField(blank=True, default="")  # the client's own label, e.g. "Plot at Oyarifa"
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                              related_name="geo_assets")
    region = models.TextField(blank=True, default="")
    district = models.TextField(blank=True, default="")
    locality = models.TextField()
    address = models.TextField(blank=True, default="")
    plot_number = models.TextField(blank=True, default="")
    site_plan_ref = models.TextField(blank=True, default="")
    ghana_post_gps = models.TextField(blank=True, default="")  # the country's digital address, saved as text
    location = gis.PointField(srid=4326, null=True, blank=True)
    location_source = models.TextField(choices=[(s, s) for s in LOCATION_SOURCES], default="none")
    current_boundary = models.ForeignKey("BoundaryVersion", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    disputed_flag = models.BooleanField(default=False)  # drives RUL-17
    disputed_reason = models.TextField(blank=True, default="")
    verified_at = models.DateTimeField(null=True, blank=True)  # a released report covers this plot (FR-GEO-005)
    listed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "geo_asset"
        indexes = [models.Index(fields=["country", "locality", "plot_number"])]

    def __str__(self):
        return self.reference


class AssetAccess(CountryScopedModel):
    """A professional's access to an asset while assigned (SV asg, LW asg in 02 7.4).

    CASE grants and revokes these when it assigns field work; staff can too."""

    ROLES = ["SV", "LW", "IN", "QS", "RN", "CE"]
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="access_grants")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    role = models.CharField(max_length=4, choices=[(r, r) for r in ROLES])
    case_id = models.UUIDField(null=True, blank=True)  # CASE case, when granted by an assignment
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "geo_asset_access"


class BoundaryVersion(CountryScopedModel):
    """One saved shape of a plot. Never edited (FR-GEO-001)."""

    SOURCES = ["surveyor_coordinates", "digitised_site_plan", "geojson_upload", "drawn", "records_programme"]
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="boundaries")
    version = models.PositiveIntegerField()
    geom = gis.MultiPolygonField(srid=4326)
    source = models.TextField(choices=[(s, s) for s in SOURCES])
    input_srid = models.PositiveIntegerField(default=4326)  # the coordinate system the coordinates came in
    area_sqm = models.DecimalField(max_digits=14, decimal_places=2)
    area_acres = models.DecimalField(max_digits=12, decimal_places=4)
    perimeter_m = models.DecimalField(max_digits=12, decimal_places=2)
    centroid = gis.PointField(srid=4326)
    point_count = models.PositiveIntegerField()
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")  # the surveyor's file or site plan
    note = models.TextField(blank=True, default="")
    captured_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "geo_boundary_version"
        constraints = [models.UniqueConstraint(fields=["asset", "version"], name="geo_boundary_version_uq")]


class CountryExtent(CountryScopedModel):
    """The land area a country covers, loaded by an administrator. Coordinates
    outside it are refused, which catches swapped latitude and longitude."""

    geom = gis.MultiPolygonField(srid=4326)
    label = models.TextField(blank=True, default="")
    loaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "geo_country_extent"
        constraints = [models.UniqueConstraint(fields=["country"], name="geo_country_extent_uq")]


class OverlayLayer(CountryScopedModel):
    """A map layer a plot is checked against. Configuration per country (FR-CTY-001)."""

    KINDS = ["government_acquisition", "forest_reserve", "road_reserve", "waterway", "wetland", "flood_zone",
             "known_dispute", "planning_zone", "other"]
    code = models.SlugField(max_length=64)
    name = models.TextField()
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    description = models.TextField(blank=True, default="")
    buffer_m = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)  # null = setting
    status = models.TextField(default="draft")
    is_sample = models.BooleanField(default=False)  # fictional demonstration data
    current_version = models.ForeignKey("OverlayLayerVersion", null=True, blank=True, on_delete=models.PROTECT,
                                        related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "geo_overlay_layer"
        constraints = [models.UniqueConstraint(fields=["country", "code"], name="geo_layer_code_uq")]


LAYER = state.register("overlay_layer", "geo_overlay_layer", {
    "draft": {"active", "retired"},
    "active": {"retired"},
    "retired": {"active"},
})


class OverlayLayerVersion(CountryScopedModel):
    """One loaded file of a layer. Old versions are kept so old results stay traceable (FR-GEO-004)."""

    layer = models.ForeignKey(OverlayLayer, on_delete=models.PROTECT, related_name="versions")
    version = models.PositiveIntegerField()
    status = models.TextField(default="active")
    source = models.TextField()  # who published the map and when, e.g. "Lands Commission sheet 0503 [TO VERIFY]"
    source_format = models.TextField(default="geojson")
    input_srid = models.PositiveIntegerField(default=4326)
    valid_from = models.DateField(null=True, blank=True)
    feature_count = models.PositiveIntegerField()
    sha256 = models.CharField(max_length=64)
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")  # the uploaded file, write-once
    note = models.TextField(blank=True, default="")
    loaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "geo_overlay_layer_version"
        constraints = [models.UniqueConstraint(fields=["layer", "version"], name="geo_layer_version_uq")]


LAYER_VERSION = state.register("overlay_layer_version", "geo_overlay_layer_version", {
    "active": {"superseded"},
})


class OverlayFeature(models.Model):
    """One shape of a layer version. Append-only."""

    id = models.BigAutoField(primary_key=True)
    layer_version = models.ForeignKey(OverlayLayerVersion, on_delete=models.PROTECT, related_name="features")
    name = models.TextField(blank=True, default="")
    properties = models.JSONField(default=dict)
    geom = gis.MultiPolygonField(srid=4326)

    class Meta:
        db_table = "geo_overlay_feature"


class OverlayRun(CountryScopedModel):
    """One overlay check of one boundary against every active layer (FR-GEO-002, 003)."""

    TRIGGERS = ["boundary_saved", "recheck", "layer_updated"]
    VERDICTS = ["red", "amber", "green"]
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="overlay_runs")
    boundary = models.ForeignKey(BoundaryVersion, on_delete=models.PROTECT, related_name="overlay_runs")
    status = models.TextField(default="pending")
    trigger = models.TextField(choices=[(t, t) for t in TRIGGERS], default="boundary_saved")
    proposed_verdict = models.TextField(choices=[(v, v) for v in VERDICTS], null=True, blank=True)
    verdict_reasons = models.JSONField(default=list)
    items = models.JSONField(default=list)  # per layer: layer, version, result id or missing/failed
    layers_expected = models.PositiveIntegerField(default=0)
    layers_checked = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "geo_overlay_run"

    @property
    def result_list(self):
        ids = [i["result_id"] for i in self.items or [] if i.get("result_id")]
        return (OverlayResult.objects.filter(pk__in=ids).select_related("layer_version__layer")
                .order_by("layer_version__layer__code"))


RUN = state.register("overlay_run", "geo_overlay_run", {
    "pending": {"completed", "incomplete", "failed"},
})


class OverlayResult(CountryScopedModel):
    """Inside, near or clear for one boundary and one layer version. Append-only."""

    OUTCOMES = ["inside", "near", "clear"]
    boundary = models.ForeignKey(BoundaryVersion, on_delete=models.PROTECT, related_name="overlay_results")
    layer_version = models.ForeignKey(OverlayLayerVersion, on_delete=models.PROTECT, related_name="results")
    run = models.ForeignKey(OverlayRun, on_delete=models.PROTECT, related_name="results")
    outcome = models.TextField(choices=[(o, o) for o in OUTCOMES])
    distance_m = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    buffer_m = models.DecimalField(max_digits=10, decimal_places=2)
    affected_area_sqm = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    affected_share = models.DecimalField(max_digits=7, decimal_places=4, default=0)  # 0 to 1 of the plot
    feature_ids = models.JSONField(default=list)
    feature_names = models.JSONField(default=list)
    computed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "geo_overlay_result"
        constraints = [models.UniqueConstraint(fields=["boundary", "layer_version"], name="geo_result_uq")]


class OverlapFlag(CountryScopedModel):
    """A plot that overlaps another plot on the register (FR-GEO-005)."""

    OTHER_KINDS = ["verified", "listed", "registered"]
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="overlap_flags")
    boundary = models.ForeignKey(BoundaryVersion, on_delete=models.PROTECT, related_name="+")
    other_asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="+")
    other_boundary = models.ForeignKey(BoundaryVersion, on_delete=models.PROTECT, related_name="+")
    other_kind = models.TextField(choices=[(k, k) for k in OTHER_KINDS])
    overlap_area_sqm = models.DecimalField(max_digits=14, decimal_places=2)
    overlap_share = models.DecimalField(max_digits=7, decimal_places=4)  # of this plot
    other_overlap_share = models.DecimalField(max_digits=7, decimal_places=4)  # of the other plot
    status = models.TextField(default="open")
    resolution = models.TextField(blank=True, default="")
    resolution_note = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "geo_overlap_flag"
        constraints = [models.UniqueConstraint(fields=["boundary", "other_boundary"], name="geo_overlap_uq")]


OVERLAP = state.register("overlap_flag", "geo_overlap_flag", {
    "open": {"confirmed", "dismissed", "superseded"},
    "confirmed": {"superseded"},
})


class SatelliteImage(CountryScopedModel):
    """An image of the plot with the boundary drawn, and its date (FR-GEO-006). Append-only."""

    PURPOSES = ["report", "monitoring", "on_request"]
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="satellite_images")
    boundary = models.ForeignKey(BoundaryVersion, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    purpose = models.TextField(choices=[(p, p) for p in PURPOSES], default="report")
    status = models.TextField(choices=[("available", "available"), ("unavailable", "unavailable")])
    provider = models.TextField()
    scene_id = models.TextField(blank=True, default="")
    captured_on = models.DateField(null=True, blank=True)  # the image date shown in the report
    cloud_cover = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    resolution_m = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    built_up_index = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    vegetation_index = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    gap_reason = models.TextField(blank=True, default="")
    report_id = models.UUIDField(null=True, blank=True)  # RPT report, when fetched for a report
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "geo_satellite_image"


class MonitoringEnrolment(CountryScopedModel):
    """Why a plot is watched: a live listing, an active project, or a staff decision (FR-GEO-007)."""

    REASONS = ["listing", "project", "manual"]
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="enrolments")
    reason = models.TextField(choices=[(r, r) for r in REASONS])
    source_id = models.UUIDField(null=True, blank=True)  # listing or project id
    status = models.TextField(default="active")
    baseline_image = models.ForeignKey(SatelliteImage, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="+")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.TextField(blank=True, default="")
    enrolled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "geo_monitoring_enrolment"
        constraints = [models.UniqueConstraint(fields=["asset", "reason", "source_id"],
                                               condition=models.Q(status="active"),
                                               name="geo_enrolment_active_uq")]


ENROLMENT = state.register("monitoring_enrolment", "geo_monitoring_enrolment", {
    "active": {"ended"},
})


class MonitoringAlert(CountryScopedModel):
    """New structures or clearing seen on a watched plot (FR-GEO-007, RUL-13)."""

    CHANGE_KINDS = ["new_structure", "clearing", "other"]
    RESOLUTIONS = ["no_change", "change_explained", "change_confirmed"]
    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="monitoring_alerts")
    enrolment = models.ForeignKey(MonitoringEnrolment, null=True, on_delete=models.PROTECT, related_name="alerts")
    previous_image = models.ForeignKey(SatelliteImage, on_delete=models.PROTECT, related_name="+")
    new_image = models.ForeignKey(SatelliteImage, on_delete=models.PROTECT, related_name="+")
    previous_date = models.DateField(null=True)
    new_date = models.DateField(null=True)
    change_score = models.DecimalField(max_digits=6, decimal_places=4)
    threshold = models.DecimalField(max_digits=6, decimal_places=4)
    change_kind = models.TextField(choices=[(k, k) for k in CHANGE_KINDS])
    status = models.TextField(default="open")
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolution = models.TextField(choices=[(r, r) for r in RESOLUTIONS], blank=True, default="")
    resolution_note = models.TextField(blank=True, default="")
    resolution_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="+")
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "geo_monitoring_alert"


ALERT = state.register("monitoring_alert", "geo_monitoring_alert", {
    "open": {"under_review", "resolved"},
    "under_review": {"resolved", "open"},
})
