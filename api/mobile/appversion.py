"""Minimum app version (FR-APP-006, 02 section 8.10).

Every app call carries `Tenmina-App: <app>/<platform>/<version>`, for example
`field/android/1.4.0` or `client/ios/2.0.1`. When the version is below the
minimum for that app and platform, the API answers 426 app-version-unsupported.
Evidence captured before the minimum was raised is still accepted for 30 days,
so an update never loses queued evidence.

Minimums are administration settings (FeatureFlag values) named
`app.min_version.<app>.<platform>`; the row's update time is when it was raised.
"""
import re
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone

from core.errors import DomainError

HEADER = "Tenmina-App"
GRACE_DAYS = 30  # [TO VERIFY] document 06 section 3.5
APPS = ("field", "client")
PLATFORMS = ("android", "ios")
DEFAULT_STORE_URLS = {"android": "https://play.google.com/store/apps/details?id=com.tenmina.{app} [TO VERIFY]",
                      "ios": "https://apps.apple.com/app/tenmina-{app} [TO VERIFY]"}
# Calls that carry evidence captured earlier: the view applies the grace rule with the signed capture time.
GRACE_PATHS = ("/v1/mobile/evidence", "/v1/mobile/check-ins", "/v1/mobile/check-outs")
OPEN_PATHS = ("/v1/mobile/app-config", "/v1/schema", "/v1/docs", "/v1/auth/")


def parse(value: str | None):
    if not value:
        return None
    parts = value.strip().split("/")
    if len(parts) != 3:
        return None
    app, platform, version = parts[0].lower(), parts[1].lower(), parts[2]
    if app not in APPS or platform not in PLATFORMS:
        return None
    return app, platform, version


def vtuple(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-+]", v or "0")[:3])


def _flag(name):
    from administration.models import FeatureFlag

    return FeatureFlag.objects.filter(name=name, country__isnull=True).first()


def minimum(app: str, platform: str):
    f = _flag(f"app.min_version.{app}.{platform}")
    if not f or not f.value:
        return None, None
    return f.value, f.updated_at


def config(app: str, platform: str, version: str | None = None) -> dict:
    from administration import flags

    minv, raised = minimum(app, platform)
    latest = flags.setting(f"app.latest_version.{app}.{platform}", default=minv or "")
    url = flags.setting(f"app.store_url.{app}.{platform}", default=DEFAULT_STORE_URLS[platform].format(app=app))
    return {
        "app": app, "platform": platform, "min_version": minv or "", "latest_version": latest or "",
        "min_raised_at": raised, "store_url": url,
        "update_required": bool(version and minv and vtuple(version) < vtuple(minv)),
        "update_available": bool(version and latest and vtuple(version) < vtuple(latest)),
        "fee_payment_mode": flags.setting("app.fee_payment_mode", default="web"),
    }


def problem(app, platform, minv):
    return DomainError(
        "Please update Tenmina from the store. Anything waiting to upload stays safe on your phone.",
        code="app-version-unsupported", status=426, title="This version of the app is too old",
        extra={"min_version": minv, "store_url": config(app, platform)["store_url"]})


def enforce(request, captured_at=None):
    """Raise 426 if the calling app is too old. `captured_at` (signed device time) lets items
    captured before the minimum was raised through for GRACE_DAYS."""
    info = parse(request.headers.get(HEADER))
    if info is None:
        return
    app, platform, version = info
    minv, raised = minimum(app, platform)
    if not minv or vtuple(version) >= vtuple(minv):
        return
    if captured_at is not None and raised is not None and captured_at < raised \
            and timezone.now() < raised + timedelta(days=GRACE_DAYS):
        return
    raise problem(app, platform, minv)


class AppVersionMiddleware:
    """Checks the Tenmina-App header on every /v1/ call. Add to settings.MIDDLEWARE after
    AuthenticationMiddleware; mobile views also check it themselves."""

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
                                     "instance": path, **exc.extra}, status=exc.status,
                                    content_type="application/problem+json")
        return self.get_response(request)
