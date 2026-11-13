from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("me/pro/payables", views.MyPayableViewSet, basename="pro-my-payable")
router.register("me/pro/expense-claims", views.MyExpenseViewSet, basename="pro-my-expense")
router.register("me/pro/statements", views.MyStatementViewSet, basename="pro-my-statement")
router.register("admin/pro/agreements", views.AgreementViewSet, basename="pro-agreement")
router.register("admin/pro/rate-cards", views.RateCardViewSet, basename="pro-rate-card")
router.register("pro/payables", views.PayableViewSet, basename="pro-payable")
router.register("pro/expense-claims", views.ExpenseViewSet, basename="pro-expense")
router.register("pro/payment-runs", views.PaymentRunViewSet, basename="pro-payment-run")
router.register("pro/payment-lines", views.PaymentLineViewSet, basename="pro-payment-line")

urlpatterns = [
    path("me/pro/agreement", views.my_agreement),
    path("me/pro/jobs", views.my_jobs),
    path("admin/pro/scopes", views.scopes),
    path("pro/runner-months/<uuid:agreement_id>/<str:month>/close", views.close_runner_month),
    path("pro/cost-per-case", views.cost_per_case),
    path("pro/statements", views.generate_statements),
    path("pro/overdue-checks", views.overdue_check),
    *router.urls,
]
