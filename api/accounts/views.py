"""ACC API (02 section 7.4): sign-up, sign-in, MFA, profile, home dashboard,
organisations, roles and rights, invitations, licences, identity checks,
national identity checks, representatives, family members, bank accounts
and vetting."""
from django.conf import settings
from django.contrib.auth import login, logout
from django.db import transaction
from django.db.models import Q
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response

from core.errors import DomainError, Forbidden, Invalid
from core.idempotency import idempotent
from core.permissions import has_role, roles
from core.views import ModelViewSet, require_mfa

from . import home as home_registry
from . import selectors, services
from .models import (ApiToken, BankAccount, FamilyMember, IdentityCheck, Invitation, Membership, NationalIdCheck,
                     Organisation, Person, ProfessionalLicence, RepresentativeGrant, RightsRequest, RoleGrant, Vetting)
from .serializers import (AcceptInvitationSerializer, AddMemberResultSerializer, AddMemberSerializer,
                          AdminPersonSerializer, BankAccountSerializer, BankVerificationSerializer, CodeSerializer,
                          CsrfSerializer, DecisionSerializer, DetailSerializer, FamilyMemberSerializer,
                          GrantRoleSerializer, HomeSerializer, IdentityCheckSerializer, InvitationSerializer,
                          LicenceSerializer, LoginSerializer, ManualCheckSerializer, MembershipSerializer,
                          MfaSetupResultSerializer, MfaStepUpResultSerializer, NationalIdCheckSerializer,
                          OrganisationSerializer, OtpSendSerializer, OtpVerifyResultSerializer, OtpVerifySerializer,
                          PasswordChangeSerializer, PasswordResetConfirmSerializer, PasswordResetSerializer,
                          PersonSerializer, ReasonSerializer, RefreshSerializer, RegisterSerializer,
                          RepresentativeSerializer,
                          RequestNationalIdCheckSerializer, RightsRequestSerializer, RoleGrantSerializer,
                          SignupResultSerializer, SignupSerializer, StaffPortalResultSerializer,
                          StartIdentityCheckSerializer, TokenPairSerializer, VettingSerializer)

T = settings.TENMINA
NEUTRAL = {"detail": "If the details are right, we have sent a code."}


def _tokens(person, request, mfa_at=None):
    access, _ = ApiToken.issue(person, "access", T["ACCESS_TOKEN_TTL"], mfa_at=mfa_at,
                               app=request.headers.get("Tenmina-App", ""))
    refresh, _ = ApiToken.issue(person, "refresh", T["REFRESH_TOKEN_TTL"], app=request.headers.get("Tenmina-App", ""))
    return {"access": access, "refresh": refresh, "expires_in": int(T["ACCESS_TOKEN_TTL"].total_seconds())}


def _ip(request):
    return request.META.get("REMOTE_ADDR", "")


def _valid(serializer_cls, request, **kw):
    s = serializer_cls(data=request.data, context={"request": request}, **kw)
    s.is_valid(raise_exception=True)
    return s.validated_data


def _second_factor(request, p):
    """MFA at sign-in. A wrong code counts towards the lockout."""
    if not p.mfa_enabled:
        return None
    code = request.data.get("code")
    if not code:
        raise DomainError("Enter the code from your authenticator app.", code="mfa-required", status=401)
    if not services.mfa_verify(p, code):
        services._count_failure(p)
        raise Invalid("That code is not right.", code="mfa-invalid")
    return timezone.now()


# ---------------------------------------------------------------- auth

@extend_schema(request=None, responses={200: CsrfSerializer})
@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def csrf(request):
    """Sets the csrftoken cookie for the web apps."""
    return Response({"csrf_token": get_token(request)})


@extend_schema(request=SignupSerializer, responses={201: SignupResultSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def signup(request):
    """US-ACC-001, US-DPR-001: sign up, accept the privacy notice; a one-time
    code goes to the email and to the phone. The account stays unverified
    until both codes are entered at /v1/auth/otp/verify."""
    d = _valid(SignupSerializer, request)
    d.pop("mode", None)
    p = services.register(**d, ip=_ip(request))
    return Response({"person": PersonSerializer(p).data, "verification": {"email": "sent", "phone": "sent"}},
                    status=201)


@extend_schema(request=RegisterSerializer, responses={201: PersonSerializer}, deprecated=True)
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def register_legacy(request):
    """Deprecated: use /v1/auth/signup. The phone is optional here, the account
    cannot sign in until its email is confirmed by code, and the privacy
    notice is asked for at sign-in when not accepted here."""
    d = _valid(RegisterSerializer, request)
    p = services.register(**d, ip=_ip(request), legacy=True)
    return Response(PersonSerializer(p).data, status=201)


@extend_schema(request=OtpSendSerializer, responses={202: DetailSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def otp_send(request):
    """Send a sign-up or sign-in code. The answer is the same whether or not
    the account exists."""
    d = _valid(OtpSendSerializer, request)
    channel = d.get("channel") or ("email" if "@" in d["identifier"] else "phone")
    if d["purpose"] == "signup":
        services.send_signup_code(d["identifier"], channel)
    else:
        services.send_login_code(d["identifier"], channel)
    return Response(NEUTRAL, status=202)


@extend_schema(request=OtpVerifySerializer, responses={200: OtpVerifyResultSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def otp_verify(request):
    d = _valid(OtpVerifySerializer, request)
    p = services.verify_signup_code(d["identifier"], d["channel"], d["code"])
    out = {"email_verified": bool(p.email_verified_at), "phone_verified": bool(p.phone_verified_at),
           "verified": p.is_verified}
    if p.is_verified and p.is_active:
        out["person"] = PersonSerializer(p).data
        if d.get("mode") == "token":
            out.update(_tokens(p, request))
        else:
            login(request, p, backend="django.contrib.auth.backends.ModelBackend")
    return Response(out)


otp_verify = transaction.non_atomic_requests(otp_verify)


@extend_schema(request=LoginSerializer, responses={200: PersonSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def session_login(request):
    """US-ACC-002, US-ACC-009: web sign-in with email or phone and a password
    or a one-time code. If MFA is on, `code` is required and counts as a
    step-up."""
    d = _valid(LoginSerializer, request)
    p = services.check_credentials(request, d["identifier"], d.get("password"), otp=d.get("otp"),
                                   channel=d.get("channel"))
    at = _second_factor(request, p)
    login(request, p, backend="django.contrib.auth.backends.ModelBackend")
    if at:
        request.session["mfa_at"] = at.isoformat()
    return Response(PersonSerializer(p).data)


session_login = transaction.non_atomic_requests(session_login)


@extend_schema(request=None, responses={204: None})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def session_logout(request):
    if isinstance(getattr(request, "auth", None), ApiToken):
        request.auth.revoked_at = timezone.now()
        request.auth.save(update_fields=["revoked_at"])
    raw = request.data.get("refresh") if hasattr(request, "data") else None
    if raw:
        ApiToken.objects.filter(token_hash=ApiToken.hash(raw), revoked_at__isnull=True).update(
            revoked_at=timezone.now())
    logout(request)
    return Response(status=204)


@extend_schema(request=LoginSerializer, responses={200: TokenPairSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def token(request):
    """Mobile sign-in for both apps: access and refresh bearer tokens."""
    d = _valid(LoginSerializer, request)
    p = services.check_credentials(request, d["identifier"], d.get("password"), otp=d.get("otp"),
                                   channel=d.get("channel"))
    at = _second_factor(request, p)
    return Response({"person": PersonSerializer(p).data, **_tokens(p, request, at)})


token = transaction.non_atomic_requests(token)


@extend_schema(request=RefreshSerializer, responses={200: TokenPairSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def refresh(request):
    raw = request.data.get("refresh", "")
    tok = ApiToken.objects.filter(token_hash=ApiToken.hash(raw), kind="refresh").first()
    if tok and tok.revoked_at:
        # Reuse of a rotated refresh token: revoke every token of the person (10.3).
        services.revoke_tokens(tok.person)
        raise DomainError("Sign in again.", code="unauthenticated", status=401)
    if not tok or tok.expires_at < timezone.now() or tok.person.status in ("suspended", "closed", "anonymised"):
        raise DomainError("Sign in again.", code="unauthenticated", status=401)
    tok.revoked_at = timezone.now()  # rotate
    tok.save(update_fields=["revoked_at"])
    return Response(_tokens(tok.person, request))


@extend_schema(request=PasswordResetSerializer, responses={202: DetailSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def password_reset(request):
    d = _valid(PasswordResetSerializer, request)
    services.request_password_reset(d["identifier"], d.get("channel"))
    return Response(NEUTRAL, status=202)


@extend_schema(request=PasswordResetConfirmSerializer, responses={200: DetailSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def password_reset_confirm(request):
    d = _valid(PasswordResetConfirmSerializer, request)
    services.confirm_password_reset(d["identifier"], d["code"], d["new_password"], d.get("channel"))
    return Response({"detail": "Your password is changed. Sign in with the new password."})


password_reset_confirm = transaction.non_atomic_requests(password_reset_confirm)


@extend_schema(request=PasswordChangeSerializer, responses={200: DetailSerializer})
@api_view(["POST"])
def password_change(request):
    d = _valid(PasswordChangeSerializer, request)
    services.change_password(request.user, d["old_password"], d["new_password"])
    return Response({"detail": "Your password is changed."})


@extend_schema(request=AcceptInvitationSerializer, responses={200: PersonSerializer})
@api_view(["POST"])
@permission_classes([permissions.AllowAny])
def accept_invitation(request):
    """US-ACC-006: the single-use link creates the account and its roles."""
    d = _valid(AcceptInvitationSerializer, request)
    p = services.accept_invitation(**d, ip=_ip(request))
    return Response(PersonSerializer(p).data)


@extend_schema(request=None, responses={200: MfaSetupResultSerializer})
@api_view(["POST"])
def mfa_setup(request):
    uri = services.mfa_setup(request.user)
    return Response({"otpauth_uri": uri, "secret": request.user.mfa_secret})


@extend_schema(request=CodeSerializer, responses={200: MfaStepUpResultSerializer})
@api_view(["POST"])
def mfa_confirm(request):
    if not services.mfa_verify(request.user, request.data.get("code", "")):
        raise Invalid("That code is not right.", code="mfa-invalid")
    services.mfa_confirm(request.user)
    return _stepped_up(request)


@extend_schema(request=CodeSerializer, responses={200: MfaStepUpResultSerializer})
@api_view(["POST"])
def mfa_step_up(request):
    """Fresh MFA for an approval (6.3). Valid for 5 minutes."""
    if not request.user.mfa_enabled:
        raise DomainError("Set up an authenticator app first.", code="mfa-not-set-up", status=409)
    if not services.mfa_verify(request.user, request.data.get("code", "")):
        raise Invalid("That code is not right.", code="mfa-invalid")
    return _stepped_up(request)


@extend_schema(request=CodeSerializer, responses={204: None})
@api_view(["POST"])
def mfa_disable(request):
    """Clients may switch MFA off with a current code; staff, professionals
    and approvers never can (FR-ACC-003)."""
    if not services.mfa_verify(request.user, request.data.get("code", "")):
        raise Invalid("That code is not right.", code="mfa-invalid")
    services.disable_mfa(request.user, request.user)
    return Response(status=204)


def _stepped_up(request):
    now = timezone.now()
    if isinstance(request.auth, ApiToken):
        request.auth.mfa_at = now
        request.auth.save(update_fields=["mfa_at"])
    else:
        request.session["mfa_at"] = now.isoformat()
    return Response({"mfa_at": now.isoformat(), "valid_for_seconds": int(T["MFA_FRESHNESS"].total_seconds())},
                    status=status.HTTP_200_OK)


@extend_schema(methods=["GET"], responses=PersonSerializer)
@extend_schema(methods=["PATCH"], request=PersonSerializer, responses=PersonSerializer)
@api_view(["GET", "PATCH"])
def me(request):
    """Profile, language and notification preferences (FR-ACC-010)."""
    if request.method == "PATCH":
        s = PersonSerializer(request.user, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        services.update_profile(request.user, dict(s.validated_data))
    return Response(PersonSerializer(request.user).data)


@extend_schema(responses=HomeSerializer)
@api_view(["GET"])
def home(request):
    """US-ACC-012: everything the client has running at home."""
    p = request.user
    items = home_registry.items_for(p)
    return Response({"person": PersonSerializer(p).data,
                     "family_members": FamilyMemberSerializer(selectors.family_members_of(p), many=True).data,
                     "items": items, "needs_action_count": sum(1 for i in items if i["needs_action"])})


# ---------------------------------------------------------------- organisations (US-ACC-011)

class OrganisationViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          mixins.UpdateModelMixin, viewsets.GenericViewSet):
    serializer_class = OrganisationSerializer
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Organisation.objects.none()
        u = self.request.user
        if has_role(u, "CM", "RV", "AD"):
            return selectors.scope_to_staff_countries(Organisation.objects.all(), u).order_by("-created_at")
        return selectors.organisations_of(u).order_by("-created_at")

    def perform_create(self, serializer):
        d = dict(serializer.validated_data)
        org = services.create_organisation(self.request.user, name=d.pop("name"), kind=d.pop("kind"),
                                           country=d.pop("country"), **d)
        serializer.instance = org

    def perform_update(self, serializer):
        org = serializer.instance
        if not (services.is_org_admin(self.request.user, org) or has_role(self.request.user, "AD")):
            raise Forbidden("Only an administrator of this organisation changes its details.")
        locked = ("kind", "country") if has_role(self.request.user, "AD") else (
            "name", "kind", "country", "registration_number")
        for k in locked:
            serializer.validated_data.pop(k, None)
        serializer.save()

    @extend_schema(methods=["GET"], responses=MembershipSerializer(many=True))
    @extend_schema(methods=["POST"], request=AddMemberSerializer, responses={201: AddMemberResultSerializer})
    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        org = self.get_object()
        if request.method == "GET":
            qs = Membership.objects.filter(organisation=org, status="active").select_related("person")
            return Response(MembershipSerializer(qs, many=True).data)
        d = _valid(AddMemberSerializer, request)
        m, inv = services.add_member(org, request.user, **d)
        return Response({"membership": MembershipSerializer(m).data if m else None,
                         "invitation_id": inv.pk if inv else None}, status=201)

    @extend_schema(request=None, responses={200: MembershipSerializer})
    @action(detail=True, methods=["delete"], url_path=r"members/(?P<membership_id>[0-9a-f-]+)")
    def remove_member(self, request, pk=None, membership_id=None):
        org = self.get_object()
        m = get_object_or_404(Membership, pk=membership_id, organisation=org)
        services.remove_member(m, request.user, request.data.get("reason", "") if request.data else "")
        return Response(MembershipSerializer(m).data)


# ---------------------------------------------------------------- administration of people (US-ACC-006)

class AdminPeopleViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AdminPersonSerializer
    permission_classes = [roles("AD")]

    @extend_schema(parameters=[OpenApiParameter("role", str), OpenApiParameter("q", str)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Person.objects.none()
        qs = Person.objects.all().order_by("-created_at")
        role = self.request.query_params.get("role")
        if role:
            qs = qs.filter(role_grants__role=role, role_grants__revoked_at__isnull=True).distinct()
        q = self.request.query_params.get("q")
        if q:
            qs = qs.filter(Q(full_name__icontains=q) | Q(email__icontains=q) | Q(phone__icontains=q))
        return qs

    @extend_schema(request=GrantRoleSerializer, responses={201: RoleGrantSerializer})
    @action(detail=True, methods=["post"])
    def roles(self, request, pk=None):
        p = self.get_object()
        d = _valid(GrantRoleSerializer, request)
        g = services.admin_grant_role(request.user, p, d.pop("role"), **d)
        return Response(RoleGrantSerializer(g).data, status=201)

    @extend_schema(request=ReasonSerializer, responses=AdminPersonSerializer)
    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        p = self.get_object()
        services.suspend_person(p, request.user, request.data.get("reason", ""))
        return Response(AdminPersonSerializer(p).data)

    @extend_schema(request=None, responses=AdminPersonSerializer)
    @action(detail=True, methods=["post"])
    def reactivate(self, request, pk=None):
        p = self.get_object()
        services.reactivate_person(p, request.user)
        return Response(AdminPersonSerializer(p).data)

    @extend_schema(request=None, responses=AdminPersonSerializer)
    @action(detail=True, methods=["post"], url_path="mfa-disable")
    def mfa_disable(self, request, pk=None):
        """Refused for staff, professionals and approvers (US-ACC-003 AC3)."""
        p = self.get_object()
        services.disable_mfa(p, request.user)
        return Response(AdminPersonSerializer(p).data)


class RoleGrantViewSet(viewsets.GenericViewSet):
    serializer_class = RoleGrantSerializer
    permission_classes = [roles("AD")]
    queryset = RoleGrant.objects.all()

    @extend_schema(request=ReasonSerializer, responses=RoleGrantSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        g = self.get_object()
        services.revoke_grant(g, request.user, request.data.get("reason", ""))
        return Response(RoleGrantSerializer(g).data)


class InvitationViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                        viewsets.GenericViewSet):
    """Administrators invite staff and professionals; a case manager invites
    a seller to a named case (FR-ACC-006)."""

    serializer_class = InvitationSerializer
    permission_classes = [roles("AD", "CM")]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Invitation.objects.none()
        qs = Invitation.objects.all().order_by("-created_at")
        if not has_role(self.request.user, "AD"):
            qs = qs.filter(invited_by=self.request.user)
        return qs

    @idempotent
    def create(self, request, *args, **kwargs):
        d = _valid(InvitationSerializer, request)
        inv, _ = services.invite(by=request.user, email=d["email"], roles=d.get("roles") or [],
                                 full_name=d.get("full_name", ""), country=d.get("country"),
                                 organisation=d.get("organisation"), case_id=d.get("case_id"))
        return Response(InvitationSerializer(inv).data, status=201)

    @extend_schema(request=None, responses=InvitationSerializer)
    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        inv = self.get_object()
        services.revoke_invitation(inv, request.user)
        return Response(InvitationSerializer(inv).data)


class RightsRequestViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                           viewsets.GenericViewSet):
    """Release rights and payment rights: one administrator asks, two other
    administrators approve with MFA (01 C2, 02 10.4)."""

    serializer_class = RightsRequestSerializer
    permission_classes = [roles("AD")]
    queryset = RightsRequest.objects.select_related("person", "approval_request").order_by("-created_at")

    @idempotent
    def create(self, request, *args, **kwargs):
        d = _valid(RightsRequestSerializer, request)
        rr = services.request_rights(by=request.user, person=d["person"], right=d["right"],
                                     country=d.get("country"), reason=d.get("reason", ""))
        return Response(RightsRequestSerializer(rr).data, status=201)

    @extend_schema(request=DecisionSerializer, responses=RightsRequestSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def approvals(self, request, pk=None):
        rr = self.get_object()
        d = _valid(DecisionSerializer, request)
        services.decide_rights(rr, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                               note=d.get("note", ""))
        rr.refresh_from_db()
        return Response(RightsRequestSerializer(rr).data)

    @extend_schema(request=None, responses=RightsRequestSerializer)
    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        rr = self.get_object()
        services.withdraw_rights_request(rr, request.user)
        return Response(RightsRequestSerializer(rr).data)


# ---------------------------------------------------------------- licences (US-ACC-005)

class LicenceViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                     viewsets.GenericViewSet):
    serializer_class = LicenceSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ProfessionalLicence.objects.none()
        u = self.request.user
        qs = ProfessionalLicence.objects.select_related("person").order_by("-created_at")
        if has_role(u, "AD", "RV", "CM"):
            qs = selectors.scope_to_staff_countries(qs, u)
            person = self.request.query_params.get("person")
            return qs.filter(person_id=person) if person else qs
        return qs.filter(person=u)

    @idempotent
    def create(self, request, *args, **kwargs):
        d = _valid(LicenceSerializer, request)
        person = d.pop("person", None) or request.user
        lic = services.add_licence(request.user, person, **d)
        return Response(LicenceSerializer(lic).data, status=201)


class AdminLicenceViewSet(viewsets.GenericViewSet):
    serializer_class = LicenceSerializer
    permission_classes = [roles("AD", "RV")]
    queryset = ProfessionalLicence.objects.all()

    @extend_schema(request=None, responses=LicenceSerializer)
    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        lic = self.get_object()
        services.verify_licence(lic, request.user)
        return Response(LicenceSerializer(lic).data)

    @extend_schema(request=ReasonSerializer, responses=LicenceSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        lic = self.get_object()
        services.reject_licence(lic, request.user, _valid(ReasonSerializer, request)["reason"])
        return Response(LicenceSerializer(lic).data)


# ---------------------------------------------------------------- identity checks (US-ACC-004a/b)

@extend_schema(methods=["GET"], responses=IdentityCheckSerializer(many=True))
@extend_schema(methods=["POST"], request=StartIdentityCheckSerializer, responses={201: IdentityCheckSerializer})
@api_view(["GET", "POST"])
def my_identity_checks(request):
    if request.method == "GET":
        qs = IdentityCheck.objects.filter(person=request.user).order_by("-created_at")
        return Response(IdentityCheckSerializer(qs, many=True).data)
    d = _valid(StartIdentityCheckSerializer, request)
    chk = services.start_identity_check(request.user, **d)
    return Response(IdentityCheckSerializer(chk).data, status=201)


class IdentityCheckViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """The manual check queue for case managers and reviewers."""

    serializer_class = IdentityCheckSerializer
    permission_classes = [roles("CM", "RV")]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return IdentityCheck.objects.none()
        qs = selectors.scope_to_staff_countries(IdentityCheck.objects.select_related("person"), self.request.user)
        st = self.request.query_params.get("status")
        return (qs.filter(status=st) if st else qs).order_by("-created_at")

    @extend_schema(request=ManualCheckSerializer, responses={201: IdentityCheckSerializer})
    @idempotent
    def create(self, request):
        """Record a manual document check for a client with no provider check."""
        d = _valid(ManualCheckSerializer, request)
        person = d.pop("person", None)
        if person is None:
            raise Invalid("Choose the client.", code="validation-error")
        chk = services.create_manual_check(request.user, person, **d)
        return Response(IdentityCheckSerializer(chk).data, status=201)

    @extend_schema(request=ManualCheckSerializer, responses=IdentityCheckSerializer)
    @action(detail=True, methods=["post"], url_path="manual-decision")
    def manual_decision(self, request, pk=None):
        chk = self.get_object()
        d = _valid(ManualCheckSerializer, request)
        d.pop("person", None)
        services.record_manual_check(chk, request.user, **d)
        return Response(IdentityCheckSerializer(chk).data)


# ---------------------------------------------------------------- national identity checks (US-ACC-013)

class NationalIdCheckViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Check a party, a payee or (for a refund exception) the client against
    the national identity system. Accepts no card image (RUL-31)."""

    serializer_class = NationalIdCheckSerializer
    permission_classes = [roles("CM", "RV", "LW")]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return NationalIdCheck.objects.none()
        u = self.request.user
        qs = NationalIdCheck.objects.all().order_by("-requested_at")
        if not has_role(u, "CM", "RV"):
            qs = qs.filter(requested_by=u)
        qs = selectors.scope_to_staff_countries(qs, u, roles=("CM", "RV", "LW"))
        for f in ("context_type", "context_id", "result", "person"):
            v = self.request.query_params.get(f)
            if v:
                qs = qs.filter(**{f: v})
        return qs

    @extend_schema(request=RequestNationalIdCheckSerializer, responses={201: NationalIdCheckSerializer})
    @idempotent
    def create(self, request):
        services.refuse_document_proof(request.user, request.data, context="national-id-checks")
        d = _valid(RequestNationalIdCheckSerializer, request)
        country = d.pop("country", None) or services._person_country(request.user)
        if not selectors.in_staff_scope(request.user, country, roles=("CM", "RV", "LW")):
            raise Forbidden("This country is outside your scope.")
        chk = services.request_national_id_check(by=request.user, country=country, **d)
        return Response(NationalIdCheckSerializer(chk).data, status=201)

    @extend_schema(request=StaffPortalResultSerializer, responses=NationalIdCheckSerializer)
    @action(detail=True, methods=["post"], url_path="staff-result")
    def staff_result(self, request, pk=None):
        services.refuse_document_proof(request.user, request.data, context="staff-result")
        chk = self.get_object()
        d = _valid(StaffPortalResultSerializer, request)
        services.record_staff_portal_result(chk, request.user, **d)
        return Response(NationalIdCheckSerializer(chk).data)

    @extend_schema(request=None, responses=NationalIdCheckSerializer)
    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        chk = self.get_object()
        services.run_national_id_check(chk)
        return Response(NationalIdCheckSerializer(chk).data)


# ---------------------------------------------------------------- representatives (US-ACC-008)

class MyRepresentativeViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin,
                              mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = RepresentativeSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RepresentativeGrant.objects.none()
        return RepresentativeGrant.objects.filter(client=self.request.user).order_by("-created_at")

    @idempotent
    def create(self, request, *args, **kwargs):
        d = _valid(RepresentativeSerializer, request)
        g = services.name_representative(request.user, email=d["invited_email"], full_name=d.get("invited_name", ""),
                                         subject_type=d["subject_type"], subject_id=d["subject_id"],
                                         expires_at=d.get("expires_at"))
        return Response(RepresentativeSerializer(g).data, status=201)

    def perform_destroy(self, instance):
        services.revoke_representative(instance, self.request.user)


@extend_schema(responses=RepresentativeSerializer(many=True))
@api_view(["GET"])
def represented(request):
    """What I can follow as someone's representative (read-only)."""
    now = timezone.now()
    qs = RepresentativeGrant.objects.filter(representative=request.user, status="active").filter(
        Q(expires_at__isnull=True) | Q(expires_at__gt=now)).order_by("-created_at")
    return Response(RepresentativeSerializer(qs, many=True).data)


# ---------------------------------------------------------------- family members (US-ACC-012)

class FamilyMemberViewSet(ModelViewSet):
    serializer_class = FamilyMemberSerializer
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return FamilyMember.objects.none()
        u = self.request.user
        if has_role(u, "CM", "RV") and self.request.method == "GET" and self.request.query_params.get("client"):
            qs = FamilyMember.objects.filter(client_id=self.request.query_params["client"])
            return selectors.scope_to_staff_countries(qs, u).order_by("-created_at")
        return FamilyMember.objects.filter(client=u).exclude(status="anonymised").order_by("-created_at")

    @idempotent
    def create(self, request, *args, **kwargs):
        d = _valid(FamilyMemberSerializer, request)
        fm = services.add_family_member(request.user, dict(d))
        return Response(FamilyMemberSerializer(fm).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        fm = self.get_object()
        d = _valid(FamilyMemberSerializer, request, partial=True)
        services.update_family_member(fm, request.user, dict(d))
        return Response(FamilyMemberSerializer(fm).data)

    def perform_destroy(self, instance):
        """Removing keeps the record under retention rules (US-ACC-012 AC3)."""
        services.remove_family_member(instance, self.request.user)

    def destroy(self, request, *args, **kwargs):
        fm = self.get_object()
        self.perform_destroy(fm)
        return Response(FamilyMemberSerializer(fm).data)


# ---------------------------------------------------------------- client bank accounts (RUL-24)

class BankAccountViewSet(ModelViewSet):
    serializer_class = BankAccountSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BankAccount.objects.none()
        u = self.request.user
        qs = BankAccount.objects.select_related("holder", "approval_request").order_by("-created_at")
        if has_role(u, "CM", "RV"):
            qs = selectors.scope_to_staff_countries(qs, u)
            st = self.request.query_params.get("status")
            return qs.filter(verification_status=st) if st else qs
        return qs.filter(holder=u)

    @idempotent
    def create(self, request, *args, **kwargs):
        d = _valid(BankAccountSerializer, request)
        acct = services.add_bank_account(request.user, **d)
        return Response(BankAccountSerializer(acct).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        acct = self.get_object()
        d = _valid(BankAccountSerializer, request, partial=True)
        services.update_bank_account(acct, request.user, dict(d))
        acct.refresh_from_db()
        return Response(BankAccountSerializer(acct).data)

    @extend_schema(request=BankVerificationSerializer, responses=BankAccountSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def verifications(self, request, pk=None):
        acct = self.get_object()
        d = _valid(BankVerificationSerializer, request)
        services.prepare_bank_verification(acct, request.user, **d)
        return Response(BankAccountSerializer(acct).data)

    @extend_schema(request=DecisionSerializer, responses=BankAccountSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    @idempotent
    def approvals(self, request, pk=None):
        acct = self.get_object()
        d = _valid(DecisionSerializer, request)
        services.decide_bank_verification(acct, request.user, decision=d["decision"], mfa_at=require_mfa(request),
                                          note=d.get("note", ""))
        acct.refresh_from_db()
        return Response(BankAccountSerializer(acct).data)

    @extend_schema(request=ReasonSerializer, responses=BankAccountSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("RV")])
    def suspend(self, request, pk=None):
        acct = self.get_object()
        services.suspend_bank_account(acct, request.user, _valid(ReasonSerializer, request)["reason"])
        return Response(BankAccountSerializer(acct).data)


# ---------------------------------------------------------------- vetting (FR-CARE-002, FR-TSK-003)

class VettingViewSet(ModelViewSet):
    serializer_class = VettingSerializer
    http_method_names = ["get", "post", "patch"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Vetting.objects.none()
        u = self.request.user
        qs = Vetting.objects.select_related("person").order_by("-created_at")
        if has_role(u, "CM", "RV"):
            qs = selectors.scope_to_staff_countries(qs, u)
            for f in ("person", "kind", "status"):
                v = self.request.query_params.get(f)
                if v:
                    qs = qs.filter(**{f: v})
            return qs
        if self.request.method != "GET":
            return qs.none()
        return qs.filter(person=u)

    @idempotent
    def create(self, request, *args, **kwargs):
        d = _valid(VettingSerializer, request)
        v = services.create_vetting(request.user, d.pop("person"), kind=d.pop("kind"), **d)
        return Response(VettingSerializer(v).data, status=201)

    def partial_update(self, request, *args, **kwargs):
        v = self.get_object()
        d = _valid(VettingSerializer, request, partial=True)
        d.pop("person", None)
        d.pop("kind", None)
        d.pop("country", None)
        services.update_vetting(v, request.user, dict(d))
        return Response(VettingSerializer(v).data)

    @extend_schema(request=None, responses=VettingSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    def complete(self, request, pk=None):
        v = self.get_object()
        services.complete_vetting(v, request.user)
        return Response(VettingSerializer(v).data)

    @extend_schema(request=ReasonSerializer, responses=VettingSerializer)
    @action(detail=True, methods=["post"], permission_classes=[roles("CM", "RV")])
    def revoke(self, request, pk=None):
        v = self.get_object()
        services.revoke_vetting(v, request.user, _valid(ReasonSerializer, request)["reason"])
        return Response(VettingSerializer(v).data)

