import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from audit.models import AuditEvent
from audit.services import verify_chain
from core import approvals, state
from core.errors import MfaRequired, SameApprover, StateConflict
from countries.models import Country


def test_transition_rules_and_audit(seeded):
    ng = Country.objects.get(code="NG")
    with pytest.raises(StateConflict):
        state.transition(ng, "country", "active")
    state.transition(ng, "country", "manual_phase", actor=seeded["people"]["admin"])
    assert AuditEvent.objects.filter(entity="country", action="country.manual_phase").exists()


def test_database_rejects_status_change_outside_the_machine(seeded):
    ng = Country.objects.get(code="NG")
    with pytest.raises(IntegrityError), transaction.atomic():
        Country.objects.filter(pk=ng.pk).update(status="active")


def _entries(n=3):
    from audit.services import record

    for i in range(n):
        record(action="test.entry", entity="test", entity_id=i, data={"i": i})


def test_audit_chain_verifies_and_is_append_only(seeded):
    before = verify_chain()["checked"]  # module seeds write audit entries too
    _entries()
    assert verify_chain() == {"ok": True, "checked": before + 3, "broken_at": None}
    with pytest.raises(Exception), transaction.atomic():
        AuditEvent.objects.all().update(action="tampered")


def test_audit_chain_detects_tampering(seeded):
    _entries()
    with connection.cursor() as c:
        c.execute("ALTER TABLE aud_event DISABLE TRIGGER trg_aud_event_append_only")
        c.execute("UPDATE aud_event SET action = 'x' WHERE seq = (SELECT min(seq) FROM aud_event)")
        c.execute("ALTER TABLE aud_event ENABLE TRIGGER trg_aud_event_append_only")
    assert verify_chain()["ok"] is False


def test_two_person_approval(seeded):
    p = seeded["people"]
    req = approvals.request_approval("refund", seeded["gh"].pk, p["cm"])
    now = timezone.now()
    with pytest.raises(SameApprover):
        approvals.decide(req, p["cm"], mfa_at=now)
    with pytest.raises(MfaRequired):
        approvals.decide(req, p["reviewer"], mfa_at=None)
    approvals.decide(req, p["reviewer"], mfa_at=now)
    with pytest.raises(SameApprover):
        approvals.decide(req, p["reviewer"], mfa_at=now)
    req = approvals.decide(req, p["reviewer2"], mfa_at=now)
    assert req.status == "approved"


def test_login_lockout_and_mfa_step_up(seeded, api, mfa):
    c = api()
    for _ in range(5):
        r = c.post("/v1/auth/login", {"email": "ama@example.com", "password": "wrong-password"})
        assert r.status_code == 401
    r = c.post("/v1/auth/login", {"email": "ama@example.com", "password": "tenmina-dev-123"})
    assert r.status_code == 423 and r.json()["code"] == "account-locked"
    rv = seeded["people"]["reviewer"]
    c = api(rv)
    mfa(c, rv)


def test_token_auth_and_problem_json(seeded, api):
    c = api()
    r = c.post("/v1/auth/token", {"email": "kofi@example.com", "password": "tenmina-dev-123"})
    assert r.status_code == 200
    c.credentials(HTTP_AUTHORIZATION="Bearer " + r.json()["access"])
    assert c.get("/v1/me").json()["roles"] == ["CL"]
    r = api().get("/v1/me")
    assert r.status_code in (401, 403) and r["Content-Type"] == "application/problem+json"


def test_register(db, seeded, api):
    r = api().post("/v1/auth/register", {"email": "new@example.com", "password": "a-long-password-1",
                                          "full_name": "New Client", "residence_country": "DE"})
    assert r.status_code == 201, r.content
    assert r.json()["roles"] == ["CL"]
