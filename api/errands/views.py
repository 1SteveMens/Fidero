"""TSK API (02 section 7.4): the catalogue, errands, documents, payments, assignment, step fee instructions,
result checks and handovers; the agent panel; and the field app's `/v1/mobile/errands/*`."""
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import FamilyMember, Organisation, Person
from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, is_staff
from core.views import ETagMixin, mfa_at, require_mfa

from . import catalogue, selectors, services
from . import serializers as S
from .models import Agent, Errand

UUID_RE = "[0-9a-fA-F-]{36}"
PARSERS = [JSONParser, MultiPartParser]


def _evidence(request, country, *, data_class="identity_documents", required=True):
    """A file sent with the request, or evidence the caller uploaded before."""
    from evidence.models import Evidence
    from evidence.services import store

    f = request.FILES.get("file")
    if f is not None:
        return store(data=f.read(), country=country, uploaded_by=request.user,
                     content_type=f.content_type or "application/octet-stream", original_name=f.name,
                     data_class=data_class)
    eid = request.data.get("evidence_id")
    if eid:
        ev = Evidence.objects.filter(pk=eid, uploaded_by=request.user).first()
        if ev is None:
            raise Invalid("That upload was not found. Upload the file again.", code="evidence-rejected")
        return ev
    if required:
        raise Invalid("Attach the file.", extra={"errors": [{"pointer": "/file", "message": "Required."}]})
    return None


class CatalogueView(APIView):
    """The errand catalogue for a country (Pub): checklist, official fees, Tenmina's charge, target time
    (FR-TSK-001). Incomplete items are shown only to staff, with what is missing."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("country", str, required=True),
                               OpenApiParameter("include_incomplete", bool)],
                   responses=S.CatalogueSerializer)
    def get(self, request):
        from countries.models import Country

        code = (request.query_params.get("country") or "").upper()
        c = Country.objects.filter(code=code).first()
        if c is None:
            raise NotFound("No such country.")
        from administration import flags

        flags.require("lines.tsk", c)
        incl = request.query_params.get("include_incomplete") in ("1", "true") and request.user.is_authenticated \
            and is_staff(request.user)
        return Response({"country": c.code, "items": catalogue.items(c, include_incomplete=incl)})


class ErrandViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Errands (FR-TSK-002 to FR-TSK-005): clients their own, the assigned agent, staff their countries."""

    lookup_value_regex = UUID_RE
    serializer_class = S.ErrandSerializer
    filterset_fields = ["status"]
    parser_classes = PARSERS

    def get_queryset(self):
        return selectors.visible_errands(self.request.user).order_by("-created_at")

    def _out(self, e, status=200):
        e.refresh_from_db()
        return Response(S.ErrandSerializer(e, context={"request": self.request}).data, status=status)

    def _own(self, pk):
        e = self.get_object()
        if e.client_id != self.request.user.pk and not is_staff(self.request.user):
            raise NotFound()
        return e

    @extend_schema(request=S.ErrandCreateInput, responses={201: S.ErrandSerializer})
    @idempotent
    def create(self, request):
        from countries.models import Country

        s = S.ErrandCreateInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        client = request.user
        if d.get("client_id"):
            if not has_role(request.user, "CM"):
                raise Forbidden("Only a case manager orders for a client.")
            client = Person.objects.filter(pk=d["client_id"]).first()
            if client is None:
                raise Invalid("That client was not found.")
        country = Country.objects.filter(code=(d.get("country") or "").upper()).first() if d.get("country") \
            else client.home_country
        if country is None:
            raise Invalid("Choose the country.")
        e = services.create_errand(client, country=country, code=d["code"], by=request.user,
                                   for_family_member_id=d.get("for_family_member_id"), notes=d.get("notes", ""))
        return self._out(e, 201)

    @extend_schema(request={"multipart/form-data": S.DocumentUploadInput, "application/json": S.DocumentUploadInput},
                   responses={201: S.ErrandDocumentSerializer})
    @action(detail=True, methods=["post"], url_path=r"documents/(?P<key>[A-Za-z0-9_\-]+)")
    @idempotent
    def documents(self, request, pk=None, key=None):
        """Upload a checklist document (FR-TSK-002)."""
        e = self._own(pk)
        doc = services.upload_document(e, request.user, key, evidence=_evidence(request, e.country))
        return Response(S.ErrandDocumentSerializer(doc).data, status=201)

    @extend_schema(request=S.DocumentReviewInput, responses=S.ErrandDocumentSerializer)
    @action(detail=True, methods=["post"], url_path=r"documents/(?P<key>[A-Za-z0-9_\-]+)/reviews")
    def document_reviews(self, request, pk=None, key=None):
        e = self.get_object()
        doc = e.documents.filter(key=key).first()
        if doc is None:
            raise NotFound()
        s = S.DocumentReviewInput(data=request.data)
        s.is_valid(raise_exception=True)
        doc = services.review_document(doc, request.user, accept=s.validated_data["accept"],
                                       reason=s.validated_data.get("reason", ""))
        return Response(S.ErrandDocumentSerializer(doc).data)

    @extend_schema(request=S.ErrandSubmitInput, responses=S.ErrandSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def submit(self, request, pk=None):
        """Submit with every checklist document; Tenmina's charge becomes an order to pay through the provider and
        the official fees are paid into held funds at the partner bank (FR-TSK-002)."""
        s = S.ErrandSubmitInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.submit_errand(self._own(pk), request.user, **s.validated_data))

    @extend_schema(responses=S.PaymentRoutesSerializer)
    @action(detail=True, methods=["get"])
    def payments(self, request, pk=None):
        """The two payments and their routes, and what still stops an agent being assigned."""
        e = self._own(pk)
        return Response({**services.payment_routes(e), "blocking_reasons": services.funding_blockers(e)})

    @extend_schema(request=S.ErrandAssignInput, responses=S.ErrandSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def assignments(self, request, pk=None):
        """Assign a vetted agent with an active agreement, and the agency as the verified payee (FR-TSK-003)."""
        from escrow.models import Payee

        e = self.get_object()
        s = S.ErrandAssignInput(data=request.data)
        s.is_valid(raise_exception=True)
        agent = Agent.objects.filter(pk=s.validated_data["agent_id"]).first()
        if agent is None:
            raise Invalid("That agent is not on the panel.")
        payee = Payee.objects.filter(pk=s.validated_data["agency_payee_id"]).first() \
            if s.validated_data.get("agency_payee_id") else None
        return self._out(services.assign(e, request.user, agent=agent, agency_payee=payee))

    @extend_schema(request=None, responses=S.ErrandSerializer)
    @action(detail=True, methods=["post"], url_path="agency-approvals")
    @idempotent
    def agency_approvals(self, request, pk=None):
        return self._out(services.approve_agency(self._own(pk), request.user, mfa_at=require_mfa(request)))

    @extend_schema(methods=["POST"], request=S.ErrandStandingApprovalInput, responses=S.ErrandSerializer)
    @extend_schema(methods=["DELETE"], request=None, responses=S.ErrandSerializer)
    @action(detail=True, methods=["post", "delete"], url_path="standing-approvals")
    def standing_approvals(self, request, pk=None):
        """RUL-11: step fees up to a monthly amount; each still needs its receipt and two staff approvals."""
        e = self._own(pk)
        if request.method == "DELETE":
            services.withdraw_standing_approval(e, request.user)
            return self._out(e)
        s = S.ErrandStandingApprovalInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.give_standing_approval(e, request.user, monthly_max=s.validated_data["monthly_max"],
                                        mfa_at=mfa_at(request), code=s.validated_data.get("code"))
        return self._out(e, 201)

    @extend_schema(request=None, responses={201: S.ErrandInstructionResult})
    @action(detail=True, methods=["post"], url_path=r"steps/(?P<seq>[0-9]+)/instructions")
    @idempotent
    def step_instructions(self, request, pk=None, seq=None):
        """Instruction to pay a step's official fee to the agency (FR-TSK-003, RUL-22, RUL-23)."""
        e = self.get_object()
        step = e.steps.filter(seq=int(seq)).first()
        if step is None:
            raise NotFound()
        ins = services.prepare_step_fee(step, request.user)
        return Response({"instruction_id": str(ins.pk), "status": ins.status,
                         "amount": {"amount": f"{ins.amount:.2f}", "currency": ins.currency},
                         "payee": ins.payee.legal_name,
                         "client_approval": "standing approval" if ins.client_approval_method == "standing"
                         else "waiting for the client"}, status=201)

    @extend_schema(request=S.ResultCheckInput, responses=S.ErrandSerializer)
    @action(detail=True, methods=["post"], url_path="result-checks")
    @idempotent
    def result_checks(self, request, pk=None):
        """Staff check the resulting document; completes the errand and sends work.accepted (FR-TSK-004)."""
        s = S.ResultCheckInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.check_result(self.get_object(), request.user, **s.validated_data))

    @extend_schema(request={"multipart/form-data": S.ErrandHandoverInput, "application/json": S.ErrandHandoverInput},
                   responses={201: S.ErrandHandoverSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def handovers(self, request, pk=None):
        """Handover to the client, a named representative, a family member or a courier (FR-TSK-005)."""
        e = self.get_object()
        return _handover(request, e)

    @extend_schema(request=None, responses=S.ErrandHandoverSerializer)
    @action(detail=True, methods=["post"], url_path="handover-confirmations")
    def handover_confirmations(self, request, pk=None):
        h = services.confirm_handover(self.get_object(), request.user)
        return Response(S.ErrandHandoverSerializer(h).data)

    @extend_schema(request=S.ErrandReasonInput, responses=S.ErrandSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        s = S.ErrandReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.cancel_errand(self._own(pk), request.user, reason=s.validated_data["reason"]))


def _handover(request, e):
    s = S.ErrandHandoverInput(data=request.data)
    s.is_valid(raise_exception=True)
    d = s.validated_data
    with transaction.atomic():
        ev = _evidence(request, e.country, data_class="identity_documents")
        receiver = Person.objects.filter(pk=d["receiver_person_id"]).first() if d.get("receiver_person_id") else None
        fm = FamilyMember.objects.filter(pk=d["family_member_id"]).first() if d.get("family_member_id") else None
        h = services.record_handover(e, request.user, method=d["method"], proof_kind=d["proof_kind"], evidence=ev,
                                     receiver_person=receiver, family_member=fm,
                                     courier_name=d.get("courier_name", ""),
                                     tracking_reference=d.get("tracking_reference", ""),
                                     receiver_name=d.get("receiver_name", ""))
    return Response(S.ErrandHandoverSerializer(h).data, status=201)


class AgentViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The errand agent panel (FR-TSK-003): staff only."""

    lookup_value_regex = UUID_RE
    serializer_class = S.AgentSerializer
    filterset_fields = ["status"]

    def get_queryset(self):
        return selectors.agent_panel(self.request.user).order_by("-created_at")

    def _out(self, a, status=200):
        a.refresh_from_db()
        return Response(S.AgentSerializer(a).data, status=status)

    @extend_schema(request=S.AgentInput, responses={201: S.AgentSerializer})
    @idempotent
    def create(self, request):
        from accounts.models import Vetting

        if not is_staff(request.user):
            raise Forbidden()
        s = S.AgentInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        person = Person.objects.filter(pk=d["person_id"]).first()
        if person is None:
            raise Invalid("That person was not found.")
        v = Vetting.objects.filter(pk=d["vetting_id"]).first() if d.get("vetting_id") else None
        org = Organisation.objects.filter(pk=d["agency_org_id"]).first() if d.get("agency_org_id") else None
        a = services.add_agent(request.user, person=person, vetting=v, agency_org=org,
                               pro_agreement_id=d.get("pro_agreement_id"))
        return self._out(a, 201)

    @extend_schema(request=S.AgentUpdateInput, responses=S.AgentSerializer)
    def partial_update(self, request, pk=None):
        s = S.AgentUpdateInput(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        org = Organisation.objects.filter(pk=d["agency_org_id"]).first() if d.get("agency_org_id") else None
        return self._out(services.update_agent(self.get_object(), request.user,
                                               pro_agreement_id=d.get("pro_agreement_id"), agency_org=org))

    @extend_schema(request=S.ErrandReasonInput, responses=S.AgentSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        s = S.ErrandReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.set_agent_status(self.get_object(), request.user, to="suspended",
                                                   reason=s.validated_data["reason"]))

    @extend_schema(request=None, responses=S.AgentSerializer)
    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        return self._out(services.set_agent_status(self.get_object(), request.user, to="active"))

    @extend_schema(request=S.ErrandReasonInput, responses=S.AgentSerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        s = S.ErrandReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.set_agent_status(self.get_object(), request.user, to="removed",
                                                   reason=s.validated_data["reason"]))


# --------------------------------------------------------------------------- Tenmina Field: /v1/mobile/errands/*

class FieldErrandViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The agent's own errands in Tenmina Field (FR-TSK-003)."""

    lookup_value_regex = UUID_RE
    serializer_class = S.FieldErrandSerializer
    parser_classes = PARSERS

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.has_tenmina_role("CE"):
            return Errand.objects.none()
        return selectors.errands_for_agent(self.request.user).order_by("due_on", "created_at")

    def _errand(self, pk):
        e = self.get_queryset().filter(pk=pk).first()
        if e is None:
            raise NotFound("This errand is not assigned to you.")
        return e

    def _step(self, pk, seq):
        step = self._errand(pk).steps.filter(seq=int(seq)).first()
        if step is None:
            raise NotFound()
        return step

    def _out(self, e):
        e.refresh_from_db()
        return Response(S.FieldErrandSerializer(e).data)

    @extend_schema(request=None, responses=S.ErrandStepSerializer)
    @action(detail=True, methods=["post"], url_path=r"steps/(?P<seq>[0-9]+)/start")
    def start(self, request, pk=None, seq=None):
        step = services.start_step(self._step(pk, seq), request.user)
        step.refresh_from_db()
        return Response(S.ErrandStepSerializer(step).data)

    @extend_schema(request=S.StepProofInput, responses={201: S.ErrandStepSerializer})
    @action(detail=True, methods=["post"], url_path=r"steps/(?P<seq>[0-9]+)/receipts")
    @idempotent
    def receipts(self, request, pk=None, seq=None):
        """Upload the acknowledgement or receipt for a step, photographed in the app (FR-TSK-003)."""
        s = S.StepProofInput(data=request.data)
        s.is_valid(raise_exception=True)
        step = services.record_step_proof(self._step(pk, seq), request.user, **s.validated_data)
        step.refresh_from_db()
        return Response(S.ErrandStepSerializer(step).data, status=201)

    @extend_schema(request=None, responses=S.ErrandStepSerializer)
    @action(detail=True, methods=["post"], url_path=r"steps/(?P<seq>[0-9]+)/done")
    def done(self, request, pk=None, seq=None):
        """Mark a step done: refused without its receipt or acknowledgement (TC-TSK-003-04)."""
        step = services.complete_step(self._step(pk, seq), request.user)
        step.refresh_from_db()
        return Response(S.ErrandStepSerializer(step).data)

    @extend_schema(request=S.ErrandResultInput, responses={201: S.FieldErrandSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def results(self, request, pk=None):
        """Upload the resulting document (FR-TSK-004); Tenmina checks it before the errand completes."""
        s = S.ErrandResultInput(data=request.data)
        s.is_valid(raise_exception=True)
        e = services.upload_result(self._errand(pk), request.user, evidence_id=s.validated_data["evidence_id"])
        e.refresh_from_db()
        return Response(S.FieldErrandSerializer(e).data, status=201)

    @extend_schema(request=S.ErrandHandoverInput, responses={201: S.ErrandHandoverSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def handovers(self, request, pk=None):
        return _handover(request, self._errand(pk))

    @extend_schema(request=None, responses=S.ErrandDocumentLinkSerializer)
    @action(detail=True, methods=["get"], url_path=r"documents/(?P<key>[A-Za-z0-9_\-]+)/link")
    def document_link(self, request, pk=None, key=None):
        """A short-lived link to a checklist document the agent's open step needs (TC-TSK-002-03)."""
        from evidence.services import issue_link

        e = self._errand(pk)
        doc = e.documents.filter(key=key).first()
        if doc is None or doc.evidence_id is None or not selectors.agent_may_open(request.user, doc):
            raise NotFound()
        out = issue_link(doc.evidence, request.user, variant="original", request=request)
        return Response({"url": out["url"], "expires_at": out["expires_at"].isoformat()})
