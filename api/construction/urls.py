from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("projects", views.ProjectViewSet, basename="project")
router.register("milestones", views.MilestoneViewSet, basename="milestone")
router.register("inspections", views.InspectionViewSet, basename="inspection")
router.register("defects", views.DefectViewSet, basename="defect")
router.register("variations", views.VariationViewSet, basename="variation")
router.register("panel-members", views.PanelMemberViewSet, basename="panel-member")
router.register("project-payments", views.PaymentViewSet, basename="project-payment")
router.register("materials-orders", views.MaterialsOrderViewSet, basename="materials-order")

urlpatterns = [*router.urls]
