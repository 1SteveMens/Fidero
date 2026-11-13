from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("events", views.EventViewSet, basename="event")
router.register("event-vendors", views.VendorViewSet, basename="event-vendor")
router.register("vendor-payments", views.VendorPaymentViewSet, basename="vendor-payment")

urlpatterns = [*router.urls]
