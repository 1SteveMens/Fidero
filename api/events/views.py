"""EVT API (02 section 7.4). Clients see their own events; staff their countries. The family member who
confirms deliveries uses the code channel (ADR-20), or this API when signed in."""
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.views import ETagMixin, require_mfa

from . import serializers as S
from . import services
from .models import Vendor, VendorPayment

UUID_RE = r"[0-9a-fA-F-]{36}"


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


class Base(ETagMixin, viewsets.GenericViewSet):
    permission_classes = [permissions.IsAuthenticated]
    lookup_value_regex = UUID_RE


class EventViewSet(Base, mixins.ListModelMixin, mixins.RetrieveModelMixin):
    """Events with budget, date and vendors; budget against actual (FR-EVT-001, FR-EVT-003)."""

    serializer_class = S.EventSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        return services.events_for(self.request.user).order_by("-created_at")

    def get_serializer_class(self):
        return S.EventDetailSerializer if self.action == "retrieve" else S.EventSerializer

    def _out(self, request, e, status=200):
        e.refresh_from_db()
        return Response(S.EventDetailSerializer(e, context={"request": request}).data, status=status)

    @extend_schema(request=S.EventCreate, responses={201: S.EventDetailSerializer})
    @idempotent
    def create(self, request):
        from accounts.models import Person

        d = _valid(S.EventCreate, request)
        client = None
        if d.get("client_id"):
            client = Person.objects.filter(pk=d["client_id"]).first()
            if client is None:
                raise Invalid("Client not found.", code="validation-error")
        e = services.create_event(request.user, client=client, country=_country(d["country"]), kind=d["kind"],
                                  name=d["name"], event_date=d["event_date"], budget=d["budget"],
                                  locality=d["locality"], confirmer_family_member_id=d.get("confirmer_family_member_id"))
        return self._out(request, e, 201)

    @extend_schema(request=S.BudgetIn, responses=S.EventDetailSerializer)
    @action(detail=True, methods=["post"])
    def budget(self, request, pk=None):
        """The client changes the budget; the change is recorded."""
        d = _valid(S.BudgetIn, request)
        return self._out(request, services.change_budget(self.get_object(), request.user, budget=d["budget"],
                                                         reason=d["reason"]))

    @extend_schema(request=S.ConfirmerIn, responses=S.EventDetailSerializer)
    @action(detail=True, methods=["put"])
    def confirmer(self, request, pk=None):
        """The family member who confirms deliveries by a one-time code (ADR-20)."""
        d = _valid(S.ConfirmerIn, request)
        return self._out(request, services.set_confirmer(self.get_object(), request.user, d["family_member_id"]))

    @extend_schema(request=S.VendorCreate, responses={201: S.VendorSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def vendors(self, request, pk=None):
        """Add a vendor; opens the vendor verification case (FR-EVT-001)."""
        d = _valid(S.VendorCreate, request)
        v = services.add_vendor(self.get_object(), request.user, kind=d["kind"], name=d["name"],
                                is_organisation=d["is_organisation"], registration_number=d["registration_number"],
                                registration_evidence_id=d.get("registration_evidence_id"),
                                contact_name=d["contact_name"], contact_phone=d["contact_phone"],
                                quote=d.get("quote"), quote_evidence_id=d.get("quote_evidence_id"),
                                payee_id=d.get("payee_id"))
        return Response(S.VendorSerializer(v).data, status=201)

    @extend_schema(request=None, responses={201: S.EscrowOpened})
    @action(detail=True, methods=["post"])
    @idempotent
    def escrow(self, request, pk=None):
        """Open the event escrow for the budget, naming the verified vendors (open_line_escrow kind event)."""
        from escrow.services import payment_instructions

        esc = services.open_escrow(self.get_object(), request.user)
        return Response({"escrow_id": str(esc.pk), "reference": esc.reference, "status": esc.status,
                         "pay_to": payment_instructions(esc)}, status=201)

    @extend_schema(methods=["GET"], responses=S.PaymentSerializer(many=True))
    @extend_schema(methods=["POST"], request=S.PaymentCreate, responses={201: S.PaymentSerializer})
    @action(detail=True, methods=["get", "post"], url_path="vendor-payments")
    def vendor_payments(self, request, pk=None):
        """Deposits against a signed quote; payments against invoice and delivery evidence (FR-EVT-002)."""
        e = self.get_object()
        if request.method == "GET":
            return Response(S.PaymentSerializer(e.payments.select_related("vendor").order_by("created_at"),
                                                many=True).data)
        return self._create_payment(request, e)

    @idempotent
    def _create_payment(self, request, e):
        d = _valid(S.PaymentCreate, request)
        p = services.propose_payment(e, request.user, vendor_id=d["vendor_id"], kind=d["kind"], amount=d["amount"],
                                     quote_evidence_id=d.get("quote_evidence_id"),
                                     invoice_evidence_id=d.get("invoice_evidence_id"),
                                     delivery_evidence_ids=d["delivery_evidence_ids"], description=d["description"])
        return Response(S.PaymentSerializer(p).data, status=201)

    @extend_schema(responses=S.ReceiptSerializer(many=True))
    @action(detail=True, methods=["get"])
    def receipts(self, request, pk=None):
        """A receipt for every payment (FR-EVT-003)."""
        return Response(services.receipts(self.get_object()))

    @extend_schema(request=None, responses=S.EventDetailSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        return self._out(request, services.close_event(self.get_object(), request.user))

    @extend_schema(request=S.ReasonIn, responses=S.EventDetailSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        return self._out(request, services.cancel_event(self.get_object(), request.user,
                                                        _valid(S.ReasonIn, request)["reason"]))


class VendorViewSet(Base, mixins.RetrieveModelMixin):
    serializer_class = S.VendorSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        return Vendor.objects.filter(event__in=services.events_for(self.request.user)).select_related("event",
                                                                                                     "payee")

    @extend_schema(request=S.VendorPayeeIn, responses={201: S.VendorSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def payee(self, request, pk=None):
        """Record the vendor's account in its own name; two staff then verify it (FR-ESC-015)."""
        d = _valid(S.VendorPayeeIn, request)
        v = self.get_object()
        services.register_vendor_payee(v, request.user, **d)
        v.refresh_from_db()
        return Response(S.VendorSerializer(v).data, status=201)

    @extend_schema(request=S.ReasonIn, responses=S.VendorSerializer)
    @action(detail=True, methods=["post"])
    def remove(self, request, pk=None):
        v = services.remove_vendor(self.get_object(), request.user, _valid(S.ReasonIn, request)["reason"])
        return Response(S.VendorSerializer(v).data)


class VendorPaymentViewSet(Base, mixins.RetrieveModelMixin):
    serializer_class = S.PaymentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.serializer_class.Meta.model.objects.none()
        u = self.request.user
        qs = VendorPayment.objects.select_related("event", "vendor")
        mine = qs.filter(event__in=services.events_for(u))
        return mine | qs.filter(event__confirmer_family_member__person=u)

    def _out(self, p):
        p.refresh_from_db()
        return Response(S.PaymentSerializer(p).data)

    def _own(self):
        p = self.get_object()
        if not services.can_view(self.request.user, p.event):
            raise NotFound()
        return p

    @extend_schema(request=S.PaymentEvidenceIn, responses=S.PaymentSerializer)
    @action(detail=True, methods=["post"])
    def evidence(self, request, pk=None):
        d = _valid(S.PaymentEvidenceIn, request)
        return self._out(services.add_payment_evidence(self._own(), request.user,
                                                       invoice_evidence_id=d.get("invoice_evidence_id"),
                                                       delivery_evidence_ids=d["delivery_evidence_ids"]))

    @extend_schema(request=None, responses=S.PaymentSerializer)
    @action(detail=True, methods=["post"], url_path="family-confirmation-requests")
    def family_confirmation_requests(self, request, pk=None):
        p = self._own()
        services.resend_confirmation(p, request.user)
        return self._out(p)

    @extend_schema(request=S.CodeIn, responses=S.PaymentSerializer)
    @action(detail=True, methods=["post"], url_path="family-confirmations")
    def family_confirmations(self, request, pk=None):
        """The nominated family member, signed in, confirms the delivery with the code they received."""
        p = self.get_object()
        return self._out(services.confirm_delivery(p, request.user, code=_valid(S.CodeIn, request)["code"]))

    @extend_schema(request=S.ClientApprovalIn, responses=S.PaymentSerializer)
    @action(detail=True, methods=["post"], url_path="client-approval")
    @idempotent
    def client_approval(self, request, pk=None):
        """RUL-11: the client approves with a fresh MFA step-up; the instruction to the vendor's verified payee
        goes to two staff with release rights."""
        p = self._own()
        if not services.is_client(request.user, p.event):
            raise NotFound()
        d = _valid(S.ClientApprovalIn, request)
        mfa_at = require_mfa(request)
        return self._out(services.client_approve(p, request.user, mfa_at=mfa_at, confirm_amount=d.get("confirm_amount"),
                                                 acknowledge_budget_warning=d["acknowledge_budget_warning"]))

    @extend_schema(request=None, responses={201: S.PaymentSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def instructions(self, request, pk=None):
        """A fresh instruction to pay the vendor, after an earlier one was withdrawn or refused (CM)."""
        p = self._own()
        services.prepare_instruction(p, request.user)
        p.refresh_from_db()
        return Response(S.PaymentSerializer(p).data, status=201)

    @extend_schema(request=S.ReasonIn, responses=S.PaymentSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._out(services.reject_payment(self._own(), request.user, _valid(S.ReasonIn, request)["reason"]))
