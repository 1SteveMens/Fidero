from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("errands", views.ErrandViewSet, basename="errand")
router.register("errand-agents", views.AgentViewSet, basename="errand-agent")
router.register("mobile/errands", views.FieldErrandViewSet, basename="mobile-errand")

urlpatterns = [
    path("errand-catalogue", views.CatalogueView.as_view()),
    *router.urls,
]
