"""Partner API bearer tokens (OAuth 2.0 client credentials, 5.6). Used only on
/v1/partner/... views; a person's session or token never works there."""
from rest_framework import authentication, exceptions


class PartnerPrincipal:
    """request.user on partner calls: the API client, not a person."""

    is_authenticated = True
    is_anonymous = False
    is_active = True

    def __init__(self, client):
        self.client = client
        self.pk = self.id = client.pk

    def has_tenmina_role(self, *roles, country=None):
        return False

    def __str__(self):
        return f"partner:{self.client.client_id}"


class PartnerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode()
        if not header.startswith(self.keyword + " "):
            return None
        from core.errors import DomainError

        from .services import authenticate

        try:
            tok = authenticate(header[len(self.keyword) + 1:].strip())
        except DomainError as exc:
            raise exceptions.AuthenticationFailed(exc.detail) from exc
        return PartnerPrincipal(tok.client), tok

    def authenticate_header(self, request):
        return 'Bearer realm="partner"'


try:  # OpenAPI: the partner API's own bearer scheme (02 7.8 `partnerOAuth`)
    from drf_spectacular.extensions import OpenApiAuthenticationExtension

    class PartnerOAuthScheme(OpenApiAuthenticationExtension):
        target_class = "partners.auth.PartnerTokenAuthentication"
        name = "partnerOAuth"

        def get_security_definition(self, auto_schema):
            return {"type": "oauth2", "flows": {"clientCredentials": {
                "tokenUrl": "/v1/partner/oauth/token",
                "scopes": {"plot_status.read": "Plot status", "report.read": "Full report with consent",
                           "orders.write": "Order verifications", "usage.read": "Metered usage",
                           "webhooks.manage": "Webhook subscriptions"}}}}
except ImportError:  # pragma: no cover
    pass
