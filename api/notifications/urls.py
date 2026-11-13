from django.urls import path

from . import views

urlpatterns = [
    path("me/notifications", views.Inbox.as_view()),
    path("me/notifications/unread-count", views.UnreadCount.as_view()),
    path("me/notifications/read-all", views.MarkAllRead.as_view()),
    path("me/notifications/<uuid:pk>/read", views.MarkRead.as_view()),
    path("me/notification-preferences", views.Preferences.as_view()),
    path("me/push-devices", views.PushDevices.as_view()),
    path("me/push-devices/<uuid:pk>", views.PushDeviceDetail.as_view()),
    path("admin/messages", views.MessageLog.as_view()),
    path("admin/messages/<uuid:pk>", views.MessageLogDetail.as_view()),
    path("admin/notification-templates", views.Templates.as_view()),
    path("admin/notification-templates/catalogue", views.TemplateCatalogue.as_view()),
    path("admin/notification-templates/preview", views.TemplatePreview.as_view()),
    path("admin/confirmation-codes", views.ConfirmationList.as_view()),
    path("admin/confirmation-codes/<uuid:pk>/call-records", views.ConfirmationCallRecord.as_view()),
    path("admin/confirmation-codes/<uuid:pk>/call-checks", views.ConfirmationCallCheck.as_view()),
    path("me/confirmations", views.MyConfirmations.as_view()),
    path("me/confirmations/<uuid:pk>/disputes", views.MyConfirmationDispute.as_view()),
    path("family-confirmations/codes", views.ConfirmByCode.as_view()),
    path("family-confirmations/<str:token>", views.PublicConfirmation.as_view()),
    path("hooks/messaging", views.DeliveryHook.as_view()),
    path("hooks/messaging/replies", views.ReplyHook.as_view()),
]
