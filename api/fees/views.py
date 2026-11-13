"""FEE API (02 7.4: /v1/institutions*, /v1/invoices*, /v1/fee-payments*, /v1/fee-schedules,
/v1/fee-runner-tasks, /v1/family-members/{id}/statement). Clients see only their own objects; an
institution contact only its own institution's bills; staff their countries; runners their tasks."""
import base64

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, roles
from core.views import require_mfa

from . import selectors, services
from .models import Institution, InstitutionContact, Invoice, Payment, RunnerTask, Schedule
from .serializers import (FeeApprovalOut, FeeBeneficiaryIn, FeeBeneficiarySerializer, FeeCheckIn, FeeClientApprovalIn,
                          FeeClientPaymentIn, FeeConfirmIn, FeeContactIn, FeeContactSerializer, FeeEligibilityIn, FeeInstitutionIn,
                          FeeInstitutionPatch, FeeInstitutionSerializer, FeeInvoiceDocumentIn, FeeInvoiceIn, FeeInvoiceSerializer,
                          FeeLookAlikeIn, FeeOrderOut, FeePayeeIn, FeePayeeOut, FeePaymentSerializer, FeePlanIn, FeePreviewOut, FeeReasonIn,
                          FeeReceiptIn, FeeRouteIn, FeeRunnerCompleteIn, FeeRunnerTaskIn, FeeRunnerTaskSerializer, FeeScheduleIn,
                          FeeSchedulePatch, FeeScheduleSerializer, FeeStatementDocSerializer, FeeStatementOut)

STAFF = ("CM", "RV", "AD")


def _valid(cls, request):
    s = cls(data=request.data, context={"request": request})
    s.is_valid(raise_exception=True)
    return s.validated_data


def _country(code):
    from countries.models import Country

    c = Country.objects.filter(code=str(code or "").upper()).first()
    if c is None:
        raise Invalid("Unknown country.", code="validation-error")
    return c


def _get(model, pk):
    obj = model.objects.filter(pk=pk).first()
    if obj is None:
        raise NotFound()
    return obj


def _person(pk):
    from accounts.models import Person

    return _get(Person, pk) if pk else None


def _family_member(pk):
    from accounts.models import FamilyMember

    return _get(FamilyMember, pk) if pk else None


def _evidence(request, d, country, *, id_key="evidence_id", b64_key="document_base64", required=True):
    """An evidence id the caller may use, or the file itself as base64, stored tamper-evident (FR-EVD-001)."""
    from evidence.models import Evidence
    from evidence.services import store

    if d.get(id_key):
        ev = Evidence.objects.filter(pk=d[id_key]).first()
        if ev is None:
            raise Invalid("That file was not found.", code="validation-error")
        return ev
    raw = d.get(b64_key)
    if raw:
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception:  # noqa: BLE001
            raise Invalid(f"{b64_key} is not valid base64.", code="validation-error") from None
        return store(data=data, country=country, uploaded_by=request.user,
                     content_type=d.get("content_type") or "application/pdf",
                     original_name=d.get("file_name") or "document", source="upload", data_class="family_payment")
    if required:
        raise Invalid("Attach the document: evidence_id or document_base64.", code="validation-error")
    return None


def _P(name="id"):
    return OpenApiParameter(name, OpenApiTypes.UUID, OpenApiParameter.PATH)


def _etag(resp, obj):
    resp["ETag"] = f'"{obj.row_version}"'
    return resp


def _if_match(request, obj):
    im = request.headers.get("If-Match")
    if im and im.strip('"') != str(obj.row_version):
        from rest_framework.exceptions import APIException

        exc = APIException("This changed since you loaded it. Reload and try again.")
        exc.status_code = 412
        raise exc


# ----------------------------------------------------------------- institutions

class InstitutionViewSet(viewsets.GenericViewSet):
    serializer_class = FeeInstitutionSerializer
    queryset = Institution.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Institution.objects.none()
        return selectors.institutions_visible(self.request.user).select_related(
            "country", "payee", "verification_case", "look_alike_of").order_by("-created_at")

    def _obj(self, pk) -> Institution:
        inst = self.get_queryset().filter(pk=pk).first()
        if inst is None:
            raise NotFound()
        return inst

    def _out(self, inst, status=200):
        inst.refresh_from_db()
        return _etag(Response(FeeInstitutionSerializer(inst, context={"request": self.request}).data, status=status),
                     inst)

    @extend_schema(responses=FeeInstitutionSerializer(many=True), parameters=[
        OpenApiParameter("status", str), OpenApiParameter("type", str), OpenApiParameter("country", str),
        OpenApiParameter("search", str)])
    def list(self, request):
        qs = self.get_queryset()
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("type"):
            qs = qs.filter(type=p["type"])
        if p.get("country"):
            qs = qs.filter(country__code=p["country"].upper())
        if p.get("search"):
            qs = qs.filter(legal_name__icontains=p["search"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(FeeInstitutionSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(request=FeeInstitutionIn, responses={201: FeeInstitutionSerializer, 200: FeeInstitutionSerializer})
    @idempotent
    def create(self, request):
        """Register an institution; opens its verification case (FR-FEE-001). A duplicate returns the existing
        record with 200."""
        d = _valid(FeeInstitutionIn, request)
        country = _country(d["country"])
        reg_ev = _evidence(request, {"evidence_id": d.get("registration_evidence_id")}, country, required=False)
        client = _person(d.get("client_id")) if has_role(request.user, "CM", "RV", country=country) else None
        inst, created = services.register_institution(
            request.user, country=country, type=d["type"], legal_name=d["legal_name"],
            registration_number=d["registration_number"], address=d["address"], phone=d["phone"], email=d["email"],
            returns_confirmation=d["returns_confirmation"], invoice_channel=d["invoice_channel"],
            proposed_bank_name=d["proposed_bank_name"], proposed_account_number=d["proposed_account_number"],
            proposed_account_name=d["proposed_account_name"], registration_evidence=reg_ev, client=client)
        if d.get("family_member_id"):
            fm = _family_member(d["family_member_id"])
            services.add_beneficiary(client or request.user, inst, fm)
        return self._out(inst, 201 if created else 200)

    @extend_schema(parameters=[_P()], responses=FeeInstitutionSerializer)
    def retrieve(self, request, pk=None):
        return self._out(self._obj(pk))

    @extend_schema(parameters=[_P()], request=FeeInstitutionPatch, responses=FeeInstitutionSerializer)
    def partial_update(self, request, pk=None):
        """Contact details and whether it shares confirmations. Bank details change only through a payee change."""
        inst = self._obj(pk)
        if not has_role(request.user, "CM", "RV", country=inst.country):
            raise NotFound()
        _if_match(request, inst)
        d = _valid(FeeInstitutionPatch, request)
        for f in ("address", "phone", "email", "returns_confirmation", "invoice_channel"):
            if f in d:
                setattr(inst, f, d[f])
        if "registration_number" in d:
            inst.registration_number = d["registration_number"]
            inst.registration_number_norm = services._reg_norm(d["registration_number"])
        if d.get("registration_evidence_id"):
            inst.registration_evidence = _evidence(request, {"evidence_id": d["registration_evidence_id"]},
                                                   inst.country)
            services._link(inst.registration_evidence, "institution", inst.pk, "registration_certificate",
                           request.user)
        inst.save()
        services.audit(request.user, "institution.updated", inst, {"fields": sorted(d)})
        return self._out(inst)

    @extend_schema(parameters=[_P()], request=FeeContactIn, responses={201: FeeContactSerializer})
    @action(detail=True, methods=["get", "post"], permission_classes=[roles("CM", "RV", "AD")])
    def contacts(self, request, pk=None):
        """Name the institution contact (role IC) who confirms invoices (FR-FEE-001, FR-ACC-011)."""
        inst = self._obj(pk)
        if request.method == "GET":
            return Response(FeeContactSerializer(inst.contacts.filter(status="active"), many=True).data)
        d = _valid(FeeContactIn, request)
        ev = _evidence(request, {"evidence_id": d.get("evidence_id")}, inst.country, required=False)
        c = services.add_contact(inst, request.user, full_name=d["full_name"], phone=d["phone"], email=d["email"],
                                 role_title=d["role_title"], person=_person(d.get("person_id")),
                                 may_confirm_invoices=d["may_confirm_invoices"],
                                 may_send_receipts=d["may_send_receipts"], evidence=ev)
        return Response(FeeContactSerializer(c).data, status=201)

    @extend_schema(parameters=[_P(), _P("contact_id")], request=FeeReasonIn, responses=FeeContactSerializer)
    @action(detail=True, methods=["post"], url_path=r"contacts/(?P<contact_id>[^/.]+)/removal",
            permission_classes=[roles("CM", "RV")])
    def remove_contact(self, request, pk=None, contact_id=None):
        inst = self._obj(pk)
        c = InstitutionContact.objects.filter(pk=contact_id, institution=inst).first()
        if c is None:
            raise NotFound()
        c = services.remove_contact(c, request.user, _valid(FeeReasonIn, request)["reason"])
        return Response(FeeContactSerializer(c).data)

    @extend_schema(parameters=[_P()], request=FeePayeeIn, responses={201: FeePayeeOut})
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def payee(self, request, pk=None):
        """Record the institution's account in its own name from the bank's name check or a bank letter
        (FR-FEE-001, FR-ESC-015). Two other staff verify it at /v1/payees/{id}/verification-approvals."""
        inst = self._obj(pk)
        d = _valid(FeePayeeIn, request)
        from accounts.models import NationalIdCheck

        nid = None
        if d.get("national_id_check_id"):
            nid = _get(NationalIdCheck, d["national_id_check_id"])
        p = services.create_payee(
            inst, request.user, bank_name=d["bank_name"], account_number=d["account_number"],
            account_name=d["account_name"], account_name_source=d["account_name_source"],
            account_name_evidence=_evidence(request, {"evidence_id": d.get("account_name_evidence_id")},
                                            inst.country, required=False),
            legal_name_evidence=_evidence(request, {"evidence_id": d.get("legal_name_evidence_id")}, inst.country,
                                          required=False),
            signatory_name=d["signatory_name"], signatory_id_number=d["signatory_id_number"],
            national_id_check=nid, contact_email=d["contact_email"], contact_phone=d["contact_phone"],
            signatory=_person(d.get("signatory_person_id")))
        return Response(_payee_out(p), status=201)

    @extend_schema(parameters=[_P()], request=None, responses=FeePayeeOut)
    @action(detail=True, methods=["post"], url_path="payee-verification", permission_classes=[roles("CM", "RV")])
    @idempotent
    def payee_verification(self, request, pk=None):
        """Prepare the two-person verification of the institution's account (RUL-22, FR-ADM-003)."""
        inst = self._obj(pk)
        p = services.prepare_payee_verification(inst, request.user)
        return Response(_payee_out(p))

    @extend_schema(parameters=[_P()], request=FeeEligibilityIn, responses=FeeInstitutionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def eligibility(self, request, pk=None):
        """Mark an institution not eligible for direct payment (FR-FEE-006): a case manager proposes with the
        reason, a reviewer checks. No cash route is offered."""
        inst = self._obj(pk)
        d = _valid(FeeEligibilityIn, request)
        if d["action"] == "propose":
            services.propose_not_eligible(inst, request.user, d["reason"])
        else:
            services.decide_not_eligible(inst, request.user, confirm=d["action"] == "confirm", note=d["reason"])
        return self._out(inst)

    @extend_schema(parameters=[_P()], request=FeeLookAlikeIn, responses=FeeInstitutionSerializer)
    @action(detail=True, methods=["post"], url_path="look-alike-review", permission_classes=[roles("RV")])
    def look_alike_review(self, request, pk=None):
        inst = self._obj(pk)
        d = _valid(FeeLookAlikeIn, request)
        services.review_look_alike(inst, request.user, decision=d["decision"], note=d["note"])
        return self._out(inst)

    @extend_schema(parameters=[_P()], request=FeeReasonIn, responses=FeeInstitutionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    def reverification(self, request, pk=None):
        """Start a new verification of a not eligible, not verified or suspended institution."""
        inst = self._obj(pk)
        services.reopen(inst, request.user, _valid(FeeReasonIn, request)["reason"])
        return self._out(inst)

    @extend_schema(parameters=[_P()], request=FeeBeneficiaryIn, responses={201: FeeBeneficiarySerializer,
                                                                         200: FeeBeneficiarySerializer(many=True)})
    @action(detail=True, methods=["get", "post"])
    def beneficiaries(self, request, pk=None):
        """The client's family member at this institution, with the Tenmina reference the institution quotes."""
        from .models import Beneficiary

        inst = self._obj(pk)
        if request.method == "GET":
            qs = Beneficiary.objects.filter(institution=inst, status="active")
            if not has_role(request.user, *STAFF, country=inst.country):
                qs = qs.filter(client=request.user)
            return Response(FeeBeneficiarySerializer(qs, many=True).data)
        d = _valid(FeeBeneficiaryIn, request)
        b = services.add_beneficiary(request.user, inst, d["family_member_id"],
                                     institution_account_ref=d["institution_account_ref"])
        return Response(FeeBeneficiarySerializer(b).data, status=201)

    @extend_schema(parameters=[_P()], request=FeeRunnerTaskIn, responses={201: FeeRunnerTaskSerializer})
    @action(detail=True, methods=["post"], url_path="runner-tasks", permission_classes=[roles("CM")])
    @idempotent
    def runner_tasks(self, request, pk=None):
        """Ask a runner to collect an invoice or deliver a receipt in person; no amount, no money (FR-FEE-006)."""
        inst = self._obj(pk)
        d = _valid(FeeRunnerTaskIn, request)
        inv = _get(Invoice, d["invoice_id"]) if d.get("invoice_id") else None
        t = services.create_runner_task(inst, request.user, kind=d["kind"], runner=_person(d["runner_id"]),
                                        due_at=d["due_at"], invoice=inv,
                                        family_member=_family_member(d.get("family_member_id")),
                                        deliver_to_family_member=_family_member(d.get("deliver_to_family_member_id")),
                                        instructions=d["instructions"])
        return Response(FeeRunnerTaskSerializer(t).data, status=201)


def _payee_out(p):
    return {"id": p.pk, "legal_name": p.legal_name, "account_name": p.account_name, "account_last4": p.last4,
            "name_match": p.name_match, "verification_status": p.verification_status,
            "approval_request": p.approval_request_id}


# ----------------------------------------------------------------- invoices

class InvoiceViewSet(viewsets.GenericViewSet):
    serializer_class = FeeInvoiceSerializer
    queryset = Invoice.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Invoice.objects.none()
        return selectors.invoices_visible(self.request.user).select_related(
            "country", "institution", "family_member", "checked_by", "contact_confirmed_by",
            "service_order").order_by("-created_at")

    def _obj(self, pk) -> Invoice:
        inv = self.get_queryset().filter(pk=pk).first()
        if inv is None:
            raise NotFound()
        return inv

    def _out(self, inv, status=200):
        inv = Invoice.objects.select_related("institution", "family_member").get(pk=inv.pk)
        return _etag(Response(FeeInvoiceSerializer(inv, context={"request": self.request}).data, status=status), inv)

    @extend_schema(responses=FeeInvoiceSerializer(many=True), parameters=[
        OpenApiParameter("status", str), OpenApiParameter("family_member", OpenApiTypes.UUID),
        OpenApiParameter("institution", OpenApiTypes.UUID), OpenApiParameter("check_status", str)])
    def list(self, request):
        qs = self.get_queryset()
        p = request.query_params
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("check_status"):
            qs = qs.filter(check_status=p["check_status"])
        if p.get("family_member"):
            qs = qs.filter(family_member_id=p["family_member"])
        if p.get("institution"):
            qs = qs.filter(institution_id=p["institution"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(FeeInvoiceSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(request=FeeInvoiceIn, responses={201: FeeInvoiceSerializer})
    @idempotent
    def create(self, request):
        """Submit a bill or fee note with its reference and document (FR-FEE-002). The client names the family
        member; the institution's contact quotes the Tenmina reference."""
        d = _valid(FeeInvoiceIn, request)
        inst = selectors.institution(d["institution_id"])
        if inst is None:
            raise NotFound()
        fm = _family_member(d.get("family_member_id"))
        if fm is not None and fm.client_id != request.user.pk and not has_role(request.user, "CM", "RV",
                                                                               country=inst.country):
            raise NotFound()
        ev = _evidence(request, d, inst.country)
        inv = services.submit_invoice(
            request.user, institution=inst, institution_reference=d["institution_reference"],
            amount=d["amount"]["amount"], currency=d["amount"]["currency"], family_member=fm,
            tenmina_reference=d["tenmina_reference"], due_on=d.get("due_on"), description=d["description"],
            name_on_invoice=d["name_on_invoice"], institution_name_on_invoice=d["institution_name_on_invoice"],
            account_number_on_invoice=d["account_number_on_invoice"], evidence=ev)
        return self._out(inv, 201)

    @extend_schema(parameters=[_P()], responses=FeeInvoiceSerializer)
    def retrieve(self, request, pk=None):
        return self._out(self._obj(pk))

    @extend_schema(parameters=[_P()], request=FeeInvoiceDocumentIn, responses=FeeInvoiceSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def document(self, request, pk=None):
        """The bill for a draft from a schedule, or a corrected bill (a new version needs a new check)."""
        inv = self._obj(pk)
        d = _valid(FeeInvoiceDocumentIn, request)
        ev = _evidence(request, d, inv.country)
        inv = services.attach_document(inv, request.user, ev, institution_reference=d.get("institution_reference"),
                                       amount=d["amount"]["amount"] if d.get("amount") else None,
                                       due_on=d.get("due_on"), name_on_invoice=d.get("name_on_invoice"),
                                       institution_name_on_invoice=d.get("institution_name_on_invoice"),
                                       account_number_on_invoice=d.get("account_number_on_invoice"))
        return self._out(inv)

    @extend_schema(parameters=[_P()], request=FeeReasonIn, responses=FeeInvoiceSerializer)
    @action(detail=True, methods=["post"], url_path="contact-confirmation")
    @idempotent
    def contact_confirmation(self, request, pk=None):
        """The institution's named contact confirms the bill (IC)."""
        inv = self._obj(pk)
        services.contact_confirm(inv, request.user, _valid(FeeReasonIn, request)["reason"])
        return self._out(inv)

    @extend_schema(parameters=[_P()], request=FeeCheckIn, responses=FeeInvoiceSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def checks(self, request, pk=None):
        """Record the check against the institution and the family member (FR-FEE-002)."""
        inv = self._obj(pk)
        _if_match(request, inv)
        d = _valid(FeeCheckIn, request)
        contact = _get(InstitutionContact, d["contact_id"]) if d.get("contact_id") else None
        services.check_invoice(inv, request.user, outcome=d["outcome"], contact=contact, note=d["note"],
                               resolve_flags=d["resolve_flags"])
        return self._out(inv)

    @extend_schema(parameters=[_P()], request=FeeRouteIn, responses=FeeInvoiceSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    def route(self, request, pk=None):
        """Override the country's payment route for this bill, before the client approves."""
        inv = self._obj(pk)
        d = _valid(FeeRouteIn, request)
        services.set_route(inv, request.user, d["route"], d["reason"])
        return self._out(inv)

    @extend_schema(parameters=[_P()], responses=FeePreviewOut)
    @action(detail=True, methods=["get"], url_path="approval-preview")
    def approval_preview(self, request, pk=None):
        """What the client confirms: the amount, and the payee name as the bank states it (7.9)."""
        inv = self._obj(pk)
        if inv.client_id != request.user.pk and not has_role(request.user, *STAFF, country=inv.country):
            raise NotFound()
        return Response(services.approval_preview(inv))

    @extend_schema(parameters=[_P()], request=FeeClientApprovalIn, responses=FeeApprovalOut,
                   description="x-requires-mfa-step-up: the client approves a payment (FR-FEE-003, RUL-11).")
    @action(detail=True, methods=["post"], url_path="client-approval")
    @idempotent
    def client_approval(self, request, pk=None):
        inv = self._obj(pk)
        if inv.client_id != request.user.pk:
            raise NotFound()
        _if_match(request, inv)
        d = _valid(FeeClientApprovalIn, request)
        mfa_at = None if d["code"] else require_mfa(request)
        out = services.client_approve(inv, request.user, mfa_at=mfa_at, code=d["code"] or None,
                                      confirm_amount={"amount": d["confirm_amount"]["amount"],
                                                      "currency": d["confirm_amount"]["currency"]},
                                      confirm_payee_account_name=d["confirm_payee_account_name"], note=d["note"])
        return Response(out)

    @extend_schema(parameters=[_P()], request=FeeReasonIn, responses=FeeInvoiceSerializer)
    @action(detail=True, methods=["post"], url_path="client-decline")
    def client_decline(self, request, pk=None):
        inv = self._obj(pk)
        services.client_decline(inv, request.user, _valid(FeeReasonIn, request)["reason"])
        return self._out(inv)

    @extend_schema(parameters=[_P()], request=FeeReasonIn, responses=FeeInvoiceSerializer)
    @action(detail=True, methods=["post"])
    def cancellation(self, request, pk=None):
        inv = self._obj(pk)
        services.cancel_invoice(inv, request.user, _valid(FeeReasonIn, request)["reason"])
        return self._out(inv)

    @extend_schema(parameters=[_P()], request=None, responses={201: FeePaymentSerializer})
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def instructions(self, request, pk=None):
        """Prepare the release instruction to the institution from held funds (FR-FEE-003, RUL-22)."""
        inv = self._obj(pk)
        pay = services.prepare_instruction(inv, request.user)
        return Response(FeePaymentSerializer(pay, context={"request": request}).data, status=201)


# ----------------------------------------------------------------- payments and receipts

class PaymentViewSet(viewsets.GenericViewSet):
    serializer_class = FeePaymentSerializer
    queryset = Payment.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Payment.objects.none()
        return selectors.payments_visible(self.request.user).select_related(
            "invoice", "invoice__institution", "release_instruction").order_by("-created_at")

    def _obj(self, pk) -> Payment:
        p = self.get_queryset().filter(pk=pk).first()
        if p is None:
            raise NotFound()
        return p

    def _out(self, p, status=200):
        p = Payment.objects.select_related("invoice", "invoice__institution").get(pk=p.pk)
        return _etag(Response(FeePaymentSerializer(p, context={"request": self.request}).data, status=status), p)

    @extend_schema(responses=FeePaymentSerializer(many=True), parameters=[OpenApiParameter("status", str)])
    def list(self, request):
        qs = self.get_queryset()
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(FeePaymentSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(parameters=[_P()], responses=FeePaymentSerializer)
    def retrieve(self, request, pk=None):
        return self._out(self._obj(pk))

    @extend_schema(parameters=[_P()], request=FeeClientPaymentIn, responses=FeePaymentSerializer)
    @action(detail=True, methods=["post"], url_path="client-payment")
    @idempotent
    def client_payment(self, request, pk=None):
        """client_direct: the client tells us they paid the institution's verified account."""
        p = self._obj(pk)
        d = _valid(FeeClientPaymentIn, request)
        ev = _evidence(request, d, p.country, required=False)
        services.report_client_payment(p, request.user, paid_on=d.get("paid_on"), reference=d["reference"],
                                       evidence=ev)
        return self._out(p)

    @extend_schema(parameters=[_P()], request=FeeConfirmIn, responses=FeePaymentSerializer)
    @action(detail=True, methods=["post"], url_path="institution-confirmation")
    @idempotent
    def institution_confirmation(self, request, pk=None):
        """client_direct: the institution confirms receipt (its contact, or a case manager recording the
        contact's call or receipt)."""
        p = self._obj(pk)
        d = _valid(FeeConfirmIn, request)
        ev = _evidence(request, d, p.country, required=False)
        contact = _get(InstitutionContact, d["contact_id"]) if d.get("contact_id") else None
        amt = d.get("amount")
        services.confirm_received(p, request.user, amount=amt["amount"] if amt else None,
                                  currency=amt["currency"] if amt else None, method=d["method"], contact=contact,
                                  note=d["note"], evidence=ev, received=d["received"])
        return self._out(p)

    @extend_schema(parameters=[_P()], request=FeeReceiptIn, responses=FeePaymentSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def receipts(self, request, pk=None):
        """Attach the institution's receipt and, where it agrees, the confirmation (FR-FEE-004)."""
        p = self._obj(pk)
        d = _valid(FeeReceiptIn, request)
        receipt = _evidence(request, d, p.country)
        conf = _evidence(request, {"evidence_id": d.get("confirmation_evidence_id"),
                                   "document_base64": d.get("confirmation_document_base64"),
                                   "content_type": d.get("content_type"), "file_name": "confirmation"},
                         p.country, required=False)
        services.add_receipt(p, request.user, receipt_evidence=receipt, confirmation_evidence=conf)
        return self._out(p)


# ----------------------------------------------------------------- schedules and plans

class ScheduleViewSet(viewsets.GenericViewSet):
    serializer_class = FeeScheduleSerializer
    queryset = Schedule.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Schedule.objects.none()
        return selectors.schedules_visible(self.request.user).select_related("institution").order_by("-created_at")

    def _obj(self, pk):
        s = self.get_queryset().filter(pk=pk).first()
        if s is None:
            raise NotFound()
        return s

    @extend_schema(responses=FeeScheduleSerializer(many=True))
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(FeeScheduleSerializer(page, many=True).data)

    @extend_schema(request=FeeScheduleIn, responses={201: FeeScheduleSerializer})
    @idempotent
    def create(self, request):
        """A recurring fee schedule per term or month, with reminders and the client's approval each time
        (FR-FEE-005)."""
        d = _valid(FeeScheduleIn, request)
        inst = selectors.institution(d["institution_id"])
        fm = _family_member(d["family_member_id"])
        if inst is None or (fm.client_id != request.user.pk and not has_role(request.user, "CM",
                                                                              country=inst.country)):
            raise NotFound()
        s = services.create_schedule(request.user, institution=inst, family_member=fm, period=d["period"],
                                     expected_amount=d["expected"]["amount"], currency=d["expected"]["currency"],
                                     next_due_on=d["next_due_on"], reminder_lead_days=d["reminder_lead_days"],
                                     label=d["label"])
        return Response(FeeScheduleSerializer(s).data, status=201)

    @extend_schema(parameters=[_P()], responses=FeeScheduleSerializer)
    def retrieve(self, request, pk=None):
        return _etag(Response(FeeScheduleSerializer(self._obj(pk)).data), self._obj(pk))

    @extend_schema(parameters=[_P()], request=FeeSchedulePatch, responses=FeeScheduleSerializer)
    def partial_update(self, request, pk=None):
        s = self._obj(pk)
        _if_match(request, s)
        d = _valid(FeeSchedulePatch, request)
        data = {"expected_amount": d["expected"]["amount"] if d.get("expected") else None,
                "next_due_on": d.get("next_due_on"), "reminder_lead_days": d.get("reminder_lead_days"),
                "label": d.get("label")}
        s = services.update_schedule(s, request.user, data)
        if d.get("status") and d["status"] != s.status:
            s = services.set_schedule_status(s, request.user, d["status"])
        return Response(FeeScheduleSerializer(s).data)


class PlanViewSet(viewsets.GenericViewSet):
    serializer_class = FeeOrderOut

    @extend_schema(request=FeePlanIn, responses={201: FeeOrderOut})
    @idempotent
    def create(self, request):
        """The monthly family payments plan: one Tenmina fee for every payment in that month [TO VERIFY]."""
        d = _valid(FeePlanIn, request)
        o = services.subscribe_plan(request.user, _country(d["country"]), d["period_month"])
        return Response({"id": o.pk, "reference": o.reference, "kind": o.kind, "status": o.status}, status=201)


# ----------------------------------------------------------------- runner tasks

class RunnerTaskViewSet(viewsets.GenericViewSet):
    serializer_class = FeeRunnerTaskSerializer
    queryset = RunnerTask.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RunnerTask.objects.none()
        return selectors.runner_tasks_visible(self.request.user).select_related("institution", "runner") \
            .order_by("-created_at")

    def _obj(self, pk):
        t = self.get_queryset().filter(pk=pk).first()
        if t is None:
            raise NotFound()
        return t

    @extend_schema(responses=FeeRunnerTaskSerializer(many=True), parameters=[OpenApiParameter("status", str)])
    def list(self, request):
        qs = self.get_queryset()
        if request.query_params.get("status"):
            qs = qs.filter(status=request.query_params["status"])
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(FeeRunnerTaskSerializer(page, many=True).data)

    @extend_schema(parameters=[_P()], responses=FeeRunnerTaskSerializer)
    def retrieve(self, request, pk=None):
        return Response(FeeRunnerTaskSerializer(self._obj(pk)).data)

    @extend_schema(parameters=[_P()], request=FeeRunnerCompleteIn, responses=FeeRunnerTaskSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def completion(self, request, pk=None):
        """The runner records the collected bill or the handover, with evidence."""
        t = self._obj(pk)
        d = _valid(FeeRunnerCompleteIn, request)
        ev = _evidence(request, d, t.country)
        data = None
        if d.get("invoice"):
            data = dict(d["invoice"])
        t = services.complete_runner_task(t, request.user, evidence=ev, note=d["note"], invoice_data=data)
        return Response(FeeRunnerTaskSerializer(t).data)

    @extend_schema(parameters=[_P()], request=FeeReasonIn, responses=FeeRunnerTaskSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM")])
    def cancellation(self, request, pk=None):
        t = services.cancel_runner_task(self._obj(pk), request.user, _valid(FeeReasonIn, request)["reason"])
        return Response(FeeRunnerTaskSerializer(t).data)


# ----------------------------------------------------------------- statement per family member (FR-FEE-007)

class FamilyStatementViewSet(viewsets.GenericViewSet):
    serializer_class = FeeStatementOut

    def get_queryset(self):
        from accounts.models import FamilyMember

        if getattr(self, "swagger_fake_view", False):
            return FamilyMember.objects.none()
        return FamilyMember.objects.filter(client=self.request.user)

    def _fm(self, request, pk, staff_read=False):
        """The caller's own family member; staff in the member's country may read (not create) statements."""
        from accounts.models import FamilyMember

        fm = FamilyMember.objects.filter(pk=pk).select_related("country", "client").first()
        if fm is None:
            raise NotFound()
        if fm.client_id == request.user.pk:
            return fm
        if staff_read and has_role(request.user, *STAFF, country=fm.country):
            return fm
        raise NotFound()

    @extend_schema(parameters=[_P()], responses=FeeStatementOut)
    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        """Invoices, payments, receipts and the amount held at the bank for one family member.
        Staff in the family member's country can read it too (back office, SCR-BO-30)."""
        fm = self._fm(request, pk, staff_read=True)
        return Response(services.statement(fm.client, fm))

    @extend_schema(parameters=[_P()], request=None, responses={201: FeeStatementDocSerializer,
                                                               200: FeeStatementDocSerializer(many=True)})
    @action(detail=True, methods=["get", "post"], url_path="statement-pdfs")
    @idempotent
    def statement_pdfs(self, request, pk=None):
        """Download the statement as a PDF with its hash stored (US-FEE-007 AC2)."""
        from .models import Statement

        fm = self._fm(request, pk, staff_read=request.method == "GET")
        if request.method == "GET":
            return Response(FeeStatementDocSerializer(Statement.objects.filter(client=fm.client, family_member=fm)
                                                   .order_by("-created_at"), many=True).data)
        st = services.statement_pdf(request.user, fm)
        return Response(FeeStatementDocSerializer(st).data, status=201)
