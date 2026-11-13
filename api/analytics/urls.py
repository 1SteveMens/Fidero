from django.urls import path

from . import views

urlpatterns = [
    path("analytics/catalogue", views.CatalogueView.as_view(), name="analytics-catalogue"),
    path("analytics/metrics", views.DashboardView.as_view(), name="analytics-dashboard"),
    path("analytics/metrics/<str:name>", views.MetricView.as_view(), name="analytics-metric"),
    path("analytics/review", views.ReviewView.as_view(), name="analytics-review"),
    path("analytics/exports", views.ExportView.as_view(), name="analytics-exports"),
]
