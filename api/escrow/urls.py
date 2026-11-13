from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("escrows", views.EscrowViewSet, basename="escrow")
router.register("held-funds", views.HeldFundsViewSet, basename="held-funds")
router.register("release-instructions", views.ReleaseInstructionViewSet, basename="release-instruction")
router.register("standing-approvals", views.StandingApprovalViewSet, basename="standing-approval")
router.register("bank-events", views.BankEventViewSet, basename="bank-event")
router.register("bank-positions", views.BankPositionViewSet, basename="bank-position")
router.register("bank-statements", views.StatementViewSet, basename="bank-statement")
router.register("payees", views.PayeeViewSet, basename="payee")
router.register("payee-changes", views.PayeeChangeViewSet, basename="payee-change")
router.register("admin/programme-accounts", views.ProgrammeAccountViewSet, basename="programme-account")
router.register("admin/programme-rates", views.ProgrammeRateViewSet, basename="programme-rate")
router.register("admin/fx-observations", views.ObservationViewSet, basename="fx-observation")
router.register("fx-quotes", views.FxQuoteViewSet, basename="fx-quote")
router.register("fx-conversions", views.FxConversionViewSet, basename="fx-conversion")

urlpatterns = [
    path("payees/<uuid:payee_pk>/changes", views.PayeeChangeRequestView.as_view({"post": "create"}),
         name="payee-changes-create"),
    path("fx/comparison", views.fx_comparison, name="fx-comparison"),
    path("admin/fx-collections", views.fx_collect, name="fx-collect"),
    *router.urls,
]
