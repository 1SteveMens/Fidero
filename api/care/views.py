"""CARE API (02 section 7.4): care plans, the carer panel, visits, confirmations, reviewer decisions, payment
instructions and concerns; and the field app's `/v1/mobile/visits/*` for carers."""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import FamilyMember, Organisation, Person
from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, is_staff
from core.views import ETagMixin, mfa_at, require_mfa

from . import selectors, services
from . import serializers as S
from .models import Carer, Visit

UUID_RE = "[0-9a-fA-F-]{36}"


def _money(d):
    return {"amount": str(d["amount"]), "currency": d["currency"]} if d else None


def _point(d):
    return {"lat": d["lat"], "lng": d["lng"]} if d else None


class CarePlanViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Care plans (FR-CARE-001): clients their own, staff their countries, the assigned carer to read."""

    lookup_value_regex = UUID_RE
    serializer_class = S.CarePlanSerializer
    filterset_fields = ["status"]

    def get_queryset(self):
        return selectors.visible_plans(self.request.user).order_by("-created_at")

    def _out(self, plan, status=200):
        plan.refresh_from_db()
        return Response(S.CarePlanSerializer(plan, context={"request": self.request}).data, status=status)

    @extend_schema(request=S.CarePlanCreateInput, responses={201: S.CarePlanSerializer})
    @idempotent
    def create(self, request):
        s = S.CarePlanCreateInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        client = request.user
        if d.get("client_id"):
            if not has_role(request.user, "CM"):
                raise Forbidden("Only a case manager creates a plan for a client.")
            client = Person.objects.filter(pk=d["client_id"]).first()
            if client is None:
                raise Invalid("That client was not found.")
        plan = services.create_plan(
            request.user, client=client, family_member_id=d["family_member_id"], items=d["items"],
            schedule=d["schedule"], visit_fee=_money(d["visit_fee"]), confirmers=d["confirmers"],
            address=d.get("address", ""), point=_point(d.get("point")), confirm_channel=d["confirm_channel"],
            notes=d.get("notes", ""))
        return self._out(plan, 201)

    @extend_schema(request=S.CarePlanUpdateInput, responses=S.CarePlanSerializer)
    def partial_update(self, request, pk=None):
        plan = self.get_object()
        s = S.CarePlanUpdateInput(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        if "visit_fee" in d:
            d["visit_fee"] = _money(d["visit_fee"])
        if "point" in d:
            d["point"] = _point(d["point"])
        return self._out(services.update_plan(plan, request.user, d))

    @extend_schema(request=S.CareAssignInput, responses=S.CarePlanSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def assignments(self, request, pk=None):
        """Assign a vetted carer; the family is told who to expect (FR-CARE-002)."""
        plan = self.get_object()
        s = S.CareAssignInput(data=request.data)
        s.is_valid(raise_exception=True)
        carer = Carer.objects.filter(pk=s.validated_data["carer_id"]).first()
        if carer is None:
            raise Invalid("That carer is not on the panel.")
        return self._out(services.assign_carer(plan, request.user, carer))

    @extend_schema(request=S.CarePlanActivateInput, responses=S.CarePlanSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def activate(self, request, pk=None):
        """The client accepts the terms and agrees the carer; visits are scheduled (US-CARE-001 AC3)."""
        plan = self.get_object()
        s = S.CarePlanActivateInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.activate_plan(plan, request.user, mfa_at=mfa_at(request), **s.validated_data))

    @extend_schema(request=None, responses=S.CarePlanSerializer)
    @action(detail=True, methods=["post"], url_path="carer-approvals")
    @idempotent
    def carer_approvals(self, request, pk=None):
        """The client agrees a new carer as the payee of visit payments (RUL-28), with a fresh step-up."""
        plan = self.get_object()
        return self._out(services.approve_carer(plan, request.user, mfa_at=require_mfa(request)))

    @extend_schema(request=S.CareReasonInput, responses=S.CarePlanSerializer)
    @action(detail=True, methods=["post"])
    def pause(self, request, pk=None):
        s = S.CareReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.pause_plan(self.get_object(), request.user, reason=s.validated_data["reason"]))

    @extend_schema(request=None, responses=S.CarePlanSerializer)
    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._out(services.resume_plan(self.get_object(), request.user))

    @extend_schema(request=S.CareOptionalReasonInput, responses=S.CarePlanSerializer)
    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        s = S.CareOptionalReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.end_plan(self.get_object(), request.user,
                                           reason=s.validated_data.get("reason", "")))

    @extend_schema(methods=["POST"], request=S.CareStandingApprovalInput, responses=S.CarePlanSerializer)
    @extend_schema(methods=["DELETE"], request=None, responses=S.CarePlanSerializer)
    @action(detail=True, methods=["post", "delete"], url_path="standing-approvals")
    def standing_approvals(self, request, pk=None):
        """RUL-11: visit payments up to a monthly amount without approving each one; withdrawable at any time."""
        plan = self.get_object()
        if request.method == "DELETE":
            services.withdraw_standing_approval(plan, request.user)
            return self._out(plan)
        s = S.CareStandingApprovalInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.give_standing_approval(plan, request.user, monthly_max=s.validated_data["monthly_max"],
                                        mfa_at=mfa_at(request), code=s.validated_data.get("code"))
        return self._out(plan, 201)

    @extend_schema(responses=S.CareStatementSerializer)
    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        plan = self.get_object()
        return Response({"plan_id": str(plan.pk), "by_status": selectors.statement(plan)})


class CarerViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The carer panel (FR-CARE-002): staff manage it; a client reads the carers on their own plans."""

    lookup_value_regex = UUID_RE
    serializer_class = S.CarerSerializer
    filterset_fields = ["status", "pay_route"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Carer.objects.none()
        return selectors.panel(self.request.user).order_by("-created_at")

    def _out(self, carer, status=200):
        carer.refresh_from_db()
        return Response(S.CarerSerializer(carer).data, status=status)

    @extend_schema(request=S.CarerInput, responses={201: S.CarerSerializer})
    @idempotent
    def create(self, request):
        from accounts.models import Vetting
        from escrow.models import Payee

        if not is_staff(request.user):
            raise Forbidden()
        s = S.CarerInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        person = Person.objects.filter(pk=d["person_id"]).first()
        if person is None:
            raise Invalid("That person was not found.")
        vetting = Vetting.objects.filter(pk=d["vetting_id"]).first() if d.get("vetting_id") else None
        payee = Payee.objects.filter(pk=d["payee_id"]).first() if d.get("payee_id") else None
        org = Organisation.objects.filter(pk=d["agency_org_id"]).first() if d.get("agency_org_id") else None
        c = services.add_carer(request.user, person=person, vetting=vetting, pay_route=d["pay_route"], payee=payee,
                               agency_org=org, languages=d.get("languages", []), areas=d.get("areas", ""))
        return self._out(c, 201)

    @extend_schema(request=S.CarerUpdateInput, responses=S.CarerSerializer)
    def partial_update(self, request, pk=None):
        from escrow.models import Payee

        carer = self.get_object()
        s = S.CarerUpdateInput(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        payee = Payee.objects.filter(pk=d["payee_id"]).first() if d.get("payee_id") else None
        org = Organisation.objects.filter(pk=d["agency_org_id"]).first() if d.get("agency_org_id") else None
        return self._out(services.update_carer(carer, request.user, pay_route=d.get("pay_route"), payee=payee,
                                               agency_org=org, languages=d.get("languages"), areas=d.get("areas")))

    @extend_schema(responses=dict)
    @action(detail=True, methods=["get"])
    def vetting(self, request, pk=None):
        """The vetting record behind this carer: identity, references, background check, training."""
        return Response(S.CarerSerializer(self.get_object()).data["vetting"])

    @extend_schema(request=S.CareReasonInput, responses=S.CarerSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        s = S.CareReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.suspend_carer(self.get_object(), request.user, reason=s.validated_data["reason"]))

    @extend_schema(request=None, responses=S.CarerSerializer)
    @action(detail=True, methods=["post"])
    def reinstate(self, request, pk=None):
        return self._out(services.reinstate_carer(self.get_object(), request.user))

    @extend_schema(request=S.RemoveCarerInput, responses=S.CarerSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def remove(self, request, pk=None):
        """Removal for cause: future visits go to the replacement; the reason feeds the track record."""
        s = S.RemoveCarerInput(data=request.data)
        s.is_valid(raise_exception=True)
        rep = None
        if s.validated_data.get("replacement_id"):
            rep = Carer.objects.filter(pk=s.validated_data["replacement_id"]).first()
            if rep is None:
                raise Invalid("The replacement carer is not on the panel.")
        return self._out(services.remove_carer(self.get_object(), request.user, reason=s.validated_data["reason"],
                                               replacement=rep))


class VisitViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Visits with check-in, items, photos and confirmation (FR-CARE-003, FR-CARE-005): CL own, FM own, staff,
    the assigned carer."""

    lookup_value_regex = UUID_RE
    serializer_class = S.VisitSerializer
    filterset_fields = ["status", "plan"]

    @extend_schema(parameters=[OpenApiParameter("review", bool, description="Staff: only visits waiting for a "
                                                                              "reviewer's decision")])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        qs = selectors.visible_visits(self.request.user).order_by("-window_start")
        if self.request.query_params.get("review") in ("1", "true") and is_staff(self.request.user):
            qs = qs.filter(review_queued_at__isnull=False, status__in=["checked_out", "unconfirmed", "disputed"],
                           confirmation__reviewer_decision__isnull=True)
        return qs

    def get_serializer_class(self):
        if self.request is not None and self.request.user.is_authenticated \
                and self.request.user.has_tenmina_role("CE") and not is_staff(self.request.user):
            return S.FieldVisitSerializer
        return S.VisitSerializer

    def _out(self, visit):
        visit.refresh_from_db()
        return Response(self.get_serializer_class()(visit, context={"request": self.request}).data)

    @extend_schema(request=S.CareConfirmationInput, responses=S.VisitSerializer,
                   parameters=[OpenApiParameter("Idempotency-Key", str, OpenApiParameter.HEADER)])
    @action(detail=True, methods=["post"])
    @idempotent
    def confirmations(self, request, pk=None):
        """FR-CARE-004, RUL-23, ADR-20: a named confirmer confirms with the code; staff record a phone call that a
        second staff member must check. The carer's app has no access."""
        visit = self.get_object()
        s = S.CareConfirmationInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if d["method"] == "call":
            if not d.get("family_member_id") or not d.get("call_note"):
                raise Invalid("A call needs the family member called and a note.")
            fm = FamilyMember.objects.filter(pk=d["family_member_id"]).first()
            services.record_call(visit, request.user, family_member=fm, note=d["call_note"])
        else:
            if not d.get("code"):
                raise Invalid("Enter the 6-digit code.")
            services.confirm_with_code(visit, request.user, code=d["code"], method=d["method"])
        return self._out(visit)

    @extend_schema(request=S.CareCallCheckInput, responses=S.VisitSerializer)
    @action(detail=True, methods=["post"], url_path="call-checks")
    @idempotent
    def call_checks(self, request, pk=None):
        """A second staff member checks a recorded call before it counts for payment (FR-CARE-004)."""
        s = S.CareCallCheckInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.check_call(self.get_object(), request.user, agree=s.validated_data["agree"]))

    @extend_schema(request=S.ReviewerDecisionInput, responses=S.VisitSerializer)
    @action(detail=True, methods=["post"], url_path="reviewer-decisions")
    @idempotent
    def reviewer_decisions(self, request, pk=None):
        s = S.ReviewerDecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.reviewer_decide(self.get_object(), request.user, **s.validated_data))

    @extend_schema(request=None, responses={201: S.CareInstructionResult})
    @action(detail=True, methods=["post"])
    @idempotent
    def instructions(self, request, pk=None):
        """Instruction to pay the carer or agency for a confirmed visit (FR-CARE-004, RUL-23)."""
        ins = services.prepare_payment(self.get_object(), request.user)
        return Response({"instruction_id": str(ins.pk), "status": ins.status,
                         "amount": {"amount": f"{ins.amount:.2f}", "currency": ins.currency},
                         "client_approval": "standing approval" if ins.client_approval_method == "standing"
                         else "waiting for the client"}, status=201)

    @extend_schema(request=None, responses=S.VisitSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def codes(self, request, pk=None):
        """Staff send a new code to the family (the old one stops working)."""
        services.resend_code(self.get_object(), request.user)
        return self._out(self.get_object())

    @extend_schema(request=S.CareReasonInput, responses=S.VisitSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        s = S.CareReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.cancel_visit(self.get_object(), request.user, reason=s.validated_data["reason"]))


class PaymentBatchViewSet(viewsets.GenericViewSet):
    serializer_class = S.CareBatchResult

    @extend_schema(request=None, responses={201: S.CareBatchResult})
    @idempotent
    def create(self, request):
        """Run the weekly care payment batch now: confirmed visits only; unconfirmed ones are listed as awaiting
        confirmation (US-CARE-004 AC3, AC4)."""
        if not has_role(request.user, "CM", "RV"):
            raise Forbidden()
        return Response(services.payment_batch(by=request.user), status=201)


class ConcernViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Concerns (FR-CARE-006): reviewers see the restricted log; the client sees the outcome only."""

    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "severity", "kind"]

    def get_queryset(self):
        return selectors.visible_concerns(self.request.user).order_by("-raised_at")

    def get_serializer_class(self):
        if self.request is not None and self.request.user.is_authenticated \
                and has_role(self.request.user, "RV", "CM", "AD"):
            return S.ConcernSerializer
        return S.ClientConcernSerializer

    def _out(self, c):
        c.refresh_from_db()
        return Response(S.ConcernSerializer(c).data)

    @extend_schema(request=None, responses=S.ConcernSerializer)
    @action(detail=True, methods=["post"])
    def acknowledge(self, request, pk=None):
        return self._out(services.acknowledge_concern(self.get_object(), request.user))

    @extend_schema(request=S.ConcernActionInput, responses=S.ConcernSerializer)
    @action(detail=True, methods=["post"], url_path="action")
    def record_action(self, request, pk=None):
        s = S.ConcernActionInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(services.action_concern(self.get_object(), request.user, **s.validated_data))

    @extend_schema(request=None, responses=S.ConcernSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return self._out(services.close_concern(self.get_object(), request.user))


# --------------------------------------------------------------------------- Tenmina Field: /v1/mobile/visits/*

class FieldVisitViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The carer's own visits in Tenmina Field (FR-CARE-003). The family's code is never here (ADR-20)."""

    lookup_value_regex = UUID_RE
    serializer_class = S.FieldVisitSerializer
    filterset_fields = ["status"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.has_tenmina_role("CE"):
            return Visit.objects.none()
        return Visit.objects.filter(carer__person=self.request.user).exclude(status="cancelled").select_related(
            "plan__family_member", "carer__person", "checkin", "checkout").order_by("window_start")

    def _visit(self, pk):
        v = self.get_queryset().filter(pk=pk).first()
        if v is None:
            raise NotFound("This visit is not assigned to you.")
        return v

    @extend_schema(request=S.CareItemInput, responses=S.FieldVisitSerializer)
    @action(detail=True, methods=["put"], url_path=r"items/(?P<key>[a-z0-9_\-]+)")
    def items(self, request, pk=None, key=None):
        """Mark a plan item done (with the agreed photo or reading), not done with a reason, or not applicable."""
        v = self._visit(pk)
        s = S.CareItemInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        services.record_item(v, request.user, key, outcome=d["outcome"], reason=d.get("reason", ""),
                             reading=d.get("reading"), evidence_id=d.get("evidence_id"))
        v.refresh_from_db()
        return Response(S.FieldVisitSerializer(v).data)

    @extend_schema(request=S.ConcernInput, responses={201: S.ClientConcernSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def concerns(self, request, pk=None):
        """Raise a health, safety or welfare concern; the client and a reviewer hear the same day (FR-CARE-006)."""
        v = self._visit(pk)
        s = S.ConcernInput(data=request.data)
        s.is_valid(raise_exception=True)
        c = services.raise_concern(request.user, visit=v, **s.validated_data)
        return Response(S.ClientConcernSerializer(c).data, status=201)
