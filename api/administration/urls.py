from django.urls import path

from . import views

urlpatterns = [
    path("admin/config-versions", views.ConfigVersionList.as_view()),
    path("admin/config-versions/<uuid:pk>", views.ConfigVersionDetail.as_view()),
    path("admin/config-versions/<uuid:pk>/publish", views.ConfigVersionPublish.as_view()),
    path("admin/config-versions/<uuid:pk>/retire", views.ConfigVersionRetire.as_view()),
    path("admin/prices", views.PriceAdmin.as_view()),
    path("admin/fx-rates", views.FxRateAdmin.as_view()),
    path("fx-guides", views.FxGuides.as_view()),
    path("admin/partners", views.PartnerList.as_view()),
    path("admin/partners/<uuid:pk>", views.PartnerDetail.as_view()),
    path("admin/partners/<uuid:pk>/bank-changes", views.PartnerBankChange.as_view()),
    path("admin/partners/<uuid:pk>/deactivate", views.PartnerDeactivate.as_view()),
    path("admin/partners/<uuid:pk>/reactivate", views.PartnerReactivate.as_view()),
    path("admin/locked-texts/<str:kind>/versions", views.LockedTextVersions.as_view()),
    path("admin/locked-texts/<str:kind>/versions/<uuid:pk>", views.LockedTextDetail.as_view()),
    path("admin/locked-texts/<str:kind>/versions/<uuid:pk>/signoffs", views.LockedTextSignoff.as_view()),
    path("admin/locked-texts/<str:kind>/versions/<uuid:pk>/submit", views.LockedTextSubmit.as_view()),
    path("admin/locked-texts/<str:kind>/versions/<uuid:pk>/approvals", views.LockedTextApprovals.as_view()),
    path("legal-texts/<str:kind>/current", views.LegalTextCurrent.as_view()),
    path("admin/settings", views.SettingList.as_view()),
    path("admin/settings/<str:key>", views.SettingDetail.as_view()),
    path("admin/change-requests", views.ChangeRequestList.as_view()),
    path("admin/change-requests/<uuid:pk>", views.ChangeRequestDetail.as_view()),
    path("admin/change-requests/<uuid:pk>/approvals", views.ChangeRequestApprovals.as_view()),
    path("admin/change-requests/<uuid:pk>/withdraw", views.ChangeRequestWithdraw.as_view()),
    path("admin/feature-flags", views.FeatureFlagList.as_view()),
    path("admin/feature-flags/changes", views.FeatureFlagChange.as_view()),
    path("admin/app-versions", views.AppVersionAdmin.as_view()),
    path("app-config", views.AppConfig.as_view()),
]
