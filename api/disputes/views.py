"""DSP API (02 section 7.4): open, statements, withdrawals by the raising party, decisions and referrals by
staff who are not parties. Parties see only their own disputes; staff are scoped to their countries."""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.idempotency import idempotent
from core.views import require_mfa

from . import services
from .models import Dispute
from .serializers import (DecisionApprovalIn, DecisionIn, DecisionSerializer, DisputeListSerializer,
                          DisputeSerializer, MediationOutcomeIn, OpenIn, ReferralIn, StatementIn,
                          DisputeStatementSerializer, WithdrawIn)


def _valid(cls, request):
    s = cls(data=request.data, context={"request": request})
    s.is_valid(raise_exception=True)
    return s.validated_data


class DisputeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = DisputeSerializer
    queryset = Dispute.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Dispute.objects.none()
        qs = services.visible(self.request.user).select_related("country")
        p = self.request.query_params
        if p.get("status"):
            qs = qs.filter(status__in=p["status"].split(","))
        if p.get("subject_id"):
            qs = qs.filter(subject_id=p["subject_id"])
        return qs

    def get_serializer_class(self):
        return DisputeListSerializer if self.action == "list" else DisputeSerializer

    @extend_schema(parameters=[OpenApiParameter("status", str, required=False),
                               OpenApiParameter("subject_id", str, required=False)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _ctx(self, d):
        return DisputeSerializer(d, context={"request": self.request}).data

    @extend_schema(request=OpenIn, responses={201: DisputeSerializer},
                   summary="Open a dispute; linked releases freeze at once (FR-DSP-001, RUL-15)")
    @idempotent
    def create(self, request):
        d = _valid(OpenIn, request)
        x = services.open_dispute(request.user, subject_type=d["subject_type"], subject_id=d["subject_id"],
                                  reason=d["reason"], category=d["category"], statement=d.get("statement", ""),
                                  evidence_ids=d.get("evidence_ids") or [], project_id=d.get("project_id"))
        return Response(self._ctx(x), status=201)

    @extend_schema(request=StatementIn, responses={201: DisputeStatementSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def statements(self, request, pk=None):
        d = _valid(StatementIn, request)
        s = services.add_statement(self.get_object(), request.user, text=d["text"],
                                   evidence_ids=d.get("evidence_ids") or [])
        return Response(DisputeStatementSerializer(s).data, status=201)

    @extend_schema(request=None, responses=DisputeSerializer,
                   summary="Confirm my evidence is complete (all parties: early move to Decision)")
    @action(detail=True, methods=["post"], url_path="evidence-complete")
    def evidence_complete(self, request, pk=None):
        x = services.confirm_evidence_complete(self.get_object(), request.user)
        return Response(self._ctx(x))

    @extend_schema(request=WithdrawIn, responses=DisputeSerializer,
                   summary="The party who raised it withdraws; frozen releases return to their prior state")
    @action(detail=True, methods=["post"])
    def withdrawals(self, request, pk=None):
        d = _valid(WithdrawIn, request)
        x = services.withdraw(self.get_object(), request.user, d.get("reason", ""))
        return Response(self._ctx(x))

    @extend_schema(request=DecisionIn, responses={201: DecisionSerializer},
                   summary="Record the decision and reasons for two staff to approve (CM, RV; not a party)")
    @action(detail=True, methods=["post"])
    @idempotent
    def decisions(self, request, pk=None):
        d = _valid(DecisionIn, request)
        dec = services.propose_decision(self.get_object(), request.user, outcome=d["outcome"],
                                        in_favour_of=d["in_favour_of"], reasons=d["reasons"],
                                        details=d.get("details") or {})
        return Response(DecisionSerializer(dec).data, status=201)

    @extend_schema(request=DecisionApprovalIn, responses=DecisionSerializer,
                   summary="Approve or reject the waiting decision (RV, AD; MFA; not a party or approver of the "
                           "disputed release)")
    @action(detail=True, methods=["post"], url_path="decision-approvals")
    @idempotent
    def decision_approvals(self, request, pk=None):
        d = _valid(DecisionApprovalIn, request)
        dec = services.approve_decision(self.get_object(), request.user, decision=d["decision"],
                                        mfa_at=require_mfa(request), note=d.get("note", ""))
        return Response(DecisionSerializer(dec).data)

    @extend_schema(request=ReferralIn, responses=DisputeSerializer, summary="Refer to mediation (RV)")
    @action(detail=True, methods=["post"])
    def referrals(self, request, pk=None):
        d = _valid(ReferralIn, request)
        x = services.refer(self.get_object(), request.user, mediator=d["mediator"], reason=d["reason"])
        return Response(self._ctx(x))

    @extend_schema(request=MediationOutcomeIn, responses={201: DecisionSerializer},
                   summary="Record the mediation outcome for two staff to approve (FR-DSP-005)")
    @action(detail=True, methods=["post"], url_path="mediation-outcomes")
    @idempotent
    def mediation_outcomes(self, request, pk=None):
        d = _valid(MediationOutcomeIn, request)
        x = self.get_object()
        if x.status != "referred":
            from core.errors import StateConflict

            raise StateConflict("Only a referred dispute has a mediation outcome.")
        dec = services.propose_decision(x, request.user, outcome=d["outcome"], in_favour_of=d["in_favour_of"],
                                        reasons=d["reasons"], details=d.get("details") or {},
                                        mediation_reference=d["mediation_reference"])
        return Response(DecisionSerializer(dec).data, status=201)
