"""GEO routes, mounted under /v1/ (02 section 7.4)."""
from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("assets", views.AssetViewSet, basename="geo-asset")
router.register("asset-access-grants", views.AccessGrantViewSet, basename="geo-access-grant")
router.register("overlap-flags", views.OverlapFlagViewSet, basename="geo-overlap-flag")
router.register("satellite-images", views.SatelliteImageViewSet, basename="geo-satellite-image")
router.register("monitoring/enrolments", views.MonitoringEnrolmentViewSet, basename="geo-enrolment")
router.register("monitoring/runs", views.MonitoringRunViewSet, basename="geo-monitoring-run")
router.register("monitoring-alerts", views.MonitoringAlertViewSet, basename="geo-monitoring-alert")
router.register("admin/overlay-layers", views.OverlayLayerViewSet, basename="geo-overlay-layer")
router.register("admin/overlay-layer-versions", views.LayerVersionViewSet, basename="geo-overlay-layer-version")
router.register("admin/geo/country-extents", views.CountryExtentViewSet, basename="geo-country-extent")

urlpatterns = [
    path("geo/map", views.area_map),
    path("geo/ghana-post/<str:code>", views.ghana_post),
    *router.urls,
]
