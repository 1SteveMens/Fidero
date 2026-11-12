"""Accounts and identity (ACC). Foundation part: people, roles, organisations,
API tokens and MFA. The rest of ACC (licences, identity checks, family
members, bank accounts, vetting, representatives) builds on these."""
import hashlib
import secrets

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone

from core.models import BaseModel
from core.permissions import ALL_ROLES


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
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, blank=True, default="")
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
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = PersonManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    class Meta:
        db_table = "acc_person"

    def __str__(self):
        return self.full_name or self.email

    def roles(self, country=None) -> set[str]:
        qs = self.role_grants.filter(revoked_at__isnull=True)
        if country is not None:
            code = getattr(country, "code", country)
            qs = qs.filter(models.Q(country__isnull=True) | models.Q(country__code=code))
        return set(qs.values_list("role", flat=True))

    def has_tenmina_role(self, *roles, country=None) -> bool:
        return bool(self.roles(country) & set(roles))

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())


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

    class Meta:
        db_table = "acc_organisation"

    def __str__(self):
        return self.name


class RoleGrant(BaseModel):
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="role_grants")
    role = models.CharField(max_length=4, choices=[(r, r) for r in ALL_ROLES])
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")  # null = every country
    organisation = models.ForeignKey(Organisation, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="members")
    granted_by = models.ForeignKey(Person, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "acc_role_grant"


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
