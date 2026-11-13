"""Sign-up, one-time codes, sign-in, lockout, password reset and MFA
(US-ACC-001, 002, 003, 009; TC-ACC-001 to 003, TC-ACC-009)."""
from datetime import timedelta

import pyotp
import pytest
from django.utils import timezone

from accounts.adapters import FakeOtpSender
from accounts.models import ApiToken, OneTimeCode, Person
from audit.models import AuditEvent
from notifications.models import Message

SIGNUP = {"email": "esi@example.com", "password": "a-long-password-1", "full_name": "Esi Owusu",
          "phone": "+447700900555", "residence_country": "GB", "privacy_notice_version": "1.0"}


def _code(dest, purpose="signup"):
    return FakeOtpSender.last_code(dest, purpose)


def test_signup_journey_with_two_codes(seeded, api):
    """US-ACC-001 AC1, US-DPR-001 AC1, TC-ACC-001-01: both codes confirm the
    account; the notice version is stored; then sign-in works."""
    c = api()
    r = c.post("/v1/auth/signup", SIGNUP)
    assert r.status_code == 201, r.content
    assert r.json()["verification"] == {"email": "sent", "phone": "sent"}
    p = Person.objects.get(email="esi@example.com")
    assert not p.is_verified
    r = c.post("/v1/auth/login", {"identifier": "esi@example.com", "password": SIGNUP["password"]})
    assert r.status_code == 403 and r.json()["code"] == "account-unverified"
    r = c.post("/v1/auth/otp/verify", {"identifier": "esi@example.com", "channel": "email",
                                       "code": _code("esi@example.com")})
    assert r.status_code == 200 and r.json()["verified"] is False
    r = c.post("/v1/auth/otp/verify", {"identifier": "+447700900555", "channel": "phone",
                                       "code": _code("+447700900555"), "mode": "token"})
    assert r.status_code == 200 and r.json()["verified"] is True and r.json()["access"]
    r = api().post("/v1/auth/login", {"identifier": "+447700900555", "password": SIGNUP["password"]})
    assert r.status_code == 200
    assert r.json()["privacy_notice_pending"] is None
    assert AuditEvent.objects.filter(action="person.signed_in", entity_id=str(p.pk)).exists()


def test_wrong_expired_and_used_codes_fail(seeded, api):
    """US-ACC-001 AC2, TC-ACC-001-02."""
    c = api()
    c.post("/v1/auth/signup", SIGNUP)
    good = _code("esi@example.com")
    bad = "111111" if good != "111111" else "222222"
    r = c.post("/v1/auth/otp/verify", {"identifier": "esi@example.com", "channel": "email", "code": bad})
    assert r.status_code == 422 and r.json()["code"] == "otp-invalid"
    OneTimeCode.objects.filter(destination="esi@example.com").update(expires_at=timezone.now() - timedelta(seconds=1))
    r = c.post("/v1/auth/otp/verify", {"identifier": "esi@example.com", "channel": "email", "code": good})
    assert r.status_code == 422
    c.post("/v1/auth/otp/send", {"identifier": "esi@example.com", "channel": "email"})
    new = _code("esi@example.com")
    assert c.post("/v1/auth/otp/verify", {"identifier": "esi@example.com", "channel": "email",
                                          "code": new}).status_code == 200
    r = c.post("/v1/auth/otp/verify", {"identifier": "esi@example.com", "channel": "email", "code": new})
    assert r.status_code == 422  # used


def test_code_attempts_are_limited(seeded, api):
    """10.3: 5 tries per code."""
    c = api()
    c.post("/v1/auth/signup", SIGNUP)
    good = _code("+447700900555")
    for _ in range(5):
        c.post("/v1/auth/otp/verify", {"identifier": "+447700900555", "channel": "phone", "code": "999998"})
    r = c.post("/v1/auth/otp/verify", {"identifier": "+447700900555", "channel": "phone", "code": good})
    assert r.status_code == 422


def test_dev_master_code_is_accepted_in_dev_only(seeded, settings):
    from accounts import services

    p = services.register(**SIGNUP)
    assert services.verify_signup_code(p.email, "email", "000000").email_verified_at
    settings.ENVIRONMENT = "prod"
    services.send_code(p, "phone", "signup")
    with pytest.raises(Exception):
        services.verify_signup_code(p.phone, "phone", "000000")


def test_duplicate_signup_is_refused_neutrally(seeded, api):
    """US-ACC-001 AC3, TC-ACC-001-03: no hint of whose account it is."""
    r1 = api().post("/v1/auth/signup", {**SIGNUP, "email": "ama@example.com"})
    r2 = api().post("/v1/auth/signup", {**SIGNUP, "phone": "+447700900101"})
    assert r1.status_code == r2.status_code == 422
    assert r1.json()["code"] == r2.json()["code"] == "signup-refused"
    assert r1.json()["detail"] == r2.json()["detail"]
    assert "ama" not in r1.json()["detail"].lower()


def test_signup_needs_the_current_privacy_notice(seeded, api):
    """TC-DPR-001-02: sign-up without acceptance is blocked."""
    r = api().post("/v1/auth/signup", {**SIGNUP, "privacy_notice_version": ""})
    assert r.status_code == 422 and r.json()["code"] == "privacy-notice-required"
    assert r.json()["privacy_notice_version"] == "1.0"


def test_sign_in_by_one_time_code_goes_only_to_verified_channel(seeded, api, people):
    """US-ACC-002 AC2."""
    ama = people["client"]
    c = api()
    assert c.post("/v1/auth/otp/send", {"identifier": ama.phone, "purpose": "login"}).status_code == 202
    code = _code(ama.phone, "login")
    r = c.post("/v1/auth/token", {"identifier": ama.phone, "otp": code})
    assert r.status_code == 200 and r.json()["access"]
    Person.objects.filter(pk=ama.pk).update(phone_verified_at=None)
    FakeOtpSender.sent.clear()
    c.post("/v1/auth/otp/send", {"identifier": ama.phone, "purpose": "login"})
    assert _code(ama.phone, "login") is None
    r = c.post("/v1/auth/otp/send", {"identifier": "nobody@example.com", "purpose": "login"})
    assert r.status_code == 202  # same answer whether or not the account exists


def test_lockout_notifies_and_expires(seeded, api, people):
    """US-ACC-009 AC1-3, TC-ACC-009-01/02: 4 failures do not lock, 5 do; the
    user is told; after 15 minutes the right password works."""
    ama = people["client"]
    c = api()
    for _ in range(4):
        assert c.post("/v1/auth/login", {"identifier": ama.email, "password": "nope-nope-nope"}).status_code == 401
    assert c.post("/v1/auth/login", {"identifier": ama.email, "password": "tenmina-dev-123"}).status_code == 200
    for _ in range(5):
        c.post("/v1/auth/login", {"identifier": ama.email, "password": "nope-nope-nope"})
    r = c.post("/v1/auth/login", {"identifier": ama.email, "password": "tenmina-dev-123"})
    assert r.status_code == 423 and r.json()["code"] == "account-locked"
    assert Message.objects.filter(person=ama, template="account_locked", channel="email").exists()
    Person.objects.filter(pk=ama.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
    assert c.post("/v1/auth/login", {"identifier": ama.email, "password": "tenmina-dev-123"}).status_code == 200


def test_password_reset_journey(seeded, api, people):
    ama = people["client"]
    raw, _ = ApiToken.issue(ama, "access", timedelta(minutes=10))
    c = api()
    assert c.post("/v1/auth/password-reset", {"identifier": ama.email}).status_code == 202
    code = _code(ama.email, "password_reset")
    r = c.post("/v1/auth/password-reset/confirm", {"identifier": ama.email, "code": "000001" if code != "000001"
                                                   else "000002", "new_password": "a-brand-new-pass-9"})
    assert r.status_code == 422
    r = c.post("/v1/auth/password-reset/confirm", {"identifier": ama.email, "code": code,
                                                   "new_password": "a-brand-new-pass-9"})
    assert r.status_code == 200
    assert ApiToken.objects.get(token_hash=ApiToken.hash(raw)).revoked_at is not None
    assert c.post("/v1/auth/login", {"identifier": ama.email, "password": "a-brand-new-pass-9"}).status_code == 200


def test_refresh_rotates_and_reuse_revokes_everything(seeded, api):
    r = api().post("/v1/auth/token", {"identifier": "kofi@example.com", "password": "tenmina-dev-123"})
    first = r.json()["refresh"]
    r2 = api().post("/v1/auth/token/refresh", {"refresh": first})
    assert r2.status_code == 200
    r3 = api().post("/v1/auth/refresh", {"refresh": first})
    assert r3.status_code == 401
    assert api().post("/v1/auth/refresh", {"refresh": r2.json()["refresh"]}).status_code == 401


def _bearer(api, email, code=None):
    data = {"identifier": email, "password": "tenmina-dev-123"}
    if code:
        data["code"] = code
    r = api().post("/v1/auth/token", data)
    assert r.status_code == 200, r.content
    c = api()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + r.json()["access"])
    return c


def test_staff_must_enrol_mfa_before_working(seeded, api, people):
    """US-ACC-003 AC1, TC-ACC-003-01/02: a staff member without MFA gets 403
    until enrolled; with MFA the code is required at sign-in."""
    cm = people["cm"]
    Person.objects.filter(pk=cm.pk).update(mfa_enabled=False, mfa_secret="")
    c = _bearer(api, cm.email)
    r = c.get("/v1/identity-checks")
    assert r.status_code == 403 and r.json()["code"] == "mfa-enrolment-required"
    assert c.get("/v1/me").status_code == 200
    secret = c.post("/v1/auth/mfa/setup").json()["secret"]
    assert c.post("/v1/auth/mfa/confirm", {"code": pyotp.TOTP(secret).now()}).status_code == 200
    assert c.get("/v1/identity-checks").status_code == 200
    r = api().post("/v1/auth/token", {"identifier": cm.email, "password": "tenmina-dev-123"})
    assert r.status_code == 401 and r.json()["code"] == "mfa-required"
    assert _bearer(api, cm.email, pyotp.TOTP(secret).now()).get("/v1/identity-checks").status_code == 200


def test_mfa_cannot_be_switched_off_for_staff(seeded, api, people, mfa):
    """US-ACC-003 AC3."""
    admin = people["admin"]
    c = api(admin)
    r = c.post(f"/v1/admin/people/{people['reviewer'].pk}/mfa-disable")
    assert r.status_code == 409 and r.json()["code"] == "mfa-mandatory"
    ama = people["client"]
    Person.objects.filter(pk=ama.pk).update(mfa_enabled=True, mfa_secret="JBSWY3DPEHPK3PXP")
    assert c.post(f"/v1/admin/people/{ama.pk}/mfa-disable").status_code == 200


def test_client_must_enrol_before_first_approval(seeded, people):
    """US-ACC-003 AC2: an approval needs a fresh step-up; without MFA there is none."""
    from core.views import require_mfa
    from core.errors import MfaRequired

    class R:
        auth = None
        session = {}

    with pytest.raises(MfaRequired):
        require_mfa(R())


def test_legacy_register_cannot_sign_in_until_verified(seeded, api):
    r = api().post("/v1/auth/register", {"email": "old@example.com", "password": "a-long-password-1",
                                         "full_name": "Old Client"})
    assert r.status_code == 201
    assert r.json()["privacy_notice_pending"] == "1.0"
    r = api().post("/v1/auth/login", {"email": "old@example.com", "password": "a-long-password-1"})
    assert r.status_code == 403 and r.json()["code"] == "account-unverified"


def test_profile_preferences(seeded, api, people):
    """US-ACC-010: preferred channel and channels turned off."""
    c = api(people["client"])
    r = c.patch("/v1/me", {"preferred_channel": "whatsapp", "channels_off": ["sms"]}, format="json")
    assert r.status_code == 200 and r.json()["preferred_channel"] == "whatsapp"
    assert r.json()["channels_off"] == ["sms"]
    r = c.patch("/v1/me", {"channels_off": ["whatsapp"]}, format="json")
    assert r.status_code == 422
    r = c.patch("/v1/me", {"roles": ["AD"], "email": "x@example.com"}, format="json")
    assert sorted(r.json()["roles"]) == ["CL"] and r.json()["email"] == "ama@example.com"
