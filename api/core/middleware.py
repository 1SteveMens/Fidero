import uuid

from django.conf import settings


class TraceMiddleware:
    """Accept and return W3C traceparent; expose request.trace_id (7.1)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tp = request.headers.get("traceparent", "")
        parts = tp.split("-")
        request.trace_id = parts[1] if len(parts) == 4 and len(parts[1]) == 32 else uuid.uuid4().hex
        response = self.get_response(request)
        response["traceparent"] = f"00-{request.trace_id}-{uuid.uuid4().hex[:16]}-01"
        return response


class CorsMiddleware:
    """Minimal CORS for the local portal, back office and Expo web builds."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        origin = request.headers.get("Origin")
        allowed = origin and origin in settings.CORS_ALLOWED_ORIGINS
        if request.method == "OPTIONS" and allowed:
            from django.http import HttpResponse

            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)
        if allowed:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Credentials"] = "true"
            response["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, X-CSRFToken, Idempotency-Key, If-Match, Tenmina-App, traceparent"
            )
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            response["Access-Control-Expose-Headers"] = "ETag, traceparent"
        return response
