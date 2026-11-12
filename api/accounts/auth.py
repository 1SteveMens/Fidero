from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiToken


class BearerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode()
        if not header.startswith(self.keyword + " "):
            return None
        raw = header[len(self.keyword) + 1:].strip()
        tok = ApiToken.objects.select_related("person").filter(token_hash=ApiToken.hash(raw), kind="access").first()
        if not tok or tok.revoked_at or tok.expires_at < timezone.now():
            raise exceptions.AuthenticationFailed("Your session has expired. Sign in again.")
        if not tok.person.is_active or tok.person.deleted_at:
            raise exceptions.AuthenticationFailed("This account is not active.")
        return tok.person, tok

    def authenticate_header(self, request):
        return self.keyword


class CsrfSessionAuthentication(authentication.SessionAuthentication):
    """Session cookie plus X-CSRFToken for the two web apps (7.1)."""
