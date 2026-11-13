from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("cases", views.CaseViewSet, basename="case")
router.register("tasks", views.TaskViewSet, basename="task")
router.register("document-requests", views.DocumentRequestViewSet, basename="document-request")
router.register("parties", views.PartyViewSet, basename="case-party")
router.register("search-requests", views.SearchRequestViewSet, basename="search-request")
router.register("safety-incidents", views.SafetyIncidentViewSet, basename="safety-incident")
router.register("safety-readers", views.SafetyReaderViewSet, basename="safety-reader")

urlpatterns = [
    path("work-queue", views.work_queue),
    path("assets/<uuid:asset_id>/fresh-searches", views.fresh_searches),
    path("cost-per-report", views.cost_per_report),
    *router.urls,
]
