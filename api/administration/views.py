"""ADM API (02 section 7.4): /v1/admin/... for administrators, plus the public
app configuration, legal texts and exchange-rate guides."""
import base64
import binascii

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.money import q
from core.permissions import roles
from core.views import require_mfa
from countries.models import Country

from . import appversion, registry, selectors, services
from .models import AppVersion, ChangeRequest, ConfigVersion, FeatureFlag, FxRate, LockedTextVersion, Partner, Price
from .serializers import (
    AppConfigQuerySerializer, AppConfigSerializer, AppVersionOutcomeSerializer, AppVersionSerializer,
    AppVersionUpdateSerializer, AdmApprovalStateSerializer, ChangeOutcomeSerializer, ChangeRequestSerializer,
    ConfigVersionEditSerializer, ConfigVersionSerializer, AdmDecisionSerializer, FeatureFlagSerializer,
    FlagChangeSerializer, FlagOutcomeSerializer, FxGuideSerializer, FxGuideRateSerializer, LockedTextEditSerializer,
    LockedTextSerializer, RegistryPartnerCreateSerializer, RegistryPartnerSerializer, RegistryPartnerUpdateSerializer, AdminPriceSerializer,
    PriceUpdateSerializer, PublicLockedTextSerializer, AdmReasonSerializer, AdminSettingSerializer, SettingUpdateSerializer,
    SignoffSerializer, PartnerBankDetailsSerializer, setting_view,
)

Admin = roles("AD")


def _country(code, required=True):
    if not code:
        if required:
            raise Invalid("Give a country code.", code="validation-error")
        return None
    c = Country.objects.filter(code=str(code).upper()).first()
    if not c:
        raise NotFound("No such country.")
    return c


def _approval_state(req):
    return {"request_id": req.pk, "status": req.status, "approvals": req.approvals.filter(decision="approve").count(),
            "required": req.required}


# --- Configuration versions (FR-ADM-001) ------------------------------------------

class ConfigVersionList(generics.ListCreateAPIView):
    permission_classes = [Admin]
    serializer_class = ConfigVersionSerializer

    @extend_schema(parameters=[OpenApiParameter("kind", str), OpenApiParameter("country", str),
                               OpenApiParameter("state", str), OpenApiParameter("product_line", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = ConfigVersion.objects.all()
        p = self.request.query_params
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if p.get("country"):
            qs = qs.filter(country__code=p["country"].upper())
        if p.get("state"):
            qs = qs.filter(state=p["state"])
        if p.get("product_line") is not None and "product_line" in p:
            qs = qs.filter(product_line=p["product_line"])
        return qs

    @idempotent
    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        cv = services.create_config_version(kind=d["kind"], content=d.get("content", {}), by=request.user,
                                            country=d.get("country"), product_line=d.get("product_line", ""),
                                            name=d.get("name", ""), schema_version=d.get("schema_version", "1"))
        return Response(ConfigVersionSerializer(cv).data, status=201)


class ConfigVersionDetail(APIView):
    permission_classes = [Admin]

    def _get(self, pk):
        return selectors.config_version(pk)

    @extend_schema(responses=ConfigVersionSerializer)
    def get(self, request, pk):
        return Response(ConfigVersionSerializer(self._get(pk)).data)

    @extend_schema(request=ConfigVersionEditSerializer, responses=ConfigVersionSerializer)
    def patch(self, request, pk):
        s = ConfigVersionEditSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        cv = services.update_config_draft(self._get(pk), by=request.user, **s.validated_data)
        return Response(ConfigVersionSerializer(cv).data)


class ConfigVersionPublish(APIView):
    permission_classes = [Admin]

    @extend_schema(request=None, responses=ConfigVersionSerializer)
    @idempotent
    def post(self, request, pk):
        cv = services.publish_config_version(selectors.config_version(pk), by=request.user)
        return Response(ConfigVersionSerializer(cv).data)


class ConfigVersionRetire(APIView):
    permission_classes = [Admin]

    @extend_schema(request=None, responses=ConfigVersionSerializer)
    @idempotent
    def post(self, request, pk):
        cv = services.retire_config_version(selectors.config_version(pk), by=request.user)
        return Response(ConfigVersionSerializer(cv).data)


# --- Prices and FX guides (FR-ADM-002) ---------------------------------------------

class PriceAdmin(APIView):
    permission_classes = [Admin]

    @extend_schema(parameters=[OpenApiParameter("country", str), OpenApiParameter("product_line", str),
                               OpenApiParameter("history", bool)], responses=AdminPriceSerializer(many=True))
    def get(self, request):
        p = request.query_params
        qs = Price.objects.all()
        if p.get("country"):
            qs = qs.filter(country__code=p["country"].upper())
        if p.get("product_line"):
            qs = qs.filter(product_line=p["product_line"])
        if p.get("history") not in ("1", "true"):
            qs = qs.filter(valid_to__isnull=True)
        return Response(AdminPriceSerializer(qs.order_by("product_line", "tier", "audience", "-valid_from"),
                                        many=True).data)

    @extend_schema(request=PriceUpdateSerializer, responses=AdminPriceSerializer(many=True))
    def put(self, request):
        s = PriceUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        country = s.validated_data["country"]
        out = []
        for it in s.validated_data["items"]:
            money = it["price"] if isinstance(it["price"], dict) else {}
            out.append(services.set_price(country=country, tier=it["tier"], amount=money.get("amount"),
                                          currency=money.get("currency", ""), by=request.user,
                                          product_line=it["product_line"], audience=it["audience"], note=it["note"]))
        return Response(AdminPriceSerializer(out, many=True).data)


class FxRateAdmin(APIView):
    permission_classes = [Admin]

    @extend_schema(parameters=[OpenApiParameter("country", str)], responses=FxGuideRateSerializer(many=True))
    def get(self, request):
        qs = FxRate.objects.all()
        if request.query_params.get("country"):
            qs = qs.filter(country__code=request.query_params["country"].upper())
        return Response(FxGuideRateSerializer(qs[:200], many=True).data)

    @extend_schema(request=FxGuideRateSerializer, responses=FxGuideRateSerializer)
    def put(self, request):
        data = dict(request.data)
        rate = data.get("rate")
        try:
            if rate is not None and q(rate) <= 0:
                raise ValueError
        except Exception:  # noqa: BLE001
            raise Invalid("A rate must be above zero.", code="fx-rate-invalid") from None
        s = FxGuideRateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        fx = services.set_fx_rate(country=d["country"], base=d["base_currency"], quote=d["quote_currency"],
                                  rate=d["rate"], rate_date=d.get("rate_date"), by=request.user)
        return Response(FxGuideRateSerializer(fx).data)


class FxGuides(APIView):
    """US-ADM-002: guide rates with the date they were taken, for display next
    to guide prices. Never a quote (RUL-18, FR-ESC-023)."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("country", str, required=True)], responses=FxGuideSerializer(many=True))
    def get(self, request):
        c = _country(request.query_params.get("country"))
        seen, out = set(), []
        for fx in FxRate.objects.filter(country=c).order_by("-rate_date", "-created_at"):
            pair = (fx.base_currency, fx.quote_currency)
            if pair in seen:
                continue
            seen.add(pair)
            out.append({"base_currency": fx.base_currency, "quote_currency": fx.quote_currency, "rate": fx.rate,
                        "rate_date": fx.rate_date, "source": fx.source,
                        "note": f"Guide rate of {fx.rate_date:%d %B %Y}. Not a quote."})
        return Response(FxGuideSerializer(out, many=True).data)


# --- Partners (FR-ADM-003) ---------------------------------------------------------

class PartnerList(generics.ListAPIView):
    permission_classes = [Admin]
    serializer_class = RegistryPartnerSerializer

    @extend_schema(parameters=[OpenApiParameter("country", str), OpenApiParameter("kind", str),
                               OpenApiParameter("status", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = Partner.objects.all()
        p = self.request.query_params
        if p.get("country"):
            qs = qs.filter(country__code=p["country"].upper())
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        return qs

    @extend_schema(request=RegistryPartnerCreateSerializer, responses={201: RegistryPartnerSerializer})
    @idempotent
    def post(self, request):
        s = RegistryPartnerCreateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        bank = d.pop("bank", None)
        reason = (bank or {}).pop("reason", "") if bank else ""
        p, _ = services.create_partner(by=request.user, bank=bank, reason=reason, **d)
        return Response(RegistryPartnerSerializer(p).data, status=201)


class PartnerDetail(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=RegistryPartnerSerializer)
    def get(self, request, pk):
        return Response(RegistryPartnerSerializer(selectors.partner(pk)).data)

    @extend_schema(request=RegistryPartnerUpdateSerializer, responses=RegistryPartnerSerializer)
    def patch(self, request, pk):
        p = selectors.partner(pk)
        if any(f in request.data for f in services.BANK_FIELDS):
            raise Invalid("Bank details change only through a bank change request.",
                          code="bank-change-needs-approval")
        s = RegistryPartnerUpdateSerializer(p, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return Response(RegistryPartnerSerializer(services.update_partner(p, by=request.user, **s.validated_data)).data)


class PartnerBankChange(APIView):
    """FR-ADM-003: propose new bank details; a second administrator approves."""

    permission_classes = [Admin]

    @extend_schema(request=PartnerBankDetailsSerializer, responses={201: ChangeRequestSerializer})
    @idempotent
    def post(self, request, pk):
        s = PartnerBankDetailsSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        cr = services.request_bank_change(selectors.partner(pk), by=request.user, **s.validated_data)
        return Response(ChangeRequestSerializer(cr).data, status=201)


class PartnerStatus(APIView):
    permission_classes = [Admin]
    active = True

    @extend_schema(request=AdmReasonSerializer, responses=RegistryPartnerSerializer)
    @idempotent
    def post(self, request, pk):
        s = AdmReasonSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        p = services.set_partner_status(selectors.partner(pk), active=self.active, by=request.user,
                                        reason=s.validated_data["reason"])
        return Response(RegistryPartnerSerializer(p).data)


class PartnerDeactivate(PartnerStatus):
    active = False


class PartnerReactivate(PartnerStatus):
    active = True


# --- Locked texts (FR-ADM-004) -------------------------------------------------------

def _locked(kind, pk) -> LockedTextVersion:
    ltv = LockedTextVersion.objects.filter(pk=pk, kind=kind).first()
    if not ltv:
        raise NotFound("No such text version.")
    return ltv


class LockedTextVersions(APIView):
    permission_classes = [Admin]

    @extend_schema(parameters=[OpenApiParameter("country", str)], responses=LockedTextSerializer(many=True))
    def get(self, request, kind):
        qs = LockedTextVersion.objects.filter(kind=kind)
        if request.query_params.get("country"):
            qs = qs.filter(country__code=request.query_params["country"].upper())
        return Response(LockedTextSerializer(qs, many=True).data)

    @extend_schema(request=LockedTextSerializer, responses={201: LockedTextSerializer})
    @idempotent
    def post(self, request, kind):
        s = LockedTextSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ltv = services.propose_locked_text(kind=kind, country=s.validated_data["country"],
                                           text=s.validated_data["text"], title=s.validated_data.get("title", ""),
                                           by=request.user)
        return Response(LockedTextSerializer(ltv).data, status=201)


class LockedTextDetail(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=LockedTextSerializer)
    def get(self, request, kind, pk):
        return Response(LockedTextSerializer(_locked(kind, pk)).data)

    @extend_schema(request=LockedTextEditSerializer, responses=LockedTextSerializer)
    def patch(self, request, kind, pk):
        s = LockedTextEditSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(LockedTextSerializer(services.edit_locked_text(_locked(kind, pk), by=request.user,
                                                                       **s.validated_data)).data)


class LockedTextSignoff(APIView):
    """Record the lawyer's or insurer's written approval of this exact text."""

    permission_classes = [Admin]

    @extend_schema(request=SignoffSerializer, responses=LockedTextSerializer)
    @idempotent
    def post(self, request, kind, pk):
        from evidence.models import Evidence
        from evidence.services import store

        ltv = _locked(kind, pk)
        s = SignoffSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if d.get("evidence_id"):
            ev = Evidence.objects.filter(pk=d["evidence_id"]).first()
            if not ev:
                raise NotFound("No such evidence.")
        elif d.get("document_base64"):
            try:
                raw = base64.b64decode(d["document_base64"], validate=True)
            except (binascii.Error, ValueError):
                raise Invalid("document_base64 is not valid base64.") from None
            ev = store(data=raw, country=ltv.country, uploaded_by=request.user, content_type=d["content_type"],
                       original_name=d["filename"], source="upload",
                       description=f"{d['party']} approval of {kind} v{ltv.version}")
        else:
            raise Invalid("Attach the written approval: evidence_id or document_base64.")
        ltv = services.record_signoff(ltv, party=d["party"], approved_by_name=d["approved_by_name"], evidence=ev,
                                      by=request.user)
        return Response(LockedTextSerializer(ltv).data)


class LockedTextSubmit(APIView):
    permission_classes = [Admin]

    @extend_schema(request=None, responses=AdmApprovalStateSerializer)
    @idempotent
    def post(self, request, kind, pk):
        req = services.submit_locked_text(_locked(kind, pk), by=request.user)
        return Response(_approval_state(req))


class LockedTextApprovals(APIView):
    """A second, different administrator approves with a fresh MFA step-up."""

    permission_classes = [Admin]

    @extend_schema(request=AdmDecisionSerializer, responses=LockedTextSerializer)
    @idempotent
    def post(self, request, kind, pk):
        at = require_mfa(request)
        s = AdmDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        ltv = _locked(kind, pk)
        services.decide_locked_text(ltv, request.user, mfa_at=at, **s.validated_data)
        ltv.refresh_from_db()
        return Response(LockedTextSerializer(ltv).data)


class LegalTextCurrent(APIView):
    """Terms, scope statement, privacy notice and escrow terms in force (Pub)."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("country", str, required=True)], responses=PublicLockedTextSerializer)
    def get(self, request, kind):
        c = _country(request.query_params.get("country"))
        ltv = selectors.current_locked_text(kind, c)
        if not ltv:
            raise NotFound("No text is in force for this country yet.")
        return Response(PublicLockedTextSerializer(ltv).data)


# --- Settings (FR-ADM-005) ---------------------------------------------------------

def _pending_for(key, country):
    cr = ChangeRequest.objects.filter(kind="setting", target=key, country=country, status="pending").first()
    return cr.pk if cr else None


class SettingList(APIView):
    permission_classes = [Admin]

    @extend_schema(parameters=[OpenApiParameter("country", str)], responses=AdminSettingSerializer(many=True))
    def get(self, request):
        c = _country(request.query_params.get("country"), required=False)
        return Response(AdminSettingSerializer([setting_view(k, c, _pending_for(k, c)) for k in registry.REGISTRY],
                                          many=True).data)


class SettingDetail(APIView):
    permission_classes = [Admin]

    @extend_schema(parameters=[OpenApiParameter("country", str)], responses=AdminSettingSerializer)
    def get(self, request, key):
        registry.definition(key)
        c = _country(request.query_params.get("country"), required=False)
        return Response(AdminSettingSerializer(setting_view(key, c, _pending_for(key, c))).data)

    @extend_schema(request=SettingUpdateSerializer, responses=ChangeOutcomeSerializer)
    def put(self, request, key):
        s = SettingUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        c = s.validated_data.get("country")
        row, cr = services.change_setting(key=key, value=s.validated_data["value"], by=request.user, country=c,
                                          reason=s.validated_data["reason"])
        return Response(ChangeOutcomeSerializer({
            "status": "pending_approval" if cr else "applied", "change_request": cr,
            "setting": setting_view(key, c, cr.pk if cr else None)}).data, status=202 if cr else 200)


# --- Change requests ------------------------------------------------------------------

class ChangeRequestList(generics.ListAPIView):
    """The pending list a second administrator works from (TC-ADM-005-04)."""

    permission_classes = [Admin]
    serializer_class = ChangeRequestSerializer

    @extend_schema(parameters=[OpenApiParameter("status", str), OpenApiParameter("kind", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = ChangeRequest.objects.select_related("approval_request", "country")
        p = self.request.query_params
        qs = qs.filter(status=p.get("status", "pending"))
        if p.get("kind"):
            qs = qs.filter(kind=p["kind"])
        return qs


class ChangeRequestDetail(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=ChangeRequestSerializer)
    def get(self, request, pk):
        return Response(ChangeRequestSerializer(services.get_change(pk)).data)


class ChangeRequestApprovals(APIView):
    """A second, different administrator approves or rejects with MFA."""

    permission_classes = [Admin]

    @extend_schema(request=AdmDecisionSerializer, responses=ChangeRequestSerializer)
    @idempotent
    def post(self, request, pk):
        at = require_mfa(request)
        s = AdmDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        cr = services.get_change(pk)
        services.decide_change(cr, request.user, mfa_at=at, **s.validated_data)
        cr.refresh_from_db()
        return Response(ChangeRequestSerializer(cr).data)


class ChangeRequestWithdraw(APIView):
    permission_classes = [Admin]

    @extend_schema(request=None, responses=ChangeRequestSerializer)
    @idempotent
    def post(self, request, pk):
        return Response(ChangeRequestSerializer(services.withdraw_change(services.get_change(pk),
                                                                         by=request.user)).data)


# --- Feature flags (06 section 2.6) -------------------------------------------------

class FeatureFlagList(generics.ListAPIView):
    permission_classes = [roles("AD", "RV")]
    serializer_class = FeatureFlagSerializer
    pagination_class = None

    def get_queryset(self):
        return FeatureFlag.objects.select_related("country").order_by("name", "country__code")


class FeatureFlagChange(APIView):
    """Switch a flag. Safety flags switched on wait for a second administrator;
    kill switches act at once."""

    permission_classes = [roles("AD", "RV")]

    @extend_schema(request=FlagChangeSerializer, responses=FlagOutcomeSerializer)
    @idempotent
    def post(self, request):
        s = FlagChangeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        flag, cr = services.change_flag(name=d["name"], enabled=d["enabled"], by=request.user,
                                        country=d.get("country"), value=d.get("value"), reason=d["reason"])
        return Response(FlagOutcomeSerializer({"status": "pending_approval" if cr else "applied", "flag": flag,
                                               "change_request": cr}).data, status=202 if cr else 200)


# --- App versions (FR-APP-006) -------------------------------------------------------

class AppVersionAdmin(APIView):
    permission_classes = [Admin]

    @extend_schema(responses=AppVersionSerializer(many=True))
    def get(self, request):
        return Response(AppVersionSerializer(AppVersion.objects.order_by("app", "platform"), many=True).data)

    @extend_schema(request=AppVersionUpdateSerializer, responses=AppVersionOutcomeSerializer)
    def put(self, request):
        s = AppVersionUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        av, cr = services.set_app_version(by=request.user, **s.validated_data)
        return Response(AppVersionOutcomeSerializer({"app_version": av, "change_request": cr}).data,
                        status=202 if cr else 200)


class AppConfig(APIView):
    """GET /v1/app-config (Pub): minimum and latest version, store link and fee
    payment mode for this app and platform (FR-APP-005, FR-APP-006)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(parameters=[AppConfigQuerySerializer], responses=AppConfigSerializer)
    def get(self, request):
        s = AppConfigQuerySerializer(data=request.query_params)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        st = appversion.status(d["app"], d["platform"], d["version"])
        country = Country.objects.filter(code=d.get("country", "").upper()).first() if d.get("country") else None
        return Response(AppConfigSerializer({
            "app": d["app"], "platform": d["platform"], "version": d["version"], "min_version": st["min_version"],
            "latest_version": st["latest_version"], "update_required": not st["supported"],
            "update_available": st["update_available"], "store_url": st["store_url"],
            "fee_payment_mode": services.fee_payment_mode(country, d["platform"]),
        }).data)
