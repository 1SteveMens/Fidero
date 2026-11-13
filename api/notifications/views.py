"""NTF API: the inbox for the apps, preferences, push devices, the message
log and templates for the back office, family confirmation, and the
messaging webhooks."""
import hashlib

from django.db import IntegrityError, transaction
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from core.errors import Forbidden, NotFound, _problem
from core.idempotency import idempotent
from core.permissions import roles
from countries.models import Country

from . import catalogue, services
from .models import ConfirmationCode, DeliveryEvent, Message, PushDevice, Template
from .serializers import (
    MyConfirmationSerializer,
    ConfirmationAttemptResultSerializer, ConfirmationCallCheckSerializer, ConfirmationCallRecordSerializer, CatalogueEntrySerializer,
    CodeAttemptSerializer, ConfirmationSendSerializer, FamilyConfirmationSerializer, DeliveryHookSerializer,
    MessagingHookAckSerializer, InboxMessageSerializer, LinkDecisionSerializer, InboxMarkedSerializer, MessageLogSerializer,
    NotificationPreferenceSerializer, NotificationPreferencesUpdateSerializer, TemplatePreviewResultSerializer, TemplatePreviewSerializer,
    PublicConfirmationSerializer, PushDeviceSerializer, ReplyHookSerializer, NotificationTemplateSerializer,
    UnreadCountSerializer,
)

Staff = roles("CM", "RV", "AD")


def _attempt_response(request, res):
    """A failed code attempt answers 422 without raising, so the attempt that
    was counted is not rolled back with the request."""
    body = {"ok": res["ok"], "status": res["status"], "attempts_left": res["attempts_left"]}
    if res["ok"]:
        return Response(body)
    exc = services.ConfirmationCodeInvalid(services._failure_text(res))
    return _problem(422, exc.code, exc.title, exc.detail, request, attempts_left=res["attempts_left"],
                    reason=res["status"])


# --- Inbox -----------------------------------------------------------------------

class Inbox(generics.ListAPIView):
    """In-app messages for the signed-in person. `needs_action=true` lists only
    what still needs them (orange in the apps)."""

    serializer_class = InboxMessageSerializer

    @extend_schema(parameters=[OpenApiParameter("unread", bool), OpenApiParameter("needs_action", bool)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Message.objects.none()
        p = self.request.query_params
        return services.inbox(self.request.user, unread=p.get("unread") in ("1", "true"),
                              needs_action=p.get("needs_action") in ("1", "true"))


class UnreadCount(APIView):
    @extend_schema(responses=UnreadCountSerializer)
    def get(self, request):
        return Response(services.unread_count(request.user))


class MarkRead(APIView):
    @extend_schema(request=None, responses=InboxMessageSerializer)
    def post(self, request, pk):
        return Response(InboxMessageSerializer(services.mark_read(request.user, pk)).data)


class MarkAllRead(APIView):
    @extend_schema(request=None, responses=InboxMarkedSerializer)
    def post(self, request):
        return Response({"marked": services.mark_all_read(request.user)})


# --- Preferences and push devices ---------------------------------------------------

class Preferences(APIView):
    @extend_schema(responses=NotificationPreferenceSerializer(many=True))
    def get(self, request):
        return Response(NotificationPreferenceSerializer(services.get_preferences(request.user), many=True).data)

    @extend_schema(request=NotificationPreferencesUpdateSerializer, responses=NotificationPreferenceSerializer(many=True))
    def put(self, request):
        s = NotificationPreferencesUpdateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(NotificationPreferenceSerializer(services.set_preferences(request.user, s.validated_data["items"]),
                                             many=True).data)


class PushDevices(APIView):
    @extend_schema(responses=PushDeviceSerializer(many=True))
    def get(self, request):
        return Response(PushDeviceSerializer(PushDevice.objects.filter(person=request.user,
                                                                       revoked_at__isnull=True), many=True).data)

    @extend_schema(request=PushDeviceSerializer, responses={201: PushDeviceSerializer})
    @idempotent
    def post(self, request):
        s = PushDeviceSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = services.register_device(request.user, **s.validated_data)
        return Response(PushDeviceSerializer(d).data, status=201)


class PushDeviceDetail(APIView):
    @extend_schema(request=None, responses={204: None})
    def delete(self, request, pk):
        d = PushDevice.objects.filter(pk=pk, person=request.user).first()
        if not d:
            raise NotFound()
        services.revoke_device(d, reason="removed by the user")
        return Response(status=204)


# --- Back office: message log and templates (FR-NTF-002, FR-NTF-005) -----------------

class MessageLog(generics.ListAPIView):
    permission_classes = [Staff]
    serializer_class = MessageLogSerializer

    @extend_schema(parameters=[OpenApiParameter("person", str), OpenApiParameter("channel", str),
                               OpenApiParameter("status", str), OpenApiParameter("template", str),
                               OpenApiParameter("subject_type", str), OpenApiParameter("subject_id", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        from countries.selectors import staff_country_codes
        from django.db.models import Q

        qs = Message.objects.prefetch_related("delivery_events").select_related("country", "template_version")
        codes = staff_country_codes(self.request.user, "CM", "RV", "AD")
        if codes is not None:
            qs = qs.filter(Q(country__code__in=codes) | Q(country__isnull=True))
        p = self.request.query_params
        for f in ("channel", "status", "template", "subject_type", "subject_id"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        if p.get("person"):
            qs = qs.filter(person_id=p["person"])
        return qs


class MessageLogDetail(APIView):
    permission_classes = [Staff]

    @extend_schema(responses=MessageLogSerializer)
    def get(self, request, pk):
        m = Message.objects.filter(pk=pk).first()
        if not m:
            raise NotFound()
        return Response(MessageLogSerializer(m).data)


class Templates(APIView):
    permission_classes = [roles("AD")]

    @extend_schema(parameters=[OpenApiParameter("code", str), OpenApiParameter("channel", str),
                               OpenApiParameter("language", str), OpenApiParameter("all_versions", bool)],
                   responses=NotificationTemplateSerializer(many=True))
    def get(self, request):
        qs = Template.objects.all()
        p = request.query_params
        for f in ("code", "channel", "language"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        if p.get("all_versions") not in ("1", "true"):
            qs = qs.filter(status="active")
        return Response(NotificationTemplateSerializer(qs, many=True).data)

    @extend_schema(request=NotificationTemplateSerializer, responses=NotificationTemplateSerializer)
    def put(self, request):
        s = NotificationTemplateSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        t = services.save_template(code=d["code"], channel=d["channel"], language=d.get("language", "en"),
                                   country=d.get("country"), subject=d.get("subject", ""), body=d["body"],
                                   by=request.user, whatsapp_template_name=d.get("whatsapp_template_name", ""))
        return Response(NotificationTemplateSerializer(t).data)


class TemplateCatalogue(APIView):
    permission_classes = [roles("AD")]

    @extend_schema(responses=CatalogueEntrySerializer(many=True))
    def get(self, request):
        out = []
        for code, e in catalogue.CATALOGUE.items():
            phone = [v for v in e["variables"] if catalogue.VARIABLES.get(v) in ("safe", "amount")
                     or (catalogue.VARIABLES.get(v) == "code" and e.get("allows_code"))]
            out.append({"code": code, "category": e["category"], "variables": e["variables"],
                        "required": e.get("required", []), "phone_allowed": phone,
                        "default_subject": e["defaults"]["subject"], "default_body": e["defaults"]["body"],
                        "default_phone": e["phone"]})
        return Response(CatalogueEntrySerializer(out, many=True).data)


class TemplatePreview(APIView):
    permission_classes = [roles("AD")]

    @extend_schema(request=TemplatePreviewSerializer, responses=TemplatePreviewResultSerializer)
    def post(self, request):
        s = TemplatePreviewSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        country = Country.objects.filter(code=(d.get("country") or "").upper()).first()
        subj, body, t = services.compose(d["code"], d["channel"], context=d["context"], language=d["language"],
                                         country=country, link=d["context"].get("link", ""))
        return Response({"subject": subj, "body": body, "template_version": t.version if t else None})


# --- Family confirmation (ADR-20) ------------------------------------------------------

class ConfirmationList(generics.ListAPIView):
    """Staff view of confirmations for a subject; POST sends (or resends) a code."""

    permission_classes = [Staff]
    serializer_class = FamilyConfirmationSerializer

    @extend_schema(parameters=[OpenApiParameter("subject_type", str), OpenApiParameter("subject_id", str),
                               OpenApiParameter("status", str)])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        qs = ConfirmationCode.objects.select_related("country")
        p = self.request.query_params
        for f in ("subject_type", "subject_id", "status"):
            if p.get(f):
                qs = qs.filter(**{f: p[f]})
        return qs

    @extend_schema(request=ConfirmationSendSerializer, responses={201: FamilyConfirmationSerializer})
    @idempotent
    def post(self, request):
        from accounts.models import Person

        s = ConfirmationSendSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        country = Country.objects.filter(code=d.pop("country").upper()).first()
        if not country:
            raise NotFound("No such country.")
        rp = d.pop("recipient_person", None)
        person = Person.objects.filter(pk=rp).first() if rp else None
        conf = services.send_confirmation_code(country=country, recipient_person=person, created_by=request.user, **d)
        return Response(FamilyConfirmationSerializer(conf).data, status=201)


def _conf(pk) -> ConfirmationCode:
    c = ConfirmationCode.objects.filter(pk=pk).first()
    if not c:
        raise NotFound()
    return c


class ConfirmationCallRecord(APIView):
    """Staff record a confirmation by phone; a second staff member checks it."""

    permission_classes = [Staff]

    @extend_schema(request=ConfirmationCallRecordSerializer, responses=FamilyConfirmationSerializer)
    @idempotent
    def post(self, request, pk):
        s = ConfirmationCallRecordSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        conf = services.record_call(_conf(pk), by=request.user, **s.validated_data)
        return Response(FamilyConfirmationSerializer(conf).data)


class ConfirmationCallCheck(APIView):
    permission_classes = [Staff]

    @extend_schema(request=ConfirmationCallCheckSerializer, responses=FamilyConfirmationSerializer)
    @idempotent
    def post(self, request, pk):
        s = ConfirmationCallCheckSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        conf = services.check_call(_conf(pk), by=request.user, agree=s.validated_data["agree"])
        return Response(FamilyConfirmationSerializer(conf).data)


class ConfirmByCode(APIView):
    """A confirmer with an account enters the code in the app."""

    @extend_schema(request=CodeAttemptSerializer, responses=ConfirmationAttemptResultSerializer)
    def post(self, request):
        s = CodeAttemptSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        conf = ConfirmationCode.objects.filter(subject_type=d["subject_type"], subject_id=d["subject_id"]).exclude(
            status="superseded").order_by("-created_at").first()
        if conf is None or (conf.recipient_person_id and conf.recipient_person_id != request.user.pk):
            raise NotFound()
        if conf.recipient_person_id is None:
            raise Forbidden("This confirmation is for someone without an account. Use the link or reply.")
        return _attempt_response(request, services.attempt_code(subject_type=d["subject_type"],
                                                                subject_id=d["subject_id"], code=d["code"],
                                                                actor=request.user))


class MyConfirmations(APIView):
    """Visits and deliveries a family member with an account is asked to confirm (SCR-PTL-45, US-CARE-004).
    They confirm with the code sent to their own phone (/v1/family-confirmations/codes)."""

    @extend_schema(responses=MyConfirmationSerializer(many=True))
    def get(self, request):
        return Response(MyConfirmationSerializer(services.my_confirmations(request.user), many=True).data)


class MyConfirmationDispute(APIView):
    """The named confirmer says it did not happen. Tenmina calls them; nobody is paid for it."""

    @extend_schema(request=None, responses=MyConfirmationSerializer)
    @idempotent
    def post(self, request, pk):
        return Response(MyConfirmationSerializer(services.dispute_mine(pk, request.user)).data)


class PublicConfirmation(APIView):
    """The one-tap link a confirmer receives (Pub). GET shows what is asked;
    only POST confirms or disputes: opening the link never confirms."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(responses=PublicConfirmationSerializer)
    def get(self, request, token):
        c = services.by_link(token)
        services._expire_if_due(c)
        return Response({"status": c.status, "purpose": c.purpose, "summary": c.summary, "expires_at": c.expires_at})

    @extend_schema(request=LinkDecisionSerializer, responses=ConfirmationAttemptResultSerializer)
    def post(self, request, token):
        s = LinkDecisionSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        return _attempt_response(request, services.confirm_by_link(token, decision=s.validated_data["decision"]))


# --- Webhooks (7.3) ---------------------------------------------------------------------

def _verified(request):
    from core.adapters import get_adapter

    adapter = get_adapter("messaging", default="notifications.adapters.ConsoleMessaging")
    raw = request.body
    if not adapter.verify_signature(raw, request.headers.get("X-Tenmina-Signature", "")):
        raise Forbidden("The signature does not match.")
    return raw


class DeliveryHook(APIView):
    """Delivery reports from the SMS, WhatsApp and email providers."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(request=DeliveryHookSerializer, responses=MessagingHookAckSerializer)
    def post(self, request):
        raw = _verified(request)
        s = DeliveryHookSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        dup = DeliveryEvent.objects.filter(provider=d["provider"], provider_event_id=d["event_id"]).exists()
        services.record_delivery(provider=d["provider"], event_id=d["event_id"], provider_ref=d["provider_ref"],
                                 status=d["status"], raw=raw, occurred_at=d.get("occurred_at"), payload=request.data)
        return Response({"received": True, "duplicate": dup})


class ReplyHook(APIView):
    """Inbound SMS and WhatsApp replies carrying a confirmation code (ADR-20)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(request=ReplyHookSerializer, responses=MessagingHookAckSerializer)
    def post(self, request):
        raw = _verified(request)
        s = ReplyHookSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        try:
            with transaction.atomic():
                DeliveryEvent.objects.create(provider=d["provider"], provider_event_id=d["event_id"],
                                             status="inbound_reply", raw_sha256=hashlib.sha256(raw).hexdigest(),
                                             payload={"channel": d["channel"]})
        except IntegrityError:
            return Response({"received": True, "duplicate": True})
        services.confirm_by_reply(from_address=d["sender"], text=d["text"])
        return Response({"received": True, "duplicate": False})
