from django.urls import path

from . import views

urlpatterns = [
    path("audit-events", views.AuditEventList.as_view()),
    path("audit-events/verify", views.ChainVerify.as_view()),
    path("audit-events/trails/<str:entity>/<str:entity_id>", views.TrailExport.as_view()),
    path("audit-chain-checks", views.ChainCheckList.as_view()),
    path("audit-anchors", views.AnchorList.as_view()),
    path("audit-anchors/new", views.AnchorCreate.as_view()),
    path("security-alerts", views.SecurityAlertList.as_view()),
    path("security-alerts/<uuid:pk>/acknowledge", views.SecurityAlertAcknowledge.as_view()),
]
