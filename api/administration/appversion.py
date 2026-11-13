"""Minimum app version check (FR-APP-006, 02 section 8.10).

DRF-independent: call `check(...)` from any code path, or add
`administration.middleware.AppVersionMiddleware` to settings to apply it to
every /v1 request that carries the `Tenmina-App` header
(`<app>/<platform>/<version>`, for example `field/ios/1.4.0`).

Evidence captured before the minimum was raised is still accepted for
GRACE_DAYS after the raise, so an update never loses queued evidence.
"""
from datetime import timedelta

from django.utils import timezone

from core.errors import DomainError

GRACE_DAYS = 30  # [TO VERIFY], document 06 section 3.5


class AppVersionUnsupported(DomainError):
    status = 426
    code = "app-version-unsupported"
    title = "Update the app to continue"


def parse_header(value: str):
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
        f"This version of the app is too old. Update to {st['min_version']} or later.",
        extra={"min_version": st["min_version"], "store_url": st["store_url"]})
