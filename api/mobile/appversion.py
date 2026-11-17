"""Minimum app version on every call (FR-APP-006, 02 section 8.10).

Every app call carries `Tenmina-App: <app>/<platform>/<version>`, for example
`field/android/1.4.0` or `client/ios/2.0.1`. When the version is below the
minimum for that app and platform, the API answers 426 app-version-unsupported.
Evidence captured before the minimum was raised is still accepted for the grace
period, so an update never loses queued evidence.

There is one source: administration's app version settings (`adm_app_version`,
`administration.appversion`), which administrators change in the back office
(raising a minimum needs a second administrator). This module only applies
them to requests: the middleware below, the field views and
GET /v1/mobile/app-config all read them through administration.
"""
from django.http import JsonResponse

from administration import appversion as source
from core.errors import DomainError

HEADER = source.HEADER
APPS = tuple(source.APPS)
PLATFORMS = tuple(source.PLATFORMS)
# Calls that carry evidence captured earlier: the view applies the grace rule with the signed capture time.
GRACE_PATHS = ("/v1/mobile/evidence", "/v1/mobile/check-ins", "/v1/mobile/check-outs")
OPEN_PATHS = ("/v1/mobile/app-config", "/v1/app-config", "/v1/schema", "/v1/docs", "/v1/auth/", "/v1/hooks/")


def parse(value: str | None):
    """'field/android/1.4.0' -> ('field', 'android', '1.4.0'); None when malformed or unknown."""
    parsed = source.parse_header(value)
    if parsed is None or parsed[0] not in APPS or parsed[1] not in PLATFORMS:
        return None
    return parsed


def config(app: str, platform: str, version: str | None = None, country=None) -> dict:
    return source.config(app, platform, version, country=country)


def enforce(request, captured_at=None):
    """Raise 426 if the calling app is too old. `captured_at` (signed device time) lets items captured before
    the minimum was raised through for the grace period."""
    source.check(request.headers.get(HEADER), captured_at=captured_at)


class AppVersionMiddleware:
    """Checks the Tenmina-App header on every /v1/ call (registered in settings.MIDDLEWARE after
    AuthenticationMiddleware); mobile views also check it themselves."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path
        if path.startswith("/v1/") and not path.startswith(OPEN_PATHS + GRACE_PATHS):
            try:
                enforce(request)
            except DomainError as exc:
                return JsonResponse({"type": f"https://api.tenmina/problems/{exc.code}", "title": exc.title,
                                     "status": exc.status, "detail": exc.detail, "code": exc.code,
                                     "instance": path, "trace_id": getattr(request, "trace_id", None),
                                     **exc.extra}, status=exc.status, content_type="application/problem+json")
        return self.get_response(request)
