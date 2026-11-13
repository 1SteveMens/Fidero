from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("insurance/insurers", views.InsurerViewSet, basename="ins-insurer")
router.register("insurance/intermediary-licences", views.LicenceViewSet, basename="ins-licence")
router.register("insurance/products", views.ProductViewSet, basename="ins-product")
router.register("insurance/applications", views.ApplicationViewSet, basename="ins-application")
router.register("insurance/policies", views.PolicyViewSet, basename="ins-policy")
router.register("insurance/premiums", views.PremiumViewSet, basename="ins-premium")
router.register("insurance/claims", views.ClaimViewSet, basename="ins-claim")

urlpatterns = router.urls
