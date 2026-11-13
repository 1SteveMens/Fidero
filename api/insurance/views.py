"""INS API (02 7.4 /v1/insurance/*). Clients see their own; an insurer's users (IS) see only their insurer's
applications, policies, premiums and claims; staff their countries. No endpoint decides a claim (RUL-25)."""
import base64

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role, roles

from . import selectors, services
from .models import Application, Claim, Insurer, IntermediaryLicence, Policy, Premium, Product
from .serializers import (InsApplicationIn, InsApplicationSerializer, InsClaimIn, InsClaimSerializer, InsClaimUpdateIn, InsConsentIn,
                          InsInsurerIn, InsInsurerPatch, InsInsurerSerializer, InsLicenceIn, InsLicenceSerializer, InsLineStatusOut,
                          InsOutcomeIn, InsPolicySerializer, InsPremiumConfirmIn, InsPremiumPaidIn, InsPremiumSerializer, InsProductIn,
                          InsProductSerializer, InsRenewalIn)

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
    obj = model.objects.filter(pk=pk).first() if pk else None
    if obj is None:
        raise NotFound()
    return obj


def _evidence(request, d, country, *, required=True):
    from evidence import access
    from evidence.models import Evidence
    from evidence.services import store

    if d.get("evidence_id"):
        ev = Evidence.objects.filter(pk=d["evidence_id"]).first()
        if ev is None or (ev.uploaded_by_id != request.user.pk and not access.can_view(request.user, ev)):
            raise Invalid("That file was not found.", code="validation-error")
        return ev
    if d.get("document_base64"):
        try:
            data = base64.b64decode(d["document_base64"], validate=True)
        except Exception:  # noqa: BLE001
            raise Invalid("document_base64 is not valid base64.", code="validation-error") from None
        return store(data=data, country=country, uploaded_by=request.user,
                     content_type=d.get("content_type") or "application/pdf",
                     original_name=d.get("file_name") or "document", source="upload", data_class="insurance")
    if required:
        raise Invalid("Attach the document: evidence_id or document_base64.", code="validation-error")
    return None


def _P(name="id"):
    return OpenApiParameter(name, OpenApiTypes.UUID, OpenApiParameter.PATH)


class InsurerViewSet(viewsets.GenericViewSet):
    serializer_class = InsInsurerSerializer
    permission_classes = [roles("AD", "CM", "RV")]
    queryset = Insurer.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Insurer.objects.none()
        from accounts.selectors import scope_to_staff_countries

        return scope_to_staff_countries(Insurer.objects.select_related("partner", "payee", "country"),
                                        self.request.user).order_by("-created_at")

    @extend_schema(responses=InsInsurerSerializer(many=True))
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(InsInsurerSerializer(page, many=True).data)

    @extend_schema(request=InsInsurerIn, responses={201: InsInsurerSerializer})
    @idempotent
    def create(self, request):
        from accounts.models import Organisation
        from administration.models import Partner
        from escrow.models import Payee

        d = _valid(InsInsurerIn, request)
        country = _country(d["country"])
        ins = services.create_insurer(
            request.user, country=country, partner=_get(Partner, d["partner_id"]),
            organisation=_get(Organisation, d["organisation_id"]) if d.get("organisation_id") else None,
            licence_body=d["licence_body"], licence_number=d["licence_number"],
            licence_valid_until=d.get("licence_valid_until"),
            licence_evidence=_evidence(request, {"evidence_id": d.get("licence_evidence_id")}, country,
                                       required=False),
            claim_contact=d["claim_contact"], routes=d.get("routes"),
            payee=_get(Payee, d["payee_id"]) if d.get("payee_id") else None)
        return Response(InsInsurerSerializer(ins).data, status=201)

    @extend_schema(parameters=[_P()], responses=InsInsurerSerializer)
    def retrieve(self, request, pk=None):
        return Response(InsInsurerSerializer(self._obj(pk)).data)

    def _obj(self, pk):
        ins = self.get_queryset().filter(pk=pk).first()
        if ins is None:
            raise NotFound()
        return ins

    @extend_schema(parameters=[_P()], request=InsInsurerPatch, responses=InsInsurerSerializer)
    def partial_update(self, request, pk=None):
        from escrow.models import Payee

        ins = self._obj(pk)
        d = _valid(InsInsurerPatch, request)
        if d.get("licence_evidence_id"):
            d["licence_evidence"] = _evidence(request, {"evidence_id": d.pop("licence_evidence_id")}, ins.country)
        payee_id = d.pop("payee_id", None)
        ins = services.update_insurer(ins, request.user, d)
        if payee_id:
            ins = services.set_insurer_payee(ins, request.user, _get(Payee, payee_id))
        return Response(InsInsurerSerializer(ins).data)


class LicenceViewSet(viewsets.GenericViewSet):
    serializer_class = InsLicenceSerializer
    permission_classes = [roles("AD")]
    queryset = IntermediaryLicence.objects.none()

    @extend_schema(responses=InsLicenceSerializer(many=True))
    def list(self, request):
        from accounts.selectors import scope_to_staff_countries

        qs = scope_to_staff_countries(IntermediaryLicence.objects.all(), request.user).order_by("-created_at")
        page = self.paginate_queryset(qs)
        return self.get_paginated_response(InsLicenceSerializer(page, many=True).data)

    @extend_schema(request=InsLicenceIn, responses={201: InsLicenceSerializer})
    @idempotent
    def create(self, request):
        d = _valid(InsLicenceIn, request)
        country = _country(d["country"])
        lic = services.record_intermediary_licence(request.user, country=country, body=d["body"],
                                                   reference=d["reference"], valid_until=d["valid_until"],
                                                   evidence=_evidence(request, d, country))
        return Response(InsLicenceSerializer(lic).data, status=201)


class ProductViewSet(viewsets.GenericViewSet):
    serializer_class = InsProductSerializer
    queryset = Product.objects.none()

    @extend_schema(responses=InsProductSerializer(many=True), parameters=[OpenApiParameter("country", str)])
    def list(self, request):
        """Cover products with the insurer's name, terms and the statement that the policy is the insurer's
        (FR-INS-001). Empty where the line is not open (US-INS-001 AC2)."""
        code = request.query_params.get("country") or getattr(request.user.home_country, "code", "GH")
        country = _country(code)
        if has_role(request.user, *STAFF, country=country):
            qs = Product.objects.filter(country=country).select_related("insurer", "insurer__partner")
        else:
            qs = services.products_for(country)
        page = self.paginate_queryset(qs.order_by("-created_at"))
        return self.get_paginated_response(InsProductSerializer(page, many=True).data)

    @extend_schema(responses=InsLineStatusOut, parameters=[OpenApiParameter("country", str)])
    @action(detail=False, methods=["get"], url_path="line-status")
    def line_status(self, request):
        ok, reasons = services.line_open(_country(request.query_params.get("country") or "GH"))
        return Response({"open": ok, "reasons": reasons})

    @extend_schema(request=InsProductIn, responses={201: InsProductSerializer})
    @idempotent
    def create(self, request):
        d = _valid(InsProductIn, request)
        ins = _get(Insurer, d["insurer_id"])
        if not has_role(request.user, "CM", "AD", country=ins.country):
            raise NotFound()
        p = services.create_product(request.user, insurer=ins, kind=d["kind"], name=d["name"],
                                    terms_evidence=_evidence(request, d, ins.country),
                                    premium_amount=d["premium"]["amount"], premium_currency=d["premium"]["currency"],
                                    premium_period=d["premium_period"], summary=d["summary"],
                                    application_questions=d["application_questions"])
        return Response(InsProductSerializer(p).data, status=201)

    @extend_schema(parameters=[_P()], responses=InsProductSerializer)
    def retrieve(self, request, pk=None):
        p = _get(Product, pk)
        if p.status != "published" and not has_role(request.user, *STAFF, country=p.country):
            raise NotFound()
        return Response(InsProductSerializer(p).data)

    @extend_schema(parameters=[_P()], request=None, responses=InsProductSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("AD")])
    def publication(self, request, pk=None):
        return Response(InsProductSerializer(services.publish_product(_get(Product, pk), request.user)).data)

    @extend_schema(parameters=[_P()], request=None, responses=InsProductSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("AD")])
    def withdrawal(self, request, pk=None):
        return Response(InsProductSerializer(services.withdraw_product(_get(Product, pk), request.user)).data)


class ApplicationViewSet(viewsets.GenericViewSet):
    serializer_class = InsApplicationSerializer
    queryset = Application.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Application.objects.none()
        return selectors.applications_visible(self.request.user).select_related("product", "insurer__partner") \
            .order_by("-created_at")

    def _obj(self, pk):
        a = self.get_queryset().filter(pk=pk).first()
        if a is None:
            raise NotFound()
        return a

    @extend_schema(responses=InsApplicationSerializer(many=True))
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(InsApplicationSerializer(page, many=True).data)

    @extend_schema(request=InsApplicationIn, responses={201: InsApplicationSerializer})
    @idempotent
    def create(self, request):
        """Apply; with submit and consent it is passed to the insurer at once. The premium route is shown as the
        insurer's account (FR-INS-002)."""
        d = _valid(InsApplicationIn, request)
        app = services.apply(request.user, product=_get(Product, d["product_id"]),
                             family_member=d["family_member_id"], answers=d["answers"],
                             premium_route=d["premium_route"])
        if d["submit"]:
            app = services.submit_application(app, request.user, consent=d["consent"])
        return Response(InsApplicationSerializer(app).data, status=201)

    @extend_schema(parameters=[_P()], responses=InsApplicationSerializer)
    def retrieve(self, request, pk=None):
        return Response(InsApplicationSerializer(self._obj(pk)).data)

    @extend_schema(parameters=[_P()], request=InsConsentIn, responses=InsApplicationSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def submission(self, request, pk=None):
        app = services.submit_application(self._obj(pk), request.user, consent=_valid(InsConsentIn, request)["consent"])
        return Response(InsApplicationSerializer(app).data)

    @extend_schema(parameters=[_P()], request=None, responses=InsApplicationSerializer)
    @action(detail=True, methods=["post"])
    def withdrawal(self, request, pk=None):
        app = services.withdraw_application(self._obj(pk), request.user)
        return Response(InsApplicationSerializer(app).data)

    @extend_schema(parameters=[_P()], request=InsOutcomeIn, responses=InsApplicationSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def outcomes(self, request, pk=None):
        """The insurer returns acceptance with the policy document, or declines (IS, or CM from the insurer's
        document)."""
        app = self._obj(pk)
        d = _valid(InsOutcomeIn, request)
        doc = _evidence(request, d, app.country, required=d["outcome"] == "accepted")
        services.record_outcome(app, request.user, outcome=d["outcome"], policy_number=d["policy_number"],
                                document_evidence=doc, starts_on=d.get("starts_on"), renews_on=d.get("renews_on"),
                                claim_contact=d["claim_contact"], note=d["note"])
        app.refresh_from_db()
        return Response(InsApplicationSerializer(app).data)


class PolicyViewSet(viewsets.GenericViewSet):
    serializer_class = InsPolicySerializer
    queryset = Policy.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Policy.objects.none()
        return selectors.policies_visible(self.request.user).select_related("insurer__partner", "product") \
            .order_by("-created_at")

    def _obj(self, pk):
        p = self.get_queryset().filter(pk=pk).first()
        if p is None:
            raise NotFound()
        return p

    @extend_schema(responses=InsPolicySerializer(many=True))
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(InsPolicySerializer(page, many=True).data)

    @extend_schema(parameters=[_P()], responses=InsPolicySerializer)
    def retrieve(self, request, pk=None):
        return Response(InsPolicySerializer(self._obj(pk)).data)

    @extend_schema(parameters=[_P()], request=InsClaimIn, responses={201: InsClaimSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def claims(self, request, pk=None):
        """The client starts a claim; it is passed to the insurer (FR-INS-004)."""
        from evidence import access
        from evidence.models import Evidence

        pol = self._obj(pk)
        d = _valid(InsClaimIn, request)
        docs = []
        for i in d["document_ids"]:
            ev = Evidence.objects.filter(pk=i).first()
            if ev is None or not access.can_view(request.user, ev):
                raise Invalid("That file was not found.", code="validation-error")
            docs.append(ev)
        c = services.start_claim(pol, request.user, description=d["description"], event_date=d.get("event_date"),
                                 documents=docs)
        return Response(InsClaimSerializer(c).data, status=201)

    @extend_schema(parameters=[_P()], request=InsRenewalIn, responses=InsPolicySerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def renewals(self, request, pk=None):
        """The insurer records a renewal (IS)."""
        pol = self._obj(pk)
        d = _valid(InsRenewalIn, request)
        services.record_renewal(pol, request.user, renews_on=d["renews_on"],
                                document_evidence=_evidence(request, d, pol.country, required=False), note=d["note"])
        pol.refresh_from_db()
        return Response(InsPolicySerializer(pol).data)


class PremiumViewSet(viewsets.GenericViewSet):
    serializer_class = InsPremiumSerializer
    queryset = Premium.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Premium.objects.none()
        return selectors.premiums_visible(self.request.user).select_related("policy", "policy__insurer__partner") \
            .order_by("-created_at")

    def _obj(self, pk):
        p = self.get_queryset().filter(pk=pk).first()
        if p is None:
            raise NotFound()
        return p

    def _out(self, pm):
        pm = Premium.objects.select_related("policy").get(pk=pm.pk)
        return Response(InsPremiumSerializer(pm, context={"request": self.request}).data)

    @extend_schema(responses=InsPremiumSerializer(many=True))
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(InsPremiumSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(parameters=[_P()], responses=InsPremiumSerializer)
    def retrieve(self, request, pk=None):
        return self._out(self._obj(pk))

    @extend_schema(parameters=[_P()], request=None, responses=InsPremiumSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def instructions(self, request, pk=None):
        """Instruction from held funds to the insurer's payee, where that route is used (FR-INS-002, RUL-25)."""
        pm = services.instruct_premium(self._obj(pk), request.user)
        return self._out(pm)

    @extend_schema(parameters=[_P()], request=InsPremiumPaidIn, responses=InsPremiumSerializer)
    @action(detail=True, methods=["post"], url_path="client-payment")
    @idempotent
    def client_payment(self, request, pk=None):
        pm = self._obj(pk)
        d = _valid(InsPremiumPaidIn, request)
        services.report_premium_paid(pm, request.user, reference=d["reference"],
                                     evidence=_evidence(request, d, pm.country, required=False))
        return self._out(pm)

    @extend_schema(parameters=[_P()], request=InsPremiumConfirmIn, responses=InsPremiumSerializer)
    @action(detail=True, methods=["post"], url_path="insurer-confirmation")
    @idempotent
    def insurer_confirmation(self, request, pk=None):
        pm = self._obj(pk)
        d = _valid(InsPremiumConfirmIn, request)
        services.confirm_premium(pm, request.user, received=d["received"], note=d["note"],
                                 receipt_evidence=_evidence(request, d, pm.country, required=False))
        return self._out(pm)


class ClaimViewSet(viewsets.GenericViewSet):
    serializer_class = InsClaimSerializer
    queryset = Claim.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Claim.objects.none()
        return selectors.claims_visible(self.request.user).select_related("policy").order_by("-created_at")

    def _obj(self, pk):
        c = self.get_queryset().filter(pk=pk).first()
        if c is None:
            raise NotFound()
        return c

    @extend_schema(responses=InsClaimSerializer(many=True))
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(InsClaimSerializer(page, many=True).data)

    @extend_schema(parameters=[_P()], responses=InsClaimSerializer)
    def retrieve(self, request, pk=None):
        return Response(InsClaimSerializer(self._obj(pk)).data)

    @extend_schema(parameters=[_P()], request=InsClaimUpdateIn, responses=InsClaimSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def updates(self, request, pk=None):
        """The insurer's response (IS). No Tenmina user can enter a decision (RUL-25)."""
        c = self._obj(pk)
        d = _valid(InsClaimUpdateIn, request)
        c = services.record_claim_update(c, request.user, insurer_status=d["insurer_status"], note=d["note"],
                                         evidence=_evidence(request, d, c.country, required=False))
        return Response(InsClaimSerializer(c).data)
