from django.urls import path

from . import views

urlpatterns = [
    path("countries", views.PublicCountries.as_view()),
    path("countries/metrics", views.CountryMetrics.as_view()),
    path("directory/lookups", views.DirectoryLookup.as_view()),
    path("admin/countries", views.CountryList.as_view()),
    path("admin/countries/<str:ref>", views.CountryDetail.as_view()),
    path("admin/countries/<str:ref>/manual-phase", views.ManualPhase.as_view()),
    path("admin/countries/<str:ref>/validation", views.Validation.as_view()),
    path("admin/countries/<str:ref>/pause", views.Pause.as_view()),
    path("admin/countries/<str:ref>/gate-decision", views.GateDecision.as_view()),
    path("admin/countries/<str:ref>/activation", views.Activation.as_view()),
    path("admin/countries/<str:ref>/activation/approvals", views.ActivationApprovals.as_view()),
    path("admin/countries/<str:ref>/config-versions", views.ConfigVersions.as_view()),
    path("admin/countries/<str:ref>/config-versions/<int:v>", views.ConfigVersionDetail.as_view()),
    path("admin/countries/<str:ref>/config-versions/<int:v>/submit", views.ConfigSubmit.as_view()),
    path("admin/countries/<str:ref>/config-versions/<int:v>/approvals", views.ConfigApprovals.as_view()),
    path("admin/countries/<str:ref>/config-versions/<int:v>/retire", views.ConfigRetire.as_view()),
    path("admin/cells", views.CellList.as_view()),
    path("admin/cells/<uuid:pk>", views.CellDetail.as_view()),
    path("admin/data-locations", views.DataLocations.as_view()),
]
