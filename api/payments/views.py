"""PAY API (02 section 7.4). Tenmina's own fees only: every route that takes money starts from a fee order or a
seller invoice, and no route accepts purchase, construction, project or premium money (RUL-01, FR-PAY-005)."""
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Organisation, Person
from audit.services import record
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict, _problem
from core.idempotency import idempotent
from core.permissions import roles
from core.views import require_mfa
from orders.views import get_order_for
from orders.access import is_staff_for

from . import adapters, selectors, services
from .models import FeePayment, Invoice
from .serializers import (PayDecisionInput, FakeCheckoutInfoSerializer, FakeCheckoutInput, SellerInvoiceCreateInput,
                          SellerInvoiceSerializer, OfflinePaymentInput, OfflineRefundCompletionInput, PaymentReceiptsSerializer,
                          PaymentSerializer, PaymentStartedSerializer, PaymentStartInput, InvoiceVoidInput,
                          ReceiptSerializer, ReconIssueSerializer, RefundCreateInput, RefundSerializer,
                          ReconResolutionInput, SettlementRunDetailSerializer, SettlementRunInput, SettlementRunSerializer,
                          WebhookAckSerializer)

UUID_RE = "[0-9a-fA-F-]{36}"
STAFF = roles("CM", "RV", "AD")


def _refuse_unknown(request, s, action_name, subject=None, country=None):
    """Refuse fields a money request must never carry, and keep an audit entry of the attempt.

    Returned as a response (not raised) so the audit entry is committed (TC-RUL-01-03, TC-PAY-008-02)."""
    unknown = s.unknown_fields()
    if not unknown:
        return None
    record(actor=request.user, action=action_name, entity="fee_payment",
           entity_id=getattr(subject, "pk", "none"), data={"fields": unknown},
           country=country or getattr(subject, "country", None))
    return _problem(400, "validation-error", "Some fields need attention",
                    "These fields are not accepted: " + ", ".join(unknown) + ". Tenmina takes only its own fees, "
                    "and refunds go back only to the original payment method.", request,
                    errors=[{"pointer": f"/{k}", "message": "This field is not accepted."} for k in unknown])


def _started(p):
    return Response(PaymentStartedSerializer({"payment": p, "checkout_url": p.checkout_url}).data, status=201)


# ---------------------------------------------------------------- start a payment (FR-PAY-001)


class OrderPaymentsView(APIView):
    """Start paying Tenmina's fee for an order (card or mobile money, hosted by the provider), or list the
    attempts. The amount and purpose come from the order, never from the request."""

    @extend_schema(request=None, responses=PaymentSerializer(many=True), tags=["payments"])
    def get(self, request, order_id):
        order = get_order_for(request.user, order_id)
        qs = selectors.visible_payments(request.user).filter(order=order).order_by("-created_at")
        return Response(PaymentSerializer(qs, many=True).data)

    @extend_schema(request=PaymentStartInput, responses={201: PaymentStartedSerializer}, tags=["payments"])
    @idempotent
    def post(self, request, order_id):
        order = get_order_for(request.user, order_id)
        s = PaymentStartInput(data=request.data)
        refused = _refuse_unknown(request, s, "payment.tampered_request_refused", order, order.country)
        if refused:
            return refused
        s.is_valid(raise_exception=True)
        return _started(services.start_order_payment(order, request.user, **s.validated_data))


class PaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer
    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "method", "purpose"]

    def get_queryset(self):
        return selectors.visible_payments(self.request.user).order_by("-created_at")

    @extend_schema(request=None, responses=PaymentSerializer)
    @action(detail=True, methods=["post"])
    def refresh(self, request, pk=None):
        """When the client comes back from the checkout: ask the provider how the payment stands."""
        p = self.get_object()
        services.sync_payment(p)
        p.refresh_from_db()
        return Response(PaymentSerializer(p).data)

    @extend_schema(request=None, responses=PaymentReceiptsSerializer)
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        """FR-PAY-003: the numbered receipt and any credit notes."""
        p = self.get_object()
        r = p.receipts.filter(kind="receipt").first()
        if r is None:
            raise NotFound("There is no receipt: the payment is not confirmed.")
        return Response(PaymentReceiptsSerializer({"receipt": r, "credit_notes": p.receipts.filter(
            kind="credit_note").order_by("issued_at")}).data)

    @extend_schema(methods=["GET"], request=None, responses=FakeCheckoutInfoSerializer)
    @extend_schema(methods=["POST"], request=FakeCheckoutInput, responses=PaymentSerializer)
    @action(detail=True, methods=["get", "post"], url_path="fake-checkout")
    def fake_checkout(self, request, pk=None):
        """Development only: the fake provider's hosted page. Card details are never asked for here either.
        POST an outcome to succeed or fail; the fake provider then sends its signed webhook."""
        provider = adapters.provider()
        if not isinstance(provider, adapters.FakePaymentProvider):
            raise NotFound()
        p = self.get_object()
        if request.method == "GET":
            return Response(FakeCheckoutInfoSerializer({
                "payment_id": p.pk, "provider_ref": p.provider_ref, "merchant": "Tenmina fees only",
                "amount": {"amount": f"{p.amount:.2f}", "currency": p.currency}, "method": p.method,
                "status": p.status, "outcomes": sorted(adapters.FAKE_OUTCOMES),
                "note": "A test page. A real provider hosts the card and mobile money entry."}).data)
        if request.user != p.payer:
            raise Forbidden("Only the payer can complete the checkout.")
        if p.status != "initiated":
            raise StateConflict("This checkout is closed.")
        s = FakeCheckoutInput(data=request.data)
        s.is_valid(raise_exception=True)
        hook = provider.complete(p.provider_ref, s.validated_data["outcome"],
                                 refundable=s.validated_data["refundable"])
        if hook is not None:
            services.handle_webhook(*hook)
        p.refresh_from_db()
        return Response(PaymentSerializer(p).data)


class ReceiptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReceiptSerializer
    lookup_value_regex = UUID_RE
    filterset_fields = ["kind"]

    def get_queryset(self):
        return selectors.visible_receipts(self.request.user).order_by("-issued_at")


# ---------------------------------------------------------------- webhooks (7.3)


class PaymentWebhookView(APIView):
    """POST /v1/hooks/payments: the provider's signed webhook. Verified, deduplicated on the vendor's event ID,
    and acted on only after fetching the authoritative state from the provider."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: WebhookAckSerializer}, tags=["webhooks"])
    def post(self, request):
        body = request.body
        try:
            result = services.handle_webhook(body, request.headers)
        except DomainError as exc:
            if exc.code != "unauthenticated":
                raise
            return _problem(401, exc.code, exc.title, exc.detail, request)
        return Response(result)


# ---------------------------------------------------------------- offline payments (FR-ORD-004)


class OfflinePaymentViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = PaymentSerializer
    permission_classes = [STAFF]
    lookup_value_regex = UUID_RE
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ["status"]

    def get_queryset(self):
        return selectors.visible_payments(self.request.user).filter(method="bank_transfer_offline").order_by(
            "-created_at")

    @extend_schema(request={"application/json": OfflinePaymentInput, "multipart/form-data": OfflinePaymentInput},
                   responses={201: PaymentSerializer})
    @idempotent
    def create(self, request):
        """A case manager records a bank transfer of a fee, with proof and the account it came from. Over the
        configured threshold, two more staff approve before the order counts as paid."""
        s = OfflinePaymentInput(data=request.data)
        refused = _refuse_unknown(request, s, "payment.offline_unknown_fields_refused")
        if refused:
            return refused
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        order = invoice = None
        if d.get("order_id"):
            from orders.models import Order

            order = get_object_or_404(Order, pk=d["order_id"])
        if d.get("invoice_id"):
            invoice = get_object_or_404(Invoice, pk=d["invoice_id"])
        p = services.record_offline_payment(
            request.user, order=order, invoice=invoice, amount=d["amount"], currency=d["currency"],
            reference=d["reference"], received_on=d["received_on"], source_bank_name=d["source_bank_name"],
            source_account_name=d["source_account_name"], source_account_number=d.get("source_account_number", ""),
            proof_evidence_id=d.get("proof_evidence_id"), proof_file=d.get("proof"))
        return Response(PaymentSerializer(p).data, status=201)

    @extend_schema(request=PayDecisionInput, responses=PaymentSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        s = PayDecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        mfa_at = require_mfa(request)
        p = services.decide_offline(request.user, self.get_object(), mfa_at=mfa_at, **s.validated_data)
        return Response(PaymentSerializer(p).data)


# ---------------------------------------------------------------- refunds (FR-PAY-004, FR-PAY-008)


class RefundViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = RefundSerializer
    permission_classes = [STAFF]
    lookup_value_regex = UUID_RE
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ["status"]

    def get_queryset(self):
        return selectors.staff_refunds(self.request.user).order_by("-created_at")

    @extend_schema(request=RefundCreateInput, responses={201: RefundSerializer})
    @idempotent
    def create(self, request):
        """Prepare a refund with a reason. It takes no destination: the money goes back only to the original
        card or wallet through the provider, or to the account an offline payment came from."""
        s = RefundCreateInput(data=request.data)
        p = None
        if hasattr(request.data, "get") and request.data.get("payment_id"):
            p = FeePayment.objects.filter(pk=request.data.get("payment_id")).first()
        refused = _refuse_unknown(request, s, "refund.destination_refused", p)
        if refused:
            return refused
        s.is_valid(raise_exception=True)
        d = s.validated_data
        if d.get("payment_id"):
            payment = get_object_or_404(selectors.visible_payments(request.user), pk=d["payment_id"])
            r = services.request_refund(request.user, payment, amount=d.get("amount"), reason=d["reason"])
        elif d.get("order_id"):
            r = services.request_refund_for_order(request.user, d["order_id"], amount=d.get("amount"),
                                                  reason=d["reason"])
        else:
            raise Invalid("Name the payment or order to refund.")
        return Response(RefundSerializer(r).data, status=201)

    @extend_schema(request=PayDecisionInput, responses=RefundSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        """Two staff who did not prepare the refund approve it, each with a fresh MFA step-up."""
        s = PayDecisionInput(data=request.data)
        s.is_valid(raise_exception=True)
        mfa_at = require_mfa(request)
        r = services.decide_refund(request.user, self.get_object(), mfa_at=mfa_at, **s.validated_data)
        return Response(RefundSerializer(r).data)

    @extend_schema(request=None, responses=RefundSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        """Try the provider again for a failed refund. There is no other route (FR-PAY-008, I-41)."""
        return Response(RefundSerializer(services.retry_refund(request.user, self.get_object())).data)

    @extend_schema(request={"application/json": OfflineRefundCompletionInput,
                            "multipart/form-data": OfflineRefundCompletionInput}, responses=RefundSerializer)
    @action(detail=True, methods=["post"])
    def completion(self, request, pk=None):
        """For an offline payment: record that the bank paid it back to the source account, with proof."""
        r = self.get_object()
        s = OfflineRefundCompletionInput(data=request.data)
        refused = _refuse_unknown(request, s, "refund.destination_refused", r.payment)
        if refused:
            return refused
        s.is_valid(raise_exception=True)
        d = s.validated_data
        r = services.record_offline_refund(request.user, r, bank_reference=d["bank_reference"],
                                           proof_evidence_id=d.get("proof_evidence_id"), proof_file=d.get("proof"))
        return Response(RefundSerializer(r).data)

    @extend_schema(request=None, responses=RefundSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        return Response(RefundSerializer(services.withdraw_refund(request.user, self.get_object())).data)


# ---------------------------------------------------------------- reconciliation (FR-PAY-006)


class SettlementRunViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [STAFF]
    lookup_value_regex = UUID_RE
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        return selectors.staff_runs(self.request.user).order_by("-created_at")

    def get_serializer_class(self):
        return SettlementRunDetailSerializer if self.action == "retrieve" else SettlementRunSerializer

    @extend_schema(request={"application/json": SettlementRunInput, "multipart/form-data": SettlementRunInput},
                   responses={201: SettlementRunSerializer, 200: SettlementRunSerializer})
    def create(self, request):
        """Import a day's settlement (uploaded, or fetched from the provider) and list mismatches."""
        s = SettlementRunInput(data=request.data)
        s.is_valid(raise_exception=True)
        from orders.services import _country

        c = _country(s.validated_data["country"])
        if not is_staff_for(request.user, c):
            raise Forbidden()
        f = s.validated_data.get("file")
        run = services.import_settlement(request.user, country=c, settlement_date=s.validated_data["settlement_date"],
                                         file_bytes=f.read() if f else None)
        return Response(SettlementRunSerializer(run).data, status=200 if getattr(run, "duplicate", False) else 201)


class ReconIssueViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReconIssueSerializer
    permission_classes = [STAFF]
    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "kind", "run", "payment"]

    def get_queryset(self):
        return selectors.staff_issues(self.request.user).order_by("-created_at")

    @extend_schema(request=ReconResolutionInput, responses=ReconIssueSerializer)
    @action(detail=True, methods=["post"])
    def resolution(self, request, pk=None):
        s = ReconResolutionInput(data=request.data)
        s.is_valid(raise_exception=True)
        i = services.resolve_issue(request.user, self.get_object(), s.validated_data["resolution"])
        return Response(ReconIssueSerializer(i).data)


@extend_schema(request=None, responses={200: OpenApiTypes.OBJECT}, tags=["reconciliation"])
@api_view(["POST"])
@permission_classes([STAFF])
def check_pending(request):
    """Run the 15-minute job now: ask the provider about open attempts and time out the rest."""
    return Response(services.reconcile_pending())


# ---------------------------------------------------------------- seller invoices (FR-PAY-007)


class InvoiceViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = SellerInvoiceSerializer
    lookup_value_regex = UUID_RE
    filterset_fields = ["status", "kind"]

    def get_queryset(self):
        return selectors.visible_invoices(self.request.user).order_by("-created_at")

    @extend_schema(request=SellerInvoiceCreateInput, responses={201: SellerInvoiceSerializer})
    def create(self, request):
        s = SellerInvoiceCreateInput(data=request.data)
        s.is_valid(raise_exception=True)
        d = dict(s.validated_data)
        org = get_object_or_404(Organisation, pk=d["organisation_id"])
        services._staff(request.user, org.country, ("CM", "AD"), "Only a case manager or administrator invoices.")
        person = Person.objects.filter(pk=d.get("bill_to_person")).first() if d.get("bill_to_person") else None
        inv = services.create_invoice(organisation=org, kind=d["kind"], amount=d.get("amount_amount"),
                                      currency=d.get("amount_currency"), description=d["description"],
                                      subject_type=d.get("subject_type", ""), subject_id=d.get("subject_id"),
                                      bill_to_person=person, actor=request.user, issue=d.get("issue", True))
        return Response(SellerInvoiceSerializer(inv).data, status=201)

    @extend_schema(request=None, responses=SellerInvoiceSerializer)
    @action(detail=True, methods=["post"])
    def issue(self, request, pk=None):
        inv = self.get_object()
        services._staff(request.user, inv.country, ("CM", "AD"))
        if inv.status != "draft":
            raise StateConflict("Only a draft invoice can be issued.")
        return Response(SellerInvoiceSerializer(services.issue_invoice(inv, actor=request.user)).data)

    @extend_schema(request=InvoiceVoidInput, responses=SellerInvoiceSerializer)
    @action(detail=True, methods=["post"])
    def void(self, request, pk=None):
        s = InvoiceVoidInput(data=request.data)
        s.is_valid(raise_exception=True)
        return Response(SellerInvoiceSerializer(services.void_invoice(request.user, self.get_object(),
                                                                s.validated_data["reason"])).data)

    @extend_schema(request=PaymentStartInput, responses={201: PaymentStartedSerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def payments(self, request, pk=None):
        """The seller pays a Tenmina invoice by card or mobile money through the provider."""
        inv = self.get_object()
        s = PaymentStartInput(data=request.data)
        refused = _refuse_unknown(request, s, "payment.tampered_request_refused", inv, inv.country)
        if refused:
            return refused
        s.is_valid(raise_exception=True)
        return _started(services.start_invoice_payment(inv, request.user, **s.validated_data))
