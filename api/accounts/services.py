"""ACC services: every write and every rule of the accounts module.
Other modules call only this file and selectors.py."""
import re
import secrets
from datetime import date, timedelta

import pyotp
from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from audit.services import record
from core import approvals, state
from core.adapters import get_adapter
from core.errors import DomainError, Forbidden, Invalid, NotFound, PayeeNotVerified, RuleBlocked, StateConflict
from core.events import publish
from core.permissions import ALL_ROLES, STAFF_ROLES, has_role

from .models import (RIGHTS_ROLES, ApiToken, BankAccount, FamilyMember, IdentityCheck, Invitation, Membership,
                     NationalIdCheck, OneTimeCode, Organisation, Person, ProfessionalLicence, RepresentativeGrant,
                     RightsRequest, RoleGrant, Vetting)
from .normalise import bidx, code_hash, normalise_name, normalise_phone

MAX_FAILED = 5                      # FR-ACC-009
LOCK_FOR = timedelta(minutes=15)    # FR-ACC-009
OTP_TTL = timedelta(minutes=10)     # 10.3, assumption
OTP_MAX_TRIES = 5                   # 10.3, assumption
OTP_MAX_PER_HOUR = 5                # assumption [TO VERIFY]
LICENCE_WARNING_DAYS = 30           # assumption [TO VERIFY]

# FR-ACC-003: staff, professionals, administrators and anyone who approves a
# release or a payment run. Field roles (RN, IN, CT, CE) use device keys in
# Tenmina Field (10.3) instead of an authenticator app.
MFA_REQUIRED_ROLES = {"CM", "RV", "AD", "LW", "SV", "QS", "RR", "PY", "DPO", "SUP", "IS"}
# 6.4 acc.no_money_roles(): release rights never sit with these roles.
NO_RELEASE_RIGHTS_ROLES = {"CL", "FM", "CE", "CT"}
# FR-PRO-005: payment rights never sit with a contracted professional.
NO_PAYMENT_RIGHTS_ROLES = {"LW", "SV", "RN", "IN", "QS", "CE"}
ORG_ROLE_BY_KIND = {"seller": "SE", "developer": "DV", "institution": "IC", "insurer": "IS"}
PARTY_ROLES = {"seller", "grantor", "consenting_party", "signatory"}
DOCUMENT_KEYS = {"evidence_id", "image", "photo", "scan", "file", "document", "card_image", "upload_id",
                 "photocopy", "attachment"}


def _now():
    return timezone.now()


def _cfg(country, key, default=None):
    from countries.selectors import config

    if country is None:
        return default
    return config(country, key, default)


def _notify(person, template, body, subject="", needs_action=False, channels=("in_app",), obj=None, **kw):
    from notifications.services import notify

    return notify(person, template, body=body, subject=subject, needs_action=needs_action, channels=channels,
                  subject_obj=obj, **kw)


def _staff_in(country, *roles):
    """People holding any of `roles` for `country` (or for every country)."""
    code = getattr(country, "code", country)
    qs = Person.objects.filter(role_grants__role__in=roles, role_grants__revoked_at__isnull=True,
                               is_active=True)
    if code:
        qs = qs.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country__code=code))
    return qs.distinct()


def _alert_staff(country, roles, template, body, obj=None):
    for p in _staff_in(country, *roles):
        _notify(p, template, body, needs_action=False, obj=obj)


def _person_country(person):
    from countries.models import Country

    return person.home_country or Country.objects.filter(code="GH").first()


# ---------------------------------------------------------------- one-time codes

def _otp_adapter():
    return get_adapter("one_time_codes", default="accounts.adapters.FakeOtpSender")


def _otp_salt(person, channel, purpose):
    return f"{person.pk}:{channel}:{purpose}"


def send_code(person, channel, purpose) -> OneTimeCode:
    dest = person.email if channel == "email" else person.phone
    if not dest:
        raise Invalid("There is no address on the account for this channel.", code="validation-error")
    now = _now()
    if OneTimeCode.objects.filter(person=person, channel=channel, created_at__gte=now - timedelta(hours=1)).count() \
            >= OTP_MAX_PER_HOUR:
        raise DomainError("Too many codes asked for. Try again in an hour.", code="rate-limited", status=429)
    OneTimeCode.objects.filter(person=person, channel=channel, purpose=purpose, used_at__isnull=True,
                               expires_at__gt=now).update(expires_at=now)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    otp = OneTimeCode.objects.create(person=person, channel=channel, purpose=purpose, destination=dest,
                                     code_hash=code_hash(_otp_salt(person, channel, purpose), code),
                                     expires_at=now + OTP_TTL)
    _otp_adapter().send(channel=channel, destination=dest, code=code, purpose=purpose)
    record(actor=person, action="otp.sent", entity="person", entity_id=person.pk,
           data={"channel": channel, "purpose": purpose})
    return otp


def check_code(person, channel, purpose, code) -> bool:
    """Wrong, expired, used or exhausted codes all fail the same way."""
    import hmac

    now = _now()
    otp = OneTimeCode.objects.filter(person=person, channel=channel, purpose=purpose, used_at__isnull=True) \
        .order_by("-created_at").first()
    if otp is None or otp.expires_at <= now or otp.attempts >= OTP_MAX_TRIES:
        return False
    otp.attempts += 1
    code = str(code or "").strip()
    adapter = _otp_adapter()
    ok = hmac.compare_digest(otp.code_hash, code_hash(_otp_salt(person, channel, purpose), code))
    if not ok and getattr(adapter, "accepts_master_code", lambda: False)():
        ok = code == getattr(adapter, "MASTER_CODE", None)
    if ok:
        otp.used_at = now
    otp.save(update_fields=["attempts", "used_at"])
    return ok


def find_person(identifier) -> Person | None:
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    if "@" in identifier:
        return Person.objects.filter(email=identifier.lower()).first()
    phone = normalise_phone(identifier)
    return Person.objects.filter(phone=phone).first() if phone else None


def _channel_for(identifier):
    return "email" if "@" in (identifier or "") else "phone"


# ---------------------------------------------------------------- sign-up and sign-in

def _check_phone(phone):
    phone = normalise_phone(phone)
    if not re.fullmatch(r"\+[1-9][0-9]{7,14}", phone or ""):
        raise Invalid("Enter the mobile number with its country code, for example +447700900123.",
                      code="validation-error")
    return phone


SIGNUP_REFUSED = ("We could not create an account with these details. If you already have an account, sign in "
                  "or reset your password.")


@transaction.atomic
def register(*, email, password, full_name, phone="", privacy_notice_version=None, residence_country="",
             home_country="GH", preferred_language="en", roles=("CL",), ip="", legacy=False) -> Person:
    """FR-ACC-001, FR-DPR-001: sign up with email and mobile number, each
    confirmed by a one-time code, and accept the current privacy notice.

    `legacy` serves the deprecated /v1/auth/register: the phone is optional
    and the notice, if not accepted here, is asked for at sign-in. The
    account still cannot sign in until its contact details are confirmed."""
    from django.contrib.auth.password_validation import validate_password

    from countries.models import Country
    from dataprotection import selectors as dpr

    email = (email or "").lower().strip()
    phone = _check_phone(phone) if (phone or not legacy) else ""
    country = Country.objects.filter(code=(home_country or "GH").upper()).first()
    if country is None:
        raise Invalid("We do not work in that country yet.", code="validation-error")
    notice = dpr.current_notice(country)
    if not legacy and notice is not None and str(privacy_notice_version or "") != str(notice.version):
        raise Invalid("Read and accept the privacy notice to continue.", code="privacy-notice-required",
                      extra={"privacy_notice_version": notice.version})
    if Person.objects.filter(email=email).exists() or (phone and Person.objects.filter(phone=phone).exists()):
        record(action="person.signup_refused", entity="person", entity_id="00000000-0000-0000-0000-000000000000",
               data={"reason": "duplicate"})
        raise Invalid(SIGNUP_REFUSED, code="signup-refused")
    try:
        validate_password(password)
    except Exception as exc:  # noqa: BLE001
        raise Invalid(" ".join(getattr(exc, "messages", [str(exc)])), code="weak-password") from exc
    p = Person.objects.create_user(email, password, full_name=full_name.strip(), phone=phone,
                                   residence_country=(residence_country or "").upper(), home_country=country,
                                   preferred_language=preferred_language)
    for r in roles:
        RoleGrant.objects.create(person=p, role=r)
    record(actor=p, action="person.registered", entity="person", entity_id=p.pk, data={"roles": list(roles)})
    publish("person.registered", p.pk, {"person_id": p.pk, "roles": list(roles), "country": country.code,
                                        "privacy_notice_version": privacy_notice_version, "ip": ip,
                                        "source": "signup"})
    send_code(p, "email", "signup")
    if phone:
        send_code(p, "phone", "signup")
    return p


def send_signup_code(identifier, channel):
    """Resend a sign-up code. Neutral whatever the identifier."""
    p = find_person(identifier)
    if p is None:
        return
    if (channel == "email" and p.email_verified_at) or (channel == "phone" and p.phone_verified_at):
        return
    send_code(p, channel, "signup")


def verify_signup_code(identifier, channel, code) -> Person:
    p = find_person(identifier)
    if p is None or channel not in ("email", "phone") or not check_code(p, channel, "signup", code):
        raise Invalid("That code is not right or has expired. Ask for a new code.", code="otp-invalid")
    field = "email_verified_at" if channel == "email" else "phone_verified_at"
    if getattr(p, field) is None:
        setattr(p, field, _now())
        p.save(update_fields=[field])
        record(actor=p, action=f"person.{channel}_verified", entity="person", entity_id=p.pk)
        if p.is_verified:
            publish("person.verified", p.pk, {"person_id": p.pk})
    return p


def _count_failure(p):
    p.failed_logins += 1
    fields = ["failed_logins"]
    if p.failed_logins >= MAX_FAILED:
        p.locked_until = _now() + LOCK_FOR
        p.failed_logins = 0
        fields.append("locked_until")
        record(actor=p, action="account.locked", entity="person", entity_id=p.pk)
        publish("account.locked", p.pk, {"person_id": p.pk, "until": p.locked_until})
        _notify(p, "account_locked", subject="Your Tenmina account is locked for 15 minutes",
                body="Someone entered the wrong password 5 times. Your account is locked for 15 minutes. "
                     "If this was not you, reset your password.", channels=("in_app", "email"), obj=p)
    p.save(update_fields=fields)


def check_credentials(request, identifier, password=None, *, otp=None, channel=None) -> Person:
    """FR-ACC-002 and FR-ACC-009: email or phone with a password, or a
    one-time code; 5 failures lock the account for 15 minutes. Run outside
    the request transaction so failures are counted."""
    p = find_person(identifier)
    if p and p.is_locked:
        raise DomainError("Too many attempts. Try again in 15 minutes.", code="account-locked", status=423)
    if otp:
        ok = bool(p) and check_code(p, channel or _channel_for(identifier), "login", otp)
    else:
        user = authenticate(request, username=p.email if p else (identifier or ""), password=password or "")
        ok = user is not None and p is not None and user.pk == p.pk
    if not ok:
        if p:
            _count_failure(p)
        raise DomainError("The details you entered are not right.", code="bad-credentials", status=401)
    if p.failed_logins:
        p.failed_logins = 0
        p.save(update_fields=["failed_logins"])
    if p.status in ("suspended", "closed", "anonymised") or not p.is_active:
        raise DomainError("This account is not active. Contact Tenmina.", code="account-inactive", status=403)
    if not p.is_verified:
        raise DomainError("Confirm your email and mobile number first. Use the codes we sent you.",
                          code="account-unverified", status=403,
                          extra={"email_verified": bool(p.email_verified_at),
                                 "phone_verified": bool(p.phone_verified_at)})
    record(actor=p, action="person.signed_in", entity="person", entity_id=p.pk,
           data={"method": "otp" if otp else "password"})
    return p


def send_login_code(identifier, channel=None):
    """FR-ACC-002: the code goes only to a verified email or number."""
    p = find_person(identifier)
    channel = channel or _channel_for(identifier)
    if p is None or p.is_locked or p.status not in ("active", "closing"):
        return
    if (channel == "email" and not p.email_verified_at) or (channel == "phone" and not p.phone_verified_at):
        return
    send_code(p, channel, "login")


def request_password_reset(identifier, channel=None):
    p = find_person(identifier)
    channel = channel or _channel_for(identifier)
    if p is None or p.status not in ("active", "closing"):
        return
    if (channel == "email" and not p.email_verified_at) or (channel == "phone" and not p.phone_verified_at):
        return
    send_code(p, channel, "password_reset")


def confirm_password_reset(identifier, code, new_password, channel=None) -> Person:
    from django.contrib.auth.password_validation import validate_password

    p = find_person(identifier)
    channel = channel or _channel_for(identifier)
    if p is None or not check_code(p, channel, "password_reset", code):
        raise Invalid("That code is not right or has expired. Ask for a new code.", code="otp-invalid")
    try:
        validate_password(new_password, p)
    except Exception as exc:  # noqa: BLE001
        raise Invalid(" ".join(getattr(exc, "messages", [str(exc)])), code="weak-password") from exc
    with transaction.atomic():
        p.set_password(new_password)
        p.failed_logins = 0
        p.locked_until = None
        p.save(update_fields=["password", "failed_logins", "locked_until"])
        revoke_tokens(p)
        record(actor=p, action="person.password_reset", entity="person", entity_id=p.pk)
        _notify(p, "password_changed", subject="Your Tenmina password was changed",
                body="Your password was changed. If this was not you, contact Tenmina at once.",
                channels=("in_app", "email"), obj=p)
    return p


@transaction.atomic
def change_password(person, old, new):
    from django.contrib.auth.password_validation import validate_password

    if not person.check_password(old or ""):
        raise Invalid("Your current password is not right.", code="bad-credentials")
    try:
        validate_password(new, person)
    except Exception as exc:  # noqa: BLE001
        raise Invalid(" ".join(getattr(exc, "messages", [str(exc)])), code="weak-password") from exc
    person.set_password(new)
    person.save(update_fields=["password"])
    record(actor=person, action="person.password_changed", entity="person", entity_id=person.pk)


def revoke_tokens(person):
    ApiToken.objects.filter(person=person, revoked_at__isnull=True).update(revoked_at=_now())


# ---------------------------------------------------------------- MFA (FR-ACC-003)

def mfa_required(person) -> bool:
    return bool(person.roles() & MFA_REQUIRED_ROLES)


def mfa_setup(person) -> str:
    person.mfa_secret = pyotp.random_base32()
    person.save(update_fields=["mfa_secret"])
    return pyotp.TOTP(person.mfa_secret).provisioning_uri(name=person.email, issuer_name="Tenmina")


def mfa_verify(person, code) -> bool:
    if not person.mfa_secret:
        return False
    return pyotp.TOTP(person.mfa_secret).verify(str(code).strip(), valid_window=1)


def mfa_confirm(person):
    person.mfa_enabled = True
    person.save(update_fields=["mfa_enabled"])
    record(actor=person, action="mfa.enrolled", entity="person", entity_id=person.pk)


@transaction.atomic
def disable_mfa(person, by):
    """US-ACC-003 AC3: nobody switches MFA off for staff, professionals or approvers."""
    if mfa_required(person):
        raise DomainError("Multi-factor authentication cannot be switched off for staff, professionals or "
                          "approvers.", code="mfa-mandatory", status=409)
    person.mfa_enabled = False
    person.mfa_secret = ""
    person.save(update_fields=["mfa_enabled", "mfa_secret"])
    record(actor=by, action="mfa.disabled", entity="person", entity_id=person.pk)


# ---------------------------------------------------------------- profile

PROFILE_FIELDS = {"full_name", "preferred_language", "residence_country", "preferred_channel", "channels_off",
                  "phone"}


@transaction.atomic
def update_profile(person, data: dict) -> Person:
    """FR-ACC-010: language, preferred channel and channels turned off. A new
    phone number must be confirmed again by code."""
    changed = {}
    for k, v in data.items():
        if k not in PROFILE_FIELDS:
            continue
        if k == "channels_off":
            v = sorted(set(v or []))
            bad = set(v) - set(Person.CHANNELS)
            if bad:
                raise Invalid(f"Unknown channels: {', '.join(sorted(bad))}.", code="validation-error")
            if "in_app" in v:
                raise Invalid("In-app messages cannot be turned off.", code="validation-error")
        if k == "phone":
            v = _check_phone(v)
            if Person.objects.filter(phone=v).exclude(pk=person.pk).exists():
                raise Invalid("This number cannot be used.", code="validation-error")
        if k == "residence_country":
            v = (v or "").upper()
        if getattr(person, k) != v:
            changed[k] = {"old": getattr(person, k), "new": v}
    preferred = changed.get("preferred_channel", {}).get("new", person.preferred_channel)
    off = changed.get("channels_off", {}).get("new", person.channels_off) or []
    if preferred in off:
        raise Invalid("Your preferred channel cannot also be turned off.", code="validation-error")
    if not changed:
        return person
    for k, v in changed.items():
        setattr(person, k, v["new"])
    fields = list(changed)
    if "phone" in changed:
        person.phone_verified_at = None
        fields.append("phone_verified_at")
    person.save(update_fields=fields)
    record(actor=person, action="person.updated", entity="person", entity_id=person.pk,
           data={"fields": sorted(changed)})
    if "phone" in changed:
        send_code(person, "phone", "signup")
    return person


# ---------------------------------------------------------------- roles, rights, invitations (FR-ACC-006)

def _overlap(qs, country):
    if country is None:
        return qs
    return qs.filter(Q(country__isnull=True) | Q(country=country))


def role_conflicts(person, role, country=None) -> str | None:
    """Separation of duties (6.4 acc.no_money_roles, FR-PRO-005). Returns a
    plain reason or None. The database trigger checks the same."""
    active = person.role_grants.filter(revoked_at__isnull=True)
    if role == "RR":
        if _overlap(active.filter(role__in=NO_RELEASE_RIGHTS_ROLES), country).exists():
            return "Release rights cannot go to a client, family member, carer, errand agent or contractor."
        if RepresentativeGrant.objects.filter(representative=person, status="active").exists():
            return "Release rights cannot go to a client's representative."
    if role in NO_RELEASE_RIGHTS_ROLES and _overlap(active.filter(role="RR"), country).exists():
        return "This person holds release rights, so they cannot also hold this role."
    if role == "PY" and active.filter(role__in=NO_PAYMENT_RIGHTS_ROLES).exists():
        return "Payment rights cannot go to a contracted professional."
    if role in NO_PAYMENT_RIGHTS_ROLES and active.filter(role="PY").exists():
        return "This person holds payment rights, so they cannot also hold a contracted role."
    return None


def grant_role(person, role, *, country=None, organisation=None, granted_by=None, scope_type="", scope_id=None,
               approval_request=None) -> RoleGrant:
    if role not in ALL_ROLES:
        raise Invalid(f"Unknown role {role}.", code="validation-error")
    if role in RIGHTS_ROLES and (approval_request is None or approval_request.status != "approved"):
        raise DomainError("Release and payment rights are granted only by two administrators.",
                          code="rights-need-two-administrators", status=409)
    reason = role_conflicts(person, role, country)
    if reason:
        raise DomainError(reason, code="separation-of-duties", status=409)
    g = RoleGrant.objects.create(person=person, role=role, country=country, organisation=organisation,
                                 granted_by=granted_by, scope_type=scope_type or "", scope_id=scope_id,
                                 approval_request=approval_request)
    record(actor=granted_by, action="role.granted", entity="person", entity_id=person.pk,
           data={"role": role, "country": getattr(country, "code", None), "grant_id": str(g.pk),
                 "granted_by_name": getattr(granted_by, "full_name", None), "scope_type": scope_type,
                 "scope_id": str(scope_id) if scope_id else None})
    publish("role.granted", g.pk, {"person_id": person.pk, "role": role, "grant_id": g.pk})
    return g


def admin_grant_role(by, person, role, **kw) -> RoleGrant:
    if not has_role(by, "AD"):
        raise Forbidden("Only an administrator assigns roles.")
    if role in RIGHTS_ROLES:
        raise DomainError("Release and payment rights are granted only by two administrators. Ask for them "
                          "through a rights request.", code="rights-need-two-administrators", status=409)
    return grant_role(person, role, granted_by=by, **kw)


@transaction.atomic
def revoke_grant(grant: RoleGrant, by, reason=""):
    if grant.revoked_at:
        return grant
    grant.revoked_at = _now()
    grant.revoked_by = by
    grant.revoke_reason = reason or ""
    grant.save(update_fields=["revoked_at", "revoked_by", "revoke_reason"])
    record(actor=by, action="role.revoked", entity="person", entity_id=grant.person_id,
           data={"role": grant.role, "grant_id": str(grant.pk), "reason": reason})
    publish("role.revoked", grant.pk, {"person_id": grant.person_id, "role": grant.role, "grant_id": grant.pk})
    return grant


def _rights_subject(right):
    return "release_rights_grant" if right == "RR" else "payment_rights_grant"


@transaction.atomic
def request_rights(*, by, person, right, country=None, reason="") -> RightsRequest:
    """01 C2, 02 10.4: release rights and payment rights need two administrators."""
    if right not in RIGHTS_ROLES:
        raise Invalid("Choose RR (release rights) or PY (payment rights).", code="validation-error")
    if not has_role(by, "AD"):
        raise Forbidden("Only an administrator asks for release or payment rights.")
    if not person.has_tenmina_role("RV", "AD"):
        raise DomainError("Release and payment rights go only to reviewers or senior staff.",
                          code="rights-not-allowed", status=409)
    if right in person.roles(country):
        raise StateConflict("This person already holds these rights.")
    reason_conflict = role_conflicts(person, right, country)
    if reason_conflict:
        raise DomainError(reason_conflict, code="separation-of-duties", status=409)
    if RightsRequest.objects.filter(person=person, right=right, status="pending").exists():
        raise StateConflict("A request for these rights is already waiting for approval.")
    rr = RightsRequest.objects.create(person=person, right=right, country=country, reason=reason, requested_by=by)
    label = "release rights" if right == "RR" else "payment rights"
    req = approvals.request_approval(_rights_subject(right), rr.pk, by, required=2, country=country,
                                     summary=f"Give {person.full_name} {label}")
    rr.approval_request = req
    rr.save(update_fields=["approval_request"])
    record(actor=by, action="rights.requested", entity="person", entity_id=person.pk,
           data={"right": right, "request_id": str(rr.pk)})
    return rr


def rights_approver_allowed(rr):
    return lambda a: has_role(a, "AD") and a.pk != rr.person_id


def decide_rights(rr: RightsRequest, approver, *, decision, mfa_at, note=""):
    if rr.status != "pending" or rr.approval_request is None:
        raise StateConflict("This request is closed.")
    return approvals.decide(rr.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=rights_approver_allowed(rr))


@transaction.atomic
def apply_rights(rr: RightsRequest):
    """Called when the approval closes as approved. Checks again that both
    approvers are administrators other than the person."""
    req = rr.approval_request
    if rr.status != "pending" or req is None or req.status != "approved":
        return rr
    approvers = list(req.approvals.filter(decision="approve").select_related("approver"))
    allowed = rights_approver_allowed(rr)
    if len({a.approver_id for a in approvers}) < 2 or not all(allowed(a.approver) for a in approvers):
        record(action="rights.invalid_approval", entity="rights_request", entity_id=rr.pk)
        return state.transition(rr, "rights_request", "rejected", reason="Approvers were not two administrators.")
    g = grant_role(rr.person, rr.right, country=rr.country, granted_by=req.prepared_by, approval_request=req)
    rr.grant = g
    state.transition(rr, "rights_request", "granted", actor=req.prepared_by, extra_fields=["grant"],
                     payload={"person_id": rr.person_id, "right": rr.right})
    _notify(rr.person, "rights_granted", body="You now hold "
            + ("release rights." if rr.right == "RR" else "payment rights."), obj=rr)
    return rr


@transaction.atomic
def withdraw_rights_request(rr, by):
    if rr.status != "pending":
        raise StateConflict("This request is closed.")
    if rr.approval_request:
        approvals.withdraw(rr.approval_request, by)
    return state.transition(rr, "rights_request", "withdrawn", actor=by)


def _invitation_hours(country):
    return int(_cfg(country, "accounts.invitation_hours", 72))  # assumption [TO VERIFY]


@transaction.atomic
def invite(*, by, email, roles, full_name="", country=None, organisation=None, case_id=None, link_base=""):
    """FR-ACC-006: an administrator invites staff and professionals; a case
    manager invites a seller to one named case. Returns (invitation, raw token)."""
    email = (email or "").lower().strip()
    roles = list(dict.fromkeys(roles or []))
    if set(roles) & set(RIGHTS_ROLES):
        raise DomainError("Release and payment rights are granted only by two administrators, never by "
                          "invitation.", code="rights-need-two-administrators", status=409)
    unknown = set(roles) - set(ALL_ROLES)
    if unknown:
        raise Invalid(f"Unknown roles: {', '.join(sorted(unknown))}.", code="validation-error")
    if not roles and organisation is None:
        raise Invalid("Choose at least one role.", code="validation-error")
    if has_role(by, "AD"):
        pass
    elif has_role(by, "CM") and roles and set(roles) <= {"SE", "DV"} and case_id:
        pass
    elif organisation is not None and is_org_admin(by, organisation):
        pass
    else:
        raise Forbidden("You cannot invite people with these roles.")
    country = country or (organisation.country if organisation else None) or _person_country(by)
    raw = secrets.token_urlsafe(32)
    hours = _invitation_hours(country)
    inv = Invitation.objects.create(email=email, full_name=full_name or "", roles=roles, country=country,
                                    organisation=organisation, case_id=case_id, token_hash=ApiToken.hash(raw),
                                    expires_at=_now() + timedelta(hours=hours), invited_by=by)
    link = f"{link_base or '/invitations/accept'}?token={raw}"
    _notify(None, "invitation", to_address=email, channels=("email",),
            subject="You are invited to Tenmina",
            body=f"{by.full_name} invited you to Tenmina. Accept here: {link} . The link works once and "
                 f"expires in {hours} hours.")
    record(actor=by, action="invitation.sent", entity="invitation", entity_id=inv.pk,
           data={"roles": roles, "case_id": str(case_id) if case_id else None,
                 "organisation_id": str(organisation.pk) if organisation else None})
    publish("invitation.sent", inv.pk, {"invitation_id": inv.pk, "roles": roles})
    return inv, raw


@transaction.atomic
def accept_invitation(*, token, password, full_name="", phone="", privacy_notice_version=None, ip="") -> Person:
    from django.contrib.auth.password_validation import validate_password

    from dataprotection import selectors as dpr

    inv = Invitation.objects.select_for_update().filter(token_hash=ApiToken.hash(token or "")).first()
    if inv is None or inv.status != "pending" or inv.expires_at <= _now():
        raise Invalid("This invitation link is not valid any more. Ask for a new one.", code="invitation-invalid")
    p = Person.objects.filter(email=inv.email).first()
    new = p is None
    if p is not None:
        if not p.check_password(password or ""):
            raise DomainError("The details you entered are not right.", code="bad-credentials", status=401)
    else:
        notice = dpr.current_notice(inv.country)
        if notice is not None and str(privacy_notice_version or "") != str(notice.version):
            raise Invalid("Read and accept the privacy notice to continue.", code="privacy-notice-required",
                          extra={"privacy_notice_version": notice.version})
        try:
            validate_password(password)
        except Exception as exc:  # noqa: BLE001
            raise Invalid(" ".join(getattr(exc, "messages", [str(exc)])), code="weak-password") from exc
        ph = _check_phone(phone) if phone else ""
        if ph and Person.objects.filter(phone=ph).exists():
            raise Invalid(SIGNUP_REFUSED, code="signup-refused")
        p = Person.objects.create_user(inv.email, password, full_name=(full_name or inv.full_name).strip(),
                                       phone=ph, home_country=inv.country, email_verified_at=_now())
    for r in inv.roles:
        if r not in p.roles(inv.country) or inv.case_id:
            grant_role(p, r, country=inv.country if r not in ("CL",) else None, granted_by=inv.invited_by,
                       scope_type="case" if inv.case_id else "", scope_id=inv.case_id)
    if inv.organisation:
        _add_membership(inv.organisation, p, inv.invited_by, "member")
    inv.accepted_person = p
    inv.accepted_at = _now()
    state.transition(inv, "invitation", "accepted", actor=p, extra_fields=["accepted_person", "accepted_at"])
    if new:
        record(actor=p, action="person.registered", entity="person", entity_id=p.pk,
               data={"roles": inv.roles, "invitation_id": str(inv.pk)})
        publish("person.registered", p.pk, {"person_id": p.pk, "roles": inv.roles, "source": "invitation",
                                            "country": getattr(inv.country, "code", None), "ip": ip,
                                            "privacy_notice_version": privacy_notice_version})
    return p


def revoke_invitation(inv, by):
    if inv.status != "pending":
        raise StateConflict("This invitation is closed.")
    return state.transition(inv, "invitation", "revoked", actor=by)


def expire_invitations():
    n = 0
    for inv in Invitation.objects.filter(status="pending", expires_at__lte=_now()):
        state.transition(inv, "invitation", "expired")
        n += 1
    return n


# ---------------------------------------------------------------- organisations (FR-ACC-011)

def is_org_admin(person, org) -> bool:
    return Membership.objects.filter(organisation=org, person=person, status="active", org_role="admin").exists()


def _add_membership(org, person, by, org_role="member") -> Membership:
    existing = Membership.objects.filter(organisation=org, person=person, status="active").first()
    if existing:
        return existing
    grant = None
    kind_role = ORG_ROLE_BY_KIND.get(org.kind)
    if kind_role:
        grant = grant_role(person, kind_role, country=org.country, organisation=org, granted_by=by,
                           scope_type="organisation", scope_id=org.pk)
    m = Membership.objects.create(organisation=org, person=person, org_role=org_role, role_grant=grant, added_by=by)
    record(actor=by, action="membership.added", entity="organisation", entity_id=org.pk,
           data={"person_id": str(person.pk), "org_role": org_role})
    publish("membership.added", m.pk, {"organisation_id": org.pk, "person_id": person.pk})
    return m


@transaction.atomic
def create_organisation(by, *, name, kind, country, **fields) -> Organisation:
    kind_role = ORG_ROLE_BY_KIND.get(kind)
    staff = has_role(by, "CM", "AD")
    if not staff and not (kind_role and by.has_tenmina_role(kind_role)):
        raise Forbidden("You can create an organisation only of your own kind.")
    org = Organisation.objects.create(name=name.strip(), kind=kind, country=country, created_by=by, **fields)
    record(actor=by, action="organisation.created", entity="organisation", entity_id=org.pk,
           data={"kind": kind, "name": org.name})
    publish("organisation.created", org.pk, {"organisation_id": org.pk, "kind": kind})
    if not staff or (kind_role and by.has_tenmina_role(kind_role)):
        _add_membership(org, by, by, "admin")
    return org


@transaction.atomic
def add_member(org, by, *, email, org_role="member", full_name=""):
    """Returns (membership, invitation). An unknown email gets an invitation."""
    if not (is_org_admin(by, org) or has_role(by, "AD")):
        raise Forbidden("Only an administrator of this organisation adds colleagues.")
    if org.status != "active":
        raise StateConflict("This organisation is not active.")
    p = Person.objects.filter(email=(email or "").lower().strip()).first()
    if p is None:
        inv, _ = invite(by=by, email=email, roles=[], full_name=full_name, country=org.country, organisation=org)
        return None, inv
    m = _add_membership(org, p, by, org_role)
    _notify(p, "membership_added", body=f"You were added to {org.name} on Tenmina.", obj=org)
    return m, None


@transaction.atomic
def remove_member(m: Membership, by, reason=""):
    org = m.organisation
    if not (is_org_admin(by, org) or has_role(by, "AD")):
        raise Forbidden("Only an administrator of this organisation removes colleagues.")
    if m.status != "active":
        raise StateConflict("This person is not a member any more.")
    if m.org_role == "admin" and not Membership.objects.filter(organisation=org, status="active",
                                                               org_role="admin").exclude(pk=m.pk).exists():
        raise StateConflict("An organisation needs at least one administrator.")
    m.status = "removed"
    m.removed_at = _now()
    m.removed_by = by
    m.save(update_fields=["status", "removed_at", "removed_by"])
    if m.role_grant_id:
        revoke_grant(m.role_grant, by, reason or "Removed from organisation")
    record(actor=by, action="membership.removed", entity="organisation", entity_id=org.pk,
           data={"person_id": str(m.person_id), "reason": reason})
    publish("membership.removed", m.pk, {"organisation_id": org.pk, "person_id": m.person_id})
    return m


# ---------------------------------------------------------------- licences (FR-ACC-005, RUL-20)

def _licence_err(msg):
    return DomainError(msg, code="licence-invalid", status=409, title="The licence is not valid",
                       blocking_reasons=[{"rule": "RUL-20", "message": msg}])


@transaction.atomic
def add_licence(by, person, *, role, body, number, expires_on, country=None, evidence=None) -> ProfessionalLicence:
    if by.pk != person.pk and not has_role(by, "AD", "RV"):
        raise Forbidden("You can add only your own licence.")
    if by.pk == person.pk and not person.has_tenmina_role(role):
        raise Forbidden("You do not hold this professional role.")
    country = country or _person_country(person)
    bodies = _cfg(country, f"licence_bodies.{role}")
    if bodies and body not in bodies:
        raise Invalid(f"For this role the licence body must be one of: {', '.join(bodies)}.",
                      code="validation-error")
    if expires_on <= timezone.localdate():
        raise Invalid("This licence has already expired.", code="validation-error")
    try:
        with transaction.atomic():
            lic = ProfessionalLicence.objects.create(person=person, role=role, country=country, body=body.strip(),
                                                     number=number.strip(), expires_on=expires_on, evidence=evidence)
    except IntegrityError as exc:
        raise Invalid("This licence number is already on file.", code="validation-error") from exc
    if evidence is not None:
        from evidence.services import link

        link(evidence, "licence", lic.pk, role="licence_certificate", by=by)
    record(actor=by, action="licence.submitted", entity="licence", entity_id=lic.pk,
           data={"role": role, "body": lic.body, "expires_on": expires_on})
    return lic


@transaction.atomic
def verify_licence(lic, by) -> ProfessionalLicence:
    if not has_role(by, "AD", "RV"):
        raise Forbidden("Only an administrator or reviewer verifies licences.")
    if by.pk == lic.person_id:
        raise Forbidden("You cannot verify your own licence.")
    if lic.expires_on < timezone.localdate():
        raise _licence_err("This licence has expired. Ask for the renewed licence.")
    lic.verified_by = by
    lic.verified_on = timezone.localdate()
    state.transition(lic, "licence", "verified", actor=by, extra_fields=["verified_by", "verified_on"],
                     event="licence.verified", payload={"person_id": lic.person_id, "role": lic.role})
    _notify(lic.person, "licence_verified", body=f"Your licence {lic.number} is verified.", obj=lic)
    return lic


@transaction.atomic
def reject_licence(lic, by, reason):
    if not has_role(by, "AD", "RV"):
        raise Forbidden("Only an administrator or reviewer checks licences.")
    lic.rejected_reason = reason or ""
    state.transition(lic, "licence", "rejected", actor=by, reason=reason, extra_fields=["rejected_reason"])
    _notify(lic.person, "licence_rejected", body=f"Your licence {lic.number} was not accepted: {reason}",
            needs_action=True, obj=lic)
    return lic


def require_valid_licence(person, role, on: date | None = None) -> ProfessionalLicence:
    """RUL-20: raises `licence-invalid` unless the person holds a verified,
    in-date licence for this role. Report signing calls this."""
    on = on or timezone.localdate()
    lics = ProfessionalLicence.objects.filter(person=person, role=role)
    ok = lics.filter(status="verified", expires_on__gte=on).order_by("-expires_on").first()
    if ok:
        return ok
    if not lics.exists():
        raise _licence_err("There is no licence on file for this role.")
    if lics.filter(status="verified").exists() or lics.filter(status="expired").exists():
        raise _licence_err("The licence on file has expired.")
    raise _licence_err("The licence on file is not verified yet.")


def expire_licences(today: date | None = None) -> int:
    """Daily job accounts.licence_expiry (7.12)."""
    today = today or timezone.localdate()
    n = 0
    for lic in ProfessionalLicence.objects.filter(status="verified", expires_on__lt=today).select_related("person"):
        state.transition(lic, "licence", "expired", event="licence.expired",
                         payload={"person_id": lic.person_id, "role": lic.role, "licence_id": lic.pk})
        _notify(lic.person, "licence_expired", needs_action=True, channels=("in_app", "email"), obj=lic,
                body=f"Your licence {lic.number} expired on {lic.expires_on}. You cannot sign until a renewed "
                     "licence is verified.")
        _alert_staff(lic.country, ("AD",), "licence_expired_staff",
                     f"The licence of {lic.person.full_name} expired on {lic.expires_on}.", obj=lic)
        n += 1
    for lic in ProfessionalLicence.objects.filter(status="verified", expiry_warned_at__isnull=True,
                                                  expires_on__gte=today,
                                                  expires_on__lte=today + timedelta(days=LICENCE_WARNING_DAYS)):
        _notify(lic.person, "licence_expiring", needs_action=True, obj=lic,
                body=f"Your licence {lic.number} expires on {lic.expires_on}. Send the renewed licence.")
        lic.expiry_warned_at = _now()
        lic.save(update_fields=["expiry_warned_at"])
    return n


# ---------------------------------------------------------------- client identity check (FR-ACC-004)

def _id_provider():
    return get_adapter("identity_check", default="accounts.adapters.FakeIdentityCheckProvider")


def _set_id_status(person, value):
    person.id_check_status = value
    person.save(update_fields=["id_check_status"])


@transaction.atomic
def start_identity_check(person, *, document_type, document_number, country=None) -> IdentityCheck:
    if person.id_check_status in ("passed", "manual_passed"):
        raise StateConflict("Your identity is already confirmed.")
    if IdentityCheck.objects.filter(person=person, status__in=["pending", "manual_review"]).exists():
        raise StateConflict("A check is already in progress.")
    country = country or _person_country(person)
    provider = _id_provider()
    chk = IdentityCheck.objects.create(country=country, person=person, method="provider",
                                       provider=getattr(provider, "name", type(provider).__name__),
                                       document_type=document_type, document_number=document_number.strip(),
                                       requested_by=person)
    try:
        res = provider.check(person=person, document_type=document_type, document_number=document_number,
                             country=country)
    except Exception:  # noqa: BLE001
        res = {"result": "unavailable", "reference": None}
    chk.provider_result = res.get("result", "unavailable")
    chk.provider_reference = res.get("reference") or ""
    chk.save(update_fields=["provider_result", "provider_reference"])
    if chk.provider_result == "passed":
        state.transition(chk, "identity_check", "passed", actor=person, event="identity_check.completed",
                         payload={"person_id": person.pk, "outcome": "passed"})
        _set_id_status(person, "passed")
    else:
        state.transition(chk, "identity_check", "manual_review", actor=person,
                         payload={"person_id": person.pk, "provider_result": chk.provider_result})
        _set_id_status(person, "manual_review")
        _alert_staff(country, ("CM",), "identity_manual_review",
                     f"The identity check of {person.full_name} needs a manual document check.", obj=chk)
        _notify(person, "identity_manual_review", obj=chk,
                body="We could not confirm your identity automatically. A case manager will check your "
                     "document by hand and tell you the result.")
    return chk


def _staff_check(by, person):
    if not has_role(by, "CM", "RV"):
        raise Forbidden("Only a case manager or reviewer records a manual check.")
    if by.pk == person.pk:
        raise Forbidden("You cannot check your own identity.")


@transaction.atomic
def record_manual_check(chk: IdentityCheck, by, *, document_type, document_number, outcome, evidence=None,
                        notes="") -> IdentityCheck:
    """US-ACC-004b: for the client's own identity only. Never for a party or
    payee (RUL-31)."""
    _staff_check(by, chk.person)
    if outcome not in ("passed", "failed"):
        raise Invalid("Outcome must be passed or failed.", code="validation-error")
    chk.document_type = document_type
    chk.document_number = (document_number or "").strip()
    chk.reviewed_by = by
    chk.reviewed_at = _now()
    chk.evidence = evidence
    chk.notes = notes or ""
    if not chk.document_number:
        raise Invalid("Enter the document number.", code="validation-error")
    to = "manual_passed" if outcome == "passed" else "manual_failed"
    state.transition(chk, "identity_check", to, actor=by, event="identity_check.completed",
                     payload={"person_id": chk.person_id, "outcome": to},
                     extra_fields=["document_type", "document_number", "reviewed_by", "reviewed_at", "evidence",
                                   "notes"])
    if evidence is not None:
        from evidence.services import link

        link(evidence, "identity_check", chk.pk, role="identity_document_restricted", by=by)
    _set_id_status(chk.person, "manual_passed" if outcome == "passed" else "failed")
    _notify(chk.person, "identity_checked", obj=chk, needs_action=outcome != "passed",
            body="Your identity is confirmed." if outcome == "passed"
            else "We could not confirm your identity from the document. Contact your case manager.")
    return chk


@transaction.atomic
def create_manual_check(by, person, **kw) -> IdentityCheck:
    _staff_check(by, person)
    if IdentityCheck.objects.filter(person=person, status__in=["pending", "manual_review"]).exists():
        raise StateConflict("A check is already in progress for this client.")
    chk = IdentityCheck.objects.create(country=_person_country(person), person=person, method="manual",
                                       document_type=kw["document_type"], requested_by=by)
    state.transition(chk, "identity_check", "manual_review", actor=by)
    return record_manual_check(chk, by, **kw)


def require_client_identity(person):
    """FR-ACC-004: before a report is released or an escrow opened."""
    if person.id_check_status not in ("passed", "manual_passed"):
        raise RuleBlocked("The client's identity is not confirmed yet.", code="identity-check-required",
                          blocking_reasons=[{"rule": "FR-ACC-004",
                                             "message": f"{person.full_name} has no passed identity check"}])


# ---------------------------------------------------------------- national identity checks (FR-ACC-013, RUL-31)

def _nid_adapter(country):
    from django.utils.module_loading import import_string

    path = _cfg(country, "national_id.adapter")
    if path:
        return import_string(path)()
    return get_adapter("national_id", default="accounts.adapters.FakeNationalIdProvider")


def refuse_document_proof(by, data: dict, context=""):
    """TC-RUL-31-02: a photocopy, scan or photo is never proof of identity."""
    keys = DOCUMENT_KEYS & set(data or {})
    if keys:
        record(actor=by, action="national_id_check.document_refused", entity="national_id_check",
               entity_id="00000000-0000-0000-0000-000000000000", data={"fields": sorted(keys), "context": context})
        raise DomainError("A photocopy, scan or photo of an identity card is never proof of identity. Only a "
                          "result from the national identity system counts (RUL-31).",
                          code="document-not-proof", status=422,
                          blocking_reasons=[{"rule": "RUL-31", "message": "No check from a document"}])


def may_run_national_id(by, subject_role) -> bool:
    if has_role(by, "CM", "RV"):
        return True
    return subject_role in PARTY_ROLES and has_role(by, "LW")


@transaction.atomic
def request_national_id_check(*, by, country, subject_role, subject_name, id_number, person=None,
                              context_type="", context_id=None, adapter="api") -> NationalIdCheck:
    if not may_run_national_id(by, subject_role):
        raise Forbidden("You cannot run national identity checks.")
    number = re.sub(r"\s+", "", (id_number or "")).upper()
    fmt = _cfg(country, "national_id.format")
    if fmt and "[TO VERIFY]" not in fmt:
        pattern = "^" + re.escape(fmt).replace("\\#", "#").replace("#", r"\d") + "$"
        if not re.match(pattern, number):
            raise Invalid(f"The identity number must look like {fmt}.", code="validation-error")
    if not subject_name or not number:
        raise Invalid("Enter the name and the identity number.", code="validation-error")
    chk = NationalIdCheck.objects.create(
        country=country, subject_role=subject_role, person=person, subject_name=subject_name.strip(),
        subject_name_bidx=bidx(normalise_name(subject_name)), id_number=number, id_number_bidx=bidx(number),
        channel=str(_cfg(country, "national_id.system", "")), adapter=adapter, requested_by=by,
        context_type=context_type or "", context_id=context_id)
    record(actor=by, action="national_id_check.requested", entity="national_id_check", entity_id=chk.pk,
           data={"subject_role": subject_role, "adapter": adapter, "context_type": context_type}, country=country)
    if adapter == "api":
        run_national_id_check(chk)
    return chk


def _finish_nid(chk, result, *, actor=None):
    state.transition(chk, "national_id_check", result, actor=actor, event="national_id_check.completed",
                     extra_fields=["provider_reference", "response_sha256", "checked_at", "checked_by"],
                     payload={"check_id": chk.pk, "result": result, "subject_role": chk.subject_role,
                              "person_id": chk.person_id, "context_type": chk.context_type,
                              "context_id": chk.context_id})
    if result != "match":
        _alert_staff(chk.country, ("RV", "CM"), "national_id_failed", obj=chk,
                     body=f"The national identity check of {chk.subject_name} ({chk.subject_role}) failed: "
                          f"{result.replace('_', ' ')}. Release and payee verification stay blocked.")
    _flag_duplicate_number(chk)


def _flag_duplicate_number(chk):
    """9.4: the same identity number on two sides of one deal raises a reviewer item."""
    if not chk.context_id:
        return
    other = NationalIdCheck.objects.filter(context_type=chk.context_type, context_id=chk.context_id,
                                           id_number_bidx=chk.id_number_bidx).exclude(pk=chk.pk) \
        .exclude(subject_name_bidx=chk.subject_name_bidx, subject_role=chk.subject_role).first()
    if other:
        publish("national_id_check.duplicate", chk.pk, {"check_id": chk.pk, "other_check_id": other.pk,
                                                        "context_type": chk.context_type,
                                                        "context_id": chk.context_id})
        _alert_staff(chk.country, ("RV",), "national_id_duplicate", obj=chk,
                     body="The same identity number appears twice on one deal. Review it before anything is "
                          "released.")


def run_national_id_check(chk: NationalIdCheck) -> NationalIdCheck:
    if chk.result not in ("pending", "unavailable") or chk.adapter != "api":
        return chk
    chk.attempts += 1
    chk.last_attempt_at = _now()
    chk.save(update_fields=["attempts", "last_attempt_at"])
    try:
        resp = _nid_adapter(chk.country).verify(id_number=chk.id_number, name=chk.subject_name, country=chk.country)
    except Exception:  # noqa: BLE001
        resp = {"status": "unavailable"}
    status = resp.get("status")
    if status not in ("found", "not_found"):
        if chk.result == "pending":
            state.transition(chk, "national_id_check", "unavailable", event="national_id_check.unavailable",
                             payload={"check_id": chk.pk})
            _alert_staff(chk.country, ("CM",), "national_id_unavailable", obj=chk,
                         body=f"The national identity service did not answer for {chk.subject_name}. The check "
                              "stays pending and is retried. Nothing depending on it can go ahead.")
        return chk
    if NationalIdCheck.objects.filter(provider_reference=resp.get("transaction_id")).exclude(pk=chk.pk).exists():
        record(action="national_id_check.replay_refused", entity="national_id_check", entity_id=chk.pk)
        return chk
    chk.provider_reference = resp.get("transaction_id")
    chk.response_sha256 = resp.get("response_sha256", "")
    chk.checked_at = _now()
    if status == "not_found":
        result = "not_found"
    else:  # the returned name is compared in memory and never stored
        result = "match" if normalise_name(resp.get("name", "")) == normalise_name(chk.subject_name) else "no_match"
    _finish_nid(chk, result)
    return chk


@transaction.atomic
def record_staff_portal_result(chk: NationalIdCheck, by, *, id_number, result, provider_reference,
                               returned_name="") -> NationalIdCheck:
    """The staff_portal adapter: a named staff member runs the check on the
    official platform and enters its reference (9.4). Not a document check."""
    if not has_role(by, "CM", "RV"):
        raise Forbidden("Only a case manager or reviewer records a result from the official platform.")
    if chk.adapter != "staff_portal":
        raise StateConflict("This check runs through the identity service, not by hand.")
    if chk.result not in ("pending", "unavailable"):
        raise StateConflict("This check already has a result.")
    if bidx(re.sub(r"\s+", "", id_number or "").upper()) != chk.id_number_bidx:
        raise Invalid("The identity number does not match this check.", code="identity-result-mismatch")
    if result not in ("match", "no_match", "not_found") or not provider_reference:
        raise Invalid("Enter the result and the platform's reference.", code="validation-error")
    if result == "match" and normalise_name(returned_name) != normalise_name(chk.subject_name):
        raise Invalid("The name the system returned does not match the name on the documents. Record a no "
                      "match.", code="identity-result-mismatch")
    if NationalIdCheck.objects.filter(provider_reference=provider_reference).exists():
        raise Invalid("This reference was already used for another check.", code="identity-result-mismatch")
    chk.provider_reference = provider_reference
    chk.checked_at = _now()
    chk.checked_by = by
    chk.response_sha256 = ""
    _finish_nid(chk, result, actor=by)
    return chk


def retry_national_id_checks() -> int:
    """Job accounts.national_id_retry every 15 minutes (7.12). Never falls
    back to a document check."""
    now = _now()
    n = 0
    qs = NationalIdCheck.objects.filter(result__in=["pending", "unavailable"], adapter="api").filter(
        Q(last_attempt_at__isnull=True) | Q(last_attempt_at__lte=now - timedelta(minutes=15)))
    for chk in qs:
        run_national_id_check(chk)
        n += 1
    for chk in NationalIdCheck.objects.filter(result__in=["pending", "unavailable"], escalated_at__isnull=True,
                                              requested_at__lte=now - timedelta(hours=24)):
        _alert_staff(chk.country, ("CM",), "national_id_overdue", obj=chk,
                     body=f"The national identity check of {chk.subject_name} has waited more than 24 hours.")
        publish("national_id_check.overdue", chk.pk, {"check_id": chk.pk, "context_type": chk.context_type,
                                                      "context_id": chk.context_id})
        chk.escalated_at = now
        chk.save(update_fields=["escalated_at"])
    return n


def national_id_blockers(checks: dict) -> list[dict]:
    """`checks` maps a label (e.g. "Seller Kwabena Owusu") to a
    NationalIdCheck, its id or None. Returns RUL-31 blocking reasons."""
    out = []
    for label, chk in checks.items():
        if chk is not None and not isinstance(chk, NationalIdCheck):
            chk = NationalIdCheck.objects.filter(pk=chk).first()
        if chk is None:
            out.append({"rule": "RUL-31", "message": f"{label}: no national identity check"})
        elif chk.result in ("pending", "unavailable"):
            out.append({"rule": "RUL-31", "message": f"{label}: national identity check is still pending"})
        elif chk.result != "match":
            out.append({"rule": "RUL-31",
                        "message": f"{label}: national identity check failed ({chk.result.replace('_', ' ')})"})
    return out


def require_national_id(checks: dict, what="This action"):
    reasons = national_id_blockers(checks)
    if reasons:
        raise RuleBlocked(f"{what} is blocked until every identity check passes.", code="national-id-check-required",
                          blocking_reasons=reasons)


# ---------------------------------------------------------------- representatives (FR-ACC-008)

_owner_checks = {}


def register_owner_check(subject_type, fn):
    """Modules that own cases or projects register fn(person, subject_id) -> bool."""
    _owner_checks[subject_type] = fn


@transaction.atomic
def name_representative(client, *, email, full_name="", subject_type, subject_id, expires_at=None):
    if not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client names a representative.")
    check = _owner_checks.get(subject_type)
    if check is not None and not check(client, subject_id):
        raise NotFound()
    email = (email or "").lower().strip()
    if email == client.email:
        raise Invalid("You cannot name yourself.", code="validation-error")
    rep = Person.objects.filter(email=email).first()
    if rep is not None and rep.has_tenmina_role("RR", "PY", *STAFF_ROLES):
        raise DomainError("A Tenmina staff member cannot be a client's representative.",
                          code="separation-of-duties", status=409)
    if RepresentativeGrant.objects.filter(client=client, invited_email=email, subject_type=subject_type,
                                          subject_id=subject_id, status__in=["pending", "active"]).exists():
        raise StateConflict("This person already represents you on this.")
    g = RepresentativeGrant.objects.create(client=client, representative=rep, invited_email=email,
                                           invited_name=full_name or "", subject_type=subject_type,
                                           subject_id=subject_id, expires_at=expires_at,
                                           status="active" if rep else "pending")
    record(actor=client, action="representative.named", entity="representative_grant", entity_id=g.pk,
           data={"subject_type": subject_type, "subject_id": str(subject_id)})
    publish("representative.named", g.pk, {"grant_id": g.pk, "client_id": client.pk,
                                           "subject_type": subject_type, "subject_id": subject_id})
    body = (f"{client.full_name} named you as a representative on Tenmina. You can follow the {subject_type} "
            "read-only. You cannot approve or pay anything.")
    if rep:
        _notify(rep, "representative_named", body=body, obj=g, channels=("in_app", "email"))
    else:
        _notify(None, "representative_named", to_address=email, channels=("email",),
                body=body + " Sign up with this email address to see it.")
    return g


@transaction.atomic
def revoke_representative(g: RepresentativeGrant, by):
    if g.client_id != by.pk:
        raise NotFound()
    if g.status == "revoked":
        return g
    g.status = "revoked"
    g.revoked_at = _now()
    g.save(update_fields=["status", "revoked_at"])
    record(actor=by, action="representative.revoked", entity="representative_grant", entity_id=g.pk)
    publish("representative.revoked", g.pk, {"grant_id": g.pk, "client_id": g.client_id,
                                             "representative_id": g.representative_id})
    return g


def link_pending_representatives(person):
    for g in RepresentativeGrant.objects.filter(invited_email=person.email, status="pending",
                                                representative__isnull=True):
        g.representative = person
        g.status = "active"
        g.save(update_fields=["representative", "status"])


# ---------------------------------------------------------------- family members (FR-ACC-012)

FAMILY_FIELDS = {"full_name", "relationship", "phone", "address", "latitude", "longitude", "may_confirm_visits",
                 "country"}


@transaction.atomic
def add_family_member(client, data: dict) -> FamilyMember:
    if not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client adds family members.")
    country = data.pop("country", None) or _person_country(client)
    phone = data.get("phone") or ""
    if phone:
        data["phone"] = _check_phone(phone)
    if data.get("may_confirm_visits") and not data.get("phone"):
        raise Invalid("Add a phone number so they can confirm visits.", code="validation-error")
    fm = FamilyMember.objects.create(client=client, country=country, **data)
    record(actor=client, action="family_member.added", entity="family_member", entity_id=fm.pk,
           data={"relationship": fm.relationship, "may_confirm_visits": fm.may_confirm_visits}, country=country)
    publish("family_member.added", fm.pk, {"family_member_id": fm.pk, "client_id": client.pk})
    if fm.phone:
        _notify(None, "family_member_added", to_address=fm.phone, channels=("sms",),
                body=f"{client.full_name} added you on Tenmina to arrange payments or visits for you. "
                     "Reply STOP to object. Tenmina's privacy notice explains how your details are used.")
    return fm


@transaction.atomic
def update_family_member(fm: FamilyMember, client, data: dict) -> FamilyMember:
    if fm.client_id != client.pk:
        raise NotFound()
    if fm.status != "active":
        raise StateConflict("This family member was removed.")
    changed = []
    for k, v in data.items():
        if k == "country":
            continue
        if k == "phone" and v:
            v = _check_phone(v)
        if getattr(fm, k) != v:
            setattr(fm, k, v)
            changed.append(k)
    if fm.may_confirm_visits and not fm.phone and not fm.person_id:
        raise Invalid("Add a phone number so they can confirm visits.", code="validation-error")
    if changed:
        fm.save(update_fields=changed)
        record(actor=client, action="family_member.updated", entity="family_member", entity_id=fm.pk,
               data={"fields": changed}, country=fm.country)
    return fm


@transaction.atomic
def remove_family_member(fm: FamilyMember, client) -> FamilyMember:
    """US-ACC-012 AC3: the record is kept under retention rules; nothing new
    can be linked to them."""
    if fm.client_id != client.pk:
        raise NotFound()
    fm.removed_at = _now()
    state.transition(fm, "family_member", "removed", actor=client, event="family_member.removed",
                     extra_fields=["removed_at"], payload={"client_id": client.pk})
    return fm


@transaction.atomic
def anonymise_family_member(fm: FamilyMember):
    fm.full_name = "Removed family member"
    fm.phone = ""
    fm.address = ""
    fm.latitude = fm.longitude = None
    fm.may_confirm_visits = False
    state.transition(fm, "family_member", "anonymised", extra_fields=[
        "full_name", "phone", "address", "latitude", "longitude", "may_confirm_visits"])
    return fm


# ---------------------------------------------------------------- client bank accounts (RUL-24)

def _name_match(account_name, holder):
    return "matched" if normalise_name(account_name) == normalise_name(holder.full_name) else "mismatch"


@transaction.atomic
def add_bank_account(holder, *, bank_name, account_number, account_name, country=None, branch="", evidence=None,
                     bank_partner_id=None, name_source="") -> BankAccount:
    if not holder.has_tenmina_role("CL"):
        raise Forbidden("Only a client registers their own account.")
    number = re.sub(r"\s+", "", account_number or "")
    if not re.fullmatch(r"[0-9A-Za-z-]{6,34}", number):
        raise Invalid("Enter the account number as the bank gives it.", code="validation-error")
    acct = BankAccount.objects.create(
        holder=holder, country=country or _person_country(holder), bank_name=bank_name.strip(), branch=branch or "",
        account_number=number, account_name=account_name.strip(), account_name_norm=normalise_name(account_name),
        name_match=_name_match(account_name, holder), evidence=evidence, bank_partner_id=bank_partner_id,
        name_source=name_source or "")
    record(actor=holder, action="bank_account.added", entity="bank_account", entity_id=acct.pk,
           data={"last4": acct.last4, "name_match": acct.name_match}, country=acct.country)
    if evidence is not None:
        from evidence.services import link

        link(evidence, "bank_account", acct.pk, role="bank_letter", by=holder)
    return acct


@transaction.atomic
def update_bank_account(acct: BankAccount, holder, data: dict) -> BankAccount:
    if acct.holder_id != holder.pk:
        raise NotFound()
    changed = []
    for k in ("bank_name", "branch", "account_number", "account_name"):
        if k in data and data[k] is not None and getattr(acct, k) != data[k]:
            setattr(acct, k, re.sub(r"\s+", "", data[k]) if k == "account_number" else data[k].strip())
            changed.append(k)
    if "evidence" in data and data["evidence"] is not None:
        acct.evidence = data["evidence"]
        changed.append("evidence")
    if not changed:
        return acct
    critical = {"account_number", "account_name"} & set(changed)
    if critical:
        acct.account_name_norm = normalise_name(acct.account_name)
        acct.name_match = _name_match(acct.account_name, holder)
        changed += ["account_name_norm", "name_match"]
        if acct.approval_request_id and acct.approval_request.status == "open":
            approvals.withdraw(acct.approval_request, holder)
    acct.save(update_fields=changed)
    if critical and acct.verification_status != "unverified":
        acct.refresh_from_db()
        if acct.verification_status != "pending":
            state.transition(acct, "bank_account", "pending", actor=holder, reason="Account details changed")
    record(actor=holder, action="bank_account.updated", entity="bank_account", entity_id=acct.pk,
           data={"fields": changed}, country=acct.country)
    return acct


@transaction.atomic
def prepare_bank_verification(acct: BankAccount, by, *, evidence=None, name_source="bank_letter") -> BankAccount:
    """Step one of two: a case manager or reviewer checks the bank letter or
    name check; two other staff approve (bank_account_verification)."""
    if not has_role(by, "CM", "RV"):
        raise Forbidden("Only staff verify bank accounts.")
    if by.pk == acct.holder_id:
        raise Forbidden("You cannot verify your own account.")
    if acct.verification_status not in ("unverified", "pending", "rejected"):
        raise StateConflict("This account is not waiting for verification.")
    evidence = evidence or acct.evidence
    if evidence is None:
        raise Invalid("Attach the bank letter or the bank's name check result.", code="validation-error")
    acct.name_match = _name_match(acct.account_name, acct.holder)
    if acct.name_match != "matched":
        acct.save(update_fields=["name_match"])
        raise PayeeNotVerified("The account name does not match the holder's name. Nobody can override this; send "
                               "a new bank letter or name check.",
                               blocking_reasons=[{"rule": "RUL-24", "message": "Account name mismatch"}])
    if acct.approval_request_id and acct.approval_request.status == "open":
        raise StateConflict("This account is already waiting for approval.")
    acct.evidence = evidence
    acct.name_source = name_source
    acct.prepared_by = by
    acct.save(update_fields=["evidence", "name_source", "prepared_by", "name_match"])
    if acct.verification_status != "pending":
        state.transition(acct, "bank_account", "pending", actor=by)
    req = approvals.request_approval("bank_account_verification", acct.pk, by, required=2, country=acct.country,
                                     summary=f"Verify account ending {acct.last4} of {acct.holder.full_name}")
    acct.approval_request = req
    acct.save(update_fields=["approval_request"])
    return acct


def bank_approver_allowed(acct):
    return lambda a: has_role(a, "CM", "RV") and a.pk != acct.holder_id


def decide_bank_verification(acct: BankAccount, approver, *, decision, mfa_at, note=""):
    if acct.approval_request is None or acct.approval_request.status != "open":
        raise StateConflict("This account has no open verification.")
    return approvals.decide(acct.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=bank_approver_allowed(acct))


@transaction.atomic
def apply_bank_verification(acct: BankAccount, approved: bool):
    req = acct.approval_request
    if acct.verification_status != "pending" or req is None:
        return acct
    if not approved:
        state.transition(acct, "bank_account", "rejected")
        _notify(acct.holder, "bank_account_rejected", needs_action=True, obj=acct,
                body=f"We could not verify the account ending {acct.last4}. Send a new bank letter.")
        return acct
    if _name_match(acct.account_name, acct.holder) != "matched":
        state.transition(acct, "bank_account", "rejected", reason="Name mismatch at approval")
        return acct
    acct.verified_at = _now()
    state.transition(acct, "bank_account", "verified", event="bank_account.verified", extra_fields=["verified_at"],
                     payload={"holder_id": acct.holder_id, "bank_account_id": acct.pk})
    _notify(acct.holder, "bank_account_verified", obj=acct, body=f"Your account ending {acct.last4} is verified.")
    return acct


@transaction.atomic
def suspend_bank_account(acct, by, reason):
    if not has_role(by, "RV"):
        raise Forbidden("Only a reviewer suspends an account.")
    return state.transition(acct, "bank_account", "suspended", actor=by, reason=reason)


# ---------------------------------------------------------------- vetting (FR-CARE-002, FR-TSK-003)

def _vetting_staff(by):
    if not has_role(by, "CM", "RV"):
        raise Forbidden("Only a case manager or reviewer vets carers and agents.")


@transaction.atomic
def create_vetting(by, person, *, kind, country=None, national_id_check=None, references_evidence=None,
                   background_check_evidence=None, training_evidence=None) -> Vetting:
    _vetting_staff(by)
    if by.pk == person.pk:
        raise Forbidden("You cannot vet yourself.")
    country = country or _person_country(person)
    try:
        with transaction.atomic():
            v = Vetting.objects.create(
                country=country, person=person, kind=kind, national_id_check=national_id_check,
                references_evidence=references_evidence, background_check_evidence=background_check_evidence,
                training_evidence=training_evidence, created_by=by,
                checklist_version=str(_cfg(country, "vetting.checklist_version", "[TO VERIFY]")))
    except IntegrityError as exc:
        raise StateConflict("This person already has a live vetting of this kind.") from exc
    record(actor=by, action="vetting.started", entity="vetting", entity_id=v.pk, data={"kind": kind},
           country=country)
    return v


@transaction.atomic
def update_vetting(v: Vetting, by, data: dict) -> Vetting:
    _vetting_staff(by)
    if v.status != "pending":
        raise StateConflict("Only a pending vetting can change.")
    changed = []
    for k, val in data.items():
        if val is not None:
            setattr(v, k, val)
            changed.append(k)
    if changed:
        v.save(update_fields=changed)
    return v


@transaction.atomic
def complete_vetting(v: Vetting, by) -> Vetting:
    _vetting_staff(by)
    if by.pk == v.person_id:
        raise Forbidden("You cannot vet yourself.")
    reasons = national_id_blockers({f"{v.person.full_name}": v.national_id_check})
    if v.references_evidence_id is None:
        reasons.append({"rule": "FR-CARE-002", "message": "References are missing"})
    if v.background_check_evidence_id is None:
        reasons.append({"rule": "FR-CARE-002", "message": "The background check is missing"})
    if reasons:
        raise RuleBlocked("The vetting is not complete.", code="vetting-incomplete", blocking_reasons=reasons)
    months = int(_cfg(v.country, "vetting.valid_months", 12))  # assumption [TO VERIFY]
    v.vetted_by = by
    v.vetted_at = _now()
    v.valid_until = timezone.localdate() + timedelta(days=30 * months)
    state.transition(v, "vetting", "vetted", actor=by, event="vetting.completed",
                     extra_fields=["vetted_by", "vetted_at", "valid_until"],
                     payload={"vetting_id": v.pk, "person_id": v.person_id, "kind": v.kind})
    _notify(v.person, "vetting_completed", obj=v, body="Your vetting with Tenmina is complete.")
    return v


@transaction.atomic
def revoke_vetting(v: Vetting, by, reason) -> Vetting:
    _vetting_staff(by)
    if not reason:
        raise Invalid("Give the reason.", code="validation-error")
    v.revoke_reason = reason
    return state.transition(v, "vetting", "revoked", actor=by, event="vetting.revoked", reason=reason,
                            extra_fields=["revoke_reason"], payload={"person_id": v.person_id, "kind": v.kind})


def expire_vettings(today=None) -> int:
    today = today or timezone.localdate()
    n = 0
    for v in Vetting.objects.filter(status="vetted", valid_until__lt=today):
        state.transition(v, "vetting", "expired", event="vetting.expired",
                         payload={"person_id": v.person_id, "kind": v.kind})
        n += 1
    return n


# ---------------------------------------------------------------- account status (used by DPR)

@transaction.atomic
def suspend_person(person, by, reason=""):
    if not has_role(by, "AD"):
        raise Forbidden("Only an administrator suspends an account.")
    state.transition(person, "person", "suspended", actor=by, reason=reason)
    revoke_tokens(person)
    return person


@transaction.atomic
def reactivate_person(person, by):
    if not has_role(by, "AD"):
        raise Forbidden("Only an administrator reactivates an account.")
    return state.transition(person, "person", "active", actor=by)


def mark_closing(person, by=None):
    """Account closed to new orders while open money matters finish (FR-APP-004)."""
    if person.status == "active":
        state.transition(person, "person", "closing", actor=by, event="account.closing",
                         payload={"person_id": person.pk})
    return person


@transaction.atomic
def close_account(person, by=None):
    """Revoke sign-in, sessions and tokens at once (US-APP-004 AC2)."""
    revoke_tokens(person)
    person.set_unusable_password()  # also ends every web session (session auth hash changes)
    person.is_active = False
    person.closed_at = _now()
    person.save(update_fields=["password", "is_active", "closed_at"])
    for g in RepresentativeGrant.objects.filter(Q(client=person) | Q(representative=person),
                                                status__in=["pending", "active"]):
        g.status = "revoked"
        g.revoked_at = _now()
        g.save(update_fields=["status", "revoked_at"])
    if person.status != "closed":
        state.transition(person, "person", "closed", actor=by, event="account.closed",
                         payload={"person_id": person.pk})
    return person


@transaction.atomic
def anonymise_person(person, by=None):
    """Crypto-shredding stand-in (6.10): personal fields overwritten. Rows
    other modules keep (cases, escrows, audit) hold the id only."""
    if person.status == "anonymised":
        return person
    if person.status != "closed":
        close_account(person, by)
        person.refresh_from_db()
    for acct in BankAccount.objects.filter(holder=person):
        if acct.verification_status in ("verified", "pending"):
            state.transition(acct, "bank_account", "suspended" if acct.verification_status == "verified"
                             else "rejected", reason="Account deleted")
    person.email = f"deleted+{person.pk}@anonymised.invalid"
    person.phone = ""
    person.full_name = "Deleted account"
    person.residence_country = ""
    person.mfa_secret = ""
    person.mfa_enabled = False
    person.anonymised_at = _now()
    state.transition(person, "person", "anonymised", actor=by, event="account.anonymised",
                     extra_fields=["email", "phone", "full_name", "residence_country", "mfa_secret", "mfa_enabled",
                                   "anonymised_at"], payload={"person_id": person.pk})
    for fm in FamilyMember.objects.filter(client=person).exclude(status="anonymised"):
        anonymise_family_member(fm)
    return person


def grant_rights_directly(person, right, *, preparer, approvers, country=None) -> RoleGrant:
    """For seeds and tests only: records an approved two-administrator request
    and the grant in one step, as if both administrators had approved with a
    fresh MFA step-up. Production grants go through request_rights()."""
    from core.models import Approval, ApprovalRequest

    now = _now()
    req = ApprovalRequest.objects.create(subject_type=_rights_subject(right), subject_id=person.pk,
                                         prepared_by=preparer, required=2, status="approved", closed_at=now,
                                         summary=f"{right} for {person.full_name} (seed)", country=country)
    for i, a in enumerate(approvers[:2]):
        Approval.objects.create(request=req, slot=f"approver_{i + 1}", approver=a, decision="approve", mfa_at=now)
    return grant_role(person, right, country=country, granted_by=preparer, approval_request=req)
