from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("uploads", views.UploadViewSet, basename="upload")
router.register("evidence", views.EvidenceViewSet, basename="evidence")
router.register("integrity-runs", views.IntegrityRunViewSet, basename="integrity-run")
router.register("integrity-incidents", views.IntegrityIncidentViewSet, basename="integrity-incident")

urlpatterns = [
    path("evidence-files/<str:token>", views.EvidenceFileView.as_view()),
    path("evidence-access-logs", views.SubjectAccessLogView.as_view()),
    path("fingerprint-checks", views.FingerprintCheckView.as_view()),
    *router.urls,
]
