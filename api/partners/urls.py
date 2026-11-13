from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("partner-orders", views.ClientPartnerOrderViewSet, basename="ptr-client-order")
router.register("admin/partner-clients", views.ApiClientViewSet, basename="ptr-api-client")

# The partner API lives at /v1/partner/... (02 7.4 writes /partner/v1; every module mounts under /v1/).
urlpatterns = [
    path("partner/oauth/token", views.TokenView.as_view()),
    path("partner/plot-status-queries", views.PlotStatusView.as_view()),
    path("partner/reports/<uuid:report_id>", views.ReportView.as_view()),
    path("partner/orders", views.OrdersView.as_view()),
    path("partner/orders/<uuid:order_id>", views.OrderView.as_view()),
    path("partner/usage", views.UsageView.as_view()),
    path("partner/webhooks", views.WebhooksView.as_view()),
    path("partner/webhooks/<uuid:webhook_id>", views.WebhookView.as_view()),
    path("partner-directory", views.directory),
    path("admin/partner-webhook-deliveries", views.deliver_webhooks),
    *router.urls,
]
