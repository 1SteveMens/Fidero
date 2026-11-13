from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("care-plans", views.CarePlanViewSet, basename="care-plan")
router.register("carers", views.CarerViewSet, basename="carer")
router.register("care-visits", views.VisitViewSet, basename="care-visit")
router.register("care-payment-batches", views.PaymentBatchViewSet, basename="care-payment-batch")
router.register("concerns", views.ConcernViewSet, basename="concern")
router.register("mobile/visits", views.FieldVisitViewSet, basename="mobile-visit")

urlpatterns = [*router.urls]
