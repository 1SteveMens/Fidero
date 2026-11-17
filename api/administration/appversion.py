"""Minimum app version (FR-APP-006, 02 section 8.10): the one source.

The app version settings (`adm_app_version`, one row per app and platform)
are the only source of the minimum and latest version and the store link.
`mobile.appversion` applies them to every /v1 request that carries the
`Tenmina-App` header (`<app>/<platform>/<version>`, for example
`field/ios/1.4.0`); GET /v1/app-config and GET /v1/mobile/app-config both
answer from `config(...)` below. DRF-independent: call `check(...)` from any
code path.

Evidence captured before the minimum was raised is still accepted for
GRACE_DAYS after the raise, so an update never loses queued evidence.
"""
from datetime import timedelta

from django.utils import timezone

from core.errors import DomainError

GRACE_DAYS = 30  # [TO VERIFY], document 06 section 3.5
HEADER = "Tenmina-App"
APPS = ("client", "field")
PLATFORMS = ("ios", "android")
DEFAULT_STORE_URLS = {"android": "https://play.google.com/store/apps/details?id=com.tenmina.{app} [TO VERIFY]",
                      "ios": "https://apps.apple.com/app/tenmina-{app} [TO VERIFY]"}


class AppVersionUnsupported(DomainError):
    status = 426
    code = "app-version-unsupported"
    title = "Update the app to continue"


def parse_header(value: str | None):
    """'field/ios/1.4.0' -> ('field', 'ios', '1.4.0'); None when malformed."""
    parts = [p.strip().lower() for p in (value or "").split("/")]
    if len(parts) != 3 or not all(parts):
        return None
    return parts[0], parts[1], parts[2]


def status(app: str, platform: str, version: str) -> dict:
    from .models import AppVersion
    from .services import parse_version

    av = AppVersion.objects.filter(app=app, platform=platform).first()
    if av is None:
        return {"supported": True, "min_version": None, "latest_version": None, "store_url": "",
                "update_available": False}
    v = parse_version(version)
    return {
        "supported": v >= parse_version(av.min_version),
        "min_version": av.min_version, "latest_version": av.latest_version, "store_url": av.store_url,
        "update_available": v < parse_version(av.latest_version or "0"),
        "min_raised_at": av.min_raised_at, "previous_min_version": av.previous_min_version,
    }


def config(app: str, platform: str, version: str | None = None, country=None) -> dict:
    """What an app needs at start (GET /v1/app-config, GET /v1/mobile/app-config): minimum and latest version,
    store link and how fees are paid (FR-APP-005, FR-APP-006)."""
    from .models import AppVersion
    from .services import fee_payment_mode, parse_version

    av = AppVersion.objects.filter(app=app, platform=platform).first()
    minv = av.min_version if av else ""
    latest = (av.latest_version if av else "") or minv
    v = parse_version(version) if version else None
    return {
        "app": app, "platform": platform, "version": version or "", "min_version": minv, "latest_version": latest,
        "min_raised_at": av.min_raised_at if av else None,
        "store_url": (av.store_url if av and av.store_url else DEFAULT_STORE_URLS[platform].format(app=app)),
        "update_required": bool(v is not None and minv and v < parse_version(minv)),
        "update_available": bool(v is not None and latest and v < parse_version(latest)),
        "fee_payment_mode": fee_payment_mode(country, platform),
    }


def check(header: str | None = None, *, app=None, platform=None, version=None, captured_at=None) -> None:
    """Raise AppVersionUnsupported (426) when the app is below the minimum.

    `captured_at`: the signed capture time of an evidence item being uploaded.
    An item captured before the minimum was raised, by an install that met the
    previous minimum, is accepted for GRACE_DAYS after the raise."""
    if header:
        parsed = parse_header(header)
        if parsed is None:
            return
        app, platform, version = parsed
    if not (app and platform and version):
        return
    st = status(app, platform, version)
    if st["supported"]:
        return
    raised = st.get("min_raised_at")
    if captured_at is not None and raised is not None and captured_at < raised \
            and timezone.now() - raised <= timedelta(days=GRACE_DAYS):
        from .services import parse_version

        if not st["previous_min_version"] or parse_version(version) >= parse_version(st["previous_min_version"]):
            return
    raise AppVersionUnsupported(
        f"This version of the app is too old. Update to {st['min_version']} or later. Anything waiting to upload "
        "stays safe on your phone.",
        extra={"min_version": st["min_version"],
               "store_url": st["store_url"] or DEFAULT_STORE_URLS.get(platform, "").format(app=app)})
