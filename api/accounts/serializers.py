from rest_framework import serializers

from countries.models import Country
from evidence.models import Evidence

from .models import (BankAccount, FamilyMember, IdentityCheck, Invitation, Membership, NationalIdCheck,
                     Organisation, Person, ProfessionalLicence, RepresentativeGrant, RightsRequest, RoleGrant, Vetting)
from .normalise import mask


class StrictMixin:
    """Refuse fields the API does not know (TC-ACC-012-02: only catalogued
    fields are accepted, NFR-PRIV-02)."""

    def to_internal_value(self, data):
        if hasattr(data, "keys"):
            unknown = set(data.keys()) - set(self.fields)
            if unknown:
                raise serializers.ValidationError({k: "This field is not accepted." for k in sorted(unknown)})
        return super().to_internal_value(data)


CountryCode = lambda **kw: serializers.SlugRelatedField(slug_field="code", queryset=Country.objects.all(), **kw)  # noqa: E731
EvidenceRef = lambda **kw: serializers.PrimaryKeyRelatedField(queryset=Evidence.objects.all(), **kw)  # noqa: E731


class PersonSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    home_country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    email_verified = serializers.SerializerMethodField()
    phone_verified = serializers.SerializerMethodField()
    privacy_notice_pending = serializers.SerializerMethodField()
    channels_off = serializers.ListField(child=serializers.ChoiceField(choices=Person.CHANNELS), required=False)

    class Meta:
        model = Person
        fields = ["id", "email", "phone", "full_name", "preferred_language", "residence_country", "home_country",
                  "mfa_enabled", "roles", "status", "id_check_status", "email_verified", "phone_verified",
                  "preferred_channel", "channels_off", "privacy_notice_pending", "created_at"]
        read_only_fields = ["id", "email", "mfa_enabled", "roles", "status", "id_check_status", "created_at"]

    def get_roles(self, obj) -> list[str]:
        return sorted(obj.roles())

    def get_email_verified(self, obj) -> bool:
        return bool(obj.email_verified_at)

    def get_phone_verified(self, obj) -> bool:
        return bool(obj.phone_verified_at)

    def get_privacy_notice_pending(self, obj) -> str | None:
        """US-DPR-001 AC2: the version to accept, when a newer notice exists."""
        from dataprotection.selectors import pending_notice_version

        return pending_notice_version(obj)


class PersonSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Person
        fields = ["id", "full_name", "email"]


class SignupSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=10, write_only=True)
    full_name = serializers.CharField()
    phone = serializers.CharField()
    residence_country = serializers.CharField(required=False, allow_blank=True, max_length=2)
    home_country = serializers.CharField(required=False, default="GH", max_length=2)
    preferred_language = serializers.CharField(required=False, default="en")
    privacy_notice_version = serializers.CharField(required=False, allow_blank=True)
    mode = serializers.ChoiceField(choices=["session", "token"], required=False, default="session")


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=10, write_only=True)
    full_name = serializers.CharField()
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    residence_country = serializers.CharField(required=False, allow_blank=True, max_length=2)
    home_country = serializers.CharField(required=False, default="GH", max_length=2)
    preferred_language = serializers.CharField(required=False, default="en")
    privacy_notice_version = serializers.CharField(required=False, allow_blank=True)


class SignupResultSerializer(serializers.Serializer):
    person = PersonSerializer()
    verification = serializers.DictField(child=serializers.CharField())


class OtpSendSerializer(serializers.Serializer):
    identifier = serializers.CharField(help_text="Email address or mobile number")
    channel = serializers.ChoiceField(choices=["email", "phone"], required=False)
    purpose = serializers.ChoiceField(choices=["signup", "login"], default="signup")


class OtpVerifySerializer(serializers.Serializer):
    identifier = serializers.CharField()
    channel = serializers.ChoiceField(choices=["email", "phone"])
    code = serializers.CharField()
    mode = serializers.ChoiceField(choices=["session", "token"], required=False, default="session")


class OtpVerifyResultSerializer(serializers.Serializer):
    email_verified = serializers.BooleanField()
    phone_verified = serializers.BooleanField()
    verified = serializers.BooleanField()
    person = PersonSerializer(required=False)
    access = serializers.CharField(required=False)
    refresh = serializers.CharField(required=False)
    expires_in = serializers.IntegerField(required=False)


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(required=False, help_text="Email address or mobile number")
    email = serializers.CharField(required=False, help_text="Same as identifier (older clients)")
    password = serializers.CharField(required=False, write_only=True)
    otp = serializers.CharField(required=False, help_text="One-time code instead of a password")
    channel = serializers.ChoiceField(choices=["email", "phone"], required=False)
    code = serializers.CharField(required=False, help_text="Authenticator code when MFA is on")

    def validate(self, attrs):
        attrs["identifier"] = attrs.get("identifier") or attrs.get("email") or ""
        if not attrs["identifier"]:
            raise serializers.ValidationError({"identifier": "Enter your email address or mobile number."})
        if not attrs.get("password") and not attrs.get("otp"):
            raise serializers.ValidationError({"password": "Enter your password or a one-time code."})
        return attrs


class TokenPairSerializer(serializers.Serializer):
    person = PersonSerializer(required=False)
    access = serializers.CharField()
    refresh = serializers.CharField()
    expires_in = serializers.IntegerField()
    privacy_notice_pending = serializers.CharField(allow_null=True, required=False)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class PasswordResetSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    channel = serializers.ChoiceField(choices=["email", "phone"], required=False)


class PasswordResetConfirmSerializer(serializers.Serializer):
    identifier = serializers.CharField()
    channel = serializers.ChoiceField(choices=["email", "phone"], required=False)
    code = serializers.CharField()
    new_password = serializers.CharField(min_length=10, write_only=True)


class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(min_length=10, write_only=True)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField()


class MfaSetupResultSerializer(serializers.Serializer):
    otpauth_uri = serializers.CharField()
    secret = serializers.CharField()


class MfaStepUpResultSerializer(serializers.Serializer):
    mfa_at = serializers.DateTimeField()
    valid_for_seconds = serializers.IntegerField()


class CsrfSerializer(serializers.Serializer):
    csrf_token = serializers.CharField()


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class DecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=["approve", "reject"], default="approve")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField()


# ---- organisations

class OrganisationSerializer(StrictMixin, serializers.ModelSerializer):
    country = CountryCode()
    my_org_role = serializers.SerializerMethodField()

    class Meta:
        model = Organisation
        fields = ["id", "name", "kind", "country", "registration_number", "status", "contact_email",
                  "contact_phone", "address", "my_org_role", "created_at"]
        read_only_fields = ["id", "status", "my_org_role", "created_at"]

    def get_my_org_role(self, obj) -> str | None:
        req = self.context.get("request")
        if not req:
            return None
        m = Membership.objects.filter(organisation=obj, person=req.user, status="active").first()
        return m.org_role if m else None


class MembershipSerializer(serializers.ModelSerializer):
    person = PersonSummarySerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "organisation", "person", "org_role", "status", "added_by", "removed_at", "created_at"]


class AddMemberSerializer(serializers.Serializer):
    email = serializers.EmailField()
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    org_role = serializers.ChoiceField(choices=["admin", "member"], default="member")


class AddMemberResultSerializer(serializers.Serializer):
    membership = MembershipSerializer(allow_null=True)
    invitation_id = serializers.UUIDField(allow_null=True)


# ---- roles, invitations, rights

class RoleGrantSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = RoleGrant
        fields = ["id", "person", "role", "country", "organisation", "scope_type", "scope_id", "granted_by",
                  "approval_request", "valid_to", "revoked_at", "revoke_reason", "created_at"]


class GrantRoleSerializer(StrictMixin, serializers.Serializer):
    role = serializers.CharField(max_length=4)
    country = CountryCode(required=False, allow_null=True)
    organisation = serializers.PrimaryKeyRelatedField(queryset=Organisation.objects.all(), required=False,
                                                      allow_null=True)
    scope_type = serializers.ChoiceField(choices=RoleGrant.SCOPE_TYPES, required=False)
    scope_id = serializers.UUIDField(required=False)


class AdminPersonSerializer(serializers.ModelSerializer):
    home_country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    grants = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ["id", "email", "phone", "full_name", "home_country", "status", "mfa_enabled", "id_check_status",
                  "is_active", "locked_until", "grants", "created_at"]

    def get_grants(self, obj) -> list[dict]:
        return RoleGrantSerializer(obj.role_grants.filter(revoked_at__isnull=True), many=True).data


class InvitationSerializer(StrictMixin, serializers.ModelSerializer):
    country = CountryCode(required=False, allow_null=True)
    roles = serializers.ListField(child=serializers.CharField(max_length=4), required=False)

    class Meta:
        model = Invitation
        fields = ["id", "email", "full_name", "roles", "country", "organisation", "case_id", "status", "expires_at",
                  "invited_by", "accepted_person", "accepted_at", "created_at"]
        read_only_fields = ["id", "status", "expires_at", "invited_by", "accepted_person", "accepted_at",
                            "created_at"]


class AcceptInvitationSerializer(serializers.Serializer):
    token = serializers.CharField()
    password = serializers.CharField(write_only=True)
    full_name = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")
    privacy_notice_version = serializers.CharField(required=False, allow_blank=True)


class RightsRequestSerializer(StrictMixin, serializers.ModelSerializer):
    country = CountryCode(required=False, allow_null=True)
    person_name = serializers.CharField(source="person.full_name", read_only=True)
    approval_status = serializers.CharField(source="approval_request.status", read_only=True, default=None)

    class Meta:
        model = RightsRequest
        fields = ["id", "person", "person_name", "right", "country", "reason", "requested_by", "approval_request",
                  "approval_status", "grant", "status", "created_at"]
        read_only_fields = ["id", "requested_by", "approval_request", "grant", "status", "created_at"]


# ---- licences

class LicenceSerializer(StrictMixin, serializers.ModelSerializer):
    person = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all(), required=False)
    country = CountryCode(required=False)
    evidence = EvidenceRef(required=False, allow_null=True)
    valid_today = serializers.SerializerMethodField()

    class Meta:
        model = ProfessionalLicence
        validators = []  # uniqueness is checked in services and the database
        fields = ["id", "person", "role", "country", "body", "number", "expires_on", "status", "verified_by",
                  "verified_on", "evidence", "rejected_reason", "valid_today", "created_at"]
        read_only_fields = ["id", "status", "verified_by", "verified_on", "rejected_reason", "valid_today",
                            "created_at"]

    def get_valid_today(self, obj) -> bool:
        from django.utils import timezone

        return obj.status == "verified" and obj.expires_on >= timezone.localdate()


# ---- identity

class IdentityCheckSerializer(serializers.ModelSerializer):
    person = PersonSummarySerializer(read_only=True)
    document_number = serializers.SerializerMethodField()

    class Meta:
        model = IdentityCheck
        fields = ["id", "person", "method", "provider", "provider_reference", "provider_result", "document_type",
                  "document_number", "status", "reviewed_by", "reviewed_at", "evidence", "notes", "created_at"]

    def get_document_number(self, obj) -> str:
        return mask(obj.document_number)


class StartIdentityCheckSerializer(StrictMixin, serializers.Serializer):
    document_type = serializers.ChoiceField(choices=IdentityCheck.DOCUMENT_TYPES)
    document_number = serializers.CharField()
    country = CountryCode(required=False)


class ManualCheckSerializer(StrictMixin, serializers.Serializer):
    person = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all(), required=False)
    document_type = serializers.ChoiceField(choices=IdentityCheck.DOCUMENT_TYPES)
    document_number = serializers.CharField()
    outcome = serializers.ChoiceField(choices=["passed", "failed"])
    evidence = EvidenceRef(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class NationalIdCheckSerializer(serializers.ModelSerializer):
    """Result, reference and time only (FR-ACC-013). The number is masked."""

    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    id_number = serializers.SerializerMethodField()

    class Meta:
        model = NationalIdCheck
        fields = ["id", "country", "subject_role", "person", "subject_name", "id_number", "channel", "adapter",
                  "requested_by", "requested_at", "result", "provider_reference", "checked_at", "checked_by",
                  "attempts", "context_type", "context_id"]

    def get_id_number(self, obj) -> str:
        return mask(obj.id_number)


class RequestNationalIdCheckSerializer(serializers.Serializer):
    country = CountryCode(required=False)
    subject_role = serializers.ChoiceField(choices=NationalIdCheck.SUBJECT_ROLES)
    subject_name = serializers.CharField()
    id_number = serializers.CharField()
    person = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all(), required=False, allow_null=True)
    adapter = serializers.ChoiceField(choices=["api", "staff_portal"], default="api")
    context_type = serializers.CharField(required=False, allow_blank=True, default="")
    context_id = serializers.UUIDField(required=False, allow_null=True)


class StaffPortalResultSerializer(serializers.Serializer):
    id_number = serializers.CharField()
    result = serializers.ChoiceField(choices=["match", "no_match", "not_found"])
    provider_reference = serializers.CharField()
    returned_name = serializers.CharField(required=False, allow_blank=True, default="")


# ---- representatives, family, bank accounts, vetting

class RepresentativeSerializer(StrictMixin, serializers.ModelSerializer):
    email = serializers.EmailField(source="invited_email")
    full_name = serializers.CharField(source="invited_name", required=False, allow_blank=True)
    representative = PersonSummarySerializer(read_only=True)
    client = PersonSummarySerializer(read_only=True)

    class Meta:
        model = RepresentativeGrant
        fields = ["id", "client", "email", "full_name", "representative", "subject_type", "subject_id", "read_only",
                  "expires_at", "status", "revoked_at", "created_at"]
        read_only_fields = ["id", "client", "representative", "read_only", "status", "revoked_at", "created_at"]


class FamilyMemberSerializer(StrictMixin, serializers.ModelSerializer):
    country = CountryCode(required=False)

    class Meta:
        model = FamilyMember
        fields = ["id", "full_name", "relationship", "phone", "address", "latitude", "longitude",
                  "may_confirm_visits", "country", "status", "person", "removed_at", "created_at"]
        read_only_fields = ["id", "status", "person", "removed_at", "created_at"]


class BankAccountSerializer(StrictMixin, serializers.ModelSerializer):
    country = CountryCode(required=False)
    evidence = EvidenceRef(required=False, allow_null=True)
    account_number = serializers.CharField(write_only=True)
    account_number_last4 = serializers.CharField(source="last4", read_only=True)
    holder = PersonSummarySerializer(read_only=True)
    approval_status = serializers.CharField(source="approval_request.status", read_only=True, default=None)
    purpose = serializers.ChoiceField(choices=["rent_destination", "professional_pay"], required=False)

    class Meta:
        model = BankAccount
        fields = ["id", "holder", "country", "bank_name", "branch", "account_number", "account_number_last4",
                  "account_name", "name_match", "name_source", "verification_status", "evidence", "approval_request",
                  "approval_status", "bank_partner_id", "purpose", "verified_at", "created_at"]
        read_only_fields = ["id", "holder", "name_match", "verification_status", "approval_request",
                            "approval_status", "verified_at", "created_at"]


class BankVerificationSerializer(StrictMixin, serializers.Serializer):
    evidence = EvidenceRef(required=False, allow_null=True)
    name_source = serializers.ChoiceField(choices=["bank_letter", "bank_name_check"], default="bank_letter")


class VettingSerializer(StrictMixin, serializers.ModelSerializer):
    country = CountryCode(required=False)
    person = serializers.PrimaryKeyRelatedField(queryset=Person.objects.all())
    national_id_check = serializers.PrimaryKeyRelatedField(queryset=NationalIdCheck.objects.all(), required=False,
                                                           allow_null=True)
    references_evidence = EvidenceRef(required=False, allow_null=True)
    background_check_evidence = EvidenceRef(required=False, allow_null=True)
    training_evidence = EvidenceRef(required=False, allow_null=True)

    class Meta:
        model = Vetting
        validators = []  # uniqueness is checked in services and the database
        fields = ["id", "person", "kind", "country", "national_id_check", "references_evidence",
                  "background_check_evidence", "training_evidence", "checklist_version", "status", "created_by",
                  "vetted_by", "vetted_at", "valid_until", "revoke_reason", "created_at"]
        read_only_fields = ["id", "checklist_version", "status", "created_by", "vetted_by", "vetted_at",
                            "valid_until", "revoke_reason", "created_at"]


# ---- home

class HomeItemSerializer(serializers.Serializer):
    kind = serializers.CharField()
    id = serializers.CharField()
    title = serializers.CharField()
    status = serializers.CharField(allow_blank=True)
    status_text = serializers.CharField(allow_blank=True)
    next_date = serializers.CharField(allow_null=True)
    needs_action = serializers.BooleanField()
    link = serializers.CharField(allow_blank=True)
    family_member_id = serializers.CharField(allow_null=True)
    line = serializers.CharField(allow_blank=True)
    amount = serializers.DictField(allow_null=True, required=False)


class HomeSerializer(serializers.Serializer):
    person = PersonSerializer()
    family_members = FamilyMemberSerializer(many=True)
    items = HomeItemSerializer(many=True)
    needs_action_count = serializers.IntegerField()
