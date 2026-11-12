"""RFC 9457 problem responses (document 02, 7.2).

Raise DomainError (or a subclass) from services; the API turns it into
application/problem+json with a stable `code`.
"""
from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_handler


class DomainError(Exception):
    status = 409
    code = "state-conflict"
    title = "The request conflicts with the current state"

    def __init__(self, detail="", *, code=None, status=None, title=None, blocking_reasons=None, extra=None):
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        if code:
            self.code = code
        if status:
            self.status = status
        if title:
            self.title = title
        self.blocking_reasons = blocking_reasons or []
        self.extra = extra or {}


class StateConflict(DomainError):
    pass


class RuleBlocked(DomainError):
    """A business rule (RUL-xx) blocks the action. Give blocking_reasons as
    [{"rule": "RUL-06", "message": "..."}]."""

    code = "release-blocked"
    title = "The action is blocked by a rule"


class SameApprover(DomainError):
    code = "same-approver"
    title = "A different person must approve"


class PayeeNotVerified(DomainError):
    code = "payee-not-verified"
    title = "The payee is not verified"


class Invalid(DomainError):
    status = 422
    code = "validation-error"
    title = "The request is not valid"


class Forbidden(DomainError):
    status = 403
    code = "forbidden"
    title = "You do not have permission for this"


class NotFound(DomainError):
    status = 404
    code = "not-found"
    title = "Not found"


class MfaRequired(DomainError):
    status = 401
    code = "mfa-required"
    title = "Confirm with your authenticator code first"


class FeatureOff(DomainError):
    status = 404
    code = "feature-off"
    title = "This service is not open yet"


def _problem(status, code, title, detail, request, **extra):
    body = {
        "type": f"https://api.tenmina/problems/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "code": code,
        "instance": request.path if request else None,
        "trace_id": getattr(request, "trace_id", None) if request else None,
    }
    body.update({k: v for k, v in extra.items() if v not in (None, [], {})})
    return Response(body, status=status, content_type="application/problem+json")


def problem_exception_handler(exc, context):
    request = context.get("request")
    if isinstance(exc, DomainError):
        return _problem(exc.status, exc.code, exc.title, exc.detail, request,
                        blocking_reasons=exc.blocking_reasons, **exc.extra)
    if isinstance(exc, DjangoValidationError):
        exc = drf.ValidationError(exc.message_dict if hasattr(exc, "message_dict") else exc.messages)
    if isinstance(exc, Http404):
        exc = drf.NotFound()
    if isinstance(exc, PermissionDenied):
        exc = drf.PermissionDenied()
    response = drf_handler(exc, context)
    if response is None:
        return None
    if isinstance(exc, drf.ValidationError):
        errors = []

        def walk(data, path):
            if isinstance(data, dict):
                for k, v in data.items():
                    walk(v, f"{path}/{k}")
            elif isinstance(data, list) and data and not isinstance(data[0], str):
                for i, v in enumerate(data):
                    walk(v, f"{path}/{i}")
            else:
                msgs = data if isinstance(data, list) else [data]
                for m in msgs:
                    errors.append({"pointer": path or "/", "message": str(m)})

        walk(exc.detail, "")
        return _problem(400, "validation-error", "Some fields need attention", "See errors.", request, errors=errors)
    code = {
        401: "unauthenticated", 403: "forbidden", 404: "not-found", 405: "method-not-allowed",
        412: "precondition-failed", 429: "rate-limited",
    }.get(response.status_code, "error")
    detail = response.data.get("detail") if isinstance(response.data, dict) else str(response.data)
    return _problem(response.status_code, code, str(detail), str(detail), request)
