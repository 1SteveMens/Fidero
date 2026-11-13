from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("mobile/devices", views.DeviceViewSet, basename="mobile-device")
router.register("mobile/evidence", views.FieldItemViewSet, basename="mobile-evidence")
router.register("mobile/submissions", views.SubmissionViewSet, basename="mobile-submission")
router.register("mobile/fraud-flags", views.FraudFlagViewSet, basename="mobile-fraud-flag")
router.register("mobile/assignments", views.AssignmentViewSet, basename="mobile-assignment")

urlpatterns = [
    path("mobile/app-config", views.AppConfigView.as_view()),
    path("mobile/sync", views.SyncView.as_view()),
    path("mobile/inbox", views.InboxView.as_view()),
    path("mobile/inspections", views.InspectionView.as_view()),
    path("mobile/check-ins", views.CheckInView.as_view()),
    path("mobile/check-outs", views.CheckOutView.as_view()),
    *router.urls,
]
