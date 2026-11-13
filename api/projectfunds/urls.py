from django.urls import path

from . import views

urlpatterns = [
    path("projects/<uuid:pk>/suppliers", views.ProjectSuppliers.as_view()),
    path("projects/<uuid:pk>/background-checks", views.ProjectChecks.as_view()),
    path("projects/<uuid:pk>/aml-review", views.ProjectAml.as_view()),
    path("projects/<uuid:pk>/agreement", views.ProjectAgreement.as_view()),
    path("projects/<uuid:pk>/invoices", views.ProjectInvoices.as_view()),
    path("projects/<uuid:pk>/funding", views.ProjectFunding.as_view()),
    path("project-suppliers/<uuid:pk>", views.SupplierDetail.as_view()),
    path("project-suppliers/<uuid:pk>/payee", views.SupplierPayee.as_view()),
    path("background-checks/<uuid:pk>/result", views.CheckResult.as_view()),
    path("aml-reviews/<uuid:pk>/decision", views.AmlDecision.as_view()),
    path("project-invoices/<uuid:pk>", views.InvoiceDetail.as_view()),
    path("project-invoices/<uuid:pk>/decision", views.InvoiceDecision.as_view()),
    path("project-stages/<uuid:pk>/closure", views.StageClosure.as_view()),
]
