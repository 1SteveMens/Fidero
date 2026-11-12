from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from core.views_health import health

# Every module mounts its own routes under /v1/ from <module>/urls.py.
module_urls = [path("", include(f"{m}.urls")) for m in settings.TENMINA_MODULES]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("health", health),
    path("v1/schema", SpectacularAPIView.as_view(), name="schema"),
    path("v1/docs", SpectacularSwaggerView.as_view(url_name="schema")),
    path("v1/", include(module_urls)),
]
