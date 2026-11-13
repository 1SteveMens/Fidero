"""DPR API (02 section 7.4): privacy notice, consents, subject requests,
in-app account deletion, retention rules and runs, legal holds, bulk
exports, the data catalogue and data locations."""
from django.http import HttpResponse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, roles
from core.views import require_mfa

from . import selectors, services
from .models import (BulkExport, Consent, DataCatalogueEntry, DataLocation, DataRequest, LegalHold,
                     PrivacyAcceptance, PrivacyNotice, RetentionRule, RetentionRun)
from .serializers import (AcceptNoticeSerializer, BulkExportSerializer, CatalogueGapsSerializer,
                          ConsentSerializer, CorrectionSerializer, CreateBulkExportSerializer,
                          CreateDataRequestSerializer, DataCatalogueSerializer, DataLocationSerializer,
                          DataRequestSerializer, DecisionSerializer, DeletionConfirmSerializer,
                          DeletionPreviewSerializer, GiveConsentSerializer, LegalHoldSerializer,
                          PrivacyAcceptanceSerializer, PrivacyNoticeSerializer, ReasonSerializer,
                          RecordingLinkResultSerializer, RecordingLinkSerializer, RetentionRuleSerializer,
                          RetentionRunSerializer, VideoConsentSerializer)

DPR = roles("AD", "DPO")


def _valid(cls, request, **kw):
    s = cls(data=request.data, context={"request": request}, **kw)
    s.is_valid(raise_exception=True)
    return s.validated_data


# ---------------------------------------------------------------- privacy notice (US-DPR-001)

@extend_schema(parameters=[OpenApiParameter("country", str)], responses=PrivacyNoticeSerializer)
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def current_notice(request):
    from countries.models import Country

    country = Country.objects.filter(code=(request.query_params.get("country") or "GH").upper()).first()
    n = selectors.current_notice(country)
    if n is None:
        raise NotFound()
    return Response(PrivacyNoticeSerializer(n).data)


class PrivacyNoticeViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = PrivacyNoticeSerializer
    permission_classes = [DPR]
    queryset = PrivacyNotice.objects.all().order_by("-created_at")

    def create(self, request, *args, **kwargs):
        d = _valid(PrivacyNoticeSerializer, request)
        n = services.publish_notice(request.user, **d)
        return Response(PrivacyNoticeSerializer(n).data, status=201)


@extend_schema(methods=["GET"], responses=PrivacyAcceptanceSerializer(many=True))
@extend_schema(methods=["POST"], request=AcceptNoticeSerializer, responses={201: PrivacyAcceptanceSerializer})
@api_view(["GET", "POST"])
def my_privacy_acceptances(request):
    if request.method == "GET":
        qs = PrivacyAcceptance.objects.filter(person=request.user).order_by("-accepted_at")
        return Response(PrivacyAcceptanceSerializer(qs, many=True).data)
    d = _valid(AcceptNoticeSerializer, request)
    acc = services.accept_notice(request.user, d["version"], source=request.headers.get("Tenmina-App") and "app"
                                 or "portal", ip=request.META.get("REMOTE_ADDR", ""))
    return Response(PrivacyAcceptanceSerializer(acc).data, status=201)


# ---------------------------------------------------------------- consents (US-DPR-002, RUL-16)

class ConsentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin,
                     viewsets.GenericViewSet):
    serializer_class = ConsentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Consent.objects.none()
        u = self.request.user
        qs = Consent.objects.all().order_by("-given_at")
        if has_role(u, "AD", "DPO", "CM", "RV", "LW"):
            case = self.request.query_params.get("case_id")
            if case:
                return qs.filter(case_id=case)
            if has_role(u, "AD", "DPO", "CM", "RV"):
                return qs
            return qs.filter(recorded_by=u)
        return qs.filter(person=u)

    @extend_schema(request=GiveConsentSerializer, responses={201: ConsentSerializer})
    @idempotent
    def create(self, request):
        d = _valid(GiveConsentSerializer, request)
        c = services.give_consent(request.user, **d)
        return Response(ConsentSerializer(c).data, status=201)

    def destroy(self, request, *args, **kwargs):
        """Withdraw a consent; publishes consent.changed."""
        c = self.get_object()
        services.withdraw_consent(c, request.user)
        return Response(ConsentSerializer(c).data)

    @extend_schema(request=None, responses=ConsentSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        c = self.get_object()
        services.withdraw_consent(c, request.user)
        return Response(ConsentSerializer(c).data)

    @extend_schema(request=VideoConsentSerializer, responses={201: ConsentSerializer})
    @action(detail=False, methods=["post"], permission_classes=[roles("LW", "SV", "RN", "CM", "RV")])
    @idempotent
    def video(self, request):
        d = _valid(VideoConsentSerializer, request)
        c = services.record_video_consent(request.user, **d)
        return Response(ConsentSerializer(c).data, status=201)

    @extend_schema(request=RecordingLinkSerializer, responses={201: RecordingLinkResultSerializer})
    @action(detail=False, methods=["post"], url_path="recording-links",
            permission_classes=[roles("LW", "SV", "RN", "CM", "RV")])
    def recording_links(self, request):
        d = _valid(RecordingLinkSerializer, request)
        lk = services.attach_recording(request.user, evidence=d["evidence"], case_id=d["case_id"])
        return Response({"evidence": lk.evidence_id, "case_id": lk.subject_id, "role": lk.role}, status=201)


# ---------------------------------------------------------------- my data requests and deletion (FR-APP-004)

@extend_schema(responses=DeletionPreviewSerializer)
@api_view(["GET"])
def deletion_preview(request):
    """What deleting the account removes, what is kept, why and until when,
    and any open matters that delay it."""
    return Response(services.deletion_preview(request.user))


@extend_schema(methods=["GET"], responses=DataRequestSerializer(many=True))
@extend_schema(methods=["POST"], request=DeletionConfirmSerializer, responses={201: DataRequestSerializer})
@api_view(["GET", "POST"])
def my_deletion_requests(request):
    if request.method == "GET":
        qs = DataRequest.objects.filter(subject=request.user, type="deletion").order_by("-created_at")
        return Response(DataRequestSerializer(qs, many=True).data)
    d = _valid(DeletionConfirmSerializer, request)
    if not d["confirm"]:
        raise Invalid("Confirm that you want to delete your account.", code="validation-error")
    if request.user.mfa_enabled:
        require_mfa(request)  # TC-APP-004-04
    req = services.request_deletion(request.user, source=d["source"])
    return Response(DataRequestSerializer(req).data, status=201)


@extend_schema(methods=["GET"], responses=DataRequestSerializer(many=True))
@extend_schema(methods=["POST"], request=CreateDataRequestSerializer, responses={201: DataRequestSerializer})
@api_view(["GET", "POST"])
def my_data_requests(request):
    if request.method == "GET":
        qs = DataRequest.objects.filter(subject=request.user).order_by("-created_at")
        return Response(DataRequestSerializer(qs, many=True).data)
    d = _valid(CreateDataRequestSerializer, request)
    d.pop("subject", None)
    req = services.create_request(request.user, subject=request.user, type=d["type"], details=d["details"],
                                  source="app" if request.headers.get("Tenmina-App") else "portal")
    return Response(DataRequestSerializer(req).data, status=201)


# ---------------------------------------------------------------- staff: subject requests (US-DPR-003)

class DataRequestViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = DataRequestSerializer
    permission_classes = [DPR]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DataRequest.objects.none()
        qs = DataRequest.objects.select_related("subject").order_by("due_on")
        for f in ("status", "type"):
            v = self.request.query_params.get(f)
            if v:
                qs = qs.filter(**{f: v})
        return qs

    @extend_schema(request=CreateDataRequestSerializer, responses={201: DataRequestSerializer})
    @idempotent
    def create(self, request):
        d = _valid(CreateDataRequestSerializer, request)
        subject = d.get("subject")
        if subject is None:
            raise Invalid("Choose the person.", code="validation-error")
        req = services.create_request(request.user, subject=subject, type=d["type"], details=d["details"],
                                      source="staff")
        return Response(DataRequestSerializer(req).data, status=201)

    @extend_schema(request=None, responses=DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def export(self, request, pk=None):
        req = self.get_object()
        services.run_export(req, request.user)
        return Response(DataRequestSerializer(req).data)

    @extend_schema(request=CorrectionSerializer, responses=DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def corrections(self, request, pk=None):
        req = self.get_object()
        d = _valid(CorrectionSerializer, request)
        services.apply_correction(req, request.user, field=d["field"], value=d["value"])
        return Response(DataRequestSerializer(req).data)

    @extend_schema(request=None, responses=DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def erase(self, request, pk=None):
        req = self.get_object()
        req = services.run_erasure(req, request.user)
        return Response(DataRequestSerializer(req).data)

    @extend_schema(request=None, responses=DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        req = self.get_object()
        services.complete_request(req, request.user)
        return Response(DataRequestSerializer(req).data)

    @extend_schema(request=ReasonSerializer, responses=DataRequestSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        req = self.get_object()
        services.reject_request(req, request.user, _valid(ReasonSerializer, request)["reason"])
        return Response(DataRequestSerializer(req).data)


# ---------------------------------------------------------------- retention and legal holds (US-DPR-004a/b)

class RetentionRuleViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = RetentionRuleSerializer
    permission_classes = [DPR]
    queryset = RetentionRule.objects.filter(status="active").order_by("data_class")

    @extend_schema(request=RetentionRuleSerializer, responses={201: RetentionRuleSerializer})
    def create(self, request):
        d = _valid(RetentionRuleSerializer, request)
        r = services.save_rule(request.user, **d)
        return Response(RetentionRuleSerializer(r).data, status=201)

    @extend_schema(request=RetentionRuleSerializer, responses=RetentionRuleSerializer)
    def partial_update(self, request, pk=None):
        r = self.get_object()
        d = {**RetentionRuleSerializer(r).data, **_valid(RetentionRuleSerializer, request, partial=True)}
        d.pop("country", None)
        args = {k: d[k] for k in ("data_class", "period_days", "anchor", "action", "description", "reason",
                                  "kept_on_deletion")}
        r = services.save_rule(request.user, country=r.country, rule=r, **args)
        return Response(RetentionRuleSerializer(r).data)


class RetentionRunViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = RetentionRunSerializer
    permission_classes = [DPR]
    queryset = RetentionRun.objects.all().order_by("-created_at")

    @extend_schema(request=None, responses={201: RetentionRunSerializer})
    def create(self, request):
        """Run the retention sweep now (it also runs nightly)."""
        run = services.run_retention(request.user)
        return Response(RetentionRunSerializer(run).data, status=201)


class LegalHoldViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = LegalHoldSerializer
    permission_classes = [roles("LW", "AD", "DPO", "RV")]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return LegalHold.objects.none()
        qs = LegalHold.objects.all().order_by("-placed_at")
        for f in ("subject_type", "subject_id", "status"):
            v = self.request.query_params.get(f)
            if v:
                qs = qs.filter(**{f: v})
        return qs

    @extend_schema(request=LegalHoldSerializer, responses={201: LegalHoldSerializer})
    @idempotent
    def create(self, request):
        d = _valid(LegalHoldSerializer, request)
        h = services.place_hold(request.user, **d)
        return Response(LegalHoldSerializer(h).data, status=201)

    @extend_schema(request=ReasonSerializer, responses=LegalHoldSerializer)
    @action(detail=True, methods=["post"], url_path="lift-requests")
    def lift_requests(self, request, pk=None):
        h = self.get_object()
        services.request_lift(h, request.user, _valid(ReasonSerializer, request)["reason"])
        return Response(LegalHoldSerializer(h).data)

    @extend_schema(request=DecisionSerializer, responses=LegalHoldSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        h = self.get_object()
        d = _valid(DecisionSerializer, request)
        services.decide_lift(h, request.user, decision=d["decision"], mfa_at=require_mfa(request), note=d["note"])
        h.refresh_from_db()
        return Response(LegalHoldSerializer(h).data)


# ---------------------------------------------------------------- bulk exports (US-DPR-005)

class BulkExportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = BulkExportSerializer
    permission_classes = [DPR]
    queryset = BulkExport.objects.all().order_by("-created_at")

    @extend_schema(request=CreateBulkExportSerializer, responses={201: BulkExportSerializer})
    @idempotent
    def create(self, request):
        d = _valid(CreateBulkExportSerializer, request)
        be = services.request_bulk_export(request.user, **d)
        return Response(BulkExportSerializer(be).data, status=201)

    @extend_schema(request=DecisionSerializer, responses=BulkExportSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        be = self.get_object()
        d = _valid(DecisionSerializer, request)
        services.decide_bulk_export(be, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                    note=d["note"])
        be.refresh_from_db()
        return Response(BulkExportSerializer(be).data)

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.BINARY})
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        be = self.get_object()
        data = services.download_bulk_export(be, request.user)
        resp = HttpResponse(data, content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="bulk-export-{be.pk}.csv"'
        return resp


# ---------------------------------------------------------------- data catalogue and locations

class DataCatalogueViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin,
                           viewsets.GenericViewSet):
    serializer_class = DataCatalogueSerializer
    permission_classes = [DPR]
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return DataCatalogueEntry.objects.none()
        qs = DataCatalogueEntry.objects.all().order_by("table_name", "field_name")
        t = self.request.query_params.get("table")
        return qs.filter(table_name=t) if t else qs

    @extend_schema(request=None, responses=CatalogueGapsSerializer)
    @action(detail=False, methods=["post"])
    def sync(self, request):
        """Add every uncatalogued field and list those still without a purpose."""
        added = services.sync_catalogue()
        return Response({"added": added, "uncatalogued": services.uncatalogued_fields()})


class DataLocationViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, mixins.UpdateModelMixin,
                          viewsets.GenericViewSet):
    serializer_class = DataLocationSerializer
    permission_classes = [DPR]
    queryset = DataLocation.objects.all().order_by("service")
    http_method_names = ["get", "post", "patch"]

    def create(self, request, *args, **kwargs):
        d = _valid(DataLocationSerializer, request)
        loc = services.save_location(request.user, **d)
        return Response(DataLocationSerializer(loc).data, status=201)

