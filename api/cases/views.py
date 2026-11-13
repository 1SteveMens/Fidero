"""CASE API (02 section 7.4): cases, tasks, the work queue, document requests, messages, risk screens,
safety incidents, costs, parties, official searches and fresh searches."""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action, api_view, parser_classes
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.models import Person
from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, roles
from core.views import ETagMixin

from . import selectors, services
from . import serializers as S
from .models import Case, DocumentRequest, Party, SafetyIncident, SafetyReader, SearchRequest, Task

UUID_RE = "[0-9a-fA-F-]{36}"
PARSERS = [JSONParser, MultiPartParser]


def _evidence(request, country, *, source="upload", field="file", required=True):
    """A file sent with the request, or evidence the caller uploaded before."""
    from evidence.models import Evidence
    from evidence.services import store

    f = request.FILES.get(field)
    if f is not None:
        return store(data=f.read(), country=country, uploaded_by=request.user,
                     content_type=f.content_type or "application/octet-stream", original_name=f.name, source=source)
    eid = request.data.get("evidence_id")
    if eid:
        ev = Evidence.objects.filter(pk=eid, uploaded_by=request.user).first()
        if ev is None:
            raise Invalid("That upload was not found. Upload the file again.", code="evidence-rejected")
        return ev
    if required:
        raise Invalid("Attach the file.", extra={"errors": [{"pointer": "/file", "message": "Required."}]})
    return None


def _case_for(user, pk) -> Case:
    c = selectors.visible_cases(user).filter(pk=pk).select_related("country", "template_version").first()
    if c is None:
        raise NotFound("Case not found.")
    return c


def _person(pk):
    if pk is None:
        return None
    p = Person.objects.filter(pk=pk).first()
    if p is None:
        raise Invalid("That person was not found.")
    return p


class CaseViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Case list and tracker: clients their own, staff their countries, professionals what they are assigned."""

    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "product_line"]

    def get_queryset(self):
        return selectors.visible_cases(self.request.user).select_related(
            "country", "client", "case_manager", "template_version").order_by("-created_at")

    def get_serializer_class(self):
        return S.CaseDetailSerializer if self.action == "retrieve" else S.CaseSerializer

    @extend_schema(request=S.OpenCaseInput, responses={201: S.CaseDetailSerializer})
    @idempotent
    def create(self, request):
        """Open the case for a paid order by hand, when it did not open on payment (FR-CASE-001)."""
        if not has_role(request.user, "CM", "RV"):
            raise Forbidden("Only a case manager opens a case.")
        s = S.OpenCaseInput(data=request.data)
        s.is_valid(raise_exception=True)
        case = services.create_from_order(s.validated_data["order_id"], actor=request.user)
        if case is None:
            raise Invalid("This order's line opens its own case.")
        return Response(S.CaseDetailSerializer(case, context={"request": request}).data, status=201)

    def _detail(self, request, case, status=200):
        case.refresh_from_db()
        return Response(S.CaseDetailSerializer(case, context={"request": request}).data, status=status)

    @extend_schema(request=None, responses=S.CaseDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def accept(self, request, pk=None):
        """Paid to in progress; the template's steps become tasks (FR-CASE-002)."""
        return self._detail(request, services.accept(self.get_object(), request.user))

    @extend_schema(request=S.ReasonInput, responses=S.CaseDetailSerializer)
    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        s = S.ReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._detail(request, services.hold(self.get_object(), request.user, s.validated_data["reason"],
                                                   s.validated_data.get("client_message", "")))

    @extend_schema(request=None, responses=S.CaseDetailSerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._detail(request, services.resume(self.get_object(), request.user))

    @extend_schema(request=S.CancelInput, responses=S.CaseDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def cancel(self, request, pk=None):
        s = S.CancelInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        return self._detail(request, services.cancel(self.get_object(), request.user, d["reason"],
                                                     d["refund_decision"], d.get("refund_amount")))

    @extend_schema(request=S.DecisionInput, responses=S.CaseDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def decisions(self, request, pk=None):
        """Verification decision for institution, property, vendor, supplier, contractor and developer checks."""
        s = S.DecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._detail(request, services.decide_verification(self.get_object(), request.user,
                                                                  **s.validated_data))

    @extend_schema(methods=["GET"], request=None, responses=S.DocumentRequestSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.DocumentRequestInput, responses={201: S.DocumentRequestSerializer})
    @action(detail=True, methods=["get", "post"], url_path="document-requests")
    def document_requests(self, request, pk=None):
        case = self.get_object()
        if request.method == "GET":
            return Response(S.DocumentRequestSerializer(case.document_requests.order_by("-created_at"),
                                                        many=True).data)
        s = S.DocumentRequestInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.DocumentRequestSerializer(services.request_document(case, request.user,
                                                                              **s.validated_data)).data, status=201)

    @extend_schema(methods=["GET"], request=None, responses=S.MessageSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.MessageInput, responses={201: S.MessageSerializer})
    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        case = self.get_object()
        if request.method == "GET":
            if services.is_assigned(request.user, case) and not services.is_case_staff(request.user, case):
                raise NotFound("Not found.")
            return Response(S.MessageSerializer(case.messages.select_related("sender"), many=True).data)
        s = S.MessageInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.MessageSerializer(services.post_message(case, request.user, s.validated_data["body"])).data,
                        status=201)

    @extend_schema(methods=["GET"], request=None, responses=S.RiskScreenSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.RiskScreenInput, responses={201: S.RiskScreenSerializer})
    @action(detail=True, methods=["get", "post"], url_path="risk-screens")
    def risk_screens(self, request, pk=None):
        case = self.get_object()
        if not (services.is_case_staff(request.user, case) or services.is_assigned(request.user, case)):
            raise NotFound("Not found.")
        if request.method == "GET":
            return Response(S.RiskScreenSerializer(case.risk_screens.order_by("-created_at"), many=True).data)
        s = S.RiskScreenInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        task = get_object_or_404(Task, pk=d.pop("task_id"), case=case)
        return Response(S.RiskScreenSerializer(services.record_risk_screen(case, request.user, task=task, **d)).data,
                        status=201)

    @extend_schema(request=S.SafetyIncidentInput, responses={201: S.SafetyIncidentLoggedSerializer})
    @action(detail=True, methods=["post"], url_path="safety-incidents")
    @idempotent
    def safety_incidents(self, request, pk=None):
        """Write only: the incident goes to the restricted log (FR-CASE-010)."""
        case = self.get_object()
        s = S.SafetyIncidentInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        inc = services.log_safety_incident(actor=request.user, country=case.country, case=case,
                                           occurred_at=d.get("occurred_at"), severity=d["severity"],
                                           narrative=d["narrative"], persons_named=d.get("persons_named", ""),
                                           location_note=d.get("location_note", ""))
        return Response({"id": inc.pk, "logged_at": inc.created_at,
                         "message": "The incident is logged. The safety lead and your case manager are told. If you "
                                    "are in danger, leave and call the duty phone."}, status=201)

    @extend_schema(methods=["GET"], request=None, responses=S.CostSummarySerializer)
    @extend_schema(methods=["POST"], request=S.CostInput, responses={201: S.CostItemSerializer})
    @action(detail=True, methods=["get", "post"])
    def costs(self, request, pk=None):
        case = self.get_object()
        if not services.is_case_staff(request.user, case):
            raise NotFound("Not found.")
        if request.method == "GET":
            return Response({"items": S.CostItemSerializer(case.costs.order_by("incurred_on"), many=True).data,
                             **selectors.cost_summary(case)})
        s = S.CostInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        money = d["amount"]
        if "amount" not in money or "currency" not in money:
            raise Invalid('Give the amount as {"amount": "120.00", "currency": "GHS"}.')
        item = services.add_cost(case, actor=request.user, item_type=d["item_type"], amount=money["amount"],
                                 currency=money["currency"], incurred_on=d.get("incurred_on"),
                                 description=d.get("description", ""))
        return Response(S.CostItemSerializer(item).data, status=201)

    @extend_schema(methods=["GET"], request=None, responses=S.PartySerializer(many=True))
    @extend_schema(methods=["POST"], request=S.PartyInput, responses={201: S.PartySerializer})
    @action(detail=True, methods=["get", "post"])
    @idempotent
    def parties(self, request, pk=None):
        """FR-ACC-013: the sellers, grantors, consenting parties and signatories to check (RUL-31)."""
        case = self.get_object()
        if not services._may_handle_parties(request.user, case):
            raise NotFound("Not found.")
        if request.method == "GET":
            return Response(S.PartySerializer(case.parties.select_related("national_id_check"), many=True).data)
        s = S.PartyInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        from accounts.models import NationalIdCheck, Organisation

        org = Organisation.objects.filter(pk=d.get("for_organisation_id")).first() \
            if d.get("for_organisation_id") else None
        chk = NationalIdCheck.objects.filter(pk=d.get("national_id_check_id")).first() \
            if d.get("national_id_check_id") else None
        party = services.add_party(case, request.user, role=d["role"], name=d["name"],
                                   person=_person(d.get("person_id")), for_organisation=org,
                                   organisation_name=d.get("organisation_name", ""), id_number=d.get("id_number", ""),
                                   national_id_check=chk, adapter=d.get("adapter", "api"))
        return Response(S.PartySerializer(party).data, status=201)

    @extend_schema(methods=["GET"], request=None, responses=S.SearchRequestSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.SearchSubmitInput, responses={201: S.SearchRequestSerializer})
    @action(detail=True, methods=["get", "post"], url_path="search-requests")
    @idempotent
    def search_requests(self, request, pk=None):
        """FR-CASE-016, RUL-30: searches lodged from Tenmina's own registry account, by staff only."""
        case = self.get_object()
        if not services.is_case_staff(request.user, case):
            raise NotFound("Not found.")
        if request.method == "GET":
            return Response(S.SearchRequestSerializer(case.search_requests.select_related(
                "registry_partner", "submitted_by", "result_received_by", "confirmed_by"), many=True).data)
        s = S.SearchSubmitInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        task = get_object_or_404(Task, pk=d.pop("task_id"), case=case)
        sr = services.submit_search(case, request.user, task=task, channel=d["channel"],
                                    tenmina_account_ref=d["tenmina_account_ref"],
                                    registry_reference=d.get("registry_reference", ""),
                                    submitted_at=d.get("submitted_at"), search_on=d.get("search_on", ""),
                                    partner_id=d.get("registry_partner_id"))
        return Response(S.SearchRequestSerializer(sr).data, status=201)


class TaskViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Tasks: staff in their countries; professionals and runners see only their own (TC-CASE-006-02)."""

    serializer_class = S.TaskSerializer
    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "step_key", "case"]

    def get_queryset(self):
        return selectors.visible_tasks(self.request.user).select_related(
            "case", "assignee", "second_assignee").order_by("due_at")

    @extend_schema(request=S.TaskUpdateInput, responses=S.TaskSerializer)
    def partial_update(self, request, pk=None):
        """Assign a named person, or change the due date with a reason (FR-CASE-003)."""
        task = self.get_object()
        s = S.TaskUpdateInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        kw = {}
        if "assignee_id" in d:
            kw["assignee"] = _person(d["assignee_id"])
        if "second_assignee_id" in d:
            kw["second_assignee"] = _person(d["second_assignee_id"])
        if kw:
            task = services.assign_task(task, request.user, **kw)
        if "due_at" in d:
            task = services.change_due(task, request.user, d["due_at"], d.get("reason", ""))
        if not kw and "due_at" not in d:
            raise Invalid("Nothing to change.")
        task.refresh_from_db()
        return Response(S.TaskSerializer(task).data)

    @extend_schema(request=S.CompleteInput, responses=S.TaskSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def complete(self, request, pk=None):
        task = services.complete_task(self.get_object(), request.user, note=request.data.get("note", ""))
        task.refresh_from_db()
        return Response(S.TaskSerializer(task).data)

    @extend_schema(request=None, responses=S.TaskSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        task = services.start_task(self.get_object(), request.user)
        return Response(S.TaskSerializer(task).data)

    @extend_schema(request={"multipart/form-data": S.EvidenceInput, "application/json": S.EvidenceInput},
                   responses={201: S.TaskEvidenceLinkSerializer})
    @action(detail=True, methods=["post"], parser_classes=PARSERS)
    def evidence(self, request, pk=None):
        """Attach evidence, e.g. a receipt photographed in the phone browser (FR-CASE-006)."""
        task = self.get_object()
        kind = request.data.get("kind", "")
        if kind in ("official_search_result", "search_result"):
            services.attach_task_evidence(task, request.user, None, kind)  # refused before anything is stored
        ev = _evidence(request, task.case.country)
        services.attach_task_evidence(task, request.user, ev, kind)
        return Response({"evidence_id": ev.pk, "kind": kind, "sha256": ev.sha256}, status=201)


class DocumentRequestViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = S.DocumentRequestSerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        return DocumentRequest.objects.filter(case__in=selectors.visible_cases(self.request.user))

    @extend_schema(request={"multipart/form-data": S.DocumentResponseInput,
                            "application/json": S.DocumentResponseInput}, responses=S.DocumentRequestSerializer)
    @action(detail=True, methods=["post"], parser_classes=PARSERS)
    @idempotent
    def responses(self, request, pk=None):
        """The client uploads the requested document; the request closes and the case manager is told."""
        req = self.get_object()
        if not services.is_client(request.user, req.case):
            if services.is_representative(request.user, req.case):
                raise Forbidden("A representative can see the case but only the client can send documents.")
            raise NotFound("Not found.")
        ev = _evidence(request, req.case.country)
        return Response(S.DocumentRequestSerializer(services.respond_document_request(req, request.user, ev)).data)

    @extend_schema(request=S.RemovalInput, responses=S.DocumentRequestSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        req = self.get_object()
        return Response(S.DocumentRequestSerializer(services.cancel_document_request(
            req, request.user, request.data.get("reason", ""))).data)


class PartyViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = S.PartySerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        return Party.objects.filter(case__in=selectors.visible_cases(self.request.user))

    def get_object(self):
        p = super().get_object()
        if not services._may_handle_parties(self.request.user, p.case):
            raise NotFound("Not found.")
        return p

    @extend_schema(request=S.PartyCheckInput, responses=S.PartySerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def checks(self, request, pk=None):
        s = S.PartyCheckInput(data=request.data)
        s.is_valid(raise_exception=True)
        party = services.check_party(self.get_object(), request.user, **s.validated_data)
        return Response(S.PartySerializer(party).data)

    @extend_schema(request=S.RemovalInput, responses=S.PartySerializer)
    @action(detail=True, methods=["post"])
    def removal(self, request, pk=None):
        party = services.remove_party(self.get_object(), request.user, request.data.get("reason", ""))
        return Response(S.PartySerializer(party).data)


class SearchRequestViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Results and confirmations: case managers and reviewers only; never runners, sellers, developers or
    clients (RUL-30)."""

    serializer_class = S.SearchRequestSerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        return SearchRequest.objects.select_related("case", "registry_partner")

    def get_object(self):
        sr = super().get_object()
        if not services.is_case_staff(self.request.user, sr.case):
            raise NotFound("Not found.")
        return sr

    @extend_schema(request={"multipart/form-data": S.SearchResultInput, "application/json": S.SearchResultInput},
                   responses=S.SearchRequestSerializer)
    @action(detail=True, methods=["post"], parser_classes=PARSERS)
    @idempotent
    def results(self, request, pk=None):
        sr = self.get_object()
        services._require_search_staff(request.user, sr.case)
        s = S.SearchResultInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        ev = _evidence(request, sr.country, source="official_channel")
        sr = services.record_result(sr, request.user, evidence=ev, registry_result_date=d["registry_result_date"],
                                    registry_reference=d.get("registry_reference", ""), summary=d.get("summary", ""),
                                    confirmed_with=d.get("confirmed_with", ""), confirmed_at=d.get("confirmed_at"))
        return Response(S.SearchRequestSerializer(sr).data)

    @extend_schema(request=S.SearchConfirmInput, responses=S.SearchRequestSerializer)
    @action(detail=True, methods=["post"])
    def confirmations(self, request, pk=None):
        s = S.SearchConfirmInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.SearchRequestSerializer(services.confirm_result(self.get_object(), request.user,
                                                                          **s.validated_data)).data)

    @extend_schema(request=S.RemovalInput, responses=S.SearchRequestSerializer)
    @action(detail=True, methods=["post"])
    def rejections(self, request, pk=None):
        return Response(S.SearchRequestSerializer(services.reject_search(
            self.get_object(), request.user, request.data.get("reason", ""))).data)

    @extend_schema(request=S.CopyCompareInput, responses={201: S.CopyCheckSerializer})
    @action(detail=True, methods=["post"], url_path="copy-comparisons")
    def copy_comparisons(self, request, pk=None):
        from evidence.models import Evidence

        sr = self.get_object()
        s = S.CopyCompareInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        ev = get_object_or_404(Evidence, pk=d["evidence_id"])
        return Response(S.CopyCheckSerializer(services.compare_copy(sr, request.user, evidence=ev,
                                                                    matches=d["matches"],
                                                                    note=d.get("note", ""))).data, status=201)


class SafetyIncidentViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """The restricted log: only people individually granted safety.read; every read is audited."""

    serializer_class = S.SafetyIncidentSerializer
    pagination_class = None
    queryset = SafetyIncident.objects.none()

    @extend_schema(parameters=[OpenApiParameter("case", str, required=False)])
    def list(self, request):
        case = None
        if request.query_params.get("case"):
            case = Case.objects.filter(pk=request.query_params["case"]).first()
            if case is None:
                raise NotFound("Not found.")
        return Response(S.SafetyIncidentSerializer(services.read_incidents(request.user, case=case), many=True).data)


class SafetyReaderViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = S.SafetyReaderSerializer
    permission_classes = [roles("AD")]
    pagination_class = None

    def get_queryset(self):
        return SafetyReader.objects.select_related("person", "country").order_by("-created_at")

    @extend_schema(request=S.SafetyReaderInput, responses={201: S.SafetyReaderSerializer})
    def create(self, request):
        from countries.models import Country

        s = S.SafetyReaderInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        country = Country.objects.filter(code=d["country"].upper()).first() if d.get("country") else None
        r = services.grant_safety_read(request.user, _person(d["person_id"]), country=country,
                                       reason=d.get("reason", ""))
        return Response(S.SafetyReaderSerializer(r).data, status=201)

    @extend_schema(request=S.RemovalInput, responses=S.SafetyReaderSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        r = get_object_or_404(SafetyReader, pk=pk)
        return Response(S.SafetyReaderSerializer(services.revoke_safety_read(request.user, r,
                                                                             request.data.get("reason", ""))).data)


@extend_schema(parameters=[OpenApiParameter("owner", str, required=False), OpenApiParameter("step", str, required=False),
                           OpenApiParameter("status", str, required=False)],
               responses=S.TaskSerializer(many=True))
@api_view(["GET"])
def work_queue(request):
    """Tasks by due date, overdue first and highlighted (FR-CASE-005, FR-CASE-006)."""
    if not has_role(request.user, "CM", "RV", "LW", "SV", "RN", "IN", "QS", "CE"):
        raise Forbidden("The work queue is for Tenmina staff and professionals.")
    qp = request.query_params
    qs = selectors.work_queue(request.user, owner=qp.get("owner"), step=qp.get("step"), status=qp.get("status"))
    items = list(qs[:500])
    now = timezone.now()
    items.sort(key=lambda t: (t.due_at >= now, t.due_at))
    return Response({"items": S.TaskSerializer(items, many=True).data, "next_cursor": None})


@extend_schema(request=S.FreshSearchInput, responses={201: S.CaseDetailSerializer})
@api_view(["POST"])
@parser_classes([JSONParser])
def fresh_searches(request, asset_id):
    """FR-CASE-014: start a fresh-search case on a verified asset."""
    from geo.models import Asset

    asset = Asset.objects.filter(pk=asset_id).first()
    if asset is None or not has_role(request.user, "CM", "RV", country=asset.country):
        raise NotFound("Asset not found.")
    case = services.open_fresh_search(asset, actor=request.user, reason=request.data.get("reason", ""))
    return Response(S.CaseDetailSerializer(case, context={"request": request}).data, status=201)


@extend_schema(parameters=[OpenApiParameter("country", str, required=False)], responses=S.CostPerReportSerializer)
@api_view(["GET"])
def cost_per_report(request):
    """BO-02: total cost of released report cases divided by their number (FR-CASE-011)."""
    if not has_role(request.user, "CM", "RV", "AD"):
        raise Forbidden("Staff only.")
    from countries.models import Country

    code = request.query_params.get("country")
    country = Country.objects.filter(code=code.upper()).first() if code else None
    return Response(selectors.cost_per_report(country))
