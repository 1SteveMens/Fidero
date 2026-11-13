"""ORD API (02 section 7.4): catalogue, orders, terms, documents, referrals, extra inspections."""
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from accounts.models import Person
from administration import flags
from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import roles
from core.views import ETagMixin

from . import catalogue, legal, pricing, selectors, services
from .models import Order, ReferralCode, ReferralReward
from .serializers import (OrderDocumentSerializer, OrderDocumentUploadInput, ExtraInspectionInput, LeadSourceSummarySerializer,
                          OrderCreateSerializer, OrderSerializer, OrderWriteSerializer, CatalogueProductSerializer,
                          TierQuoteSerializer, OrderReasonInput, ReferralCodeCreateSerializer, ReferralCodeSerializer,
                          ReferralInput, ReferralRewardSerializer, ReferralRewardPaidInput, OrderSubmitInput,
                          TermsAcceptanceInput, TermsAcceptanceSerializer, OrderTermsSerializer)

UUID_RE = "[0-9a-fA-F-]{36}"


def _client_meta(request):
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR")
    return {"ip": ip or None, "user_agent": request.headers.get("User-Agent", "")}


def _raw_tamper(request):
    return {k: request.data[k] for k in services.TAMPER_KEYS if hasattr(request.data, "keys") and k in request.data}


def _country_param(request):
    code = request.query_params.get("country")
    if not code and request.user.is_authenticated and request.user.home_country_id:
        code = request.user.home_country.code
    if not code:
        raise Invalid("Give ?country=, for example GH.")
    return services._country(code)


COUNTRY_PARAM = OpenApiParameter("country", str, description="ISO country code, e.g. GH")


# ---------------------------------------------------------------- catalogue (public)


@extend_schema(parameters=[COUNTRY_PARAM], responses=CatalogueProductSerializer(many=True), tags=["catalogue"])
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def products(request):
    """Every product Tenmina sells in a country, and whether it is open there."""
    c = _country_param(request)
    out = []
    for p in catalogue.PRODUCTS.values():
        price = local = None
        if not p.tiered:
            try:
                q = pricing.quote(c, p.kind)
                price, local = q.price.as_dict(), q.local_price.as_dict() if q.local_price else None
            except Invalid:
                pass
        out.append({"kind": p.kind, "name": p.name, "description": p.description, "line": p.line,
                    "tiered": p.tiered, "asset_types": list(p.asset_types), "bill_to": p.bill_to,
                    "roles": list(p.roles), "available": flags.enabled(p.flag, c) if p.flag else True,
                    "price": price, "local_price": local})
    return Response(CatalogueProductSerializer(out, many=True).data)


@extend_schema(parameters=[
    COUNTRY_PARAM, OpenApiParameter("kind", str, description="Order kind, default verification"),
    OpenApiParameter("asset_type", str, description="plot or building"),
    OpenApiParameter("residence", str, description="Where the client lives, for the guide currency")],
    responses=TierQuoteSerializer(many=True), tags=["catalogue"])
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def tiers(request):
    """FR-ORD-002: tiers and prices. Card is charged in the price currency, mobile money in the local currency;
    GBP, EUR and CAD are guides only."""
    c = _country_param(request)
    kind = request.query_params.get("kind", "verification")
    residence = request.query_params.get("residence") or (
        request.user.residence_country if request.user.is_authenticated else "")
    quotes = pricing.tiers(c, kind, asset_type=request.query_params.get("asset_type", "plot"), residence=residence)
    return Response(TierQuoteSerializer([q.as_dict() for q in quotes], many=True).data)


@extend_schema(parameters=[COUNTRY_PARAM], responses=OrderTermsSerializer, tags=["catalogue"])
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def terms(request):
    """FR-ORD-003: the scope statement and client terms in force, with their versions."""
    return Response(OrderTermsSerializer(legal.current(_country_param(request))).data)


@extend_schema(parameters=[COUNTRY_PARAM], responses={200: OpenApiTypes.OBJECT}, tags=["catalogue"])
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def lead_source_options(request):
    """FR-ORD-005: the lead sources a client chooses from."""
    return Response({"lead_sources": services.lead_sources(_country_param(request))})


@extend_schema(parameters=[COUNTRY_PARAM], responses=LeadSourceSummarySerializer(many=True), tags=["orders"])
@api_view(["GET"])
@permission_classes([roles("CM", "AD", "AN")])
def lead_source_summary(request):
    """FR-ORD-005, BR-16: which channels bring paying clients."""
    c = services._country(request.query_params["country"]) if request.query_params.get("country") else None
    return Response(LeadSourceSummarySerializer(selectors.lead_source_summary(country=c), many=True).data)


# ---------------------------------------------------------------- orders


class OrderViewSet(ETagMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = OrderSerializer
    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return selectors.visible_orders(self.request.user)

    def _respond(self, order, status=200):
        order.refresh_from_db()
        return Response(OrderSerializer(order).data, status=status)

    @extend_schema(request=OrderCreateSerializer, responses={201: OrderSerializer})
    @idempotent
    def create(self, request):
        """FR-ORD-001 to 003, 005, 006: create an order. With draft=true, save what is there so far."""
        s = OrderCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = {**s.flat(), **_raw_tamper(request)}
        on_behalf = None
        if data.get("on_behalf_of"):
            on_behalf = Person.objects.filter(pk=data["on_behalf_of"]).first()
            if on_behalf is None:
                raise NotFound("We could not find that client.")
        order = services.create_order(actor=request.user, country=data.pop("country"), kind=data.pop("kind"),
                                      data=data, draft=data.pop("draft", False), on_behalf_of=on_behalf,
                                      **_client_meta(request))
        return self._respond(order, 201)

    @extend_schema(request=OrderWriteSerializer, responses=OrderSerializer)
    def partial_update(self, request, pk=None):
        """Change a draft (US-ORD-001 AC3)."""
        order = self.get_object()
        s = OrderWriteSerializer(data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        order = services.update_draft(order, request.user, {**s.flat(), **_raw_tamper(request)})
        return self._respond(order)

    @extend_schema(request=OrderSubmitInput, responses=OrderSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def submit(self, request, pk=None):
        """Draft to awaiting payment. Every required field, a fixed price and the terms accepted."""
        order = self.get_object()
        s = OrderSubmitInput(data=request.data)
        s.is_valid(raise_exception=True)
        if s.validated_data.get("accept_terms"):
            services.accept_terms(order, request.user, s.validated_data.get("terms_version", ""),
                                  s.validated_data.get("scope_version", ""), **_client_meta(request))
        return self._respond(services.submit(order, request.user))

    @extend_schema(request=TermsAcceptanceInput, responses=OrderSerializer)
    @action(detail=True, methods=["post"], url_path="terms-acceptance")
    @idempotent
    def terms_acceptance(self, request, pk=None):
        """FR-ORD-003: accept the scope statement and terms in force; time and versions are stored."""
        order = self.get_object()
        s = TermsAcceptanceInput(data=request.data)
        s.is_valid(raise_exception=True)
        services.accept_terms(order, request.user, s.validated_data["terms_version"],
                              s.validated_data["scope_version"], **_client_meta(request))
        return self._respond(order)

    @extend_schema(responses=TermsAcceptanceSerializer(many=True))
    @action(detail=True, methods=["get"])
    def acceptances(self, request, pk=None):
        order = self.get_object()
        return Response(TermsAcceptanceSerializer(order.acceptances.order_by("accepted_at"), many=True).data)

    @extend_schema(request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post"])
    def edit(self, request, pk=None):
        """Reopen an unpaid order as a draft to change it."""
        return self._respond(services.reopen(self.get_object(), request.user))

    @extend_schema(request=OrderReasonInput, responses=OrderSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def cancel(self, request, pk=None):
        s = OrderReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._respond(services.cancel(self.get_object(), request.user, s.validated_data["reason"]))

    @extend_schema(methods=["POST"], request=ReferralInput, responses=OrderSerializer)
    @extend_schema(methods=["DELETE"], request=None, responses=OrderSerializer)
    @action(detail=True, methods=["post", "delete"])
    def referral(self, request, pk=None):
        """FR-ORD-006: apply or remove a referral code on a draft."""
        order = self.get_object()
        if request.method == "DELETE":
            return self._respond(services.remove_referral(order, request.user))
        s = ReferralInput(data=request.data)
        s.is_valid(raise_exception=True)
        return self._respond(services.apply_referral(order, request.user, s.validated_data["code"]))

    @extend_schema(methods=["GET"], request=None, responses=OrderDocumentSerializer(many=True))
    @extend_schema(methods=["POST"], request={"multipart/form-data": OrderDocumentUploadInput},
                   responses={201: OrderDocumentSerializer})
    @action(detail=True, methods=["get", "post"], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def documents(self, request, pk=None):
        """FR-ORD-001: the site plan and other documents of the order."""
        order = self.get_object()
        if request.method == "GET":
            return Response(OrderDocumentSerializer(services.order_documents(order).order_by("created_at"),
                                               many=True).data)
        s = OrderDocumentUploadInput(data=request.data)
        s.is_valid(raise_exception=True)
        f = s.validated_data["file"]
        ev = services.add_document(order, request.user, data=f.read(),
                                   content_type=getattr(f, "content_type", "") or "application/octet-stream",
                                   name=f.name, role=s.validated_data["role"])
        return Response(OrderDocumentSerializer(ev).data, status=201)


@extend_schema(request=ExtraInspectionInput, responses={201: OrderSerializer}, tags=["orders"])
@api_view(["POST"])
@permission_classes([roles("CL")])
def extra_inspection(request, project_id):
    """FR-ORD-007: order an extra inspection on an active build at the configured price."""
    s = ExtraInspectionInput(data=request.data)
    s.is_valid(raise_exception=True)
    order = services.order_extra_inspection(actor=request.user, project_id=project_id, data=dict(s.validated_data),
                                            **_client_meta(request))
    return Response(OrderSerializer(order).data, status=201)


# ---------------------------------------------------------------- referrals


@extend_schema(parameters=[COUNTRY_PARAM], responses=ReferralCodeSerializer, tags=["referrals"])
@api_view(["GET"])
def my_referral_code(request):
    """FR-ORD-006: your own code to share. Created the first time you ask."""
    return Response(ReferralCodeSerializer(services.my_referral_code(request.user, _country_param(request))).data)


class ReferralCodeViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReferralCodeSerializer
    lookup_value_regex = UUID_RE

    def get_queryset(self):
        return selectors.visible_codes(self.request.user).order_by("-created_at")

    @extend_schema(request=ReferralCodeCreateSerializer, responses={201: ReferralCodeSerializer})
    def create(self, request):
        """Staff create a code for an association, webinar or remittance partner."""
        s = ReferralCodeCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        owner = Person.objects.filter(pk=d.pop("owner")).first() if d.get("owner") else None
        d.pop("owner", None)
        code = services.create_referral_code(request.user, owner=owner, **d)
        return Response(ReferralCodeSerializer(code).data, status=201)

    @extend_schema(request=None, responses=ReferralCodeSerializer)
    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        return Response(ReferralCodeSerializer(services.deactivate_referral_code(request.user,
                                                                                 self.get_object())).data)


class ReferralRewardViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReferralRewardSerializer
    lookup_value_regex = UUID_RE
    filterset_fields = ["status"]

    def get_queryset(self):
        return selectors.visible_rewards(self.request.user).order_by("-created_at")

    @extend_schema(request=ReferralRewardPaidInput, responses=ReferralRewardSerializer)
    @action(detail=True, methods=["post"])
    def paid(self, request, pk=None):
        s = ReferralRewardPaidInput(data=request.data)
        s.is_valid(raise_exception=True)
        r = services.mark_reward_paid(request.user, self.get_object(), s.validated_data["reference"])
        return Response(ReferralRewardSerializer(r).data)

    @extend_schema(request=OrderReasonInput, responses=ReferralRewardSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        s = OrderReasonInput(data=request.data)
        s.is_valid(raise_exception=True)
        r = services.void_reward(request.user, self.get_object(), s.validated_data["reason"])
        return Response(ReferralRewardSerializer(r).data)


def get_order_for(user, order_id) -> Order:
    """For PAY's views: an order the user may see, or 404."""
    return get_object_or_404(selectors.visible_orders(user), pk=order_id)


__all__ = ["OrderViewSet", "ReferralCodeViewSet", "ReferralRewardViewSet", "ReferralCode", "ReferralReward"]
