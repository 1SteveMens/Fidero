"""EVD API: upload slots, evidence, signed links, access logs, fingerprints and integrity."""
from django.db.models import Q
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import BaseParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import STAFF_ROLES, has_role, roles
from core.views import ETagMixin

from . import access, services
from .models import Evidence, IntegrityIncident, IntegrityRun, UploadSlot
from .serializers import (
    AccessLogSerializer, EvidenceLinkSerializer, EvidenceSerializer, FileUploadSerializer,
    FingerprintRequestSerializer, FingerprintResultSerializer, IntegrityIncidentSerializer,
    IntegrityRunRequestSerializer, IntegrityRunSerializer, LinkRequestSerializer, ResolveRequestSerializer,
    ScanVerdictSerializer, SignedLinkSerializer, UploadSlotRequestSerializer, UploadSlotSerializer,
)


class RawBytesParser(BaseParser):
    """PUT the file body as application/octet-stream (or any media type)."""

    media_type = "*/*"

    def parse(self, stream, media_type=None, parser_context=None):
        return stream.read() if stream is not None else b""


def staff_country_ids(user):
    """None means every country; an empty set means not staff."""
    grants = user.role_grants.filter(role__in=STAFF_ROLES, revoked_at__isnull=True)
    ids = set(grants.values_list("country_id", flat=True))
    if None in ids:
        return None
    return ids


def file_bytes(request) -> bytes:
    f = request.FILES.get("file") if hasattr(request, "FILES") else None
    if f is not None:
        return f.read()
    data = request.data
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    raise Invalid("Send the file as the request body or as a multipart field named 'file'.")


class UploadViewSet(ETagMixin, viewsets.GenericViewSet, mixins.RetrieveModelMixin):
    """FR-EVD-001, FR-EVD-005: ask for a slot with the file's SHA-256, then send the bytes."""

    serializer_class = UploadSlotSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return UploadSlot.objects.none()
        return UploadSlot.objects.filter(requested_by=self.request.user).select_related("country")

    @extend_schema(request=UploadSlotRequestSerializer, responses={201: UploadSlotSerializer})
    @idempotent
    def create(self, request):
        req = UploadSlotRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        d = dict(req.validated_data)
        code = d.pop("country", "")
        slot = services.request_slot(user=request.user, country_code=code or None, **d)
        return Response(UploadSlotSerializer(slot).data, status=201)

    @extend_schema(
        request={"application/octet-stream": OpenApiTypes.BINARY, "multipart/form-data": FileUploadSerializer},
        responses={201: EvidenceSerializer})
    @action(detail=True, methods=["put", "post"], url_path="content",
            parser_classes=[MultiPartParser, RawBytesParser])
    def content(self, request, pk=None):
        slot = UploadSlot.objects.filter(pk=pk).first()
        if slot is None:
            raise NotFound("Upload slot not found.")
        ev = services.upload_to_slot(slot, file_bytes(request), request.user)
        return Response(EvidenceSerializer(ev).data, status=201)


class EvidenceViewSet(ETagMixin, viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Evidence records. Never updated or deleted through the API (FR-EVD-002)."""

    serializer_class = EvidenceSerializer
    parser_classes = [JSONParser]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Evidence.objects.none()
        user = self.request.user
        qs = Evidence.objects.select_related("country", "uploaded_by").prefetch_related("links")
        st, sid = self.request.query_params.get("subject_type"), self.request.query_params.get("subject_id")
        if st and sid:
            qs = qs.filter(links__subject_type=st, links__subject_id=sid)
        name = self.request.query_params.get("original_name")
        if name:
            qs = qs.filter(original_name=name)
        if self.action != "list":
            return qs.distinct()
        ids = staff_country_ids(user)
        if ids is None:
            return qs.distinct()
        visible = Q(uploaded_by=user)
        if ids:
            visible |= Q(country_id__in=ids)
        if st and sid and access.can_view_subject(user, st, sid):
            visible |= Q(links__subject_type=st, links__subject_id=sid)
        return qs.filter(visible).distinct()

    def get_object(self):
        ev = Evidence.objects.filter(pk=self.kwargs["pk"]).select_related("country").first()
        if ev is None or not access.can_view(self.request.user, ev):
            raise NotFound("Evidence not found.")
        self._etag_obj = ev
        return ev

    @extend_schema(parameters=[OpenApiParameter("subject_type", str), OpenApiParameter("subject_id", str),
                               OpenApiParameter("original_name", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=None, responses={403: OpenApiTypes.OBJECT})
    def destroy(self, request, pk=None):
        """Always refused and logged (TC-EVD-002-02)."""
        services.refuse_delete(self.get_object(), request.user, request)

    @extend_schema(parameters=[OpenApiParameter("variant", str, enum=["preview", "original"])],
                   responses=SignedLinkSerializer)
    @action(detail=True, methods=["get"])
    def link(self, request, pk=None):
        """A signed link valid for 15 minutes or less (FR-EVD-003). The preview is the default."""
        ev = Evidence.objects.filter(pk=pk).select_related("country").first()
        if ev is None:
            raise NotFound("Evidence not found.")
        data = services.issue_link(ev, request.user, variant=request.query_params.get("variant"), request=request)
        return Response(SignedLinkSerializer(data).data)

    @extend_schema(request=LinkRequestSerializer, responses={201: EvidenceLinkSerializer})
    @action(detail=True, methods=["post"], url_path="links")
    def add_link(self, request, pk=None):
        ev = self.get_object()
        req = LinkRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        if not access.can_attach(request.user, d["subject_type"], d["subject_id"], ev.country):
            raise NotFound("We could not find that item, or you cannot add evidence to it.")
        lk = services.link(ev, d["subject_type"], d["subject_id"], role=d["role"], by=request.user)
        return Response(EvidenceLinkSerializer(lk).data, status=201)

    @extend_schema(responses=AccessLogSerializer(many=True))
    @action(detail=True, methods=["get"], url_path="access-log", pagination_class=None)
    def access_log(self, request, pk=None):
        ev = self.get_object()
        return Response(AccessLogSerializer(ev.access_log.select_related("person").order_by("-created_at")[:500],
                                            many=True).data)

    @extend_schema(request=ScanVerdictSerializer, responses=EvidenceSerializer)
    @action(detail=True, methods=["post"], url_path="scan-results", permission_classes=[roles("AD", "RV")])
    def scan_result(self, request, pk=None):
        """The scanner's verdict for a file held as pending (manual adapter for the asynchronous scanner)."""
        ev = self.get_object()
        req = ScanVerdictSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        services.record_scan(ev, req.validated_data["verdict"], detail=req.validated_data["detail"],
                             scanner=req.validated_data["scanner"], by=request.user)
        ev.refresh_from_db()
        return Response(EvidenceSerializer(ev).data)


class SubjectAccessLogView(APIView):
    """Who opened the evidence in a folder, for example a released report's folder."""

    @extend_schema(parameters=[OpenApiParameter("subject_type", str, required=True),
                               OpenApiParameter("subject_id", str, required=True)],
                   responses=AccessLogSerializer(many=True))
    def get(self, request):
        st, sid = request.query_params.get("subject_type"), request.query_params.get("subject_id")
        if not st or not sid:
            raise Invalid("Give subject_type and subject_id.")
        rows = services.access_log_for(st, sid)
        first = rows.first()
        if first is None and staff_country_ids(request.user) != set():
            return Response([])
        country = first.country if first else None
        if not (access.can_view_subject(request.user, st, sid, country)):
            raise NotFound("Not found.")
        return Response(AccessLogSerializer(rows[:500], many=True).data)


class EvidenceFileView(APIView):
    """GET a file through a signed link. Works without signing in until it expires; a signed-in
    user can only use links issued to them."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={(200, "application/octet-stream"): OpenApiTypes.BINARY})
    def get(self, request, token):
        data, ct, name, _ = services.open_link(token, user=request.user, request=request)
        resp = HttpResponse(data, content_type=ct)
        safe = name.replace('"', "")
        resp["Content-Disposition"] = f'inline; filename="{safe}"'
        resp["Cache-Control"] = "private, no-store"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp


class FingerprintThrottle(SimpleRateThrottle):
    scope = "fingerprint"
    rate = "20/min"  # per address, assumption

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class FingerprintCheckView(APIView):
    """Public: does this SHA-256 match a document Tenmina issued? Answers only yes or no and the release date."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [FingerprintThrottle]

    @extend_schema(request=FingerprintRequestSerializer, responses=FingerprintResultSerializer)
    def post(self, request):
        req = FingerprintRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        return Response(FingerprintResultSerializer(
            services.check_fingerprint(req.validated_data["sha256"], request=request)).data)


class IntegrityRunViewSet(viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Daily integrity sampling (10.7 step 7). Administrators may also start a run."""

    serializer_class = IntegrityRunSerializer
    permission_classes = [roles("AD", "RV")]
    queryset = IntegrityRun.objects.all()

    @extend_schema(request=IntegrityRunRequestSerializer, responses={201: IntegrityRunSerializer})
    def create(self, request):
        if not has_role(request.user, "AD"):
            raise NotFound("Not found.")
        req = IntegrityRunRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        run = services.integrity_sample(size=req.validated_data.get("size"),
                                        seed=req.validated_data.get("seed") or None, by=request.user)
        return Response(IntegrityRunSerializer(run).data, status=201)


class IntegrityIncidentViewSet(ETagMixin, viewsets.GenericViewSet, mixins.ListModelMixin,
                               mixins.RetrieveModelMixin):
    serializer_class = IntegrityIncidentSerializer
    permission_classes = [roles("AD", "RV")]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return IntegrityIncident.objects.none()
        qs = IntegrityIncident.objects.select_related("country")
        ids = staff_country_ids(self.request.user)
        if ids is not None:
            qs = qs.filter(country_id__in=ids)
        st = self.request.query_params.get("status")
        return qs.filter(status=st) if st else qs

    @extend_schema(request=ResolveRequestSerializer, responses=IntegrityIncidentSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("AD")])
    def resolve(self, request, pk=None):
        inc = self.get_object()
        req = ResolveRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        return Response(IntegrityIncidentSerializer(
            services.resolve_incident(inc, request.user, req.validated_data["note"])).data)

