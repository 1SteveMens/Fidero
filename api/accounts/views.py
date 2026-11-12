from django.conf import settings
from django.contrib.auth import login, logout
from django.middleware.csrf import get_token
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from core.errors import DomainError, Invalid

from . import services
from .models import ApiToken
from .serializers import PersonSerializer, RegisterSerializer

T = settings.TENMINA


def _tokens(person, request, mfa_at=None):
    access, _ = ApiToken.issue(person, "access", T["ACCESS_TOKEN_TTL"], mfa_at=mfa_at,
                               app=request.headers.get("Tenmina-App", ""))
    refresh, _ = ApiToken.issue(person, "refresh", T["REFRESH_TOKEN_TTL"], app=request.headers.get("Tenmina-App", ""))
    return {"access": access, "refresh": refresh, "expires_in": int(T["ACCESS_TOKEN_TTL"].total_seconds())}


@extend_schema(request=None, responses={200: dict})
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def csrf(request):
    """Sets the csrftoken cookie for the web apps."""
    return Response({"csrf_token": get_token(request)})


@extend_schema(request=RegisterSerializer, responses={201: PersonSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register(request):
    s = RegisterSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    p = services.register(**s.validated_data)
    if request.data.get("mode") == "token":
        return Response({"person": PersonSerializer(p).data, **_tokens(p, request)}, status=201)
    login(request, p, backend="django.contrib.auth.backends.ModelBackend")
    return Response(PersonSerializer(p).data, status=201)


@extend_schema(request=dict, responses={200: PersonSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def session_login(request):
    """Web sign-in. If MFA is on, `code` is required and counts as a step-up."""
    p = services.check_credentials(request, request.data.get("email"), request.data.get("password"))
    if p.mfa_enabled:
        code = request.data.get("code")
        if not code:
            raise DomainError("Enter the code from your authenticator app.", code="mfa-required", status=401)
        if not services.mfa_verify(p, code):
            raise Invalid("That code is not right.", code="mfa-invalid")
    login(request, p, backend="django.contrib.auth.backends.ModelBackend")
    if p.mfa_enabled:
        request.session["mfa_at"] = timezone.now().isoformat()
    return Response(PersonSerializer(p).data)


@extend_schema(request=None, responses={204: None})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def session_logout(request):
    logout(request)
    return Response(status=204)


@extend_schema(request=dict, responses={200: dict})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def token(request):
    """Mobile sign-in: returns access and refresh bearer tokens."""
    p = services.check_credentials(request, request.data.get("email"), request.data.get("password"))
    mfa_at = None
    if p.mfa_enabled:
        code = request.data.get("code")
        if not code:
            raise DomainError("Enter the code from your authenticator app.", code="mfa-required", status=401)
        if not services.mfa_verify(p, code):
            raise Invalid("That code is not right.", code="mfa-invalid")
        mfa_at = timezone.now()
    return Response({"person": PersonSerializer(p).data, **_tokens(p, request, mfa_at)})


@extend_schema(request=dict, responses={200: dict})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def refresh(request):
    raw = request.data.get("refresh", "")
    tok = ApiToken.objects.filter(token_hash=ApiToken.hash(raw), kind="refresh", revoked_at__isnull=True).first()
    if not tok or tok.expires_at < timezone.now():
        raise DomainError("Sign in again.", code="unauthenticated", status=401)
    tok.revoked_at = timezone.now()  # rotate
    tok.save(update_fields=["revoked_at"])
    return Response(_tokens(tok.person, request))


@extend_schema(request=PersonSerializer, responses={200: PersonSerializer})
@api_view(["GET", "PATCH"])
def me(request):
    if request.method == "PATCH":
        s = PersonSerializer(request.user, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
    return Response(PersonSerializer(request.user).data)


@extend_schema(request=None, responses={200: dict})
@api_view(["POST"])
def mfa_setup(request):
    uri = services.mfa_setup(request.user)
    return Response({"otpauth_uri": uri, "secret": request.user.mfa_secret})


@extend_schema(request=dict, responses={200: dict})
@api_view(["POST"])
def mfa_confirm(request):
    if not services.mfa_verify(request.user, request.data.get("code", "")):
        raise Invalid("That code is not right.", code="mfa-invalid")
    request.user.mfa_enabled = True
    request.user.save(update_fields=["mfa_enabled"])
    return _stepped_up(request)


@extend_schema(request=dict, responses={200: dict})
@api_view(["POST"])
def mfa_step_up(request):
    """Fresh MFA for an approval (6.3). Valid for 5 minutes."""
    if not request.user.mfa_enabled:
        raise DomainError("Set up an authenticator app first.", code="mfa-not-set-up", status=409)
    if not services.mfa_verify(request.user, request.data.get("code", "")):
        raise Invalid("That code is not right.", code="mfa-invalid")
    return _stepped_up(request)


def _stepped_up(request):
    now = timezone.now()
    if isinstance(request.auth, ApiToken):
        request.auth.mfa_at = now
        request.auth.save(update_fields=["mfa_at"])
    else:
        request.session["mfa_at"] = now.isoformat()
    return Response({"mfa_at": now.isoformat(), "valid_for_seconds": int(T["MFA_FRESHNESS"].total_seconds())},
                    status=status.HTTP_200_OK)
