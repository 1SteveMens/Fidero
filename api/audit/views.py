"""AUD API. There is no endpoint that edits or deletes an entry (FR-AUD-002):
every audit view is read-only, so PUT, PATCH and DELETE answer 405."""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import NotFound
from core.idempotency import idempotent
from core.permissions import roles

from . import selectors, services
from .models import AuditAnchor, SecurityAlert
from .serializers import (
    AlertAcknowledgeSerializer, AuditAnchorSerializer, AuditPageSerializer, AuditSearchSerializer, ChainCheckSerializer,
    SecurityAlertSerializer, TrailExportSerializer, AuditVerifyResultSerializer,
)

Searchers = roles("RV", "AD", "DPO")
Admins = roles("AD")


class AuditEventList(APIView):
    """FR-AUD-003: search the audit log by case, user, date and action. The
    search itself is logged."""

    permission_classes = [Searchers]

    @extend_schema(parameters=[AuditSearchSerializer], responses=AuditPageSerializer)
    def get(self, request):
        q = AuditSearchSerializer(data=request.query_params)
        q.is_valid(raise_exception=True)
        params = q.validated_data
        rows = list(selectors.search(params, viewer=request.user)[: params["limit"]])
        services.record(actor=request.user, action="audit.searched", entity="aud_event", entity_id="search",
                        data={k: str(v) for k, v in params.items() if k != "limit"})
        from .serializers import AuditEventSerializer

        return Response({"items": AuditEventSerializer(rows, many=True).data,
                         "next_cursor": str(rows[-1].seq) if len(rows) == params["limit"] else None})


class TrailExport(APIView):
    """An entity's whole trail with a digest of the extract. Logged as an export."""

    permission_classes = [Searchers]

    @extend_schema(responses=TrailExportSerializer)
    def get(self, request, entity, entity_id):
        if selectors.search({"entity": entity, "entity_id": entity_id}, viewer=request.user).count() == 0:
            raise NotFound("No audit entries for this object.")
        return Response(services.export_trail(entity, entity_id, by=request.user))


class ChainVerify(APIView):
    """FR-AUD-004: recompute the chain and check the anchors now."""

    permission_classes = [Admins]

    @extend_schema(request=None, responses=AuditVerifyResultSerializer)
    @idempotent
    def post(self, request):
        chk = services.run_chain_check(by=request.user)
        return Response({"ok": chk.ok, "checked": chk.checked, "broken_at": chk.broken_at,
                         "anchors_ok": chk.anchors_ok, "anchor_problem": chk.anchor_problem, "check_id": chk.pk})


class ChainCheckList(generics.ListAPIView):
    permission_classes = [Searchers]
    serializer_class = ChainCheckSerializer

    def get_queryset(self):
        from .models import ChainCheck

        return ChainCheck.objects.all().order_by("-ran_at")

    pagination_class = None


class AnchorList(generics.ListAPIView):
    permission_classes = [Searchers]
    serializer_class = AuditAnchorSerializer
    pagination_class = None

    def get_queryset(self):
        return AuditAnchor.objects.order_by("-seq")[:100]


class AnchorCreate(APIView):
    permission_classes = [Admins]

    @extend_schema(request=None, responses=AuditAnchorSerializer)
    def post(self, request):
        a = services.anchor()
        if a is None:
            raise NotFound("The audit log is empty.")
        return Response(AuditAnchorSerializer(a).data, status=201)


class SecurityAlertList(generics.ListAPIView):
    """10.10: alerts raised by security events (administrators and reviewers)."""

    permission_classes = [roles("AD", "RV")]
    serializer_class = SecurityAlertSerializer

    @extend_schema(parameters=[OpenApiParameter("open", bool), OpenApiParameter("kind", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = SecurityAlert.objects.all()
        if self.request.query_params.get("open") in ("1", "true"):
            qs = qs.filter(acknowledged_at__isnull=True)
        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)
        return qs


class SecurityAlertAcknowledge(APIView):
    permission_classes = [roles("AD", "RV")]

    @extend_schema(request=AlertAcknowledgeSerializer, responses=SecurityAlertSerializer)
    @idempotent
    def post(self, request, pk):
        alert = SecurityAlert.objects.filter(pk=pk).first()
        if not alert:
            raise NotFound()
        s = AlertAcknowledgeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(SecurityAlertSerializer(services.acknowledge_alert(alert, request.user,
                                                                           s.validated_data["note"])).data)
