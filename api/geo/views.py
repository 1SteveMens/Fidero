"""GEO API (02 section 7.4): assets and boundaries, overlay results, overlaps,
satellite images, monitoring, overlay layers and digital addresses.

Object scoping: a client or owner sees their own assets; staff (CM, RV, AD)
see assets in the countries they hold the role for; professionals see only
assets they are assigned to (AssetAccess)."""
from django.db.models import Q
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.adapters import get_adapter
from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import STAFF_ROLES, has_role
from core.views import ETagMixin
from countries.models import Country

from . import selectors as sel
from . import serializers as S
from . import services
from .geometry import as_geojson
from .models import (Asset, AssetAccess, BoundaryVersion, CountryExtent, MonitoringAlert, MonitoringEnrolment,
                     OverlapFlag, OverlayFeature, OverlayLayer, OverlayLayerVersion, OverlayRun, SatelliteImage)

CASE_STAFF = ("CM", "AD")
READ_STAFF = tuple(STAFF_ROLES)


def _country(code=None, user=None):
    code = code or (user.home_country.code if user is not None and user.home_country_id else None)
    if not code:
        raise Invalid("Give the country code.")
    c = Country.objects.filter(code=str(code).upper()).first()
    if c is None:
        raise Invalid(f"Unknown country {code}.")
    return c


def _require_staff(user, country, *roles):
    if not has_role(user, *(roles or READ_STAFF), country=country):
        raise Forbidden("Only Tenmina staff for this country can do this.")


def _evidence(evidence_id, country):
    if not evidence_id:
        return None
    from evidence.models import Evidence

    ev = Evidence.objects.filter(pk=evidence_id).first()
    if ev is None or ev.country_id != country.pk:
        raise Invalid("The evidence was not found in this country.")
    return ev


def _feature(geom, props, fid=None):
    f = {"type": "Feature", "geometry": as_geojson(geom), "properties": props}
    if fid is not None:
        f["id"] = str(fid)
    return f


# --------------------------------------------------------------------------- assets


@extend_schema_view(
    list=extend_schema(summary="Assets I can see", responses=S.AssetSerializer(many=True)),
    retrieve=extend_schema(summary="One asset", responses=S.AssetSerializer),
    create=extend_schema(summary="Register a plot, building, off-plan unit or managed property",
                         request=S.AssetCreateSerializer, responses={201: S.AssetSerializer}),
    partial_update=extend_schema(summary="Change address details (not the boundary)",
                                 request=S.AssetUpdateSerializer, responses=S.AssetSerializer),
)
class AssetViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = Asset.objects.none()
    serializer_class = S.AssetSerializer
    filterset_fields = ["type", "locality", "disputed_flag"]

    def get_queryset(self):
        qs = sel.visible_assets(self.request.user).select_related("country", "owner", "current_boundary")
        p = self.request.query_params
        if p.get("country"):
            qs = qs.filter(country__code=p["country"].upper())
        if p.get("owner") and has_role(self.request.user, *READ_STAFF):
            qs = qs.filter(owner_id=p["owner"])
        if p.get("q"):
            q = p["q"]
            qs = qs.filter(Q(reference__icontains=q) | Q(locality__icontains=q) | Q(plot_number__icontains=q)
                           | Q(name__icontains=q) | Q(ghana_post_gps__icontains=q))
        return qs

    # helpers ------------------------------------------------------------

    def _asset(self) -> Asset:
        return self.get_object()

    def _can_manage(self, asset):
        user = self.request.user
        return sel.is_owner(user, asset) or sel.is_staff_for(user, asset, *CASE_STAFF)

    def _staff_or_assigned(self, asset, staff=READ_STAFF, assigned=("SV", "LW")):
        user = self.request.user
        if not (sel.is_staff_for(user, asset, *staff) or sel.is_assigned(user, asset, *assigned)):
            raise Forbidden("Only staff and the assigned professionals can see this.")

    # CRUD ---------------------------------------------------------------

    @idempotent
    def create(self, request):
        s = S.AssetCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        user = request.user
        country = _country(d.pop("country", None), user)
        owner_id = d.pop("owner_id", None)
        if has_role(user, *CASE_STAFF, country=country):
            owner = None
            if owner_id:
                from accounts.models import Person

                owner = Person.objects.filter(pk=owner_id).first()
                if owner is None:
                    raise Invalid("The owner was not found.")
        elif has_role(user, "CL", "SE", "DV"):
            if owner_id and str(owner_id) != str(user.pk):
                raise Forbidden("You can only register your own property.")
            owner = user
        else:
            raise Forbidden("Only clients, sellers, developers and case managers can register a property.")
        asset = services.create_asset(actor=user, country=country, owner=owner, **d)
        return Response(S.AssetSerializer(asset).data, status=201)

    def partial_update(self, request, pk=None):
        asset = self._asset()
        if not self._can_manage(asset):
            raise Forbidden("Only the owner or a case manager can change this property.")
        s = S.AssetUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        loc = d.pop("location", ...) if "location" in request.data else ...
        asset = services.update_asset(asset, actor=request.user, location=loc, **d)
        return Response(S.AssetSerializer(asset).data)

    # boundary (FR-GEO-001) ----------------------------------------------

    @extend_schema(methods=["GET"], summary="Current boundary as a GeoJSON Feature",
                   responses=S.GeoFeatureSerializer)
    @extend_schema(methods=["PUT"], summary="Save a new boundary version; runs overlay and overlap checks",
                   request=S.BoundaryInputSerializer, responses={201: S.BoundaryVersionSerializer})
    @action(detail=True, methods=["get", "put"], url_path="boundary")
    def boundary(self, request, pk=None):
        asset = self._asset()
        user = request.user
        if request.method == "GET":
            if asset.current_boundary_id is None:
                raise NotFound("No boundary has been saved for this property yet.")
            b = asset.current_boundary
            return Response(_feature(b.geom, {
                "asset_id": str(asset.pk), "reference": asset.reference, "version": b.version, "source": b.source,
                "area_sqm": str(b.area_sqm), "area_acres": str(b.area_acres), "created_at": b.created_at.isoformat(),
            }, b.pk))
        s = S.BoundaryInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        staff = sel.is_staff_for(user, asset, *CASE_STAFF)
        assigned = sel.is_assigned(user, asset, "SV", "LW")
        if not (staff or assigned):
            if sel.is_owner(user, asset):
                if d["source"] != "drawn":
                    raise Forbidden("You can draw your plot on the map. Surveyor coordinates come from the "
                                    "assigned surveyor.")
            else:
                raise Forbidden("Only the assigned surveyor or a case manager can save the boundary.")
        bv = services.save_boundary(
            asset, actor=user, source=d["source"], coordinates=d.get("coordinates"), geojson=d.get("geojson"),
            points=d.get("points"), srid=d.get("srid") or 4326,
            evidence=_evidence(d.get("evidence_id"), asset.country), note=d.get("note", ""))
        bv = BoundaryVersion.objects.select_related("asset", "captured_by").get(pk=bv.pk)
        return Response(S.BoundaryVersionSerializer(bv).data, status=201)

    @extend_schema(summary="Every boundary version, newest first", responses=S.BoundaryVersionSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="boundaries", pagination_class=None)
    def boundaries(self, request, pk=None):
        asset = self._asset()
        qs = asset.boundaries.select_related("asset", "captured_by").order_by("-version")
        return Response(S.BoundaryVersionSerializer(qs, many=True).data)

    # overlay (FR-GEO-002, 003) ------------------------------------------

    def _section7(self, asset):
        s7 = services.section7(asset)
        history = (OverlayRun.objects.filter(asset=asset).exclude(pk=getattr(s7["run"], "pk", None))
                   .select_related("boundary").order_by("-created_at")[:20])
        return {"asset_id": asset.pk, "boundary_id": asset.current_boundary_id,
                "proposed_verdict": s7["proposed_verdict"], "status": s7["status"], "reasons": s7["reasons"],
                "run": s7["run"], "history": list(history)}

    @extend_schema(summary="Overlay results per layer and the proposed section 7 verdict",
                   responses=S.Section7Serializer)
    @action(detail=True, methods=["get"], url_path="overlay-results")
    def overlay_results(self, request, pk=None):
        asset = self._asset()
        self._staff_or_assigned(asset)
        return Response(S.Section7Serializer(self._section7(asset)).data)

    @extend_schema(summary="Re-run the overlay checks on the current boundary", request=None,
                   responses={201: S.Section7Serializer})
    @action(detail=True, methods=["post"], url_path="overlay-checks")
    @idempotent
    def overlay_checks(self, request, pk=None):
        asset = self._asset()
        _require_staff(request.user, asset.country, *CASE_STAFF)
        services.recheck(asset, actor=request.user)
        return Response(S.Section7Serializer(self._section7(asset)).data, status=201)

    # overlaps (FR-GEO-005) ----------------------------------------------

    @extend_schema(summary="Overlaps with other plots (staff only)", responses=S.OverlapFlagSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="overlaps", pagination_class=None)
    def overlaps(self, request, pk=None):
        asset = self._asset()
        _require_staff(request.user, asset.country)
        qs = (OverlapFlag.objects.filter(asset=asset).select_related("asset", "other_asset__owner", "resolved_by")
              .order_by("-created_at"))
        return Response(S.OverlapFlagSerializer(qs, many=True).data)

    # satellite (FR-GEO-006) ---------------------------------------------

    @extend_schema(summary="Latest satellite image with the boundary drawn", responses=S.SatelliteImageSerializer)
    @action(detail=True, methods=["get"], url_path="satellite-image")
    def satellite_image(self, request, pk=None):
        asset = self._asset()
        img = (SatelliteImage.objects.filter(asset=asset, status="available").order_by("-captured_on", "-created_at")
               .first())
        if img is None:
            img = SatelliteImage.objects.filter(asset=asset).order_by("-created_at").first()
        if img is None:
            raise NotFound("No satellite image has been fetched for this property yet.")
        return Response(S.SatelliteImageSerializer(img).data)

    @extend_schema(methods=["GET"], summary="All satellite images of this property",
                   responses=S.SatelliteImageSerializer(many=True))
    @extend_schema(methods=["POST"], summary="Fetch a new image now (staff)", request=S.SatelliteFetchSerializer,
                   responses={201: S.SatelliteImageSerializer})
    @action(detail=True, methods=["get", "post"], url_path="satellite-images", pagination_class=None)
    def satellite_images(self, request, pk=None):
        asset = self._asset()
        if request.method == "GET":
            qs = SatelliteImage.objects.filter(asset=asset).order_by("-created_at")
            return Response(S.SatelliteImageSerializer(qs, many=True).data)
        return self._fetch(request, asset)

    @idempotent
    def _fetch(self, request, asset):
        _require_staff(request.user, asset.country, *CASE_STAFF)
        s = S.SatelliteFetchSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        img = services.fetch_image(asset, actor=request.user, purpose=s.validated_data["purpose"],
                                   report_id=s.validated_data.get("report_id"))
        return Response(S.SatelliteImageSerializer(img).data, status=201)

    @extend_schema(summary="Image and section 4 text for a report (RPT)", request=S.SatelliteFetchSerializer,
                   responses={201: S.ReportImageSerializer})
    @action(detail=True, methods=["post"], url_path="report-image")
    @idempotent
    def report_image(self, request, pk=None):
        asset = self._asset()
        _require_staff(request.user, asset.country, *CASE_STAFF)
        s = S.SatelliteFetchSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        out = services.image_for_report(asset.pk, report_id=s.validated_data.get("report_id"), actor=request.user)
        return Response(S.ReportImageSerializer(out).data, status=201)

    # map (SCR-BO-07) ----------------------------------------------------

    @extend_schema(summary="Map of the plot: boundary, nearby layer features and overlapping plots (GeoJSON)",
                   responses=S.GeoFeatureCollectionSerializer)
    @action(detail=True, methods=["get"], url_path="map")
    def map(self, request, pk=None):
        asset = self._asset()
        user = request.user
        feats = []
        if asset.current_boundary_id:
            b = asset.current_boundary
            feats.append(_feature(b.geom, {"kind": "boundary", "asset_id": str(asset.pk),
                                           "reference": asset.reference, "version": b.version}, b.pk))
        elif asset.location is not None:
            feats.append(_feature(asset.location, {"kind": "location", "asset_id": str(asset.pk),
                                                   "reference": asset.reference}, asset.pk))
        detailed = sel.is_staff_for(user, asset) or sel.is_assigned(user, asset)
        if detailed and asset.current_boundary_id:
            try:
                radius = min(float(request.query_params.get("radius_m", 500)), 5000.0)
            except ValueError:
                raise Invalid("radius_m must be a number of metres.")
            degrees = radius / 111_320.0  # display only; checks use geography distances
            near = (OverlayFeature.objects.filter(
                layer_version__layer__country=asset.country, layer_version__layer__status="active",
                layer_version__status="active",
                geom__dwithin=(asset.current_boundary.geom, degrees))
                .select_related("layer_version__layer"))
            for f in near[:500]:
                lyr = f.layer_version.layer
                feats.append(_feature(f.geom, {"kind": "layer", "layer_code": lyr.code, "layer_name": lyr.name,
                                               "layer_kind": lyr.kind, "layer_version": f.layer_version.version,
                                               "name": f.name, "is_sample": lyr.is_sample}, f"lf-{f.pk}"))
            if sel.is_staff_for(user, asset):
                for flag in OverlapFlag.objects.filter(boundary_id=asset.current_boundary_id,
                                                       status__in=["open", "confirmed"]).select_related(
                        "other_boundary", "other_asset"):
                    feats.append(_feature(flag.other_boundary.geom, {
                        "kind": "overlap", "flag_id": str(flag.pk), "other_asset_id": str(flag.other_asset_id),
                        "other_reference": flag.other_asset.reference, "status": flag.status,
                        "overlap_area_sqm": str(flag.overlap_area_sqm)}, f"ov-{flag.pk}"))
        return Response({"type": "FeatureCollection", "features": feats})

    # monitoring (FR-GEO-007) ---------------------------------------------

    @extend_schema(methods=["GET"], summary="Monitoring enrolments of this property",
                   responses=S.MonitoringEnrolmentSerializer(many=True))
    @extend_schema(methods=["POST"], summary="Start watching this property (staff)", request=S.MonitoringEnrolSerializer,
                   responses={201: S.MonitoringEnrolmentSerializer})
    @action(detail=True, methods=["get", "post"], url_path="monitoring", pagination_class=None)
    def monitoring(self, request, pk=None):
        asset = self._asset()
        if request.method == "GET":
            qs = asset.enrolments.select_related("asset", "baseline_image").order_by("-created_at")
            return Response(S.MonitoringEnrolmentSerializer(qs, many=True).data)
        _require_staff(request.user, asset.country, *CASE_STAFF)
        e = services.enrol(asset, reason="manual", actor=request.user)
        return Response(S.MonitoringEnrolmentSerializer(e).data, status=201)

    # access and dispute ------------------------------------------------

    @extend_schema(methods=["GET"], summary="Professionals with access", responses=S.AssetAccessGrantSerializer(many=True))
    @extend_schema(methods=["POST"], summary="Give an assigned professional access (staff)",
                   request=S.AssetAccessGrantCreateSerializer, responses={201: S.AssetAccessGrantSerializer})
    @action(detail=True, methods=["get", "post"], url_path="access-grants", pagination_class=None)
    def access_grants(self, request, pk=None):
        asset = self._asset()
        if request.method == "GET":
            _require_staff(request.user, asset.country)
            qs = asset.access_grants.select_related("person").order_by("-created_at")
            return Response(S.AssetAccessGrantSerializer(qs, many=True).data)
        _require_staff(request.user, asset.country, *CASE_STAFF)
        s = S.AssetAccessGrantCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        from accounts.models import Person

        person = Person.objects.filter(pk=s.validated_data["person_id"]).first()
        if person is None:
            raise Invalid("The person was not found.")
        g = services.grant_access(asset, person, role=s.validated_data["role"], actor=request.user,
                                  case_id=s.validated_data.get("case_id"),
                                  expires_at=s.validated_data.get("expires_at"))
        return Response(S.AssetAccessGrantSerializer(g).data, status=201)

    @extend_schema(summary="Mark or clear the disputed flag (RUL-17)", request=S.DisputedFlagSerializer,
                   responses=S.AssetSerializer)
    @action(detail=True, methods=["post"], url_path="disputed-flag")
    def disputed_flag(self, request, pk=None):
        asset = self._asset()
        _require_staff(request.user, asset.country)
        s = S.DisputedFlagSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        asset = services.set_disputed(asset, actor=request.user, **s.validated_data)
        return Response(S.AssetSerializer(asset).data)


class AccessGrantViewSet(viewsets.GenericViewSet):
    queryset = AssetAccess.objects.all()
    serializer_class = S.AssetAccessGrantSerializer

    @extend_schema(summary="Revoke a professional's access", request=None, responses=S.AssetAccessGrantSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        g = AssetAccess.objects.filter(pk=pk).select_related("asset__country", "person").first()
        if g is None:
            raise NotFound()
        _require_staff(request.user, g.asset.country, *CASE_STAFF)
        return Response(S.AssetAccessGrantSerializer(services.revoke_access(g, actor=request.user)).data)


# --------------------------------------------------------------------------- overlap queue


class OverlapFlagViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The back office queue of overlaps. Staff only: it names other clients' plots."""

    queryset = OverlapFlag.objects.none()
    serializer_class = S.OverlapFlagSerializer
    filterset_fields = ["status", "other_kind"]

    def get_queryset(self):
        user = self.request.user
        if not has_role(user, *READ_STAFF):
            return OverlapFlag.objects.none()
        qs = sel.in_country(OverlapFlag.objects.all(), user, READ_STAFF)
        return qs.select_related("asset", "other_asset__owner", "resolved_by")

    @extend_schema(summary="Confirm or dismiss an overlap", request=S.OverlapResolveSerializer,
                   responses=S.OverlapFlagSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def resolve(self, request, pk=None):
        flag = self.get_object()
        _require_staff(request.user, flag.country, *CASE_STAFF)
        s = S.OverlapResolveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        flag = services.resolve_overlap(flag, actor=request.user, **s.validated_data)
        return Response(S.OverlapFlagSerializer(flag).data)


# --------------------------------------------------------------------------- satellite images


class SatelliteImageViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = SatelliteImage.objects.none()
    serializer_class = S.SatelliteImageSerializer

    def get_queryset(self):
        return SatelliteImage.objects.filter(asset__in=sel.visible_assets(self.request.user))

    @extend_schema(summary="The image file (SVG or PNG)", responses={(200, "image/svg+xml"): bytes})
    @action(detail=True, methods=["get"])
    def content(self, request, pk=None):
        img = self.get_object()
        if img.evidence_id is None:
            raise NotFound("This image is not available.")
        data = get_adapter("evidence_store").get(img.evidence.storage_key)
        return HttpResponse(data, content_type=img.evidence.content_type)


# --------------------------------------------------------------------------- monitoring


class MonitoringEnrolmentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = MonitoringEnrolment.objects.none()
    serializer_class = S.MonitoringEnrolmentSerializer
    filterset_fields = ["status", "reason"]

    def get_queryset(self):
        user = self.request.user
        if not has_role(user, *READ_STAFF):
            return MonitoringEnrolment.objects.none()
        return sel.in_country(MonitoringEnrolment.objects.all(), user, READ_STAFF).select_related(
            "asset", "baseline_image")

    @extend_schema(summary="Stop watching", request=S.EndEnrolmentSerializer,
                   responses=S.MonitoringEnrolmentSerializer)
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        e = self.get_object()
        _require_staff(request.user, e.country, *CASE_STAFF)
        s = S.EndEnrolmentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.MonitoringEnrolmentSerializer(
            services.end_enrolment(e, actor=request.user, reason=s.validated_data["reason"])).data)


class MonitoringAlertViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = MonitoringAlert.objects.none()
    serializer_class = S.MonitoringAlertSerializer
    filterset_fields = ["status", "change_kind", "asset"]

    def get_queryset(self):
        user = self.request.user
        if getattr(self, "swagger_fake_view", False) or not user.is_authenticated:
            return MonitoringAlert.objects.none()
        qs = MonitoringAlert.objects.select_related("asset", "previous_image", "new_image", "assigned_to")
        q = Q(asset__owner=user)
        if has_role(user, *READ_STAFF):
            countries = sel.role_countries(user, READ_STAFF)
            if countries is None:
                return qs
            q |= Q(country_id__in=countries)
        return qs.filter(q)

    @extend_schema(summary="Take the alert for review", request=None, responses=S.MonitoringAlertSerializer)
    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        alert = self.get_object()
        _require_staff(request.user, alert.country, *CASE_STAFF)
        return Response(S.MonitoringAlertSerializer(services.take_alert(alert, actor=request.user)).data)

    @extend_schema(summary="Resolve with what was found", request=S.AlertResolveSerializer,
                   responses=S.MonitoringAlertSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def resolve(self, request, pk=None):
        alert = self.get_object()
        _require_staff(request.user, alert.country, *CASE_STAFF)
        s = S.AlertResolveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        alert = services.resolve_alert(alert, actor=request.user, resolution=d["resolution"], note=d["note"],
                                       evidence=_evidence(d.get("evidence_id"), alert.country))
        return Response(S.MonitoringAlertSerializer(alert).data)


class MonitoringRunViewSet(viewsets.GenericViewSet):
    serializer_class = S.MonitoringRunInputSerializer

    @extend_schema(summary="Run the monitoring comparison now (normally weekly)",
                   request=S.MonitoringRunInputSerializer, responses={201: S.MonitoringRunResultSerializer})
    @idempotent
    def create(self, request):
        s = S.MonitoringRunInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        country = _country(d["country"]) if d.get("country") else None
        if country is not None:
            _require_staff(request.user, country, *CASE_STAFF)
        elif sel.role_countries(request.user, CASE_STAFF) is not None:
            raise Forbidden("Give the country you work in.")
        out = services.run_monitoring(country=country, before=d.get("before"), asset_ids=d.get("asset_ids"),
                                      actor=request.user)
        return Response(S.MonitoringRunResultSerializer(out).data, status=201)


# --------------------------------------------------------------------------- overlay layers (admin)


@extend_schema_view(
    list=extend_schema(summary="Overlay layers", responses=S.OverlayLayerSerializer(many=True)),
    retrieve=extend_schema(summary="One overlay layer", responses=S.OverlayLayerSerializer),
    create=extend_schema(summary="Create a layer (administrator)", request=S.OverlayLayerCreateSerializer,
                         responses={201: S.OverlayLayerSerializer}),
    partial_update=extend_schema(summary="Rename or change the buffer (administrator)",
                                 request=S.OverlayLayerUpdateSerializer, responses=S.OverlayLayerSerializer),
)
class OverlayLayerViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = OverlayLayer.objects.none()
    serializer_class = S.OverlayLayerSerializer
    filterset_fields = ["kind", "status"]

    def get_queryset(self):
        user = self.request.user
        if not has_role(user, *READ_STAFF):
            return OverlayLayer.objects.none()
        qs = sel.in_country(OverlayLayer.objects.all(), user, READ_STAFF).select_related("country",
                                                                                         "current_version")
        if self.request.query_params.get("country"):
            qs = qs.filter(country__code=self.request.query_params["country"].upper())
        return qs

    def create(self, request):
        s = S.OverlayLayerCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        country = _country(d.pop("country"))
        _require_staff(request.user, country, "AD")
        layer = services.create_layer(actor=request.user, country=country, **d)
        return Response(S.OverlayLayerSerializer(layer).data, status=201)

    def partial_update(self, request, pk=None):
        layer = self.get_object()
        _require_staff(request.user, layer.country, "AD")
        s = S.OverlayLayerUpdateSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return Response(S.OverlayLayerSerializer(
            services.update_layer(layer, actor=request.user, **s.validated_data)).data)

    @extend_schema(methods=["GET"], summary="Versions of this layer, newest first",
                   responses=S.OverlayLayerVersionSerializer(many=True))
    @extend_schema(methods=["POST"], summary="Upload a new version (GeoJSON). The old one is kept.",
                   request={"multipart/form-data": S.LayerUploadSerializer,
                            "application/json": S.LayerUploadSerializer},
                   responses={201: S.OverlayLayerVersionSerializer})
    @action(detail=True, methods=["get", "post"], url_path="versions", pagination_class=None,
            parser_classes=[MultiPartParser, FormParser, JSONParser])
    def versions(self, request, pk=None):
        layer = self.get_object()
        if request.method == "GET":
            qs = layer.versions.select_related("loaded_by").order_by("-version")
            return Response(S.OverlayLayerVersionSerializer(qs, many=True).data)
        return self._upload(request, layer)

    @idempotent
    def _upload(self, request, layer):
        import json

        _require_staff(request.user, layer.country, "AD")
        s = S.LayerUploadSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        f = d.get("file")
        if f is not None:
            data, name = f.read(), f.name
        elif d.get("geojson") is not None:
            gj = d["geojson"]
            data = (gj if isinstance(gj, str) else json.dumps(gj)).encode()
            name = f"{layer.code}.geojson"
        else:
            raise Invalid("Upload a file or send the GeoJSON.", code="layer-file-invalid")
        v = services.load_layer_version(layer, actor=request.user, data=data, filename=name, source=d["source"],
                                        valid_from=d.get("valid_from"), srid=d.get("srid") or 4326,
                                        note=d.get("note", ""))
        if d.get("recheck"):
            services.recheck_layer(layer, actor=request.user)
        return Response(S.OverlayLayerVersionSerializer(v).data, status=201)

    @extend_schema(summary="Switch a layer on or off", request=S.LayerStatusSerializer,
                   responses=S.OverlayLayerSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, pk=None):
        layer = self.get_object()
        _require_staff(request.user, layer.country, "AD")
        s = S.LayerStatusSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        layer = services.set_layer_status(layer, actor=request.user, **s.validated_data)
        return Response(S.OverlayLayerSerializer(layer).data)

    @extend_schema(summary="Features of a version as GeoJSON (default: the current version)",
                   parameters=[OpenApiParameter("version", int, required=False),
                               OpenApiParameter("bbox", str, required=False,
                                                description="min_lng,min_lat,max_lng,max_lat")],
                   responses=S.GeoFeatureCollectionSerializer)
    @action(detail=True, methods=["get"], url_path="features")
    def features(self, request, pk=None):
        layer = self.get_object()
        vnum = request.query_params.get("version")
        version = (layer.versions.filter(version=vnum).first() if vnum else layer.current_version)
        if version is None:
            raise NotFound("This layer has no such version.")
        qs = version.features.all()
        bbox = request.query_params.get("bbox")
        if bbox:
            qs = qs.filter(geom__intersects=_bbox_polygon(bbox))
        feats = [_feature(f.geom, {"name": f.name, "layer_code": layer.code, "layer_kind": layer.kind,
                                   "version": version.version, "is_sample": layer.is_sample, **f.properties},
                          f.pk) for f in qs[:5000]]
        return Response({"type": "FeatureCollection", "features": feats})

    @extend_schema(summary="Re-check plots against the current layers", request=S.OverlayRecheckSerializer,
                   responses={201: S.OverlayRecheckResultSerializer})
    @action(detail=True, methods=["post"], url_path="rechecks")
    @idempotent
    def rechecks(self, request, pk=None):
        layer = self.get_object()
        _require_staff(request.user, layer.country, *CASE_STAFF)
        s = S.OverlayRecheckSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        runs = services.recheck_layer(layer, actor=request.user, asset_ids=s.validated_data.get("asset_ids"))
        return Response(S.OverlayRecheckResultSerializer({"runs": runs}).data, status=201)


def _bbox_polygon(bbox):
    from django.contrib.gis.geos import Polygon

    try:
        minx, miny, maxx, maxy = [float(x) for x in bbox.split(",")]
    except ValueError:
        raise Invalid("bbox is min_lng,min_lat,max_lng,max_lat.")
    return Polygon.from_bbox((minx, miny, maxx, maxy))


class LayerVersionViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    queryset = OverlayLayerVersion.objects.none()
    serializer_class = S.OverlayLayerVersionSerializer

    def get_queryset(self):
        user = self.request.user
        if not has_role(user, *READ_STAFF):
            return OverlayLayerVersion.objects.none()
        return sel.in_country(OverlayLayerVersion.objects.all(), user, READ_STAFF).select_related("loaded_by")


# --------------------------------------------------------------------------- country extent


class CountryExtentViewSet(viewsets.GenericViewSet):
    serializer_class = S.CountryExtentSerializer
    lookup_field = "code"

    def _out(self, ext):
        return {"country": ext.country.code, "label": ext.label, "geometry": ext.geom, "updated_at": ext.updated_at}

    @extend_schema(summary="The land area coordinates must fall in", responses=S.CountryExtentSerializer,
                   parameters=[OpenApiParameter("code", str, OpenApiParameter.PATH)])
    def retrieve(self, request, code=None):
        country = _country(code)
        _require_staff(request.user, country)
        ext = CountryExtent.objects.filter(country=country).first()
        if ext is None:
            raise NotFound("No extent is loaded for this country.")
        return Response(S.CountryExtentSerializer(self._out(ext)).data)

    @extend_schema(summary="Load the country's land area (administrator)", request=S.CountryExtentInputSerializer,
                   responses=S.CountryExtentSerializer,
                   parameters=[OpenApiParameter("code", str, OpenApiParameter.PATH)])
    def update(self, request, code=None):
        country = _country(code)
        _require_staff(request.user, country, "AD")
        s = S.CountryExtentInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ext = services.set_country_extent(country, actor=request.user, **s.validated_data)
        return Response(S.CountryExtentSerializer(self._out(ext)).data)


# --------------------------------------------------------------------------- map and digital address


@extend_schema(summary="Back office map: plots in a box, with optional layers (GeoJSON)",
               parameters=[OpenApiParameter("country", str, required=True),
                           OpenApiParameter("bbox", str, required=True,
                                            description="min_lng,min_lat,max_lng,max_lat"),
                           OpenApiParameter("layers", str, required=False,
                                            description="Comma-separated layer codes to include")],
               responses=S.GeoFeatureCollectionSerializer)
@api_view(["GET"])
def area_map(request):
    country = _country(request.query_params.get("country"), request.user)
    _require_staff(request.user, country)
    bbox = request.query_params.get("bbox")
    if not bbox:
        raise Invalid("Give bbox as min_lng,min_lat,max_lng,max_lat.")
    box = _bbox_polygon(bbox)
    feats = []
    assets = (Asset.objects.filter(country=country, current_boundary__geom__intersects=box)
              .select_related("current_boundary")[:2000])
    for a in assets:
        feats.append(_feature(a.current_boundary.geom, {
            "kind": "boundary", "asset_id": str(a.pk), "reference": a.reference, "type": a.type,
            "locality": a.locality, "verified": bool(a.verified_at), "listed": bool(a.listed_at),
            "disputed": a.disputed_flag}, a.current_boundary_id))
    codes = [c for c in (request.query_params.get("layers") or "").split(",") if c]
    if codes:
        for f in OverlayFeature.objects.filter(
                layer_version__layer__country=country, layer_version__layer__code__in=codes,
                layer_version__status="active", geom__intersects=box).select_related("layer_version__layer")[:5000]:
            lyr = f.layer_version.layer
            feats.append(_feature(f.geom, {"kind": "layer", "layer_code": lyr.code, "layer_kind": lyr.kind,
                                           "name": f.name, "is_sample": lyr.is_sample}, f"lf-{f.pk}"))
    return Response({"type": "FeatureCollection", "features": feats})


@extend_schema(summary="Digital address (Ghana Post GPS) to coordinates, for confirmation",
               parameters=[OpenApiParameter("country", str, required=False,
                                            description="Defaults to your home country.")],
               responses=S.DigitalAddressSerializer)
@api_view(["GET"])
def ghana_post(request, code):
    user = request.user
    if not has_role(user, "CL", "SE", "DV", "CM", "AD", "SV"):
        raise Forbidden()
    country = _country(request.query_params.get("country"), user)
    return Response(S.DigitalAddressSerializer(services.resolve_digital_address(country, code)).data)
