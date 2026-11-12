"""ACC services other modules may call."""
from datetime import timedelta

import pyotp
from django.contrib.auth import authenticate
from django.db import transaction
from django.utils import timezone

from audit.services import record
from core.errors import DomainError, Invalid
from core.events import publish

from .models import Person, RoleGrant

MAX_FAILED = 5
LOCK_FOR = timedelta(minutes=15)


@transaction.atomic
def register(*, email, password, full_name, phone="", residence_country="", home_country="GH",
             preferred_language="en", roles=("CL",)) -> Person:
    from django.contrib.auth.password_validation import validate_password
    from countries.models import Country

    email = email.lower().strip()
    if Person.objects.filter(email=email).exists():
        raise Invalid("An account with this email already exists.", code="email-taken")
    try:
        validate_password(password)
    except Exception as exc:  # noqa: BLE001
        raise Invalid(" ".join(getattr(exc, "messages", [str(exc)])), code="weak-password") from exc
    country = Country.objects.filter(code=(home_country or "GH").upper()).first()
    p = Person.objects.create_user(email, password, full_name=full_name, phone=phone or "",
                                   residence_country=(residence_country or "").upper(), home_country=country,
                                   preferred_language=preferred_language)
    for r in roles:
        RoleGrant.objects.create(person=p, role=r)
    record(actor=p, action="person.registered", entity="person", entity_id=p.pk, data={"roles": list(roles)})
    publish("person.registered", p.pk, {"person_id": p.pk, "roles": list(roles)})
    return p


def check_credentials(request, email, password) -> Person:
    """Sign-in with lockout after 5 failures for 15 minutes (FR-ACC-002, assumption)."""
    p = Person.objects.filter(email=(email or "").lower().strip()).first()
    if p and p.is_locked:
        raise DomainError("Too many attempts. Try again in 15 minutes.", code="account-locked", status=423)
    user = authenticate(request, username=(email or "").lower().strip(), password=password)
    if user is None:
        if p:
            p.failed_logins += 1
            fields = ["failed_logins"]
            if p.failed_logins >= MAX_FAILED:
                p.locked_until = timezone.now() + LOCK_FOR
                p.failed_logins = 0
                fields.append("locked_until")
                record(actor=p, action="account.locked", entity="person", entity_id=p.pk)
                publish("account.locked", p.pk, {"person_id": p.pk})
            p.save(update_fields=fields)
        raise DomainError("Email or password is wrong.", code="bad-credentials", status=401)
    if user.failed_logins:
        user.failed_logins = 0
        user.save(update_fields=["failed_logins"])
    return user


def mfa_setup(person) -> str:
    person.mfa_secret = pyotp.random_base32()
    person.save(update_fields=["mfa_secret"])
    return pyotp.TOTP(person.mfa_secret).provisioning_uri(name=person.email, issuer_name="Tenmina")


def mfa_verify(person, code) -> bool:
    if not person.mfa_secret:
        return False
    return pyotp.TOTP(person.mfa_secret).verify(str(code).strip(), valid_window=1)


def grant_role(person, role, *, country=None, organisation=None, granted_by=None) -> RoleGrant:
    g = RoleGrant.objects.create(person=person, role=role, country=country, organisation=organisation,
                                 granted_by=granted_by)
    record(actor=granted_by, action="role.granted", entity="person", entity_id=person.pk,
           data={"role": role, "country": getattr(country, "code", None)})
    return g
