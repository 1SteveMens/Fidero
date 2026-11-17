"""Face ID or fingerprint for approvals: approval keys per person and phone
(FR-ACC-014, ADR-13; TC-ACC-014-01 to TC-ACC-014-09)."""
import base64
from datetime import timedelta

import pyotp
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import ApiToken, ApprovalKey, MfaChallenge
from accounts.seed import DEV_MFA_SECRET
from audit.models import AuditEvent
from core import approvals
from core.models import Approval

PASSWORD = "tenmina-dev-123"


def _with_mfa(person):
    if not person.mfa_enabled:
        person.mfa_secret, person.mfa_enabled = DEV_MFA_SECRET, True
        person.save(update_fields=["mfa_secret", "mfa_enabled"])
    return person


def _code(person):
    return pyotp.TOTP(person.mfa_secret).now()


def _raw_b64(priv):
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _enrol(client, person, priv=None, **extra):
    priv = priv or ed25519.Ed25519PrivateKey.generate()
    body = {"public_key": _raw_b64(priv), "device_name": "My iPhone", "platform": "ios", "code": _code(person),
            **extra}
    r = client.post("/v1/auth/approval-keys", body, format="json")
    return r, priv


def _sign(priv, message):
    return base64.urlsafe_b64encode(priv.sign(message.encode())).rstrip(b"=").decode()


def _biometric_step_up(client, key_id, priv, *, challenge=None, message=None):
    if challenge is None:
        r = client.post("/v1/auth/mfa/challenge")
        assert r.status_code == 201, r.content
        challenge, message = r.json()["challenge"], r.json()["message"]
    message = message or f"tenmina-step-up:v1:{challenge}"
    return client.post("/v1/auth/mfa/step-up", {"key_id": key_id, "challenge": challenge,
                                                "signature": _sign(priv, message)}, format="json")


@pytest.fixture
def ama(people):
    return _with_mfa(people["client"])


def test_enrol_needs_a_fresh_authenticator_code(seeded, api, ama):
    """FR-ACC-014, TC-ACC-014-01: a password alone never enrols a key; a
    wrong code is refused; the code itself or a code step-up in the last 5
    minutes enrols, and the enrolment is audited."""
    c = api(ama)
    priv = ed25519.Ed25519PrivateKey.generate()
    body = {"public_key": _raw_b64(priv), "device_name": "Ama's iPhone", "platform": "ios"}
    r = c.post("/v1/auth/approval-keys", body, format="json")
    assert r.status_code == 401 and r.json()["code"] == "mfa-required"
    r = c.post("/v1/auth/approval-keys", {**body, "code": "000000" if _code(ama) != "000000" else "111111"},
               format="json")
    assert r.status_code == 422 and r.json()["code"] == "mfa-invalid"
    assert not ApprovalKey.objects.filter(person=ama).exists()

    assert c.post("/v1/auth/mfa/step-up", {"code": _code(ama)}, format="json").status_code == 200
    r = c.post("/v1/auth/approval-keys", body, format="json")
    assert r.status_code == 201, r.content
    key = ApprovalKey.objects.get(pk=r.json()["id"])
    assert key.status == "active" and key.platform == "ios" and key.key_alg == "EdDSA"
    assert AuditEvent.objects.filter(action="approval_key.enrolled", entity_id=str(key.pk)).exists()


def test_enrol_refuses_a_biometric_step_up_and_stale_code(seeded, api, ama):
    """FR-ACC-014, TC-ACC-014-01: one approval key cannot enrol another, and a
    code step-up older than 5 minutes does not count."""
    c = api(ama)
    r, priv = _enrol(c, ama)
    assert r.status_code == 201
    assert _biometric_step_up(c, r.json()["id"], priv).status_code == 200
    other = ed25519.Ed25519PrivateKey.generate()
    body = {"public_key": _raw_b64(other), "device_name": "Second phone", "platform": "android"}
    r = c.post("/v1/auth/approval-keys", body, format="json")
    assert r.status_code == 401 and r.json()["code"] == "mfa-required"

    session = c.session
    session["mfa_at"] = (timezone.now() - timedelta(minutes=6)).isoformat()
    session["mfa_method"] = "totp"
    session.save()
    r = c.post("/v1/auth/approval-keys", body, format="json")
    assert r.status_code == 401


def test_enrol_refuses_bad_and_reused_keys(seeded, api, ama, people):
    """FR-ACC-014: only Ed25519 keys; one key belongs to one person."""
    c = api(ama)
    r = c.post("/v1/auth/approval-keys", {"public_key": base64.b64encode(b"x" * 31).decode(), "code": _code(ama),
                                          "device_name": "Phone", "platform": "ios"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "approval-key-invalid"
    r, priv = _enrol(c, ama)
    assert r.status_code == 201
    kofi = _with_mfa(people["client2"])
    r, _ = _enrol(api(kofi), kofi, priv=priv)
    assert r.status_code == 409 and r.json()["code"] == "approval-key-exists"
    r = c.post("/v1/auth/approval-keys", {"public_key": _raw_b64(ed25519.Ed25519PrivateKey.generate()),
                                          "code": _code(ama), "device_name": "Browser", "platform": "web"},
               format="json")
    assert r.status_code == 400


def test_enrol_accepts_spki(seeded, api, ama):
    """FR-ACC-014: a DER SubjectPublicKeyInfo works as well as raw bytes."""
    priv = ed25519.Ed25519PrivateKey.generate()
    der = priv.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    c = api(ama)
    r = c.post("/v1/auth/approval-keys", {"public_key": base64.b64encode(der).decode(), "code": _code(ama),
                                          "device_name": "Pixel", "platform": "android"}, format="json")
    assert r.status_code == 201, r.content
    assert _biometric_step_up(c, r.json()["id"], priv).status_code == 200


def test_biometric_step_up_records_the_method_on_the_approval(seeded, api, people):
    """FR-ACC-014, ADR-13, TC-ACC-014-02: a signed challenge is a fresh MFA
    step-up; the approval records mfa_method = device_biometric; the step-up is
    audited."""
    rv = people["reviewer"]
    c = api(rv)
    r, priv = _enrol(c, rv)
    key_id = r.json()["id"]
    r = _biometric_step_up(c, key_id, priv)
    assert r.status_code == 200, r.content
    assert r.json()["mfa_method"] == "device_biometric" and r.json()["valid_for_seconds"] == 300
    assert AuditEvent.objects.filter(action="mfa.stepped_up", entity_id=key_id).exists()
    assert ApprovalKey.objects.get(pk=key_id).last_used_at is not None

    req = approvals.request_approval("bulk_export", seeded["gh"].pk, people["cm"])
    r = c.post(f"/v1/approvals/{req.pk}/decisions", {"decision": "approve"}, format="json")
    assert r.status_code == 200, r.content
    a = Approval.objects.get(request=req, approver=rv)
    assert a.mfa_method == "device_biometric"
    assert r.json()["approvals"][0]["mfa_method"] == "device_biometric"

    rv2 = people["reviewer2"]
    c2 = api(rv2)
    assert c2.post("/v1/auth/mfa/step-up", {"code": _code(_with_mfa(rv2))}, format="json").status_code == 200
    assert c2.post(f"/v1/approvals/{req.pk}/decisions", {"decision": "approve"}, format="json").status_code == 200
    assert Approval.objects.get(request=req, approver=rv2).mfa_method == "totp"


def test_bearer_token_carries_the_method(seeded, api, ama):
    """FR-ACC-014: in the apps the step-up and its method sit on the access token."""
    c = api()
    r = c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD, "code": _code(ama)},
               format="json")
    assert r.status_code == 200, r.content
    c.credentials(HTTP_AUTHORIZATION="Bearer " + r.json()["access"], HTTP_TENMINA_APP="client/ios/1.0.0")
    r, priv = _enrol(c, ama)
    assert r.status_code == 201
    assert ApprovalKey.objects.get(pk=r.json()["id"]).app == "client/ios/1.0.0"
    assert _biometric_step_up(c, r.json()["id"], priv).status_code == 200
    tok = ApiToken.objects.filter(person=ama, kind="access").order_by("-created_at").first()
    assert tok.mfa_method == "device_biometric" and tok.mfa_at is not None


def test_wrong_signature_is_refused_and_spends_the_challenge(seeded, api, ama):
    """FR-ACC-014, TC-ACC-014-03: a signature from another key or over other
    text is refused, audited, and the challenge cannot be tried again."""
    c = api(ama)
    r, priv = _enrol(c, ama)
    key_id = r.json()["id"]
    ch = c.post("/v1/auth/mfa/challenge").json()
    stranger = ed25519.Ed25519PrivateKey.generate()
    r = c.post("/v1/auth/mfa/step-up", {"key_id": key_id, "challenge": ch["challenge"],
                                        "signature": _sign(stranger, ch["message"])}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "mfa-signature-invalid"
    assert AuditEvent.objects.filter(action="mfa.step_up_refused", entity_id=str(ama.pk)).exists()
    r = _biometric_step_up(c, key_id, priv, challenge=ch["challenge"], message=ch["message"])
    assert r.status_code == 422 and r.json()["code"] == "mfa-challenge-invalid"

    ch = c.post("/v1/auth/mfa/challenge").json()
    r = c.post("/v1/auth/mfa/step-up", {"key_id": key_id, "challenge": ch["challenge"],
                                        "signature": _sign(priv, ch["challenge"])}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "mfa-signature-invalid"
    r = c.post("/v1/auth/mfa/step-up", {"key_id": key_id, "challenge": "", "signature": "abc"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "mfa-challenge-invalid"


def test_reused_and_expired_challenges_are_refused(seeded, api, ama):
    """FR-ACC-014, TC-ACC-014-04: a challenge works once and for 2 minutes."""
    c = api(ama)
    r, priv = _enrol(c, ama)
    key_id = r.json()["id"]
    ch = c.post("/v1/auth/mfa/challenge").json()
    assert _biometric_step_up(c, key_id, priv, challenge=ch["challenge"]).status_code == 200
    r = _biometric_step_up(c, key_id, priv, challenge=ch["challenge"])
    assert r.status_code == 422 and r.json()["code"] == "mfa-challenge-invalid"

    old = MfaChallenge.objects.create(person=ama, challenge="expired-challenge-0001",
                                      expires_at=timezone.now() - timedelta(seconds=1))
    r = _biometric_step_up(c, key_id, priv, challenge=old.challenge)
    assert r.status_code == 422 and r.json()["code"] == "mfa-challenge-invalid"
    issued = MfaChallenge.objects.get(challenge=ch["challenge"])
    assert issued.expires_at - issued.created_at <= timedelta(minutes=2, seconds=1)


def test_revoked_key_is_refused(seeded, api, ama):
    """FR-ACC-014, TC-ACC-014-05: the person removes a phone in Account; its
    key no longer steps up; the revocation is audited."""
    c = api(ama)
    r, priv = _enrol(c, ama)
    key_id = r.json()["id"]
    listed = c.get("/v1/me/approval-keys").json()["items"]
    assert [k["id"] for k in listed] == [key_id] and listed[0]["status"] == "active"
    assert c.delete(f"/v1/me/approval-keys/{key_id}").status_code == 204
    assert AuditEvent.objects.filter(action="approval_key.revoked", entity_id=key_id).exists()
    assert c.get("/v1/me/approval-keys", {"status": "active"}).json()["items"] == []
    r = _biometric_step_up(c, key_id, priv)
    assert r.status_code == 422 and r.json()["code"] == "approval-key-revoked"
    assert c.post("/v1/auth/mfa/step-up", {"code": _code(ama)}, format="json").status_code == 200


def test_another_persons_key_and_challenge_are_refused(seeded, api, ama, people):
    """FR-ACC-014, TC-ACC-014-06: a key or a challenge of one person never
    steps up another, and nobody lists or removes another person's phones."""
    kofi = _with_mfa(people["client2"])
    ck, ca = api(kofi), api(ama)
    r, kofi_priv = _enrol(ck, kofi)
    kofi_key = r.json()["id"]
    r = _biometric_step_up(ca, kofi_key, kofi_priv)
    assert r.status_code == 422 and r.json()["code"] == "approval-key-unknown"
    assert ca.get("/v1/me/approval-keys").json()["items"] == []
    assert ca.delete(f"/v1/me/approval-keys/{kofi_key}").status_code == 404

    r, ama_priv = _enrol(ca, ama)
    ch = ck.post("/v1/auth/mfa/challenge").json()
    r = _biometric_step_up(ca, r.json()["id"], ama_priv, challenge=ch["challenge"])
    assert r.status_code == 422 and r.json()["code"] == "mfa-challenge-invalid"


def test_password_reset_suspension_and_mfa_off_revoke_every_key_but_a_lock_does_not(seeded, api, ama, people):
    """FR-ACC-014, TC-ACC-014-07: a password reset, a suspension or switching
    MFA off revokes every approval key. An account lock does not: anyone who
    knows the email address could lock the account to wipe the client's
    Face ID phones."""
    from accounts import services
    from accounts.adapters import FakeOtpSender

    c = api(ama)
    _enrol(c, ama)
    _enrol(c, ama, device_name="iPad")
    assert ApprovalKey.objects.filter(person=ama, status="active").count() == 2
    api().post("/v1/auth/password-reset", {"identifier": ama.email}, format="json")
    r = api().post("/v1/auth/password-reset/confirm", {"identifier": ama.email, "new_password": "a-new-password-22",
                                                       "code": FakeOtpSender.last_code(ama.email, "password_reset")},
                   format="json")
    assert r.status_code == 200, r.content
    assert set(ApprovalKey.objects.filter(person=ama).values_list("revoke_reason", flat=True)) == {"password_reset"}

    _enrol(c, ama)
    for _ in range(5):
        api().post("/v1/auth/login", {"identifier": ama.email, "password": "wrong-password"}, format="json")
    ama.refresh_from_db()
    assert ama.is_locked
    assert ApprovalKey.objects.filter(person=ama, status="active").count() == 1
    assert not ApprovalKey.objects.filter(person=ama, revoke_reason="account_locked").exists()

    ama.locked_until = None
    ama.save(update_fields=["locked_until"])
    _enrol(c, ama)
    services.disable_mfa(ama, ama)
    assert ApprovalKey.objects.filter(person=ama, revoke_reason="mfa_disabled").count() == 2

    kofi = _with_mfa(people["client2"])
    _enrol(api(kofi), kofi)
    services.suspend_person(kofi, people["admin"], reason="test")
    assert ApprovalKey.objects.filter(person=kofi, revoke_reason="suspended").count() == 1


def test_database_keeps_challenges_single_use_and_revocations_final(seeded, api, ama):
    """FR-ACC-014, ADR-02: the rules hold in PostgreSQL too."""
    c = api(ama)
    r, _ = _enrol(c, ama)
    key = ApprovalKey.objects.get(pk=r.json()["id"])
    c.delete(f"/v1/me/approval-keys/{key.pk}")
    with pytest.raises(IntegrityError), transaction.atomic():
        ApprovalKey.objects.filter(pk=key.pk).update(status="active", revoked_at=None)
    ch = MfaChallenge.objects.create(person=ama, challenge="db-rule-challenge", used_at=timezone.now(),
                                     expires_at=timezone.now() + timedelta(minutes=2))
    with pytest.raises(IntegrityError), transaction.atomic():
        MfaChallenge.objects.filter(pk=ch.pk).update(used_at=None)
    req = approvals.request_approval("refund", seeded["gh"].pk, ama)
    from accounts.models import Person

    rv = Person.objects.get(email="rv1@tenmina.test")
    with pytest.raises(IntegrityError), transaction.atomic():
        Approval.objects.create(request=req, slot="approver_1", approver=rv, decision="approve",
                                mfa_at=timezone.now(), mfa_method="sms")


def test_no_second_factor_means_no_keys(seeded, api, people):
    """FR-ACC-014, FR-ACC-015: a person with no authenticator and no confirmed
    number (so no SMS codes) sets one of them up first."""
    kofi = people["client2"]
    kofi.mfa_enabled, kofi.phone_verified_at = False, None
    kofi.save(update_fields=["mfa_enabled", "phone_verified_at"])
    c = api(kofi)
    r = c.post("/v1/auth/mfa/challenge")
    assert r.status_code == 409 and r.json()["code"] == "mfa-not-set-up"
    r = c.post("/v1/auth/approval-keys", {"public_key": _raw_b64(ed25519.Ed25519PrivateKey.generate()),
                                          "device_name": "Phone", "platform": "ios", "code": "123456"},
               format="json")
    assert r.status_code == 409 and r.json()["code"] == "mfa-not-set-up"
