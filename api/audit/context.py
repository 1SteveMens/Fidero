"""Request origin for audit entries (FR-AUD-001: who, when, what and from where).

The origin of the current request is kept in a context variable. It is set
from Django's `request_started` signal (connected in AuditConfig.ready), so
no settings change is needed. `AuditContextMiddleware` does the same with
the resolved trace id and may be added to settings later.
"""
import contextvars
import logging

_origin = contextvars.ContextVar("tenmina_audit_origin", default=None)
_deferred = contextvars.ContextVar("tenmina_audit_deferred", default=None)
log = logging.getLogger("tenmina.security")


def defer(fn):
    """Run fn after the request has finished, in its own transaction.

    A refused request rolls back everything it wrote (ATOMIC_REQUESTS), but a
    refusal that must be logged (cross-country access, a wrong confirmation
    code) has to survive that. Outside a request, fn runs at once."""
    pending = _deferred.get()
    if pending is None:
        fn()
    else:
        pending.append(fn)


def run_deferred():
    from django.db import transaction

    pending = _deferred.get() or []
    _deferred.set(None)
    for fn in pending:
        try:
            with transaction.atomic():
                fn()
        except Exception:  # noqa: BLE001 - never break the response for a log write
            log.exception("deferred audit write failed")


def set_origin(ip="", user_agent="", trace_id=""):
    _origin.set({"ip": (ip or "")[:64], "user_agent": (user_agent or "")[:300], "trace_id": trace_id or ""})


def clear():
    _origin.set(None)


def current() -> dict:
    return _origin.get() or {"ip": "", "user_agent": "", "trace_id": ""}


def _trace_from(traceparent: str) -> str:
    parts = (traceparent or "").split("-")
    return parts[1] if len(parts) == 4 and len(parts[1]) == 32 else ""


def on_request_started(sender, environ=None, scope=None, **kwargs):
    _deferred.set([])
    if environ is not None:
        ip = environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or environ.get("REMOTE_ADDR", "")
        set_origin(ip, environ.get("HTTP_USER_AGENT", ""), _trace_from(environ.get("HTTP_TRACEPARENT", "")))
    elif scope is not None:
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        client = scope.get("client") or ("", 0)
        ip = headers.get("x-forwarded-for", "").split(",")[0].strip() or client[0]
        set_origin(ip, headers.get("user-agent", ""), _trace_from(headers.get("traceparent", "")))


def on_request_finished(sender, **kwargs):
    run_deferred()
    clear()


class AuditContextMiddleware:
    """Optional: place after core.middleware.TraceMiddleware to record the
    trace id the API returns. Not registered in settings by this module."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
        set_origin(ip, request.META.get("HTTP_USER_AGENT", ""), getattr(request, "trace_id", ""))
        return self.get_response(request)
