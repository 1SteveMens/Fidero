"""PTR API (02 7.4, 7.8). Partner endpoints are mounted at /v1/partner/... (02 names /partner/v1; every module
mounts under /v1/). They accept only partner bearer tokens from the client credentials grant; every call is
metered and rate limited. Clients consent through /v1/consents (DPR) and confirm partner orders here; an
administrator manages API clients."""
from datetime import date

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role

from . import services
from .auth import PartnerPrincipal, PartnerTokenAuthentication
from .models import ApiClient, PartnerOrder, WebhookSubscription
from .serializers import (PtrClientCreated, PtrClientIn, PtrClientSerializer, PtrClientUpdate, PtrDeliverySerializer,
                          PtrDirectoryItem, PtrMonthIn, PtrOrderIn, PtrOrderSerializer, PtrReportOut,
                          PtrStatementSerializer, PtrStatusIn, PtrStatusOut, PtrStatusQueryIn, PtrTokenIn,
                          PtrTokenOut, PtrUsageOut, PtrWebhookCreated, PtrWebhookIn, PtrWebhookSerializer)


def _valid(cls, request):
    s = cls(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


def _month(value) -> date:
    try:
        return date.fromisoformat(f"{value}-01") if value else date.today().replace(day=1)
    except ValueError as exc:
        raise Invalid("Give the month as YYYY-MM.", code="validation-error") from exc


# =========================================================================== partner side

class PartnerView(APIView):
    authentication_classes = [PartnerTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    scope = ""

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not isinstance(request.user, PartnerPrincipal):
            from rest_framework.exceptions import NotAuthenticated

            raise NotAuthenticated("Use a partner access token from /v1/partner/oauth/token.")
        self.client = request.user.client
        services.require_on(self.client)
        services.require_scope(request.auth, self.scope)
        services.check_rate(self.client, request.path, request.method)

    def handle_exception(self, exc):
        resp = super().handle_exception(exc)
        retry = getattr(exc, "extra", {}).get("retry_after") if hasattr(exc, "extra") else None
        if retry:
            resp["Retry-After"] = str(retry)
        return resp


class TokenView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=["partner"], request=PtrTokenIn, responses=PtrTokenOut, auth=[])
    def post(self, request):
        """OAuth 2.0 client credentials: a 15-minute bearer token with the client's scopes."""
        d = _valid(PtrTokenIn, request)
        return Response(services.issue_token(d["client_id"], d["client_secret"], d.get("scope")))


class PlotStatusView(PartnerView):
    scope = "plot_status.read"

    @extend_schema(tags=["partner"], request=PtrStatusQueryIn, responses=PtrStatusOut)
    def post(self, request):
        """Status of the latest verification for a plot (J-06, FR-PTR-001, FR-PTR-002)."""
        d = _valid(PtrStatusQueryIn, request)
        return Response(services.plot_status(self.client, plot_reference=d.get("plot_reference"),
                                             point=d.get("point"), endpoint=request.path))


class ReportView(PartnerView):
    scope = "report.read"

    @extend_schema(tags=["partner"], responses=PtrReportOut)
    def get(self, request, report_id):
        """The full report, only with the client's specific consent (RUL-16)."""
        return Response(services.full_report(self.client, report_id, endpoint=request.path))


class OrdersView(PartnerView):
    scope = "orders.write"

    @extend_schema(tags=["partner"], responses=PtrOrderSerializer(many=True))
    def get(self, request):
        services.meter(self.client, request.path, "GET", "ok", 200, billable=False)
        return Response(PtrOrderSerializer(self.client.orders.all()[:100], many=True).data)

    @extend_schema(tags=["partner"], request=PtrOrderIn, responses={201: PtrOrderSerializer})
    @idempotent
    def post(self, request):
        """Order a verification for a consenting client (FR-PTR-003); the client confirms in Tenmina."""
        d = _valid(PtrOrderIn, request)
        o = services.create_order(self.client, **d)
        return Response(PtrOrderSerializer(o).data, status=201)


class OrderView(PartnerView):
    scope = "orders.write"

    @extend_schema(tags=["partner"], responses=PtrOrderSerializer)
    def get(self, request, order_id):
        o = self.client.orders.filter(pk=order_id).first()
        if o is None:
            raise NotFound()
        services.meter(self.client, request.path, "GET", "ok", 200, billable=False)
        return Response(PtrOrderSerializer(o).data)


class UsageView(PartnerView):
    scope = "usage.read"

    @extend_schema(tags=["partner"], parameters=[OpenApiParameter("month", str)], responses=PtrUsageOut)
    def get(self, request):
        """Metered usage for a month (FR-PTR-004)."""
        out = services.usage(self.client, _month(request.query_params.get("month")))
        services.meter(self.client, request.path, "GET", "ok", 200, billable=False)
        return Response(out)


class WebhooksView(PartnerView):
    scope = "webhooks.manage"

    @extend_schema(tags=["partner"], responses=PtrWebhookSerializer(many=True))
    def get(self, request):
        services.meter(self.client, request.path, "GET", "ok", 200, billable=False)
        return Response(PtrWebhookSerializer(self.client.webhooks.exclude(status="deleted"), many=True).data)

    @extend_schema(tags=["partner"], request=PtrWebhookIn, responses={201: PtrWebhookCreated})
    def post(self, request):
        """Subscribe; the signing secret is shown once."""
        d = _valid(PtrWebhookIn, request)
        sub, secret = services.subscribe_webhook(self.client, url=d["url"], events=d["events"])
        services.meter(self.client, request.path, "POST", "ok", 201, billable=False)
        data = PtrWebhookSerializer(sub).data
        data["secret"] = secret
        return Response(data, status=201)


class WebhookView(PartnerView):
    scope = "webhooks.manage"

    @extend_schema(tags=["partner"], responses={204: None})
    def delete(self, request, webhook_id):
        sub = WebhookSubscription.objects.filter(pk=webhook_id, client=self.client).first()
        if sub is None:
            raise NotFound()
        services.delete_webhook(self.client, sub)
        services.meter(self.client, request.path, "DELETE", "ok", 204, billable=False)
        return Response(status=204)


# =========================================================================== the client's portal (CL)

@extend_schema(tags=["partner"], responses=PtrDirectoryItem(many=True))
@api_view(["GET"])
def directory(request):
    """Partners a client can consent to share with (FR-PTR-002, through /v1/consents)."""
    from accounts.models import Person

    country = getattr(request.user, "home_country", None) if isinstance(request.user, Person) else None
    qs = ApiClient.objects.filter(status="active").select_related("partner")
    if country is not None:
        qs = qs.filter(country=country)
    return Response([{"id": c.pk, "name": c.name, "partner_name": c.partner.name} for c in qs])


class ClientPartnerOrderViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = PtrOrderSerializer
    queryset = PartnerOrder.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False) or not self.request.user.is_authenticated:
            return PartnerOrder.objects.none()
        return PartnerOrder.objects.filter(person=self.request.user).select_related("client", "country")

    @extend_schema(request=None, responses=PtrOrderSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def confirm(self, request, pk=None):
        return Response(PtrOrderSerializer(services.confirm_order(self.get_object(), request.user)).data)

    @extend_schema(request=None, responses=PtrOrderSerializer)
    @action(detail=True, methods=["post"])
    def decline(self, request, pk=None):
        return Response(PtrOrderSerializer(services.decline_order(self.get_object(), request.user)).data)


# =========================================================================== administration (AD)

class ApiClientViewSet(viewsets.GenericViewSet):
    serializer_class = PtrClientSerializer
    queryset = ApiClient.objects.none()

    def get_queryset(self):
        from accounts.selectors import scope_to_staff_countries

        if not has_role(self.request.user, "AD"):
            return ApiClient.objects.none()
        return scope_to_staff_countries(ApiClient.objects.select_related("country", "partner"), self.request.user,
                                        roles=("AD",))

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(PtrClientSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(PtrClientSerializer(self.get_object()).data)

    @extend_schema(request=PtrClientIn, responses={201: PtrClientCreated})
    def create(self, request):
        from accounts.models import Person
        from administration.models import Partner
        from countries.models import Country

        d = _valid(PtrClientIn, request)
        country = Country.objects.filter(code=d["country"].upper()).first()
        partner = Partner.objects.filter(pk=d["partner_id"]).first()
        if country is None or partner is None:
            raise Invalid("Unknown country or partner.", code="validation-error")
        contact = Person.objects.filter(pk=d.get("contact_person_id")).first() if d.get("contact_person_id") else None
        c, raw = services.create_client(request.user, country=country, partner=partner, name=d["name"],
                                        scopes=d["scopes"], rate_limit_per_minute=d["rate_limit_per_minute"],
                                        monthly_quota=d.get("monthly_quota"), contact_person=contact)
        data = PtrClientSerializer(c).data
        data["client_secret"] = raw
        return Response(data, status=201)

    @extend_schema(request=PtrClientUpdate, responses=PtrClientSerializer)
    def partial_update(self, request, pk=None):
        d = _valid(PtrClientUpdate, request)
        kw = {k: d[k] for k in ("scopes", "rate_limit_per_minute", "name") if k in d}
        if "monthly_quota" in d:
            kw["monthly_quota"] = d["monthly_quota"]
        return Response(PtrClientSerializer(services.update_client(self.get_object(), request.user, **kw)).data)

    @extend_schema(request=PtrStatusIn, responses=PtrClientSerializer)
    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        d = _valid(PtrStatusIn, request)
        return Response(PtrClientSerializer(services.set_client_status(self.get_object(), request.user, d["status"],
                                                                       d.get("reason", ""))).data)

    @extend_schema(request=None, responses=PtrClientCreated)
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, pk=None):
        c, raw = services.rotate_secret(self.get_object(), request.user)
        data = PtrClientSerializer(c).data
        data["client_secret"] = raw
        return Response(data)

    @extend_schema(parameters=[OpenApiParameter("month", str)], responses=PtrUsageOut)
    @action(detail=True, methods=["get"])
    def usage(self, request, pk=None):
        return Response(services.usage(self.get_object(), _month(request.query_params.get("month"))))

    @extend_schema(request=PtrMonthIn, responses={201: PtrStatementSerializer})
    @action(detail=True, methods=["post"], url_path="usage-statements")
    def usage_statements(self, request, pk=None):
        d = _valid(PtrMonthIn, request)
        st = services.close_month(self.get_object(), _month(d["month"]), request.user)
        return Response(PtrStatementSerializer(st).data, status=201)

    @extend_schema(responses=PtrDeliverySerializer(many=True))
    @action(detail=True, methods=["get"])
    def deliveries(self, request, pk=None):
        from .models import WebhookDelivery

        qs = WebhookDelivery.objects.filter(subscription__client=self.get_object()).order_by("-created_at")[:100]
        return Response(PtrDeliverySerializer(qs, many=True).data)


@extend_schema(tags=["partner"], request=None, responses={200: OpenApiTypes.OBJECT})
@api_view(["POST"])
def deliver_webhooks(request):
    """Run the webhook delivery job now (it also runs every minute)."""
    if not has_role(request.user, "AD"):
        raise Forbidden()
    return Response({"attempted": services.deliver_due()})
