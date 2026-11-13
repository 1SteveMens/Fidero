"""RPT API (02 section 7.4): reports, sections, signatures, review approvals, the PDF link, corrections,
anonymised copies, the public hash check, re-checks and re-check incidents."""
import hashlib
from datetime import date

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from audit.services import record
from core.errors import DomainError, Forbidden, Invalid, NotFound, _problem
from core.idempotency import idempotent
from core.permissions import has_role
from core.views import ETagMixin, require_mfa

from . import selectors, services
from . import serializers as S
from .models import Condition, Incident, Recheck, RecheckDraw

UUID_RE = "[0-9a-fA-F-]{36}"


def _refused(request, exc, report, action_name, alert_cm=False):
    """Refusals the rules ask to be audited (TC-RUL-02-02, TC-RUL-04-02, TC-RUL-20-02). Returned, not raised,
    so the audit entry is kept."""
    record(actor=request.user, action=action_name, entity="report", entity_id=report.pk, country=report.country,
           data={"code": exc.code, "detail": exc.detail})
    if alert_cm:
        from cases.services import _alert

        _alert(report.country, ("CM",), subject=f"Signing blocked on {report.reference}", obj=report,
               link=f"/reports/{report.pk}", body=f"{request.user.full_name} could not sign: {exc.detail}")
    return _problem(exc.status, exc.code, exc.title, exc.detail, request, blocking_reasons=exc.blocking_reasons,
                    **exc.extra)


class ReportViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "case"]

    def get_queryset(self):
        return selectors.visible_reports(self.request.user).select_related(
            "case", "scope_text_version", "template_version").order_by("-created_at")

    def _staff_or_pro(self, report):
        from cases.services import is_assigned

        return services.is_report_staff(self.request.user, report) or is_assigned(self.request.user, report.case)

    def get_serializer_class(self):
        return S.ReportDetailSerializer if self.action == "retrieve" else S.ReportSerializer

    def retrieve(self, request, *args, **kwargs):
        report = self.get_object()
        if not self._staff_or_pro(report):
            return Response(S.ClientReportSerializer(report).data)
        return Response(S.ReportDetailSerializer(report, context={"request": request}).data)

    def _detail(self, report):
        report.refresh_from_db()
        return Response(S.ReportDetailSerializer(report, context={"request": self.request}).data)

    def _work_object(self):
        report = self.get_object()
        if not self._staff_or_pro(report):
            raise NotFound("Report not found.")
        return report

    @extend_schema(request=S.SectionInput, responses=S.SectionSerializer)
    @action(detail=True, methods=["put", "patch"], url_path=r"sections/(?P<number>\d+)")
    def section(self, request, pk=None, number=None):
        """Enter findings, attach evidence and choose the section verdict (FR-RPT-002). Section 12 is locked."""
        report = self._work_object()
        s = S.SectionInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            sec = services.update_section(report, int(number), request.user, findings=d.get("findings"),
                                          verdict=d["verdict"] if "verdict" in d else ...,
                                          evidence_ids=d.get("evidence_ids", []))
        except DomainError as exc:
            if exc.code == "locked-text":
                return _refused(request, exc, report, "report.locked_text_edit_refused")
            raise
        return Response(S.SectionSerializer(sec, context={"request": request}).data)

    @extend_schema(request=None, responses={201: S.SignatureSerializer})
    @action(detail=True, methods=["post"], url_path=r"sections/(?P<number>\d+)/signatures")
    @idempotent
    def sign(self, request, pk=None, number=None):
        """Sign a section with name, licence number and time (FR-RPT-005, RUL-20). Needs a fresh MFA step-up."""
        report = self._work_object()
        require_mfa(request)
        try:
            sig = services.sign_section(report, int(number), request.user)
        except DomainError as exc:
            if exc.code == "licence-invalid":
                return _refused(request, exc, report, "report.signing_refused", alert_cm=True)
            raise
        return Response(S.SignatureSerializer(sig).data, status=201)

    @extend_schema(request=S.VerdictInput, responses=S.ReportDetailSerializer)
    @action(detail=True, methods=["post"])
    def verdict(self, request, pk=None):
        """Set the overall verdict. Green is refused while any section 4 to 10 is red (RUL-02)."""
        report = self._work_object()
        s = S.VerdictInput(data=request.data)
        s.is_valid(raise_exception=True)
        try:
            services.set_overall_verdict(report, request.user, s.validated_data["overall_verdict"])
        except DomainError as exc:
            if exc.code == "verdict-rule":
                return _refused(request, exc, report, "report.verdict_refused")
            raise
        return self._detail(report)

    @extend_schema(methods=["GET"], request=None, responses=S.ConditionSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.ConditionInput, responses={201: S.ConditionSerializer})
    @action(detail=True, methods=["get", "post"])
    def conditions(self, request, pk=None):
        """Section 11 release conditions as structured items (FR-RPT-009)."""
        report = self.get_object()
        if request.method == "GET":
            return Response(S.ConditionSerializer(report.conditions.all(), many=True).data)
        report = self._work_object()
        s = S.ConditionInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.ConditionSerializer(services.add_condition(report, request.user, **s.validated_data)).data,
                        status=201)

    @extend_schema(request=None, responses={204: None})
    @action(detail=True, methods=["delete"], url_path=r"conditions/(?P<condition_id>[0-9a-fA-F-]{36})")
    def remove_condition(self, request, pk=None, condition_id=None):
        report = self._work_object()
        services.remove_condition(get_object_or_404(Condition, pk=condition_id, report=report), request.user)
        return Response(status=204)

    @extend_schema(request=None, responses=S.ReportDetailSerializer)
    @action(detail=True, methods=["post"], url_path="submit-review")
    @idempotent
    def submit_review(self, request, pk=None):
        """Compute the allowed verdict, insert the locked scope text, open the two-person approval (5.2)."""
        return self._detail(services.submit_review(self._work_object(), request.user))

    @extend_schema(request=S.ApprovalInput, responses=S.ReportDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        """Approve (signing lawyer, then a different reviewer, or the other way) or return (RUL-03)."""
        report = self._work_object()
        at = require_mfa(request)
        s = S.ApprovalInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.approve(report, request.user, decision=s.validated_data["decision"],
                         note=s.validated_data.get("note", ""), mfa_at=at)
        return self._detail(report)

    @extend_schema(request=None, responses=S.ReportDetailSerializer)
    @action(detail=True, methods=["post"])
    def release(self, request, pk=None):
        """Retry the release of an approved report whose release was blocked (for example a pending check)."""
        return self._detail(services.retry_release(self._work_object(), request.user))

    @extend_schema(request=None, responses=S.PdfLinkSerializer)
    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        """A short-lived signed link to the stored PDF bytes (FR-RPT-007, FR-EVD-003)."""
        from evidence.services import issue_link

        report = self.get_object()
        if report.pdf_evidence_id is None:
            raise NotFound("This report has no PDF yet.")
        link = issue_link(report.pdf_evidence, request.user, variant="original", request=request)
        return Response({"url": link["url"], "expires_at": link["expires_at"], "sha256": report.pdf_sha256,
                         "content_type": "application/pdf"})

    @extend_schema(request=S.CorrectionInput, responses={201: S.ReportDetailSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def corrections(self, request, pk=None):
        """A correction is a new version with a reason (FR-RPT-010)."""
        report = self._work_object()
        s = S.CorrectionInput(data=request.data)
        s.is_valid(raise_exception=True)
        inc = None
        if s.validated_data.get("incident_id"):
            inc = get_object_or_404(Incident, pk=s.validated_data["incident_id"], status="open")
        new = services.correct(report, request.user, s.validated_data["reason"], incident=inc)
        return Response(S.ReportDetailSerializer(new, context={"request": request}).data, status=201)

    @extend_schema(request=None, responses={201: S.AnonymisedCopySerializer})
    @action(detail=True, methods=["post"], url_path="anonymised-copies")
    def anonymised_copies(self, request, pk=None):
        """A case-study copy, only with the client's written consent on file (FR-RPT-011)."""
        report = self._work_object()
        return Response(S.AnonymisedCopySerializer(services.anonymised_copy(report, request.user)).data, status=201)


class VerifyThrottle(SimpleRateThrottle):
    scope = "report_verification"
    rate = "20/min"  # per address, assumption

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ReportVerificationView(APIView):
    """Public: does this PDF (or its SHA-256) match the report with this reference? Match or no match only;
    no report content and no client name (FR-RPT-008)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [VerifyThrottle]
    parser_classes = [JSONParser, MultiPartParser]

    @extend_schema(request={"application/json": S.VerificationInput, "multipart/form-data": S.VerificationInput},
                   responses=S.VerificationResultSerializer)
    def post(self, request):
        s = S.VerificationInput(data=request.data)
        s.is_valid(raise_exception=True)
        f = request.FILES.get("file")
        digest = hashlib.sha256(f.read()).hexdigest() if f is not None else s.validated_data.get("sha256")
        if not digest:
            raise Invalid("Send the PDF or its SHA-256.")
        from evidence.services import _ip_hash

        return Response(services.verify(s.validated_data["reference"], digest, ip_hash=_ip_hash(request)))


class RecheckViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The month's draw, assignments and results. Hidden from the case's original team (RUL-32)."""

    serializer_class = S.RecheckSerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        return Recheck.objects.select_related("case", "draw", "country")

    def get_object(self):
        r = super().get_object()
        u = self.request.user
        if r.assignee_id == u.pk or services._visible_to(u, r):
            return r
        raise NotFound("Re-check not found.")

    @extend_schema(parameters=[OpenApiParameter("month", str, required=False, description="YYYY-MM"),
                               OpenApiParameter("country", str, required=False)],
                   responses=S.RecheckMonthSerializer)
    def list(self, request):
        from countries.models import Country

        u = request.user
        if not has_role(u, "RV", "AD"):
            mine = selectors.rechecks_for_assignee(u)
            return Response({"draw": None, "items": S.RecheckSerializer(mine, many=True).data, "summary": {}})
        country = Country.objects.filter(code=request.query_params.get("country", "GH").upper()).first()
        if country is None:
            raise NotFound("Country not found.")
        raw = request.query_params.get("month")
        today = date.today()
        try:
            month = date.fromisoformat(f"{raw}-01") if raw else date(today.year, today.month, 1)
        except ValueError:
            raise Invalid("Month is YYYY-MM.") from None
        d = RecheckDraw.objects.filter(country=country, sample_month=month).first()
        items = [r for r in (d.rechecks.select_related("case") if d else []) if services._visible_to(u, r)]
        return Response({"draw": S.RecheckDrawSerializer(d).data if d else None,
                         "items": S.RecheckSerializer(items, many=True).data,
                         "summary": services.month_summary(country, month)})

    @extend_schema(request=S.DrawInput, responses={201: S.RecheckDrawSerializer})
    @action(detail=False, methods=["post"])
    def draws(self, request):
        """Run the month's draw by hand when the job did not run. One draw per month; a second is refused and
        audited (TC-RUL-32-04)."""
        from countries.models import Country

        if not has_role(request.user, "RV", "AD"):
            raise Forbidden("Reviewers and administrators only.")
        s = S.DrawInput(data=request.data)
        s.is_valid(raise_exception=True)
        country = get_object_or_404(Country, code=s.validated_data["country"].upper())
        try:
            d = services.draw(country, s.validated_data["month"], by=request.user)
        except DomainError as exc:
            record(actor=request.user, action="recheck.redraw_refused", entity="recheck_draw", entity_id=country.pk,
                   country=country, data={"month": s.validated_data["month"].isoformat()})
            return _problem(exc.status, exc.code, exc.title, exc.detail, request)
        return Response(S.RecheckDrawSerializer(d).data, status=201)

    @extend_schema(request=S.AssignInput, responses=S.RecheckSerializer)
    @action(detail=True, methods=["post"])
    def assignments(self, request, pk=None):
        from accounts.models import Person

        r = self.get_object()
        s = S.AssignInput(data=request.data)
        s.is_valid(raise_exception=True)
        person = get_object_or_404(Person, pk=s.validated_data["person_id"])
        return Response(S.RecheckSerializer(services.assign_recheck(r, request.user, person,
                                                                    role=s.validated_data["role"])).data)

    @extend_schema(request=S.SkipInput, responses=S.RecheckSerializer)
    @action(detail=True, methods=["post"])
    def skips(self, request, pk=None):
        return Response(S.RecheckSerializer(services.skip_recheck(self.get_object(), request.user,
                                                                  request.data.get("reason", ""))).data)

    @extend_schema(request=S.ResultInput, responses=S.RecheckSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def results(self, request, pk=None):
        r = self.get_object()
        s = S.ResultInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.RecheckSerializer(services.record_recheck_result(
            r, request.user, result=s.validated_data["result"], findings=s.validated_data.get("findings", ""))).data)


class IncidentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = S.IncidentSerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        u = self.request.user
        if not has_role(u, "RV", "AD"):
            return Incident.objects.none()
        return Incident.objects.all().order_by("-created_at")

    @extend_schema(request=S.CloseInput, responses=S.IncidentSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """Close after any correction is released and the client told; ESC lifts its freezes."""
        s = S.CloseInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.IncidentSerializer(services.close_incident(self.get_object(), request.user,
                                                                     s.validated_data["note"])).data)
