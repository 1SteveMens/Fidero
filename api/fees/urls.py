from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("institutions", views.InstitutionViewSet, basename="fee-institution")
router.register("invoices", views.InvoiceViewSet, basename="fee-invoice")
router.register("fee-payments", views.PaymentViewSet, basename="fee-payment")
router.register("fee-schedules", views.ScheduleViewSet, basename="fee-schedule")
router.register("fee-plans", views.PlanViewSet, basename="fee-plan")
router.register("fee-runner-tasks", views.RunnerTaskViewSet, basename="fee-runner-task")
router.register("family-members", views.FamilyStatementViewSet, basename="fee-family-member")

urlpatterns = router.urls
