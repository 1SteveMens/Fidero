"""OpenAPI security schemes for the two authentication classes, so the
generated clients of the four front ends know how to sign requests."""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class BearerTokenScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.auth.BearerTokenAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "description": "Access token from /v1/auth/token (apps)."}


class SessionCookieScheme(OpenApiAuthenticationExtension):
    target_class = "accounts.auth.CsrfSessionAuthentication"
    name = "cookieAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "cookie", "name": "sessionid",
                "description": "Session cookie from /v1/auth/login, with X-CSRFToken on writes (web)."}
