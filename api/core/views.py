"""Helpers shared by every module's API."""
from django.utils import timezone
from rest_framework import mixins, viewsets
from rest_framework.exceptions import ValidationError

from .errors import MfaRequired


def mfa_at(request):
    """When the caller last passed an MFA step-up (session or bearer token)."""
    auth = getattr(request, "auth", None)
    value = getattr(auth, "mfa_at", None)
    if value is None and hasattr(request, "session"):
        raw = request.session.get("mfa_at")
        if raw:
            value = timezone.datetime.fromisoformat(raw)
    return value


def require_mfa(request):
    from django.conf import settings

    at = mfa_at(request)
    if at is None or timezone.now() - at > settings.TENMINA["MFA_FRESHNESS"]:
        raise MfaRequired()
    return at


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
