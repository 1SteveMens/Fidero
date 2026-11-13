"""Authentication classes. Imported by DRF settings while the kernel loads,
so model and kernel imports stay inside functions."""
from django.utils import timezone
from rest_framework import authentication, exceptions

# Paths a person who must use MFA may reach before enrolling (FR-ACC-003).
ENROLMENT_PATHS = ("/v1/auth/", "/v1/me", "/v1/privacy-notices")
INACTIVE = ("suspended", "closed", "anonymised")


def enforce_mfa_enrolment(request, person):
    """US-ACC-003, TC-ACC-003-02: staff, professionals and approvers without
    an authenticator get 403 everywhere except sign-in and enrolment."""
    if person.mfa_enabled:
        return
    from .services import mfa_required

    if not mfa_required(person):
        return
    if request.path.startswith(ENROLMENT_PATHS):
        return
    from core.errors import DomainError  # lazy: DRF imports this module while core.errors loads

    raise DomainError("Set up your authenticator app before you continue.", code="mfa-enrolment-required",
                      status=403)


class BearerTokenAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).decode()
        if not header.startswith(self.keyword + " "):
            return None
        raw = header[len(self.keyword) + 1:].strip()
        from .models import ApiToken  # lazy: DRF loads this module while core.errors is importing

        tok = ApiToken.objects.select_related("person").filter(token_hash=ApiToken.hash(raw), kind="access").first()
        if not tok or tok.revoked_at or tok.expires_at < timezone.now():
            raise exceptions.AuthenticationFailed("Your session has expired. Sign in again.")
        if not tok.person.is_active or tok.person.deleted_at or tok.person.status in INACTIVE:
            raise exceptions.AuthenticationFailed("This account is not active.")
        enforce_mfa_enrolment(request, tok.person)
        return tok.person, tok

    def authenticate_header(self, request):
        return self.keyword


class CsrfSessionAuthentication(authentication.SessionAuthentication):
    """Session cookie plus X-CSRFToken for the two web apps (7.1)."""

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None
        person = result[0]
        if person.status in INACTIVE:
            raise exceptions.AuthenticationFailed("This account is not active.")
        enforce_mfa_enrolment(request, person)
        return result
