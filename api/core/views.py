"""Helpers shared by every module's API."""
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError

from .errors import MfaRequired

SEARCH = OpenApiParameter("search", str, description="Part of a name or reference (the back office pickers use it).")


def search(qs, request, *fields):
    """Filter a list by `?search=`: case-insensitive match on any of `fields`.
    Only narrows what the caller may already see."""
    q = (request.query_params.get("search") or "").strip()
    if not q:
        return qs
    cond = Q()
    for f in fields:
        cond |= Q(**{f"{f}__icontains": q})
    return qs.filter(cond).distinct()


def mfa_at(request):
    """When the caller last passed an MFA step-up (session or bearer token).

    Returns a `core.mfa.MfaAt`, which also carries the method ("totp" or
    "device_biometric") so approvals record how the person stepped up."""
    from .mfa import MfaAt

    auth = getattr(request, "auth", None)
    value = getattr(auth, "mfa_at", None)
    method = getattr(auth, "mfa_method", "") if value is not None else ""
    if value is None and hasattr(request, "session"):
        raw = request.session.get("mfa_at")
        if raw:
            value = timezone.datetime.fromisoformat(raw)
            method = request.session.get("mfa_method", "")
    return MfaAt.of(value, method or "totp") if value is not None else None


def require_mfa(request):
    from django.conf import settings

    at = mfa_at(request)
    if at is None or timezone.now() - at > settings.TENMINA["MFA_FRESHNESS"]:
        raise MfaRequired()
    return at


def search_filter(qs, request, *fields, min_length=2):
    """`?search=` on a staff picker list (the back office people pickers): at least `min_length` characters,
    matched case-insensitively against any of `fields`. No term: the list as it is."""
    from django.db.models import Q

    from .errors import Invalid

    term = (request.query_params.get("search") or "").strip()
    if not term:
        return qs
    if len(term) < min_length:
        raise Invalid(f"Type at least {min_length} characters to search.", code="search-too-short")
    q = Q()
    for f in fields:
        q |= Q(**{f"{f}__icontains": term})
    return qs.filter(q).distinct()


def body(request, *fields, optional=()):
    """Read required fields from request.data, 400 if any is missing."""
    missing = [f for f in fields if request.data.get(f) in (None, "")]
    if missing:
        raise ValidationError({f: "This field is required." for f in missing})
    return [request.data.get(f) for f in fields] + [request.data.get(f) for f in optional]


class ETagMixin:
    """ETag from row_version on retrieve; If-Match checked on state actions (7.1)."""

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        obj = getattr(self, "_etag_obj", None)
        if obj is not None and hasattr(obj, "row_version"):
            response["ETag"] = f'"{obj.row_version}"'
        return response

    def get_object(self):
        obj = super().get_object()
        self._etag_obj = obj
        im = self.request.headers.get("If-Match")
        if im and self.request.method not in ("GET", "HEAD") and im.strip('"') != str(obj.row_version):
            from rest_framework.exceptions import APIException

            exc = APIException("The object changed since you loaded it. Reload and try again.")
            exc.status_code = 412
            raise exc
        return obj


class ReadOnlyViewSet(ETagMixin, viewsets.ReadOnlyModelViewSet):
    pass


class ModelViewSet(ETagMixin, viewsets.ModelViewSet):
    pass


class CreateListRetrieveViewSet(ETagMixin, mixins.CreateModelMixin, mixins.ListModelMixin,
                                mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    pass
