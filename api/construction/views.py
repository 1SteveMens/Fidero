"""BLD API (02 section 7.4): projects, the bill of quantities, milestones, inspections, defects, variations, the
panel, conflict links, payments on both routes, materials and the build dashboard. Clients see their own
projects; staff their countries; contractors, inspectors and quantity surveyors only what they work on."""
from django.db import transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounts.models import Person
from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role
from core.views import ETagMixin, mfa_at, require_mfa

from . import materials, milestones, panel, payments, projects, selectors
from . import serializers as S
from .models import Defect, MaterialsOrder, Payment, Variation

UUID_RE = "[0-9a-fA-F-]{36}"
STAFF = ("CM", "RV", "AD")


def _evidence(pk, user, country=None):
    from evidence.models import Evidence

    if not pk:
        return None
    ev = Evidence.objects.filter(pk=pk).first()
    if ev is None or (ev.uploaded_by_id != user.pk and not has_role(user, *STAFF)):
        raise Invalid("That file was not found. Upload it again.", code="evidence-rejected")
    return ev


def _country(request, code=None):
    from countries.models import Country

    if code:
        c = Country.objects.filter(code=code.upper()).first()
        if c is None:
            raise Invalid("Unknown country.", code="validation-error")
        return c
    c = getattr(request.user, "home_country", None)
    if c is None:
        raise Invalid("Give the country.", code="validation-error")
    return c


# ----------------------------------------------------------------- panel (FR-BLD-003, FR-BLD-004, FR-BLD-010)

class PanelMemberViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Contractors, inspectors, quantity surveyors and developers. Clients see only active members."""

    lookup_value_regex = UUID_RE
    filterset_fields = ["kind", "status"]

    def get_queryset(self):
        qs = selectors.visible_panel(self.request.user).select_related("country", "payee").order_by("kind", "name")
        kind = self.request.query_params.get("kind")
        return qs.filter(kind=kind) if kind else qs

    def get_serializer_class(self):
        if has_role(self.request.user, *STAFF) or self.action in ("create",):
            return S.PanelMemberSerializer
        return S.PanelMemberPublicSerializer

    @extend_schema(parameters=[OpenApiParameter("kind", str), OpenApiParameter("status", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=S.PanelMemberInput, responses={201: S.PanelMemberSerializer})
    @idempotent
    def create(self, request):
        from accounts.models import Organisation

        s = S.PanelMemberInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        person = Person.objects.filter(pk=d["person_id"]).first() if d.get("person_id") else None
        org = Organisation.objects.filter(pk=d["organisation_id"]).first() if d.get("organisation_id") else None
        if d.get("person_id") and person is None or d.get("organisation_id") and org is None:
            raise Invalid("That person or company was not found.", code="validation-error")
        m = panel.create_member(request.user, country=_country(request, d.get("country")), kind=d["kind"],
                                name=d["name"], person=person, organisation=org,
                                registration_number=d.get("registration_number", ""),
                                contact_phone=d.get("contact_phone", ""), contact_email=d.get("contact_email", ""),
                                specialities=d.get("specialities", []))
        return Response(S.PanelMemberSerializer(m).data, status=201)

    def _out(self, m):
        m.refresh_from_db()
        return Response(S.PanelMemberSerializer(m).data)

    def _staff_obj(self):
        m = self.get_object()
        if not has_role(self.request.user, *STAFF, country=m.country):
            raise NotFound()
        return m

    @extend_schema(request=S.DocumentInput, responses=S.PanelMemberSerializer)
    @action(detail=True, methods=["post"])
    def documents(self, request, pk=None):
        s = S.DocumentInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(panel.add_documents(self._staff_obj(), request.user, **s.validated_data))

    @extend_schema(request=None, responses=S.PanelMemberSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def checks(self, request, pk=None):
        """Open the contractor or developer check case (FR-BLD-003, FR-BLD-011)."""
        m = self._staff_obj()
        panel.start_check(m, request.user)
        return self._out(m)

    @extend_schema(request=None, responses=S.PanelMemberSerializer)
    @action(detail=True, methods=["post"])
    def approval(self, request, pk=None):
        return self._out(panel.approve(self._staff_obj(), request.user))

    @extend_schema(request=S.BldReasonInput, responses=S.PanelMemberSerializer)
    @action(detail=True, methods=["post"])
    def suspension(self, request, pk=None):
        s = S.BldReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(panel.suspend(self._staff_obj(), request.user, reason=s.validated_data["reason"]))

    @extend_schema(request=None, responses=S.PanelMemberSerializer)
    @action(detail=True, methods=["post"])
    def reinstatement(self, request, pk=None):
        return self._out(panel.reinstate(self._staff_obj(), request.user))

    @extend_schema(request=S.PanelRemovalInput, responses=S.PanelMemberSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def removals(self, request, pk=None):
        """FR-BLD-010: a reviewer removes the member and freezes their releases."""
        s = S.PanelRemovalInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(panel.remove(self._staff_obj(), request.user, finding=s.validated_data["finding"],
                                      flag_id=s.validated_data.get("flag_id"), mfa_at=mfa_at(request)))

    @extend_schema(methods=["GET"], responses=S.ConflictLinkSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.ConflictLinkInput, responses={201: S.ConflictLinkSerializer})
    @action(detail=True, methods=["get", "post"], url_path="conflict-links")
    def conflict_links(self, request, pk=None):
        from .models import ConflictLink

        m = self._staff_obj()
        if request.method == "GET":
            qs = ConflictLink.objects.filter(inspector=m) | ConflictLink.objects.filter(contractor=m)
            return Response(S.ConflictLinkSerializer(qs.select_related("inspector", "contractor"), many=True).data)
        s = S.ConflictLinkInput(data=request.data)
        s.is_valid(raise_exception=True)
        other = panel.get(s.validated_data["other_id"])
        insp, con = (m, other) if m.kind == "inspector" else (other, m)
        link = panel.add_conflict(request.user, inspector=insp, contractor=con, reason=s.validated_data["reason"],
                                  note=s.validated_data.get("note", ""))
        return Response(S.ConflictLinkSerializer(link).data, status=201)

    @extend_schema(request=S.PayeeLinkInput, responses=S.PanelMemberSerializer)
    @action(detail=True, methods=["post"])
    def payee(self, request, pk=None):
        from accounts.selectors import national_id_check
        from escrow.models import Payee

        m = self._staff_obj()
        s = S.PayeeLinkInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        if d.get("payee_id"):
            p = Payee.objects.filter(pk=d["payee_id"]).first()
            if p is None:
                raise NotFound("Payee not found.")
            return self._out(panel.link_payee(m, request.user, payee=p))
        need = ["legal_name", "legal_name_evidence_id", "bank_name", "account_number", "account_name_source"]
        missing = [k for k in need if not d.get(k)]
        if missing:
            raise Invalid("Give the payee's bank details.", code="validation-error",
                          extra={"errors": [{"pointer": f"/{k}", "message": "Required."} for k in missing]})
        details = {"legal_name": d["legal_name"], "legal_name_evidence": _evidence(d["legal_name_evidence_id"],
                                                                                    request.user),
                   "bank_name": d["bank_name"], "account_number": d["account_number"],
                   "account_name": d.get("account_name", ""), "account_name_source": d["account_name_source"],
                   "account_name_evidence": _evidence(d.get("account_name_evidence_id"), request.user),
                   "national_id_check": national_id_check(d["national_id_check_id"])
                   if d.get("national_id_check_id") else None,
                   "contact_phone": d.get("contact_phone", ""), "contact_email": d.get("contact_email", "")}
        return self._out(panel.link_payee(m, request.user, details=details))

    @extend_schema(responses=S.TrackRecordSerializer)
    @action(detail=True, methods=["get"], url_path="track-record")
    def track_record(self, request, pk=None):
        return Response(panel.track_record(self.get_object()))


# ----------------------------------------------------------------- projects (FR-BLD-001, FR-BLD-002, FR-PRJ-001)

class ProjectViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "type"]

    def get_queryset(self):
        return selectors.visible_projects(self.request.user).select_related(
            "country", "contractor", "client").order_by("-created_at")

    def get_serializer_class(self):
        return S.ProjectDetailSerializer if self.action == "retrieve" else S.ProjectSerializer

    def _out(self, p, status=200):
        p.refresh_from_db()
        return Response(S.ProjectDetailSerializer(p, context={"request": self.request}).data, status=status)

    def _client_obj(self):
        p = self.get_object()
        if p.client_id != self.request.user.pk:
            raise NotFound()
        return p

    @extend_schema(request=S.ProjectInput, responses={201: S.ProjectDetailSerializer})
    @idempotent
    def create(self, request):
        """Start a construction, completion or off-plan project on a verified plot, or a funded project."""
        s = S.ProjectInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        client = Person.objects.filter(pk=d["client_id"]).first() if d.get("client_id") else None
        if d["type"] == "funds":
            from . import registry

            create = registry.hook("funds", "create")
            if create is None:
                raise Invalid("Project funds are not available.", code="validation-error")
            p = create(request.user, {**d, "client": client, "country": _country(request, d.get("country")),
                                      "budget": d["budget"]["amount"]})
        else:
            p = projects.create_project(request.user, type=d["type"], title=d["title"],
                                        description=d.get("description", ""), asset_id=d.get("asset_id"),
                                        budget=d["budget"]["amount"], client=client,
                                        payment_route=d.get("payment_route"), contractor_id=d.get("contractor_id"))
        return self._out(p, 201)

    @extend_schema(responses=S.DashboardSerializer)
    @action(detail=True, methods=["get"])
    def dashboard(self, request, pk=None):
        """FR-BLD-009: budget against actual, milestones, photo timeline (previews first), inspections, payments."""
        p = self.get_object()
        if not (selectors.is_client_side(request.user, p) or has_role(request.user, *STAFF, country=p.country)):
            raise NotFound()
        return Response(selectors.dashboard(p, request.user))

    @extend_schema(methods=["GET"], responses=S.BoqSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.BoqInput, responses={201: S.BoqSerializer})
    @action(detail=True, methods=["get", "post"])
    def boq(self, request, pk=None):
        p = self.get_object()
        if request.method == "GET":
            return Response(S.BoqSerializer(p.boqs.order_by("-version"), many=True).data)
        s = S.BoqInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        items = [{k: (str(v) if v is not None else None) for k, v in it.items()} for it in d["items"]]
        split = [{"key": x["key"], "name": x["name"], "share_pct": str(x["share_pct"])} for x in d.get("split", [])]
        boq = projects.submit_boq(p, request.user, items=items, evidence_ids=d["evidence_ids"], split=split or None,
                                  note=d.get("note", ""))
        return Response(S.BoqSerializer(boq).data, status=201)

    @extend_schema(request=None, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"], url_path="budget-approval")
    @idempotent
    def budget_approval(self, request, pk=None):
        """US-BLD-002 AC3: the client approves the budget and the split is locked."""
        return self._out(projects.approve_budget(self._client_obj(), request.user))

    @extend_schema(request=S.MemberIdInput, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"], url_path="quantity-surveyor")
    def quantity_surveyor(self, request, pk=None):
        s = S.MemberIdInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(projects.assign_quantity_surveyor(self.get_object(), request.user,
                                                           s.validated_data["member_id"]))

    @extend_schema(request=S.MemberIdInput, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"])
    def contractor(self, request, pk=None):
        """The client chooses a contractor from the active panel."""
        s = S.MemberIdInput(data=request.data)
        s.is_valid(raise_exception=True)
        p = self.get_object()
        if p.client_id == request.user.pk:
            return self._out(projects.choose_contractor(p, request.user, s.validated_data["member_id"]))
        if not has_role(request.user, "CM", country=p.country):
            raise Forbidden("The client or a case manager chooses the contractor.")
        return self._out(projects.choose_contractor(p, p.client, s.validated_data["member_id"], _by=request.user))

    @extend_schema(request=S.RequiredEvidenceInput, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def contract(self, request, pk=None):
        s = S.RequiredEvidenceInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(projects.sign_contract(self.get_object(), request.user,
                                                evidence_ids=s.validated_data["evidence_ids"]))

    @extend_schema(request=None, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def escrow(self, request, pk=None):
        """The escrow route: open the construction, off-plan or project fund escrow at the bank."""
        p = self.get_object()
        projects.open_escrow(p, request.user)
        return self._out(p)

    @extend_schema(request=None, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"])
    def start(self, request, pk=None):
        p = self.get_object()
        if not has_role(request.user, "CM", country=p.country):
            raise Forbidden("A case manager starts the project.")
        return self._out(projects.start(p, request.user))

    @extend_schema(request=S.EvidenceIdsInput, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def handover(self, request, pk=None):
        """RUL-09: Tenmina staff confirm site handover; mobilisation is then prepared for payment."""
        s = S.EvidenceIdsInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(projects.confirm_handover(self.get_object(), request.user,
                                                   evidence_ids=s.validated_data.get("evidence_ids", []),
                                                   note=s.validated_data.get("note", "")))

    @extend_schema(request=S.MemberIdInput, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"], url_path="inspector-assignments")
    def inspector_assignments(self, request, pk=None):
        """FR-BLD-004, RUL-10: only a case manager, only an inspector with no link to the contractor."""
        p = self.get_object()
        if not has_role(request.user, "CM", country=p.country):
            raise Forbidden("Only a case manager assigns the inspector.")
        s = S.MemberIdInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(projects.assign_inspector(p, request.user, s.validated_data["member_id"]))

    @extend_schema(methods=["GET"], responses=S.VariationSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.VariationInput, responses={201: S.VariationSerializer})
    @action(detail=True, methods=["get", "post"])
    def variations(self, request, pk=None):
        p = self.get_object()
        if request.method == "GET":
            return Response(S.VariationSerializer(p.variations.order_by("-created_at"), many=True).data)
        s = S.VariationInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        v = projects.propose_variation(p, request.user, milestone_id=d["milestone_id"], description=d["description"],
                                       cost_change=d["cost_change"]["amount"],
                                       time_effect_days=d.get("time_effect_days", 0))
        return Response(S.VariationSerializer(v).data, status=201)

    @extend_schema(methods=["GET"], responses=S.MaterialsOrderSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.MaterialsInput, responses={201: S.MaterialsOrderSerializer})
    @action(detail=True, methods=["get", "post"], url_path="materials-orders")
    def materials_orders(self, request, pk=None):
        """FR-BLD-013 (R3)."""
        p = self.get_object()
        if request.method == "GET":
            return Response(S.MaterialsOrderSerializer(p.materials_orders.order_by("-created_at"), many=True).data)
        s = S.MaterialsInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        o = materials.request_materials(p, request.user, milestone_id=d["milestone_id"],
                                        supplier_payee_id=d["supplier_payee_id"], description=d["description"],
                                        amount=d["amount"]["amount"], quote_evidence_ids=d["quote_evidence_ids"],
                                        items=d.get("items", []))
        return Response(S.MaterialsOrderSerializer(o).data, status=201)

    @extend_schema(request=S.BldReasonInput, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancellation(self, request, pk=None):
        s = S.BldReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(projects.cancel(self.get_object(), request.user, reason=s.validated_data["reason"]))

    @extend_schema(request=S.ResumeInput, responses=S.ProjectDetailSerializer)
    @action(detail=True, methods=["post"])
    def resumption(self, request, pk=None):
        s = S.ResumeInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(projects.resume(self.get_object(), request.user,
                                         contractor_id=s.validated_data.get("contractor_id")))

    @extend_schema(responses=S.ProjectPaymentSerializer(many=True))
    @action(detail=True, methods=["get"])
    def payments(self, request, pk=None):
        p = self.get_object()
        qs = selectors.visible_payments(request.user).filter(project=p).order_by("-created_at")
        return Response(S.ProjectPaymentSerializer(qs, many=True, context={"request": request}).data)


class VariationViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_value_regex = UUID_RE
    serializer_class = S.VariationSerializer

    def get_queryset(self):
        return Variation.objects.filter(project__in=selectors.visible_projects(self.request.user))

    @extend_schema(request=S.VariationDecisionInput, responses=S.VariationSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def agreements(self, request, pk=None):
        """RUL-19: the client and the contractor each agree in writing in the app before the work."""
        s = S.VariationDecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        v = projects.decide_variation(self.get_object(), request.user, **s.validated_data)
        v.refresh_from_db()
        return Response(S.VariationSerializer(v).data)


# ----------------------------------------------------------------- milestones (FR-BLD-005 to FR-BLD-007)

class MilestoneViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_value_regex = UUID_RE
    serializer_class = S.MilestoneSerializer

    def get_queryset(self):
        qs = selectors.visible_milestones(self.request.user).select_related("project").order_by("project", "seq")
        pid = self.request.query_params.get("project_id")
        st = self.request.query_params.get("status")
        if pid:
            qs = qs.filter(project_id=pid)
        if st:
            qs = qs.filter(status=st)
        return qs

    @extend_schema(parameters=[OpenApiParameter("project_id", str), OpenApiParameter("status", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _out(self, m):
        m.refresh_from_db()
        return Response(S.MilestoneSerializer(m).data)

    @extend_schema(request=S.EvidenceReviewInput, responses=S.MilestoneSerializer)
    @action(detail=True, methods=["post"], url_path="evidence-review")
    def evidence_review(self, request, pk=None):
        s = S.EvidenceReviewInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(milestones.review_evidence(self.get_object(), request.user, **s.validated_data))

    @extend_schema(methods=["GET"], responses=S.InspectionSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.ScheduleInput, responses={201: S.InspectionSerializer})
    @action(detail=True, methods=["get", "post"])
    def inspections(self, request, pk=None):
        m = self.get_object()
        if request.method == "GET":
            return Response(S.InspectionSerializer(m.inspections.order_by("-created_at"), many=True).data)
        s = S.ScheduleInput(data=request.data)
        s.is_valid(raise_exception=True)
        i = milestones.schedule_inspection(m, request.user, inspector_id=s.validated_data.get("inspector_id"),
                                           scheduled_for=s.validated_data.get("scheduled_for"))
        return Response(S.InspectionSerializer(i).data, status=201)

    @extend_schema(request=S.ClientApprovalInput, responses=S.MilestoneSerializer)
    @action(detail=True, methods=["post"], url_path="client-approval")
    @idempotent
    def client_approval(self, request, pk=None):
        """US-BLD-005b, RUL-11, RUL-18: the client approves with their second factor and sees the re-price."""
        s = S.ClientApprovalInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        amt = d.get("confirm_amount")
        return self._out(milestones.client_approve(self.get_object(), request.user, mfa_at=mfa_at(request),
                                                   code=d.get("code") or None,
                                                   confirm_amount=amt["amount"] if amt else None))

    @extend_schema(request=None, responses={201: S.ProjectPaymentSerializer})
    @action(detail=True, methods=["post"], url_path="release-instructions")
    @idempotent
    def release_instructions(self, request, pk=None):
        """Prepare (or prepare again) the milestone payment: the main amount, or the held defect value."""
        m = self.get_object()
        if not has_role(request.user, "CM", "RV", country=m.country):
            raise Forbidden("A case manager prepares payments.")
        main_paid = Payment.objects.filter(milestone=m, part="main", status="paid").exists()
        pay = milestones.prepare_holdback(m, request.user) if main_paid else milestones.prepare_main(m, request.user)
        return Response(S.ProjectPaymentSerializer(pay, context={"request": request}).data, status=201)

    @extend_schema(responses=S.RepriceSerializer(many=True))
    @action(detail=True, methods=["get"])
    def reprices(self, request, pk=None):
        """RUL-18: every re-price with the rate and its date; opening it marks the change as shown."""
        m = self.get_object()
        rs = list(m.reprices.order_by("-created_at"))
        if rs and request.user.pk == m.project.client_id:
            from .pricing import shown

            shown(rs[0])
        return Response(S.RepriceSerializer(rs, many=True).data)

    @extend_schema(request=S.RequiredEvidenceInput, responses=S.MilestoneSerializer)
    @action(detail=True, methods=["post"], url_path="stage-evidence")
    @idempotent
    def stage_evidence(self, request, pk=None):
        """Project funds: receipts for a stage (FR-PRJ-003)."""
        s = S.RequiredEvidenceInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(milestones.submit_stage_evidence(self.get_object(), request.user,
                                                          evidence_ids=s.validated_data["evidence_ids"],
                                                          note=s.validated_data.get("note", "")))

    @extend_schema(request=S.EvidenceIdsInput, responses=S.MilestoneSerializer)
    @action(detail=True, methods=["post"], url_path="stage-confirmation")
    def stage_confirmation(self, request, pk=None):
        """Project funds stages with no visit configured: confirmed at the desk."""
        s = S.EvidenceIdsInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(milestones.confirm_stage(self.get_object(), request.user,
                                                  note=s.validated_data.get("note", "")))


class InspectionViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_value_regex = UUID_RE
    serializer_class = S.InspectionSerializer

    def get_queryset(self):
        qs = selectors.visible_inspections(self.request.user).select_related("inspector").order_by("-created_at")
        st = self.request.query_params.get("status")
        return qs.filter(status=st) if st else qs

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=S.DeclarationInput, responses=S.InspectionSerializer)
    @action(detail=True, methods=["post"])
    def declaration(self, request, pk=None):
        """The inspector confirms "You have no link to this contractor", or declares a link (RUL-10)."""
        s = S.DeclarationInput(data=request.data)
        s.is_valid(raise_exception=True)
        i = milestones.declare_link(self.get_object(), request.user, **s.validated_data)
        i.refresh_from_db()
        return Response(S.InspectionSerializer(i).data)

    @extend_schema(request=S.ExtraAssignInput, responses=S.InspectionSerializer)
    @action(detail=True, methods=["post"])
    def assignment(self, request, pk=None):
        """An extra inspection the client ordered (FR-ORD-007): a case manager assigns the inspector."""
        s = S.ExtraAssignInput(data=request.data)
        s.is_valid(raise_exception=True)
        i = milestones.assign_extra_inspection(self.get_object(), request.user, **s.validated_data)
        return Response(S.InspectionSerializer(i).data)


class DefectViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_value_regex = UUID_RE
    serializer_class = S.DefectSerializer

    def get_queryset(self):
        qs = Defect.objects.filter(project__in=selectors.visible_projects(self.request.user)).order_by("-created_at")
        st = self.request.query_params.get("status")
        return qs.filter(status=st) if st else qs

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=S.RequiredEvidenceInput, responses=S.DefectSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def close(self, request, pk=None):
        """FR-BLD-006: closed only with evidence; the held value is then released."""
        s = S.RequiredEvidenceInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = milestones.close_defect(self.get_object(), request.user, evidence_ids=s.validated_data["evidence_ids"],
                                    note=s.validated_data.get("note", ""))
        d.refresh_from_db()
        return Response(S.DefectSerializer(d).data)

    @extend_schema(request=S.ConfirmInput, responses=S.DefectSerializer)
    @action(detail=True, methods=["post"])
    def confirmation(self, request, pk=None):
        s = S.ConfirmInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = milestones.confirm_defect(self.get_object(), request.user, **s.validated_data)
        d.refresh_from_db()
        return Response(S.DefectSerializer(d).data)


# ----------------------------------------------------------------- payments on both routes

class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Stage payments: on the escrow route each mirrors a release instruction; on the client_direct route the
    client pays the verified payee directly after two staff confirm."""

    lookup_value_regex = UUID_RE
    serializer_class = S.ProjectPaymentSerializer

    def get_queryset(self):
        qs = selectors.visible_payments(self.request.user).select_related("payee", "project", "reprice") \
            .order_by("-created_at")
        st = self.request.query_params.get("status")
        return qs.filter(status=st) if st else qs

    @extend_schema(parameters=[OpenApiParameter("status", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def _out(self, p):
        p = Payment.objects.get(pk=p.pk)
        return Response(S.ProjectPaymentSerializer(p, context={"request": self.request}).data)

    @extend_schema(request=S.ClientApprovalInput, responses=S.ProjectPaymentSerializer)
    @action(detail=True, methods=["post"], url_path="client-approval")
    @idempotent
    def client_approval(self, request, pk=None):
        s = S.ClientApprovalInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        pay = self.get_object()
        if pay.milestone_id and pay.part == "main":
            milestones.client_approve(pay.milestone, request.user, mfa_at=mfa_at(request),
                                      code=d.get("code") or None,
                                      confirm_amount=d["confirm_amount"]["amount"] if d.get("confirm_amount") else None)
        else:
            payments.client_approve(pay, request.user, mfa_at=mfa_at(request), code=d.get("code") or None,
                                    confirm_amount=d["confirm_amount"]["amount"] if d.get("confirm_amount") else None)
        return self._out(pay)

    @extend_schema(request=S.BldReasonInput, responses=S.ProjectPaymentSerializer)
    @action(detail=True, methods=["post"], url_path="client-decline")
    def client_decline(self, request, pk=None):
        s = S.BldReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(payments.client_decline(self.get_object(), request.user, s.validated_data["reason"]))

    @extend_schema(request=S.StaffDecisionInput, responses=S.ProjectPaymentSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        """Two staff with release rights, each with a fresh step-up, after the client (RUL-05, RUL-11)."""
        at = require_mfa(request)
        s = S.StaffDecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        pay = self.get_object()
        with transaction.atomic():
            payments.staff_decide(pay, request.user, mfa_at=at, **s.validated_data)
        return self._out(pay)

    @extend_schema(request=S.ClientPaymentInput, responses=S.ProjectPaymentSerializer)
    @action(detail=True, methods=["post"], url_path="client-payments")
    @idempotent
    def client_payments(self, request, pk=None):
        """client_direct: the client says they paid the verified account from their own bank."""
        s = S.ClientPaymentInput(data=request.data)
        s.is_valid(raise_exception=True)
        pay = self.get_object()
        return self._out(payments.record_client_payment(
            pay, request.user, reference=s.validated_data["reference"],
            evidence=_evidence(s.validated_data.get("evidence_id"), request.user)))

    @extend_schema(request=S.ReceiptInput, responses=S.ProjectPaymentSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def receipt(self, request, pk=None):
        """client_direct: the payee confirms the money arrived, or a case manager records the bank's receipt."""
        s = S.ReceiptInput(data=request.data)
        s.is_valid(raise_exception=True)
        pay = self.get_object()
        return self._out(payments.confirm_receipt(pay, request.user,
                                                  evidence=_evidence(s.validated_data.get("evidence_id"),
                                                                     request.user),
                                                  note=s.validated_data.get("note", "")))

    @extend_schema(request=S.BldReasonInput, responses=S.ProjectPaymentSerializer)
    @action(detail=True, methods=["post"])
    def withdrawal(self, request, pk=None):
        s = S.BldReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._out(payments.withdraw(self.get_object(), request.user, reason=s.validated_data["reason"]))


class MaterialsOrderViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    lookup_value_regex = UUID_RE
    serializer_class = S.MaterialsOrderSerializer

    def get_queryset(self):
        return MaterialsOrder.objects.filter(project__in=selectors.visible_projects(self.request.user))

    @extend_schema(request=S.RequiredEvidenceInput, responses=S.MaterialsOrderSerializer)
    @action(detail=True, methods=["post"])
    def deliveries(self, request, pk=None):
        s = S.RequiredEvidenceInput(data=request.data)
        s.is_valid(raise_exception=True)
        o = materials.record_delivery(self.get_object(), request.user, **s.validated_data)
        return Response(S.MaterialsOrderSerializer(o).data)


__all__ = ["PanelMemberViewSet", "ProjectViewSet", "VariationViewSet", "MilestoneViewSet", "InspectionViewSet",
           "DefectViewSet", "PaymentViewSet", "MaterialsOrderViewSet"]
