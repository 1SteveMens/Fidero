from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("managed-properties", views.PropertyViewSet, basename="managed-property")
router.register("statement-mandates", views.MandateViewSet, basename="statement-mandate")
router.register("tenancies", views.TenancyViewSet, basename="tenancy")
router.register("rent-periods", views.RentPeriodViewSet, basename="rent-period")
router.register("pmg-inspections", views.InspectionViewSet, basename="pmg-inspection")
router.register("repairs", views.RepairViewSet, basename="repair")
router.register("repair-quotes", views.QuoteViewSet, basename="repair-quote")

urlpatterns = [
    path("pmg-jobs/rent-watch", views.run_rent_watch, name="pmg-rent-watch"),
    path("pmg-jobs/inspection-schedule", views.run_inspection_schedule, name="pmg-inspection-schedule"),
    *router.urls,
]
