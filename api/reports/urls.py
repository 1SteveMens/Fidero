from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("reports", views.ReportViewSet, basename="report")
router.register("rechecks", views.RecheckViewSet, basename="recheck")
router.register("report-incidents", views.IncidentViewSet, basename="report-incident")

urlpatterns = [
    path("report-verifications", views.ReportVerificationView.as_view()),
    *router.urls,
]
