"""Accounts and identity (ACC), document 02 sections 6.4, 6.8 and 6.15.

People, roles and scoped grants, release and payment rights granted by two
administrators, one-time codes, invitations, organisations and memberships,
professional licences, the client's own identity check, national identity
checks of parties and payees (RUL-31, no biometric data), representatives,
family members, client-owned bank accounts and vetting records.

Field-level encryption and blind indexes (6.1, 10.6) are simplified here to
plain columns plus keyed hashes (`*_bidx`). No column in any acc_* table
holds a photo, fingerprint, face or other biometric data (ADR-25).
"""
import hashlib
import secrets

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from core import state
from core.models import BaseModel, CountryScopedModel
from core.permissions import ALL_ROLES

RIGHTS_ROLES = ("RR", "PY")  # release rights and payment rights: permissions, not roles (01 C2)


class PersonManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        person = self.model(email=self.normalize_email(email).lower(), **extra)
        person.set_password(password)
        person.save(using=self._db)
        return person

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True)
        return self.create_user(email, password, **extra)


class Person(AbstractBaseUser, PermissionsMixin, BaseModel):
    STATUSES = ["active", "suspended", "closing", "closed", "anonymised"]
    ID_CHECK = ["none", "pending", "manual_review", "passed", "manual_passed", "failed"]
    CHANNELS = ["in_app", "email", "sms", "whatsapp", "push"]

    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True, default="")  # E.164
    full_name = models.TextField()
    preferred_language = models.CharField(max_length=8, default="en")
    residence_country = models.CharField(max_length=2, blank=True, default="")  # where the client lives
    home_country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access only
    mfa_secret = models.CharField(max_length=64, blank=True, default="")  # encrypt at field level in prod (10.6)
    mfa_enabled = models.BooleanField(default=False)
    failed_logins = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    id_check_status = models.TextField(default="none", choices=[(s, s) for s in ID_CHECK])  # FR-ACC-004
    preferred_channel = models.TextField(default="email", choices=[(c, c) for c in CHANNELS])  # FR-ACC-010
    channels_off = models.JSONField(default=list, blank=True)  # channels the person turned off
    closed_at = models.DateTimeField(null=True, blank=True)
    anonymised_at = models.DateTimeField(null=True, blank=True)
    data_class = models.TextField(default="account")

    objects = PersonManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "acc_person"
        constraints = [
            models.UniqueConstraint(fields=["phone"], condition=~models.Q(phone=""), name="acc_person_phone_uq"),
        ]

    def __str__(self):
        return self.full_name or self.email

    def roles(self, country=None) -> set[str]:
        qs = self.role_grants.filter(revoked_at__isnull=True).filter(
            models.Q(valid_to__isnull=True) | models.Q(valid_to__gt=timezone.now()))
        if country is not None:
            code = getattr(country, "code", country)
            qs = qs.filter(models.Q(country__isnull=True) | models.Q(country__code=code))
        return set(qs.values_list("role", flat=True))

    def has_tenmina_role(self, *roles, country=None) -> bool:
        return bool(self.roles(country) & set(roles))

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    @property
    def is_verified(self):
        """Both contact details confirmed by one-time code (FR-ACC-001). Invited
        staff confirm email by the single-use link and may have no phone."""
        return bool(self.email_verified_at and (self.phone_verified_at or not self.phone))


PERSON = state.register("person", "acc_person", {
    "active": {"suspended", "closing", "closed"},
    "suspended": {"active", "closed"},
    "closing": {"closed", "active"},
    "closed": {"anonymised"},
})


class Organisation(BaseModel):
    KINDS = ["seller", "developer", "institution", "insurer", "bank", "agency", "partner", "supplier", "vendor",
             "law_firm", "survey_firm", "contractor", "authority"]
    name = models.TextField()
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    country = models.ForeignKey("countries.Country", on_delete=models.PROTECT, related_name="+")
    registration_number = models.TextField(blank=True, default="")
    status = models.TextField(default="active")  # active | suspended | closed
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=32, blank=True, default="")
    address = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "acc_organisation"

    def __str__(self):
        return self.name


class RoleGrant(BaseModel):
    """A role, optionally scoped to a country and an object (6.4). Release
    rights (RR) and payment rights (PY) carry the approved approval request
    of two administrators; a database trigger checks it (dbsql.py)."""

    SCOPE_TYPES = ["country", "case", "project", "listing", "organisation", "authority", "family_member",
                   "institution", "care_plan", "managed_property", "tenancy", "errand", "policy", "event"]
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="role_grants")
    role = models.CharField(max_length=4, choices=[(r, r) for r in ALL_ROLES])
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")  # null = every country
    organisation = models.ForeignKey(Organisation, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="members")
    scope_type = models.TextField(blank=True, default="", choices=[("", "")] + [(s, s) for s in SCOPE_TYPES])
    scope_id = models.UUIDField(null=True, blank=True)
    granted_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    valid_to = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    revoke_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "acc_role_grant"
        indexes = [models.Index(fields=["person", "role"])]


class RightsRequest(BaseModel):
    """Release or payment rights asked for one person; two administrators
    approve (01 C2, 02 10.4: release_rights_grant, payment_rights_grant)."""

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="rights_requests")
    right = models.CharField(max_length=2, choices=[(r, r) for r in RIGHTS_ROLES])
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    reason = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    grant = models.ForeignKey(RoleGrant, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="pending")

    class Meta:
        db_table = "acc_rights_request"


RIGHTS_REQUEST = state.register("rights_request", "acc_rights_request", {
    "pending": {"granted", "rejected", "withdrawn"},
})


class ApiToken(BaseModel):
    """Bearer tokens for the two mobile apps (7.1). Only hashes are stored."""

    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="tokens")
    kind = models.CharField(max_length=8, choices=[("access", "access"), ("refresh", "refresh")])
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    mfa_at = models.DateTimeField(null=True, blank=True)
    app = models.TextField(blank=True, default="")  # e.g. field/ios/1.4.0
    device_id = models.TextField(blank=True, default="")

    class Meta:
        db_table = "acc_refresh_token"

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, person, kind, ttl, **kw):
        raw = secrets.token_urlsafe(32)
        tok = cls.objects.create(person=person, kind=kind, token_hash=cls.hash(raw),
                                 expires_at=timezone.now() + ttl, **kw)
        return raw, tok


class OneTimeCode(BaseModel):
    """Six-digit codes, 10-minute life, 5 tries (10.3, assumptions)."""

    CHANNELS = ["email", "phone"]
    PURPOSES = ["signup", "login", "password_reset"]
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="one_time_codes")
    channel = models.TextField(choices=[(c, c) for c in CHANNELS])
    purpose = models.TextField(choices=[(p, p) for p in PURPOSES])
    destination = models.TextField()
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "acc_one_time_code"
        indexes = [models.Index(fields=["person", "channel", "purpose"])]


class Invitation(BaseModel):
    """Single-use invitation link with an expiry (FR-ACC-006). Only the hash
    of the token is stored; the raw token goes out by email."""

    STATUSES = ["pending", "accepted", "revoked", "expired"]
    email = models.EmailField()
    full_name = models.TextField(blank=True, default="")
    roles = models.JSONField(default=list)
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    organisation = models.ForeignKey(Organisation, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    case_id = models.UUIDField(null=True, blank=True)  # a seller invited to one case (FR-ACC-006)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    invited_by = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    accepted_person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "acc_invitation"


INVITATION = state.register("invitation", "acc_invitation", {
    "pending": {"accepted", "revoked", "expired"},
})


class Membership(BaseModel):
    """A person working for an organisation (FR-ACC-011)."""

    organisation = models.ForeignKey(Organisation, on_delete=models.PROTECT, related_name="memberships")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="memberships")
    org_role = models.TextField(default="member", choices=[("admin", "admin"), ("member", "member")])
    status = models.TextField(default="active", choices=[("active", "active"), ("removed", "removed")])
    role_grant = models.ForeignKey(RoleGrant, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    added_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "acc_membership"
        constraints = [models.UniqueConstraint(fields=["organisation", "person"], condition=models.Q(status="active"),
                                               name="acc_membership_one_active")]


class ProfessionalLicence(BaseModel):
    """FR-ACC-005, RUL-20: only a verified, in-date licence lets a
    professional sign their section."""

    ROLES = ["LW", "SV", "QS", "IN"]
    STATUSES = ["submitted", "verified", "rejected", "expired", "revoked"]
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="licences")
    role = models.CharField(max_length=4, choices=[(r, r) for r in ROLES])
    country = models.ForeignKey("countries.Country", on_delete=models.PROTECT, related_name="+")
    body = models.TextField()  # e.g. General Legal Council
    number = models.TextField()
    expires_on = models.DateField()
    status = models.TextField(default="submitted", choices=[(s, s) for s in STATUSES])
    verified_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    verified_on = models.DateField(null=True, blank=True)
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    rejected_reason = models.TextField(blank=True, default="")
    expiry_warned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "acc_professional_licence"
        constraints = [
            models.UniqueConstraint(fields=["body", "number"], name="acc_licence_body_number_uq"),
            models.CheckConstraint(condition=~models.Q(status="verified") | (
                models.Q(verified_by__isnull=False) & models.Q(verified_on__isnull=False)),
                name="acc_licence_verified_has_verifier"),
        ]


LICENCE = state.register("licence", "acc_professional_licence", {
    "submitted": {"verified", "rejected"},
    "verified": {"expired", "revoked"},
    "rejected": {"submitted"},
})


class IdentityCheck(CountryScopedModel):
    """The client's own identity check (FR-ACC-004). Parties and payees are
    checked in NationalIdCheck, never by a document check (RUL-31)."""

    STATUSES = ["pending", "passed", "manual_review", "manual_passed", "manual_failed"]
    DOCUMENT_TYPES = ["national_id", "passport", "residence_permit", "driving_licence"]
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="identity_checks")
    method = models.TextField(choices=[("provider", "provider"), ("manual", "manual")])
    provider = models.TextField(blank=True, default="")
    provider_reference = models.TextField(blank=True, default="")
    provider_result = models.TextField(blank=True, default="")  # passed | failed | inconclusive | unavailable
    document_type = models.TextField(choices=[(d, d) for d in DOCUMENT_TYPES])
    document_number = models.TextField(blank=True, default="")  # encrypt at field level in prod (10.6)
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    reviewed_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")  # document copy, restricted access (US-ACC-004b)
    notes = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "acc_identity_check"
        constraints = [
            models.CheckConstraint(condition=~models.Q(status__in=["manual_passed", "manual_failed"]) | (
                models.Q(reviewed_by__isnull=False) & ~models.Q(document_number="")),
                name="acc_idcheck_manual_has_reviewer"),
        ]


IDENTITY_CHECK = state.register("identity_check", "acc_identity_check", {
    "pending": {"passed", "manual_review"},
    "manual_review": {"manual_passed", "manual_failed"},
})


class NationalIdCheck(CountryScopedModel):
    """FR-ACC-013, RUL-31, IF-03, 02 section 9.4. Result, reference, time and a
    hash of the raw response only. No biometric column exists, and no
    endpoint accepts a card image."""

    SUBJECT_ROLES = ["seller", "grantor", "consenting_party", "signatory", "payee", "client", "carer",
                     "errand_agent", "professional"]
    RESULTS = ["pending", "match", "no_match", "not_found", "unavailable"]
    subject_role = models.TextField(choices=[(r, r) for r in SUBJECT_ROLES])
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    subject_name = models.TextField()  # the name on the deal documents
    subject_name_bidx = models.CharField(max_length=64)  # keyed hash of the normalised name
    id_number = models.TextField()  # encrypt at field level in prod (10.6); needed for retries
    id_number_bidx = models.CharField(max_length=64, db_index=True)
    partner_id = models.UUIDField(null=True, blank=True)  # adm_partner of kind 'identity' when ADM has it
    channel = models.TextField(blank=True, default="")  # from country configuration, e.g. "Ghana Card (NIA)"
    adapter = models.TextField(default="api", choices=[("api", "api"), ("staff_portal", "staff_portal")])
    requested_by = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="+")
    requested_at = models.DateTimeField(default=timezone.now)
    result = models.TextField(default="pending", choices=[(r, r) for r in RESULTS])
    provider_reference = models.TextField(null=True, blank=True, unique=True)
    response_sha256 = models.CharField(max_length=64, blank=True, default="")
    checked_at = models.DateTimeField(null=True, blank=True)
    checked_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    attempts = models.PositiveSmallIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    context_type = models.TextField(blank=True, default="")  # 'case', 'payee', 'payee_change', 'vetting', ...
    context_id = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "acc_national_id_check"
        constraints = [
            models.CheckConstraint(condition=models.Q(result__in=["pending", "unavailable"]) | (
                models.Q(provider_reference__isnull=False) & models.Q(checked_at__isnull=False)),
                name="acc_nid_final_has_reference"),
            models.CheckConstraint(condition=~models.Q(adapter="staff_portal") | models.Q(
                result__in=["pending", "unavailable"]) | models.Q(checked_by__isnull=False),
                name="acc_nid_staff_portal_has_checker"),
        ]


NATIONAL_ID_CHECK = state.register("national_id_check", "acc_national_id_check", {
    "pending": {"match", "no_match", "not_found", "unavailable"},
    "unavailable": {"match", "no_match", "not_found"},
}, field="result")


class RepresentativeGrant(BaseModel):
    """Read-only access to one case or project for a person the client names
    (FR-ACC-008). Never a payee (RUL-22) and never an approver."""

    SUBJECT_TYPES = ["case", "project"]
    client = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="representatives_named")
    representative = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="representing")
    invited_email = models.EmailField()
    invited_name = models.TextField(blank=True, default="")
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    read_only = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="pending", choices=[(s, s) for s in ("pending", "active", "revoked")])
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "acc_representative_grant"
        constraints = [models.CheckConstraint(condition=models.Q(read_only=True), name="acc_rep_read_only")]


class FamilyMember(CountryScopedModel):
    """The people a client pays for or cares for (FR-ACC-012). A family
    member is never a payee (RUL-22)."""

    STATUSES = ["active", "removed", "anonymised"]
    client = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="family_members")
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    full_name = models.TextField()
    relationship = models.TextField()
    phone = models.CharField(max_length=32, blank=True, default="")
    address = models.TextField(blank=True, default="")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    may_confirm_visits = models.BooleanField(default=False)
    consent_id = models.UUIDField(null=True, blank=True)  # dpr_consent: the family member's own notice
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    removed_at = models.DateTimeField(null=True, blank=True)
    data_class = models.TextField(default="family")

    class Meta:
        db_table = "acc_family_member"
        constraints = [
            models.CheckConstraint(condition=models.Q(may_confirm_visits=False) | ~models.Q(phone="") | models.Q(
                person__isnull=False), name="acc_family_confirmer_reachable"),
        ]


FAMILY_MEMBER = state.register("family_member", "acc_family_member", {
    "active": {"removed", "anonymised"},
    "removed": {"anonymised"},
})


class BankAccount(CountryScopedModel):
    """A client's OWN account, e.g. the rent destination (RUL-24). Never a
    Tenmina account and never a payee's."""

    STATUSES = ["unverified", "pending", "verified", "suspended", "rejected"]
    holder = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="bank_accounts")
    bank_partner_id = models.UUIDField(null=True, blank=True)  # adm_partner of kind escrow_bank when ADM has it
    bank_name = models.TextField()
    branch = models.TextField(blank=True, default="")
    account_number = models.TextField()  # encrypt at field level in prod (10.6)
    account_name = models.TextField()
    account_name_norm = models.TextField(blank=True, default="")
    name_match = models.TextField(default="pending", choices=[(s, s) for s in ("pending", "matched", "mismatch")])
    name_source = models.TextField(blank=True, default="", choices=[
        ("", ""), ("bank_letter", "bank_letter"), ("bank_name_check", "bank_name_check")])
    verification_status = models.TextField(default="unverified", choices=[(s, s) for s in STATUSES])
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    approval_request = models.ForeignKey("core.ApprovalRequest", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    prepared_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    verified_at = models.DateTimeField(null=True, blank=True)
    purpose = models.TextField(default="rent_destination")

    class Meta:
        db_table = "acc_bank_account"
        constraints = [
            models.CheckConstraint(condition=~models.Q(verification_status="verified") | (
                models.Q(name_match="matched") & models.Q(approval_request__isnull=False)),
                name="acc_bank_verified_needs_match_and_approval"),
        ]

    @property
    def last4(self):
        return self.account_number[-4:]


BANK_ACCOUNT = state.register("bank_account", "acc_bank_account", {
    "unverified": {"pending", "rejected"},
    "pending": {"verified", "rejected", "unverified"},
    "verified": {"pending", "suspended"},
    "suspended": {"pending"},
    "rejected": {"pending", "unverified"},
}, field="verification_status")


class Vetting(CountryScopedModel):
    """Vetting of carers, errand agents and field workers (FR-CARE-002,
    FR-TSK-003). Vetted needs a national identity match (RUL-31), references
    and a background check."""

    KINDS = ["carer", "errand_agent", "runner", "inspector", "contractor"]
    STATUSES = ["pending", "vetted", "expired", "revoked"]
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="vettings")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    national_id_check = models.ForeignKey(NationalIdCheck, null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    references_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                            related_name="+")
    background_check_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                  on_delete=models.PROTECT, related_name="+")
    training_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                          related_name="+")
    checklist_version = models.TextField(blank=True, default="")  # what vetting means per country (Q-19)
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    created_by = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="+")
    vetted_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    vetted_at = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    revoke_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "acc_vetting"
        constraints = [
            models.UniqueConstraint(fields=["person", "kind"], condition=models.Q(status__in=["pending", "vetted"]),
                                    name="acc_one_live_vetting"),
            models.CheckConstraint(condition=~models.Q(status="vetted") | (
                models.Q(vetted_by__isnull=False) & models.Q(valid_until__isnull=False)
                & models.Q(references_evidence__isnull=False) & models.Q(background_check_evidence__isnull=False)
                & models.Q(national_id_check__isnull=False)), name="acc_vetting_complete"),
            models.CheckConstraint(condition=~models.Q(status="revoked") | ~models.Q(revoke_reason=""),
                                   name="acc_vetting_revoke_reason"),
        ]


VETTING = state.register("vetting", "acc_vetting", {
    "pending": {"vetted", "revoked"},
    "vetted": {"expired", "revoked"},
})
