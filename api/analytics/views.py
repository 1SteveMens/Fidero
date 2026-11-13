"""ANL API (02 section 7.4): the back-office dashboard and exports.

    GET  /v1/analytics/catalogue         metrics, columns and filters
    GET  /v1/analytics/metrics           every tile (FR-ANL-001), ?metrics=a,b for some
    GET  /v1/analytics/metrics/{name}    one metric table
    GET  /v1/analytics/review            the day-90 review measures (validation plan section 6)
    POST /v1/analytics/exports           CSV of a metric table, logged (FR-ANL-002); personal data via DPR
    GET  /v1/analytics/exports           the export log

Staff (CM, RV, AD) and analysts (AN) only, scoped to their countries (FR-CTY-003).
Filters: date_from, date_to (YYYY-MM-DD), country (code, or codes joined by commas), line, tier.
"""
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import roles

from . import selectors, services
from .serializers import CatalogueOut, DashboardOut, ExportIn, ExportLogSerializer, TableWithFiltersOut

FILTER_PARAMS = [
    OpenApiParameter("date_from", OpenApiTypes.DATE, required=False, description="Default: 11 months ago, 1st"),
    OpenApiParameter("date_to", OpenApiTypes.DATE, required=False, description="Default: today"),
    OpenApiParameter("country", str, required=False, description="Country code, or codes joined by commas"),
    OpenApiParameter("line", str, required=False, enum=["property", "family", "projects"]),
    OpenApiParameter("tier", str, required=False),
]


def _filters(request, data=None):
    q = data if data is not None else request.query_params
    return selectors.resolve_filters(request.user, date_from=q.get("date_from"), date_to=q.get("date_to"),
                                     country=q.get("country"), line=q.get("line", ""), tier=q.get("tier", ""))


class CatalogueView(APIView):
    permission_classes = [roles(*selectors.ANL_ROLES)]

    @extend_schema(responses=CatalogueOut(many=True), summary="Metrics on the dashboard and their columns")
    def get(self, request):
        return Response(selectors.catalogue())


class DashboardView(APIView):
    permission_classes = [roles(*selectors.ANL_ROLES)]

    @extend_schema(parameters=[*FILTER_PARAMS, OpenApiParameter("metrics", str, required=False,
                                                                 description="Metric names joined by commas")],
                   responses=DashboardOut, operation_id="analytics_dashboard",
                   summary="Operating dashboard with the A9 metrics (FR-ANL-001, -003)")
    def get(self, request):
        f = _filters(request)
        names = [n.strip() for n in request.query_params.get("metrics", "").split(",") if n.strip()]
        return Response(selectors.dashboard(f, request.user, names or None))


class MetricView(APIView):
    permission_classes = [roles(*selectors.ANL_ROLES)]

    @extend_schema(parameters=FILTER_PARAMS, responses=TableWithFiltersOut, operation_id="analytics_metric",
                   summary="One metric table")
    def get(self, request, name):
        f = _filters(request)
        return Response({**selectors.table(name, f, request.user), "filters": f.as_dict()})


class ReviewView(APIView):
    permission_classes = [roles(*selectors.ANL_ROLES)]

    @extend_schema(parameters=FILTER_PARAMS[:3], responses=TableWithFiltersOut,
                   summary="Day-90 review: the validation plan's go criteria from platform data")
    def get(self, request):
        f = _filters(request)
        return Response({**selectors.table("day90_review", f, request.user), "filters": f.as_dict()})


class ExportView(generics.ListAPIView):
    serializer_class = ExportLogSerializer

    def get_permissions(self):
        return [roles(*selectors.EXPORT_ROLES)()]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return selectors.ExportLog.objects.none()
        return selectors.export_log(self.request.user)

    @extend_schema(summary="Export log: who exported which table, when (FR-ANL-002)")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(request=ExportIn,
                   responses={(200, "text/csv"): OpenApiResponse(OpenApiTypes.STR, description="The metric table"),
                              202: OpenApiResponse(ExportLogSerializer,
                                                   description="Personal data: sent for two approvals in DPR")},
                   summary="Export a metric table as CSV, logged; personal data goes through the bulk export")
    def post(self, request):
        s = ExportIn(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        name = d["metric"]
        if name in selectors.PERSONAL_TABLES:
            f = selectors.resolve_filters(request.user, country=d.get("country"))
            country = services.country_of(f)
            log = services.request_personal_export(request.user, name, country=country,
                                                   purpose=d.get("purpose", ""), fields=d.get("fields"))
            return Response(ExportLogSerializer(log).data, status=202)
        f = _filters(request, {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in d.items()})
        data, log = services.export_csv(request.user, name, f, purpose=d.get("purpose", ""))
        resp = HttpResponse(data, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="tenmina-{name}-{f.date_from}-{f.date_to}.csv"'
        resp["Tenmina-Export-Id"] = str(log.pk)
        return resp
