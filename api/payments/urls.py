from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("payments", views.PaymentViewSet, basename="payment")
router.register("receipts", views.ReceiptViewSet, basename="receipt")
router.register("offline-payments", views.OfflinePaymentViewSet, basename="offline-payment")
router.register("refunds", views.RefundViewSet, basename="refund")
router.register("reconciliation/runs", views.SettlementRunViewSet, basename="settlement-run")
router.register("reconciliation/issues", views.ReconIssueViewSet, basename="recon-issue")
router.register("seller-invoices", views.InvoiceViewSet, basename="seller-invoice")

urlpatterns = [
    path("orders/<uuid:order_id>/payments", views.OrderPaymentsView.as_view()),
    path("hooks/payments", views.PaymentWebhookView.as_view()),
    path("reconciliation/pending-checks", views.check_pending),
    *router.urls,
]
