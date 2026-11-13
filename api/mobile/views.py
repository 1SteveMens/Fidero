"""MOB API for Tenmina Field and the back office (02 section 7.4, /v1/mobile/*)."""
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, is_staff, roles
from core.views import ETagMixin
from evidence.serializers import FileUploadSerializer
from evidence.views import RawBytesParser, file_bytes, staff_country_ids

from . import appversion, inbox, services
from .models import Assignment, CheckIn, Device, FraudFlag, SignedManifest, Submission
from .serializers import (
    AppConfigSerializer, AssignmentSerializer, ChallengeSerializer, CheckInSerializer, CompleteSerializer,
    DeviceRegisterSerializer, DeviceSerializer, FieldItemSerializer,
    FraudFlagSerializer, InboxItemSerializer, InspectionRequestSerializer, IntegrityCheckSerializer,
    ReasonSerializer, ReviewSerializer, SignedItemSerializer, SubmissionRequestSerializer, SubmissionSerializer,
    SyncSerializer,
)

StaffReview = roles("CM", "RV", "AD")


def _app_version(request) -> str:
    info = appversion.parse(request.headers.get(appversion.HEADER))
    return info[2] if info else ""


def _captured(payload):
    m = payload.get("manifest") if isinstance(payload, dict) else None
    return parse_datetime(m.get("captured_at_device")) if isinstance(m, dict) and isinstance(
        m.get("captured_at_device"), str) else None


class FieldAppMixin:
    """Checks the Tenmina-App minimum version (FR-APP-006). Views that carry evidence captured
    earlier set version_grace and check with the signed capture time instead."""

    version_grace = False

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not self.version_grace:
            appversion.enforce(request)


def _scope(qs, user, *, person_field="person"):
    """Field workers see their own rows; staff see their countries."""
    ids = staff_country_ids(user)
    if ids is None:
        return qs
    if ids:
        return qs.filter(Q(country_id__in=ids) | Q(**{person_field: user}))
    return qs.filter(**{person_field: user})


class AppConfigView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(parameters=[OpenApiParameter("app", str, enum=list(appversion.APPS), required=True),
                               OpenApiParameter("platform", str, enum=list(appversion.PLATFORMS), required=True),
                               OpenApiParameter("version", str)],
                   responses=AppConfigSerializer)
    def get(self, request):
        """Minimum and latest version, store link and fee payment mode (FR-APP-005, FR-APP-006)."""
        app, platform = request.query_params.get("app"), request.query_params.get("platform")
        if app not in appversion.APPS or platform not in appversion.PLATFORMS:
            raise Invalid("Give app (field or client) and platform (android or ios).")
        return Response(AppConfigSerializer(appversion.config(app, platform,
                                                              request.query_params.get("version"))).data)


class DeviceViewSet(FieldAppMixin, ETagMixin, viewsets.GenericViewSet, mixins.ListModelMixin,
                    mixins.RetrieveModelMixin):
    """Registered phones (8.2). Each person may have several; each key belongs to one person."""

    serializer_class = DeviceSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Device.objects.none()
        user = self.request.user
        qs = Device.objects.all().order_by("-registered_at")
        if is_staff(user):
            person = self.request.query_params.get("person")
            return qs.filter(person_id=person) if person else qs
        return qs.filter(person=user)

    @extend_schema(request=None, responses={201: ChallengeSerializer})
    @action(detail=False, methods=["post"])
    def challenge(self, request):
        ch = services.issue_challenge(request.user)
        return Response(ChallengeSerializer({"challenge": ch.nonce, "expires_at": ch.expires_at}).data, status=201)

    @extend_schema(request=DeviceRegisterSerializer, responses={201: DeviceSerializer, 200: DeviceSerializer})
    def create(self, request):
        req = DeviceRegisterSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        d, created = services.register_device(request.user, **req.validated_data)
        return Response(DeviceSerializer(d).data, status=201 if created else 200)

    @extend_schema(request=ReasonSerializer, responses=DeviceSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        d = self.get_object()
        if d.person_id != request.user.pk and not has_role(request.user, "CM", "RV", "AD"):
            raise NotFound("Device not found.")
        req = ReasonSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        return Response(DeviceSerializer(services.revoke_device(d, request.user, req.validated_data["reason"])).data)

    @extend_schema(request=IntegrityCheckSerializer, responses=DeviceSerializer)
    @action(detail=True, methods=["post"], url_path="integrity-checks")
    def integrity_checks(self, request, pk=None):
        d = self.get_object()
        if d.person_id != request.user.pk:
            raise NotFound("Device not found.")
        req = IntegrityCheckSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        return Response(DeviceSerializer(services.integrity_check(d, req.validated_data["assertion"],
                                                                  by=request.user)).data)


class SyncView(FieldAppMixin, APIView):
    @extend_schema(parameters=[OpenApiParameter("since", str), OpenApiParameter("device_id", str)],
                   responses=SyncSerializer)
    def get(self, request):
        """Assignments, required evidence, checklists, boundaries, visits and errand steps; what changed
        since the token, and what was removed (8.5 step 1)."""
        dev = None
        did = request.query_params.get("device_id")
        if did:
            dev = Device.objects.filter(pk=did, person=request.user).first() if services._is_uuid(did) else None
        data = services.sync(request.user, since=request.query_params.get("since"), device=dev)
        return Response(SyncSerializer(data).data)


class InboxView(FieldAppMixin, APIView):
    pagination_class = None

    @extend_schema(responses=InboxItemSerializer(many=True))
    def get(self, request):
        """The field worker's assigned work from every module (FR-MOB-001)."""
        services._require_field_worker(request.user)
        return Response(InboxItemSerializer([i.as_dict() for i in inbox.items_for(request.user)], many=True).data)


class FieldItemViewSet(FieldAppMixin, viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Signed evidence items (8.4, 8.5 steps 2 to 4)."""

    serializer_class = FieldItemSerializer
    version_grace = True

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SignedManifest.objects.none()
        qs = SignedManifest.objects.prefetch_related("flags").order_by("-received_at")
        return _scope(qs, self.request.user)

    def get_object(self):
        m = SignedManifest.objects.filter(pk=self.kwargs["pk"]).first()
        if m is None or (m.person_id != self.request.user.pk and not is_staff(self.request.user)):
            raise NotFound("Item not found.")
        return m

    def list(self, request, *args, **kwargs):
        appversion.enforce(request)
        return super().list(request, *args, **kwargs)

    @extend_schema(request=SignedItemSerializer, responses={201: FieldItemSerializer, 200: FieldItemSerializer})
    def create(self, request):
        """Register a signed item; returns the evidence id and where to upload. Repeating the same
        client_item_id returns the same item (no duplicates)."""
        SignedItemSerializer(data=request.data).is_valid(raise_exception=True)
        appversion.enforce(request, captured_at=_captured(request.data))
        m, created = services.register_item(request.user, request.data, app_version=_app_version(request))
        return Response(FieldItemSerializer(m).data, status=201 if created else 200)

    @extend_schema(
        request={"application/octet-stream": OpenApiTypes.BINARY, "multipart/form-data": FileUploadSerializer},
        responses=FieldItemSerializer)
    @action(detail=True, methods=["put", "post"], parser_classes=[MultiPartParser, RawBytesParser])
    def content(self, request, pk=None):
        m = self.get_object()
        appversion.enforce(request, captured_at=m.captured_at_device)
        return Response(FieldItemSerializer(services.stage_content(m, request.user, file_bytes(request))).data)

    @extend_schema(request={"application/json": None, "multipart/form-data": FileUploadSerializer},
                   responses=CompleteSerializer)
    @action(detail=True, methods=["post"], parser_classes=[JSONParser, MultiPartParser])
    def complete(self, request, pk=None):
        """Re-hash, scan, store and run the fraud checks; the device deletes its copy on `stored`."""
        m = self.get_object()
        appversion.enforce(request, captured_at=m.captured_at_device)
        f = request.FILES.get("file")
        m, flags = services.complete_item(m, request.user, f.read() if f else None)
        return Response(CompleteSerializer({"status": m.status, "evidence_id": m.evidence_id,
                                            "flags": flags}).data)


class SubmissionViewSet(FieldAppMixin, ETagMixin, viewsets.GenericViewSet, mixins.ListModelMixin,
                        mixins.RetrieveModelMixin):
    serializer_class = SubmissionSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Submission.objects.none()
        qs = Submission.objects.prefetch_related("items").order_by("-received_at")
        st, sid, status = (self.request.query_params.get(k) for k in ("subject_type", "subject_id", "status"))
        if st:
            qs = qs.filter(subject_type=st)
        if sid:
            qs = qs.filter(subject_id=sid)
        if status:
            qs = qs.filter(status=status)
        return _scope(qs, self.request.user)

    @extend_schema(request=SubmissionRequestSerializer, responses={202: SubmissionSerializer})
    @idempotent
    def create(self, request):
        """Submit a milestone, task, visit or errand step with its evidence (FR-MOB-006, FR-MOB-010)."""
        req = SubmissionRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        items = [{k: (str(v) if k == "evidence_id" and v else v) for k, v in i.items()} for i in d["items"]]
        sub, _ = services.submit(request.user, client_submission_id=d["client_submission_id"],
                                 subject_type=d["subject_type"], subject_id=d["subject_id"], items=items,
                                 note=d["note"])
        return Response(SubmissionSerializer(sub).data, status=202)


class InspectionView(FieldAppMixin, APIView):
    @extend_schema(request=InspectionRequestSerializer, responses={202: SubmissionSerializer})
    @idempotent
    def post(self, request):
        """Inspection result: pass, pass with defects (photos and a value each) or fail with a reason."""
        req = InspectionRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        d = req.validated_data
        sub, _ = services.submit_inspection(
            request.user, client_submission_id=d["client_submission_id"], subject_type=d["subject_type"],
            subject_id=d["subject_id"], outcome=d["outcome"], checklist=[dict(c) for c in d["checklist"]],
            defects=d["defects"], reason=d["reason"], note=d["note"])
        return Response(SubmissionSerializer(sub).data, status=202)


class _CheckView(FieldAppMixin, APIView):
    kind = "checkin"
    version_grace = True

    @extend_schema(request=SignedItemSerializer, responses={201: CheckInSerializer, 200: CheckInSerializer})
    def post(self, request):
        SignedItemSerializer(data=request.data).is_valid(raise_exception=True)
        appversion.enforce(request, captured_at=_captured(request.data))
        ci, created = services.record_checkin(request.user, request.data, self.kind,
                                              app_version=_app_version(request))
        return Response(CheckInSerializer(ci).data, status=201 if created else 200)


class CheckInView(_CheckView):
    """Signed check-in at the registered address (FR-MOB-012). Far away is recorded and flagged."""

    kind = "checkin"

    @extend_schema(parameters=[OpenApiParameter("subject_type", str), OpenApiParameter("subject_id", str)],
                   responses=CheckInSerializer(many=True))
    def get(self, request):
        appversion.enforce(request)
        qs = CheckIn.objects.prefetch_related("flags").order_by("-device_time")
        st, sid = request.query_params.get("subject_type"), request.query_params.get("subject_id")
        if st:
            qs = qs.filter(subject_type=st)
        if sid:
            qs = qs.filter(subject_id=sid)
        return Response(CheckInSerializer(_scope(qs, request.user)[:200], many=True).data)


class CheckOutView(_CheckView):
    """Signed check-out; needs a check-in first. Triggers family confirmation in CARE (ADR-20)."""

    kind = "checkout"


class FraudFlagViewSet(ETagMixin, viewsets.GenericViewSet, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Reviewer queue of field fraud flags (8.7). Clearing or upholding is audited."""

    serializer_class = FraudFlagSerializer
    permission_classes = [StaffReview]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FraudFlag.objects.none()
        qs = FraudFlag.objects.select_related("country", "manifest", "device").order_by("-created_at")
        ids = staff_country_ids(self.request.user)
        if ids is not None:
            qs = qs.filter(country_id__in=ids)
        for k in ("status", "kind", "subject_type", "subject_id", "evidence"):
            v = self.request.query_params.get(k)
            if v:
                qs = qs.filter(**{k: v})
        sub = self.request.query_params.get("submission")
        if sub:
            qs = qs.filter(evidence__in=Submission.objects.filter(pk=sub).values("items__evidence"))
        return qs

    @extend_schema(parameters=[OpenApiParameter(k, str) for k in ("status", "kind", "subject_type", "subject_id",
                                                                   "evidence", "submission")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=ReviewSerializer, responses=FraudFlagSerializer)
    @action(detail=True, methods=["post"])
    def clear(self, request, pk=None):
        req = ReviewSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        f = services.review_flag(self.get_object(), request.user, "clear", req.validated_data["note"])
        return Response(FraudFlagSerializer(f).data)

    @extend_schema(request=ReviewSerializer, responses=FraudFlagSerializer)
    @action(detail=True, methods=["post"])
    def uphold(self, request, pk=None):
        req = ReviewSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        f = services.review_flag(self.get_object(), request.user, "uphold", req.validated_data["note"])
        return Response(FraudFlagSerializer(f).data)


class AssignmentViewSet(FieldAppMixin, ETagMixin, viewsets.GenericViewSet, mixins.ListModelMixin,
                        mixins.RetrieveModelMixin, mixins.CreateModelMixin):
    """Manual field assignments (the inbox's built-in provider). Staff assign; field workers read their own."""

    serializer_class = AssignmentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Assignment.objects.none()
        qs = Assignment.objects.select_related("country").order_by("-created_at")
        status = self.request.query_params.get("status", "active")
        if status != "all":
            qs = qs.filter(status=status)
        return _scope(qs, self.request.user)

    @extend_schema(request=AssignmentSerializer, responses={201: AssignmentSerializer})
    def create(self, request, *args, **kwargs):
        if not has_role(request.user, "CM", "AD"):
            raise NotFound("Not found.")
        req = AssignmentSerializer(data=request.data)
        req.is_valid(raise_exception=True)
        d = dict(req.validated_data)
        a = services.assign(person=d.pop("person"), subject_type=d.pop("subject_type"),
                            subject_id=d.pop("subject_id"), title=d.pop("title"), country=d.pop("country"),
                            by=request.user, **d)
        return Response(AssignmentSerializer(a).data, status=201)

    @extend_schema(request=ReasonSerializer, responses=AssignmentSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        if not has_role(request.user, "CM", "AD"):
            raise NotFound("Not found.")
        a = self.get_object()
        return Response(AssignmentSerializer(services.revoke_assignment(a, request.user,
                                                                        request.data.get("reason", ""))).data)

