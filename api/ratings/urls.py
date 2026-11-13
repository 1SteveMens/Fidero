from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.register("ratings", views.RatingViewSet, basename="rating")
router.register("rating-opportunities", views.OpportunityViewSet, basename="rating-opportunity")
router.register("track-records", views.TrackRecordViewSet, basename="track-record")

urlpatterns = router.urls
