from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("consents", views.ConsentViewSet, basename="consent")
router.register("dpr/privacy-notices", views.PrivacyNoticeViewSet, basename="dpr-privacy-notice")
router.register("dpr/requests", views.DataRequestViewSet, basename="dpr-request")
router.register("dpr/retention-rules", views.RetentionRuleViewSet, basename="dpr-retention-rule")
router.register("dpr/retention-runs", views.RetentionRunViewSet, basename="dpr-retention-run")
router.register("dpr/legal-holds", views.LegalHoldViewSet, basename="dpr-legal-hold")
router.register("dpr/bulk-exports", views.BulkExportViewSet, basename="dpr-bulk-export")
router.register("dpr/data-catalogue", views.DataCatalogueViewSet, basename="dpr-data-catalogue")
router.register("dpr/data-locations", views.DataLocationViewSet, basename="dpr-data-location")

urlpatterns = [
    path("privacy-notices/current", views.current_notice),
    path("me/privacy-acceptances", views.my_privacy_acceptances),
    path("me/deletion-requests/preview", views.deletion_preview),
    path("me/deletion-requests", views.my_deletion_requests),
    path("me/data-requests", views.my_data_requests),
    *router.urls,
]
