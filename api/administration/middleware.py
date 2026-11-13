"""Optional middleware for FR-APP-006. Not registered by this module: add
"administration.middleware.AppVersionMiddleware" to settings.MIDDLEWARE after
core.middleware.TraceMiddleware to enforce the minimum app version on every
/v1 call that carries a Tenmina-App header."""
from django.http import JsonResponse

from .appversion import AppVersionUnsupported, check

EXEMPT_PREFIXES = ("/v1/app-config", "/v1/schema", "/v1/docs", "/v1/hooks/")


class AppVersionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = request.headers.get("Tenmina-App")
        if header and request.path.startswith("/v1/") and not request.path.startswith(EXEMPT_PREFIXES):
            try:
                check(header)
            except AppVersionUnsupported as exc:
                return JsonResponse(
                    {"type": f"https://api.tenmina/problems/{exc.code}", "title": exc.title, "status": exc.status,
                     "detail": exc.detail, "code": exc.code, "instance": request.path,
                     "trace_id": getattr(request, "trace_id", None), **exc.extra},
                    status=exc.status, content_type="application/problem+json")
        return self.get_response(request)
