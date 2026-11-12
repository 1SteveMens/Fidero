"""Idempotency-Key handling for POST (7.1). Same key and body returns the
stored response; same key with a different body is 422."""
import hashlib
import json

from django.db import IntegrityError, transaction
from rest_framework.response import Response

from .models import IdempotencyKey


def _principal(request):
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return str(user.pk)
    return "anon:" + hashlib.sha256(request.META.get("REMOTE_ADDR", "").encode()).hexdigest()[:16]


def idempotent(view_func):
    """Decorator for DRF action methods: @idempotent def create(self, request)."""

    def wrapper(self, request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key")
        if not key or request.method != "POST":
            return view_func(self, request, *args, **kwargs)
        principal = _principal(request)
        h = hashlib.sha256(json.dumps(request.data, sort_keys=True, default=str).encode()).hexdigest()
        stored = IdempotencyKey.objects.filter(principal=principal, key=key).first()
        if stored:
            if stored.request_hash != h:
                from .errors import Invalid

                raise Invalid("This Idempotency-Key was used with a different request.", code="idempotency-key-reuse")
            if stored.response_code:
                return Response(stored.response_body, status=stored.response_code)
        response = view_func(self, request, *args, **kwargs)
        if response.status_code < 500:
            try:
                with transaction.atomic():
                    IdempotencyKey.objects.update_or_create(
                        principal=principal, key=key,
                        defaults={"request_hash": h, "response_code": response.status_code,
                                  "response_body": json.loads(json.dumps(response.data, default=str))},
                    )
            except IntegrityError:
                pass
        return response

    wrapper.__name__ = view_func.__name__
    wrapper.__doc__ = view_func.__doc__
    return wrapper
