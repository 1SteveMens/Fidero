"""CTY API (02 section 7.4)."""
import uuid

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import roles
from core.views import require_mfa

from . import metrics, selectors, services
from .models import Cell, Country, CountryConfig
from .serializers import (
    CtyApprovalStateSerializer, CellSerializer, CellUpdateSerializer, ConfigCreateSerializer, ConfigEditSerializer,
    CountryConfigSerializer, CountryMetricsSerializer, AdminCountrySerializer, AdminCountryUpdateSerializer,
    DataLocationSerializer, CtyDecisionSerializer, DirectoryAnswerSerializer, DirectoryLookupSerializer,
    GateDecisionSerializer, PublicCountrySerializer, CtyReasonSerializer,
)

Admin = roles("AD")


def _country(ref) -> Country:
    try:
        c = Country.objects.filter(pk=uuid.UUID(str(ref))).first()
    except ValueError:
        c = Country.objects.filter(code=str(ref).upper()).first()
    if not c:
        raise NotFound("No such country.")
    return c


def _config(country, v) -> CountryConfig:
    cfg = CountryConfig.objects.filter(country=country, version=v).first()
    if not cfg:
        raise NotFound("No such configuration version.")
    return cfg


def _state(req):
    return {"request_id": req.pk, "status": req.status, "approvals": req.approvals.filter(decision="approve").count(),
            "required": req.required}


class PublicCountries(APIView):
    """Countries open to clients, for sign-up and order forms (Pub)."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=PublicCountrySerializer(many=True))
    def get(self, request):
        return Response(PublicCountrySerializer(selectors.active_countries().order_by("code"), many=True).data)


class CountryList(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=AdminCountrySerializer(many=True))
    def get(self, request):
        return Response(AdminCountrySerializer(Country.objects.all().order_by("code"), many=True).data)

    @extend_schema(request=AdminCountrySerializer, responses={201: AdminCountrySerializer})
    @idempotent
    def post(self, request):
        s = AdminCountrySerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        c = services.create_country(code=d["code"], name=d["name"], currency=d["currency"], by=request.user,
                                    timezone_name=d.get("timezone", "UTC"), cell=d.get("cell"))
        extra = {k: d[k] for k in services.LOCATION_FIELDS if k in d and k != "cell"}
        if extra:
            c = services.update_country(c, by=request.user, **extra)
        return Response(AdminCountrySerializer(c).data, status=201)


class CountryDetail(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=AdminCountrySerializer)
    def get(self, request, ref):
        return Response(AdminCountrySerializer(_country(ref)).data)

    @extend_schema(request=AdminCountryUpdateSerializer, responses=AdminCountrySerializer)
    def patch(self, request, ref):
        c = _country(ref)
        s = AdminCountryUpdateSerializer(c, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return Response(AdminCountrySerializer(services.update_country(c, by=request.user, **s.validated_data)).data)


class CountryAction(APIView):
    permission_classes = [Admin]
    action_name = ""

    @extend_schema(request=CtyReasonSerializer, responses=AdminCountrySerializer)
    @idempotent
    def post(self, request, ref):
        c = _country(ref)
        s = CtyReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if self.action_name == "manual_phase":
            c = services.start_manual_phase(c, by=request.user)
        elif self.action_name == "validation":
            c = services.start_validation(c, by=request.user)
        elif self.action_name == "pause":
            c = services.pause(c, by=request.user, reason=s.validated_data["reason"])
        return Response(AdminCountrySerializer(c).data)


class ManualPhase(CountryAction):
    action_name = "manual_phase"


class Validation(CountryAction):
    action_name = "validation"


class Pause(CountryAction):
    action_name = "pause"


class GateDecision(APIView):
    permission_classes = [Admin]

    @extend_schema(request=GateDecisionSerializer, responses=AdminCountrySerializer)
    @idempotent
    def post(self, request, ref):
        from evidence.models import Evidence

        c = _country(ref)
        s = GateDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ev = None
        if s.validated_data.get("evidence_id"):
            ev = Evidence.objects.filter(pk=s.validated_data["evidence_id"], country=c).first()
            if not ev:
                raise Invalid("The gate record must be evidence of this country.")
        c = services.record_gate_decision(c, by=request.user, passed=s.validated_data["passed"],
                                          note=s.validated_data["note"], evidence=ev)
        return Response(AdminCountrySerializer(c).data)


class Activation(APIView):
    """Ask for activation; a second administrator approves at /approvals."""

    permission_classes = [Admin]

    @extend_schema(request=None, responses=CtyApprovalStateSerializer)
    @idempotent
    def post(self, request, ref):
        return Response(_state(services.request_activation(_country(ref), by=request.user)))


class ActivationApprovals(APIView):
    permission_classes = [Admin]

    @extend_schema(request=CtyDecisionSerializer, responses=AdminCountrySerializer)
    @idempotent
    def post(self, request, ref):
        at = require_mfa(request)
        s = CtyDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        c = _country(ref)
        services.decide_activation(c, request.user, mfa_at=at, **s.validated_data)
        c.refresh_from_db()
        return Response(AdminCountrySerializer(c).data)


class ConfigVersions(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=CountryConfigSerializer(many=True))
    def get(self, request, ref):
        return Response(CountryConfigSerializer(_country(ref).configs.order_by("-version"), many=True).data)

    @extend_schema(request=ConfigCreateSerializer, responses={201: CountryConfigSerializer})
    @idempotent
    def post(self, request, ref):
        c = _country(ref)
        s = ConfigCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        src = None
        cf = s.validated_data.get("copy_from")
        if cf:
            try:
                src = CountryConfig.objects.filter(pk=uuid.UUID(cf)).first()
            except ValueError:
                src_country = Country.objects.filter(code=cf.upper()).first()
                src = selectors.current_config(src_country) if src_country else None
            if not src:
                raise NotFound("Nothing to copy from.")
        cfg = services.create_config(c, by=request.user, data=s.validated_data.get("data"), copy_from=src)
        return Response(CountryConfigSerializer(cfg).data, status=201)


class ConfigVersionDetail(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=CountryConfigSerializer)
    def get(self, request, ref, v):
        return Response(CountryConfigSerializer(_config(_country(ref), v)).data)

    @extend_schema(request=ConfigEditSerializer, responses=CountryConfigSerializer)
    def patch(self, request, ref, v):
        s = ConfigEditSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        cfg = services.update_config(_config(_country(ref), v), by=request.user, data=s.validated_data["data"])
        return Response(CountryConfigSerializer(cfg).data)


class ConfigSubmit(APIView):
    permission_classes = [Admin]

    @extend_schema(request=None, responses=CtyApprovalStateSerializer)
    @idempotent
    def post(self, request, ref, v):
        return Response(_state(services.submit_config(_config(_country(ref), v), by=request.user)))


class ConfigApprovals(APIView):
    """Publish with two administrators (the preparer and a second one)."""

    permission_classes = [Admin]

    @extend_schema(request=CtyDecisionSerializer, responses=CountryConfigSerializer)
    @idempotent
    def post(self, request, ref, v):
        at = require_mfa(request)
        s = CtyDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        cfg = _config(_country(ref), v)
        services.decide_config(cfg, request.user, mfa_at=at, **s.validated_data)
        cfg.refresh_from_db()
        return Response(CountryConfigSerializer(cfg).data)


class ConfigRetire(APIView):
    permission_classes = [Admin]

    @extend_schema(request=None, responses=CountryConfigSerializer)
    @idempotent
    def post(self, request, ref, v):
        return Response(CountryConfigSerializer(services.retire_config(_config(_country(ref), v),
                                                                       by=request.user)).data)


class CellList(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=CellSerializer(many=True))
    def get(self, request):
        return Response(CellSerializer(Cell.objects.all(), many=True).data)

    @extend_schema(request=CellSerializer, responses={201: CellSerializer})
    @idempotent
    def post(self, request):
        s = CellSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(CellSerializer(services.create_cell(by=request.user, **s.validated_data)).data, status=201)


class CellDetail(APIView):
    permission_classes = [Admin]

    @extend_schema(request=CellUpdateSerializer, responses=CellSerializer)
    def patch(self, request, pk):
        cell = Cell.objects.filter(pk=pk).first()
        if not cell:
            raise NotFound()
        s = CellUpdateSerializer(cell, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return Response(CellSerializer(services.update_cell(cell, by=request.user, **s.validated_data)).data)


class DataLocations(APIView):
    """US-CTY-002b: where each country's data lives."""

    permission_classes = [roles("AD", "DPO")]

    @extend_schema(responses=DataLocationSerializer(many=True))
    def get(self, request):
        rows = []
        for c in Country.objects.select_related("cell").order_by("code"):
            r = selectors.storage_route(c)
            rows.append({"country": c.code, "name": c.name, "status": c.status, "cell": r["cell"],
                         "region": r["region"], "data_location": c.data_location,
                         "data_location_ruling": c.data_location_ruling, "evidence_prefix": r["evidence_prefix"],
                         "backup_location": c.backup_location, "kms_key_alias": r["kms_key_alias"]})
        return Response(DataLocationSerializer(rows, many=True).data)


class DirectoryLookup(APIView):
    """ADR-16: which cell serves this sign-in or reference. Always answers with
    a cell, so it does not reveal whether an account exists."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(request=DirectoryLookupSerializer, responses=DirectoryAnswerSerializer)
    def post(self, request):
        s = DirectoryLookupSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        cell = services.route(signin=s.validated_data.get("signin"), reference=s.validated_data.get("reference"))
        return Response({"cell": cell.name if cell else None, "api_host": cell.api_host if cell else "",
                         "portal_host": cell.portal_host if cell else ""})


class CountryMetrics(APIView):
    """FR-CTY-003: counts per country of everything that carries a country,
    plus module metrics; a country-scoped viewer sees their countries only."""

    permission_classes = [roles("CM", "RV", "AD", "AN")]

    @extend_schema(parameters=[OpenApiParameter("country", str, many=True)],
                   responses=CountryMetricsSerializer(many=True))
    def get(self, request):
        codes = request.query_params.getlist("country") or None
        return Response(CountryMetricsSerializer(metrics.by_country(request.user, codes), many=True).data)
