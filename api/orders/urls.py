from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("orders", views.OrderViewSet, basename="order")
router.register("referral-codes", views.ReferralCodeViewSet, basename="referral-code")
router.register("referral-rewards", views.ReferralRewardViewSet, basename="referral-reward")

urlpatterns = [
    path("catalogue/products", views.products),
    path("catalogue/tiers", views.tiers),
    path("catalogue/terms", views.terms),
    path("catalogue/lead-sources", views.lead_source_options),
    path("orders/lead-sources", views.lead_source_summary),
    path("projects/<uuid:project_id>/extra-inspections", views.extra_inspection),
    path("me/referral-code", views.my_referral_code),
    *router.urls,
]
