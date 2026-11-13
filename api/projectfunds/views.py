"""PRJ API (02 section 7.4): suppliers, background checks, the enhanced check, the project agreement, invoices
against stages and funding. Project funds are created with POST /v1/projects (type funds) and followed on the
shared project, milestone and payment endpoints of BLD."""
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from construction import projects
from construction import selectors as bld
from construction.models import Milestone, Project
from construction.serializers import ProjectDetailSerializer
from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role

from . import selectors, services
from . import serializers as S
from .models import AmlReview, BackgroundCheck, Invoice, Supplier

STAFF = ("CM", "RV", "AD")


def _project(request, pk) -> Project:
    p = bld.visible_projects(request.user).filter(pk=pk, type="funds").first()
    if p is None:
        raise NotFound("Project not found.")
    return p


def _staff_only(request, p):
    if not has_role(request.user, *STAFF, country=p.country):
        raise NotFound()


def _ev(pk, user):
    from evidence.models import Evidence

    if not pk:
        return None
    ev = Evidence.objects.filter(pk=pk).first()
    if ev is None or (ev.uploaded_by_id != user.pk and not has_role(user, *STAFF)):
        raise Invalid("That file was not found. Upload it again.", code="evidence-rejected")
    return ev


class ProjectSuppliers(APIView):
    @extend_schema(responses=S.SupplierSerializer(many=True))
    def get(self, request, pk):
        return Response(S.SupplierSerializer(selectors.suppliers_of(_project(request, pk)), many=True).data)

    @extend_schema(request=S.SupplierInput, responses={201: S.SupplierSerializer})
    @idempotent
    def post(self, request, pk):
        s = S.SupplierInput(data=request.data)
        s.is_valid(raise_exception=True)
        sup = services.add_supplier(_project(request, pk), request.user, s.validated_data)
        return Response(S.SupplierSerializer(sup).data, status=201)


class SupplierDetail(APIView):
    def _get(self, request, pk) -> Supplier:
        sup = Supplier.objects.filter(pk=pk, project__in=bld.visible_projects(request.user)).first()
        if sup is None:
            raise NotFound("Supplier not found.")
        return sup

    @extend_schema(responses=S.SupplierSerializer)
    def get(self, request, pk):
        return Response(S.SupplierSerializer(self._get(request, pk)).data)

    @extend_schema(request=S.SupplierInput, responses=S.SupplierSerializer)
    def patch(self, request, pk):
        """Fill in missing contact or bank details (US-PRJ-001 AC2)."""
        s = S.SupplierInput(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        sup = services.update_supplier(self._get(request, pk), request.user, s.validated_data)
        return Response(S.SupplierSerializer(sup).data)


class SupplierPayee(APIView):
    @extend_schema(request=S.SupplierPayeeInput, responses=S.SupplierSerializer)
    def post(self, request, pk):
        """A case manager records the supplier's verified payee; two staff verify it in the payee registry."""
        from accounts.selectors import national_id_check
        from escrow.models import Payee

        sup = Supplier.objects.filter(pk=pk).first()
        if sup is None or not has_role(request.user, "CM", "RV", country=sup.country):
            raise NotFound("Supplier not found.")
        s = S.SupplierPayeeInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if d.get("payee_id"):
            p = Payee.objects.filter(pk=d["payee_id"]).first()
            if p is None:
                raise NotFound("Payee not found.")
            return Response(S.SupplierSerializer(services.link_supplier_payee(sup, request.user, payee=p)).data)
        if not d.get("legal_name_evidence_id") or not d.get("account_name_source"):
            raise Invalid("Give the registration document and how the account name was checked.",
                          code="validation-error")
        details = {"legal_name_evidence": _ev(d["legal_name_evidence_id"], request.user),
                   "account_name": d.get("account_name", "") or sup.account_name,
                   "account_name_source": d["account_name_source"],
                   "account_name_evidence": _ev(d.get("account_name_evidence_id"), request.user),
                   "national_id_check": national_id_check(d["national_id_check_id"])
                   if d.get("national_id_check_id") else None,
                   "contact_phone": sup.contact_phone, "contact_email": sup.contact_email}
        return Response(S.SupplierSerializer(services.link_supplier_payee(sup, request.user, details=details)).data)


class ProjectChecks(APIView):
    @extend_schema(responses=S.CheckSerializer(many=True))
    def get(self, request, pk):
        p = _project(request, pk)
        _staff_only(request, p)
        return Response(S.CheckSerializer(selectors.checks_of(p), many=True).data)

    @extend_schema(request=S.StartChecksInput, responses={201: S.CheckSerializer(many=True)})
    @idempotent
    def post(self, request, pk):
        """FR-PRJ-002: start the identity and background checks on the person running it and every supplier."""
        p = _project(request, pk)
        _staff_only(request, p)
        s = S.StartChecksInput(data=request.data)
        s.is_valid(raise_exception=True)
        out = services.start_checks(p, request.user, runner_id_number=s.validated_data.get("runner_id_number", ""))
        return Response(S.CheckSerializer(out, many=True).data, status=201)


class CheckResult(APIView):
    @extend_schema(request=S.RunnerCheckInput, responses=S.CheckSerializer)
    def post(self, request, pk):
        chk = BackgroundCheck.objects.filter(pk=pk).first()
        if chk is None or not has_role(request.user, *STAFF, country=chk.country):
            raise NotFound("Check not found.")
        s = S.RunnerCheckInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        chk = services.record_runner_check(chk, request.user, outcome=d["outcome"], note=d.get("note", ""),
                                           evidence=_ev(d.get("evidence_id"), request.user),
                                           id_number=d.get("id_number", ""))
        return Response(S.CheckSerializer(chk).data)


class ProjectAml(APIView):
    @extend_schema(responses=S.AmlSerializer)
    def get(self, request, pk):
        p = _project(request, pk)
        _staff_only(request, p)
        r = selectors.aml_review(p)
        if r is None:
            raise NotFound("No enhanced check is needed for this project.")
        return Response(S.AmlSerializer(r).data)

    @extend_schema(request=S.AmlInput, responses=S.AmlSerializer)
    def post(self, request, pk):
        """FR-PRJ-004: a case manager prepares the enhanced check above the threshold."""
        p = _project(request, pk)
        _staff_only(request, p)
        s = S.AmlInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.AmlSerializer(services.prepare_aml(p, request.user, **s.validated_data)).data)


class AmlDecision(APIView):
    @extend_schema(request=S.AmlDecisionInput, responses=S.AmlSerializer)
    def post(self, request, pk):
        r = AmlReview.objects.filter(pk=pk).first()
        if r is None or not has_role(request.user, *STAFF, country=r.country):
            raise NotFound()
        s = S.AmlDecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(S.AmlSerializer(services.decide_aml(r, request.user, **s.validated_data)).data)


class ProjectAgreement(APIView):
    @extend_schema(responses=S.AgreementSerializer)
    def get(self, request, pk):
        """FR-PRJ-005: the agreement, always with the no-advice statement."""
        p = _project(request, pk)
        a = services.current_agreement(p)
        if a is None:
            raise NotFound()
        return Response(S.AgreementSerializer(a).data)

    @extend_schema(request=None, responses=S.AgreementSerializer)
    @idempotent
    def post(self, request, pk):
        """The client accepts the agreement."""
        return Response(S.AgreementSerializer(services.accept_agreement(_project(request, pk), request.user)).data)


class ProjectInvoices(APIView):
    @extend_schema(responses=S.InvoiceSerializer(many=True))
    def get(self, request, pk):
        return Response(S.InvoiceSerializer(selectors.invoices_of(_project(request, pk)), many=True).data)

    @extend_schema(request=S.InvoiceInput, responses={201: S.InvoiceSerializer})
    @idempotent
    def post(self, request, pk):
        """FR-PRJ-003: a supplier's invoice against a stage."""
        p = _project(request, pk)
        s = S.InvoiceInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        inv = services.submit_invoice(p, request.user, supplier_id=d["supplier_id"], milestone_id=d["milestone_id"],
                                      number=d["number"], amount=d["amount"]["amount"],
                                      evidence_ids=d["evidence_ids"], description=d.get("description", ""))
        return Response(S.InvoiceSerializer(inv).data, status=201)


class InvoiceDetail(APIView):
    @extend_schema(responses=S.InvoiceSerializer)
    def get(self, request, pk):
        inv = Invoice.objects.filter(pk=pk, project__in=bld.visible_projects(request.user)).first()
        if inv is None:
            raise NotFound()
        return Response(S.InvoiceSerializer(inv).data)


class InvoiceDecision(APIView):
    @extend_schema(request=S.InvoiceDecisionInput, responses=S.InvoiceSerializer)
    @idempotent
    def post(self, request, pk):
        """Accept (a partial release to the supplier follows once the stage is confirmed) or reject."""
        inv = Invoice.objects.filter(pk=pk).first()
        if inv is None or not has_role(request.user, *STAFF, country=inv.country):
            raise NotFound()
        s = S.InvoiceDecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        inv = services.decide_invoice(inv, request.user, **s.validated_data)
        inv.refresh_from_db()
        return Response(S.InvoiceSerializer(inv).data)


class ProjectFunding(APIView):
    @extend_schema(request=None, responses=ProjectDetailSerializer)
    @idempotent
    def post(self, request, pk):
        """Escrow route: open the project fund escrow; launch route: start. Blocked until every check passes."""
        p = _project(request, pk)
        if not has_role(request.user, "CM", country=p.country):
            raise Forbidden("A case manager funds the project.")
        if p.payment_route == "escrow":
            projects.open_escrow(p, request.user)
        else:
            projects.start(p, request.user)
        p.refresh_from_db()
        return Response(ProjectDetailSerializer(p, context={"request": request}).data)


class StageClosure(APIView):
    @extend_schema(request=S.StageCloseInput, responses=S.StageClosed)
    def post(self, request, pk):
        m = Milestone.objects.filter(pk=pk, project__type="funds").first()
        if m is None or not has_role(request.user, *STAFF, country=m.country):
            raise NotFound()
        s = S.StageCloseInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.close_stage(m, request.user, note=s.validated_data.get("note", ""))
        return Response({"id": str(m.pk), "status": "paid"})
