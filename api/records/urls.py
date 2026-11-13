from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("records/authorities", views.AuthorityViewSet, basename="rec-authority")
router.register("records/allocations", views.AllocationViewSet, basename="rec-allocation")
router.register("records/overlaps", views.OverlapViewSet, basename="rec-overlap")
router.register("records/matches", views.MatchViewSet, basename="rec-match")
router.register("records/revenue-shares", views.RevenueShareViewSet, basename="rec-revenue-share")

urlpatterns = [*router.urls]
