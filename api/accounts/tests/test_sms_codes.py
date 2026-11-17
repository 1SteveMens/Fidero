"""SMS codes as the clients' second factor (FR-ACC-015, decision of
17 November 2026; TC-ACC-015-01 to TC-ACC-015-10)."""
import base64
from datetime import timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts import services
from accounts.adapters import FakeOtpSender, FakeSimSwapCheck
from accounts.models import ApiToken, ApprovalKey, OneTimeCode, Person
from audit.models import AuditEvent
from core import approvals
from core.models import Approval
from notifications.adapters import FakeSmsProvider
from notifications.models import Message

PASSWORD = "tenmina-dev-123"


def _sms(phone, purpose):
    return FakeOtpSender.last_code(phone, purpose)


def _wrong(code):
    return "123456" if code != "123456" else "654321"


@pytest.fixture(autouse=True)
def _clean():
    FakeSimSwapCheck.swapped = {}
    FakeSmsProvider.fail = False
    yield
    FakeSimSwapCheck.swapped = {}


@pytest.fixture
def ama(people):
    p = people["client"]
    assert not p.mfa_enabled and p.phone_verified_at
    return p


def test_sign_in_with_a_code_by_sms(seeded, api, ama):
    """TC-ACC-015-01: a client with no authenticator gets mfa-required with
    method sms and a masked number; the code from the SMS signs in; on the
    web the session and in the apps the token carry the method sms_code."""
    c = api()
    r = c.post("/v1/auth/login", {"identifier": ama.email, "password": PASSWORD}, format="json")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "mfa-required" and body["method"] == "sms"
    assert body["sent_to"] == "+44 •••• 101" and body["expires_in"] == 300
    code = _sms(ama.phone, "mfa_login")
    r = c.post("/v1/auth/login", {"identifier": ama.email, "password": PASSWORD, "code": code}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["second_factor"] == "sms" and r.json()["phone_masked"] == "+44 •••• 101"
    assert c.session["mfa_method"] == "sms_code"

    t = api()
    t.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD}, format="json")
    r = t.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD,
                                  "code": _sms(ama.phone, "mfa_login")}, format="json")
    assert r.status_code == 200
    assert ApiToken.objects.get(token_hash=ApiToken.hash(r.json()["access"])).mfa_method == "sms_code"


def test_codes_are_single_use_short_lived_hashed_and_limited_to_five_tries(seeded, api, ama):
    """TC-ACC-015-02: 6 digits, 5 minutes, used once, 5 wrong tries then a
    new code; only a hash is stored; the SMS warns never to share it and the
    delivery log hides the code."""
    c = api()
    c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD}, format="json")
    code = _sms(ama.phone, "mfa_login")
    assert len(code) == 6 and code.isdigit()
    otp = OneTimeCode.objects.filter(person=ama, purpose="mfa_login").latest("created_at")
    assert otp.code_hash != code and code not in otp.code_hash
    assert abs((otp.expires_at - otp.created_at) - timedelta(minutes=5)) < timedelta(seconds=2)
    sms = FakeSmsProvider.sent[-1]
    assert sms["to"] == ama.phone and code in sms["text"]
    assert "Do not share this code. Tenmina will never call you for it." in sms["text"]
    msg = Message.objects.filter(template="security_code", to_address=ama.phone).latest("created_at")
    assert code not in msg.body and msg.status == "sent"

    for i in range(5):
        r = c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD, "code": _wrong(code)},
                   format="json")
        assert r.status_code in (422, 423), r.content
        if i < 4:
            assert r.json()["code"] == "mfa-invalid"
    ama.refresh_from_db()
    ama.locked_until = None
    ama.save(update_fields=["locked_until"])
    r = c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD, "code": code}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "mfa-code-used-up"

    c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD}, format="json")
    code = _sms(ama.phone, "mfa_login")
    assert c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD, "code": code},
                  format="json").status_code == 200
    r = c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD, "code": code}, format="json")
    assert r.status_code == 422  # used once
    c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD}, format="json")
    OneTimeCode.objects.filter(person=ama, purpose="mfa_login").update(
        expires_at=timezone.now() - timedelta(seconds=1))
    r = c.post("/v1/auth/token", {"identifier": ama.email, "password": PASSWORD,
                                  "code": _sms(ama.phone, "mfa_login")}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "mfa-code-expired"
    assert AuditEvent.objects.filter(action="mfa.sms_refused", entity_id=str(ama.pk)).exists()


def test_sends_are_rate_limited(seeded, api, ama):
    """TC-ACC-015-03: at most 3 codes in 10 minutes and 10 a day [TO VERIFY]."""
    c = api(ama)
    for _ in range(3):
        assert c.post("/v1/auth/mfa/sms").status_code == 202
    r = c.post("/v1/auth/mfa/sms")
    assert r.status_code == 429 and r.json()["code"] == "rate-limited"
    OneTimeCode.objects.filter(person=ama).update(created_at=timezone.now() - timedelta(hours=1))
    for _ in range(3):
        assert c.post("/v1/auth/mfa/sms").status_code == 202
    OneTimeCode.objects.filter(person=ama).update(created_at=timezone.now() - timedelta(hours=2))
    for _ in range(3):
        assert c.post("/v1/auth/mfa/sms").status_code == 202
    OneTimeCode.objects.filter(person=ama).update(created_at=timezone.now() - timedelta(hours=3))
    assert c.post("/v1/auth/mfa/sms").status_code == 202
    r = c.post("/v1/auth/mfa/sms")
    assert r.status_code == 429 and "today" in r.json()["detail"]


def test_sms_step_up_records_sms_code_on_the_client_approval(seeded, api, ama, gh, people):
    """TC-ACC-015-04: POST /v1/auth/mfa/sms, then a step-up with method sms,
    then the client's approval records sms_code. A code in the approval body
    itself is not accepted for SMS: tries count only at the step-up."""
    from fees.tests.helpers import checked_invoice, new_institution

    inst = new_institution(gh, people, returns_confirmation=True)
    inv = checked_invoice(gh, people, inst, ama.family_members.get(full_name="Akosua Mensah"), amount="900.00")
    c = api(ama)
    pv = c.get(f"/v1/invoices/{inv.pk}/approval-preview").json()
    approve = {"confirm_amount": {"amount": "900.00", "currency": "GHS"},
               "confirm_payee_account_name": pv["institution"]["account_name"]}
    r = c.post(f"/v1/invoices/{inv.pk}/client-approval", approve, format="json")
    assert r.status_code == 401 and r.json()["code"] == "mfa-required"
    r = c.post("/v1/auth/mfa/sms")
    assert r.status_code == 202 and r.json()["sent_to"] == "+44 •••• 101"
    code = _sms(ama.phone, "mfa_step_up")
    r = c.post(f"/v1/invoices/{inv.pk}/client-approval", {**approve, "code": code}, format="json")
    assert r.status_code == 401  # an SMS code goes to the step-up, never with the action
    r = c.post("/v1/auth/mfa/step-up", {"method": "sms", "code": _wrong(code)}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "mfa-invalid"
    r = c.post("/v1/auth/mfa/step-up", {"method": "sms", "code": code}, format="json")
    assert r.status_code == 200 and r.json()["mfa_method"] == "sms_code" and r.json()["valid_for_seconds"] == 300
    r = c.post(f"/v1/invoices/{inv.pk}/client-approval", approve, format="json")
    assert r.status_code == 200, r.content
    inv.refresh_from_db()
    assert inv.client_approval_method == "sms_code"
    assert AuditEvent.objects.filter(action="mfa.stepped_up", entity_id=str(ama.pk),
                                     data__method="sms_code").exists()

    # Without `method`, a code is an SMS code for a client with no authenticator (the web's stepUp(code)).
    c.post("/v1/auth/mfa/sms")
    r = c.post("/v1/auth/mfa/step-up", {"code": _sms(ama.phone, "mfa_step_up")}, format="json")
    assert r.status_code == 200 and r.json()["mfa_method"] == "sms_code"


def test_staff_never_use_sms(seeded, api, people):
    """TC-ACC-015-05: staff and rights holders are refused SMS with a clear
    problem, in the service, in core.approvals and in PostgreSQL."""
    rv = people["reviewer"]
    c = api(rv)
    r = c.post("/v1/auth/mfa/sms")
    assert r.status_code == 403 and r.json()["code"] == "sms-not-allowed"
    assert "authenticator" in r.json()["detail"]
    r = c.post("/v1/auth/mfa/step-up", {"method": "sms", "code": "123456"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "sms-not-allowed"
    assert c.get("/v1/me").json()["second_factor"] == "authenticator"
    assert services.second_factor(rv) == "authenticator"
    rv.mfa_enabled = False
    assert services.second_factor(rv) == "none"  # never "sms"
    r = api().post("/v1/auth/login", {"identifier": rv.email, "password": PASSWORD}, format="json")
    assert r.status_code == 401 and r.json()["method"] == "totp"

    from core.errors import MfaRequired
    from core.mfa import SMS_CODE, MfaAt

    req = approvals.request_approval("bulk_export", seeded["gh"].pk, people["cm"])
    with pytest.raises(MfaRequired):
        approvals.decide(req, people["reviewer2"], mfa_at=MfaAt.of(timezone.now(), SMS_CODE))
    with pytest.raises(IntegrityError), transaction.atomic():
        Approval.objects.create(request=req, slot="approver_1", approver=people["reviewer2"], decision="approve",
                                mfa_at=timezone.now(), mfa_method="sms_code")


def test_number_change_pauses_sms_approvals_for_72_hours(seeded, api, ama):
    """TC-ACC-015-06: a new number is confirmed by a code sent to it (with the
    password); then SMS approvals pause for 72 hours with the reason shown,
    Face ID phones are removed, and the person is told."""
    c = api(ama)
    key = ApprovalKey.objects.create(person=ama, public_key="x", key_sha256="a" * 64, device_name="Old iPhone",
                                     platform="ios")
    r = c.post("/v1/me/phone", {"phone": "+447700900999", "password": "wrong-password"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "bad-credentials"
    r = c.post("/v1/me/phone", {"phone": "+447700900999", "password": PASSWORD}, format="json")
    assert r.status_code == 202 and r.json()["sent_to"] == "+44 •••• 999"
    ama.refresh_from_db()
    assert ama.phone == "+447700900101"  # nothing changes until the code comes back
    r = c.post("/v1/me/phone/confirm", {"code": _sms("+447700900999", "phone_change")}, format="json")
    assert r.status_code == 200, r.content
    me = r.json()
    assert me["phone"] == "+447700900999" and me["phone_verified"]
    assert me["sms_pause"]["reason"] == "phone_changed"
    assert "paused until" in me["sms_pause"]["detail"] and "wait safely" in me["sms_pause"]["detail"]
    key.refresh_from_db()
    assert key.status == "revoked" and key.revoke_reason == "phone_changed"
    assert Message.objects.filter(person=ama, template="phone_changed", channel="email").exists()

    ama.refresh_from_db()
    r = api(ama).post("/v1/auth/mfa/sms")
    assert r.status_code == 409 and r.json()["code"] == "sms-paused"
    assert r.json()["reason"] == "phone_changed" and r.json()["paused_until"]
    assert services.second_factor(ama) == "sms"  # sign-in by SMS still works; approvals wait
    Person.objects.filter(pk=ama.pk).update(phone_changed_at=timezone.now() - timedelta(hours=72, minutes=1))
    ama.refresh_from_db()
    assert api(ama).get("/v1/me").json()["sms_pause"] is None
    assert api(ama).post("/v1/auth/mfa/sms").status_code == 202


def test_a_reported_sim_swap_pauses_sms_approvals(seeded, api, ama):
    """TC-ACC-015-07: the SIM-swap check (fake adapter, provider [TO VERIFY])
    reports a recent swap; SMS approvals pause; the authenticator still works."""
    FakeSimSwapCheck.swapped = {ama.phone: timezone.now() - timedelta(hours=5)}
    c = api(ama)
    r = c.post("/v1/auth/mfa/sms")
    assert r.status_code == 409 and r.json()["reason"] == "sim_swap"
    assert "SIM card" in r.json()["detail"]
    ama.refresh_from_db()
    assert ama.sim_swapped_at is not None
    assert c.get("/v1/me").json()["sms_pause"]["reason"] == "sim_swap"
    assert AuditEvent.objects.filter(action="sim_swap.reported", entity_id=str(ama.pk)).exists()
    # An SMS code sent before the swap was reported does not step up either.
    OneTimeCode.objects.create(person=ama, channel="phone", purpose="mfa_step_up", destination=ama.phone,
                               code_hash="x", expires_at=timezone.now() + timedelta(minutes=5))
    r = c.post("/v1/auth/mfa/step-up", {"method": "sms", "code": "000000"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "sms-paused"


def test_face_id_enrols_with_an_sms_code(seeded, api, ama):
    """TC-ACC-015-08: a client with no authenticator turns on Face ID with an
    SMS code; not while SMS approvals are paused."""
    c = api(ama)
    priv = ed25519.Ed25519PrivateKey.generate()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    body = {"public_key": base64.b64encode(raw).decode(), "device_name": "Ama's iPhone", "platform": "ios"}
    r = c.post("/v1/auth/approval-keys", body, format="json")
    assert r.status_code == 401 and "text" in r.json()["detail"]
    c.post("/v1/auth/mfa/sms")
    r = c.post("/v1/auth/approval-keys", {**body, "code": _sms(ama.phone, "mfa_step_up")}, format="json")
    assert r.status_code == 201, r.content
    assert AuditEvent.objects.filter(action="approval_key.enrolled", data__with="sms_code").exists()
    assert c.post("/v1/auth/mfa/challenge").status_code == 201

    Person.objects.filter(pk=ama.pk).update(phone_changed_at=timezone.now())
    ama.refresh_from_db()
    priv2 = ed25519.Ed25519PrivateKey.generate()
    raw2 = priv2.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    OneTimeCode.objects.create(person=ama, channel="phone", purpose="mfa_step_up", destination=ama.phone,
                               code_hash="x", expires_at=timezone.now() + timedelta(minutes=5))
    r = api(ama).post("/v1/auth/approval-keys", {**body, "public_key": base64.b64encode(raw2).decode(),
                                                 "code": "000000"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "sms-paused"


def test_password_reset_needs_the_email_and_the_sms_code(seeded, api, ama):
    """TC-ACC-015-09: for a client whose second factor is SMS, a reset needs
    the code from the email and the code by SMS, so a stolen SIM alone never
    takes over the account. The reset revokes approval keys; a lock does not."""
    c = api()
    assert c.post("/v1/auth/password-reset", {"identifier": ama.email}, format="json").status_code == 202
    email_code = FakeOtpSender.last_code(ama.email, "password_reset")
    sms_code = _sms(ama.phone, "password_reset")
    assert email_code and sms_code
    r = c.post("/v1/auth/password-reset/confirm", {"identifier": ama.email, "code": email_code,
                                                   "new_password": "a-brand-new-pass-9"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "sms-code-required"
    r = c.post("/v1/auth/password-reset/confirm", {"identifier": ama.email, "code": email_code,
                                                   "sms_code": sms_code, "new_password": "a-brand-new-pass-9"},
               format="json")
    assert r.status_code == 200, r.content
    r = c.post("/v1/auth/token", {"identifier": ama.email, "password": "a-brand-new-pass-9"}, format="json")
    assert r.status_code == 401 and r.json()["method"] == "sms"


def test_authenticator_stays_for_clients_who_set_it_up(seeded, api, people, mfa):
    """TC-ACC-015-10: a client with an authenticator keeps it at sign-in and
    for approvals; asking for an SMS step-up explicitly still works."""
    kofi = people["client2"]
    c = api(kofi)
    mfa(c, kofi)
    kofi.refresh_from_db()
    assert c.get("/v1/me").json()["second_factor"] == "authenticator"
    r = api().post("/v1/auth/token", {"identifier": kofi.email, "password": PASSWORD}, format="json")
    assert r.status_code == 401 and r.json()["method"] == "totp"
    assert c.post("/v1/auth/mfa/sms").status_code == 202
    r = c.post("/v1/auth/mfa/step-up", {"method": "sms", "code": _sms(kofi.phone, "mfa_step_up")}, format="json")
    assert r.status_code == 200 and r.json()["mfa_method"] == "sms_code"
