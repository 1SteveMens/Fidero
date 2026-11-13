"""Subject access, correction and erasure requests, and in-app account
deletion (US-DPR-003, US-APP-004; TC-DPR-003, TC-APP-004)."""
import json
from datetime import timedelta

import pyotp
from django.utils import timezone

from accounts.models import ApiToken, FamilyMember, Person
from audit.models import AuditEvent
from core.adapters import get_adapter
from core.models import OutboxEvent
from dataprotection import registry, services
from dataprotection.models import DataRequest, LegalHold


def test_access_request_export_holds_only_own_data(seeded, api, people):
    """US-DPR-003 AC1, TC-DPR-003-01/02."""
    ama = people["client"]
    r = api(ama).post("/v1/me/data-requests", {"type": "access"}, format="json")
    assert r.status_code == 201 and r.json()["due_on"]
    rid = r.json()["id"]
    assert api(people["cm"]).post(f"/v1/dpr/requests/{rid}/export").status_code == 403
    r = api(people["admin"]).post(f"/v1/dpr/requests/{rid}/export")
    assert r.status_code == 200 and r.json()["status"] == "completed" and len(r.json()["export_sha256"]) == 64
    req = DataRequest.objects.get(pk=rid)
    pack = json.loads(get_adapter("evidence_store").get(req.export_evidence.storage_key))
    data = pack["data"]
    assert data["accounts"]["profile"]["email"] == "ama@example.com"
    assert {f["full_name"] for f in data["accounts"]["family_members"]} >= {"Akosua Mensah"}
    text = json.dumps(pack)
    assert "kofi@example.com" not in text and "0012345678901" not in text  # others' data; masked numbers
    assert AuditEvent.objects.filter(action="data_request.completed", entity_id=rid).exists()


def test_correction_keeps_old_value_in_audit(seeded, api, people):
    """US-DPR-003 AC2."""
    admin = people["admin"]
    r = api(admin).post("/v1/dpr/requests", {"subject": str(people["client2"].pk), "type": "correction",
                                             "details": "Wrong spelling"}, format="json")
    assert r.status_code == 201 and r.json()["source"] == "staff"
    rid = r.json()["id"]
    r = api(admin).post(f"/v1/dpr/requests/{rid}/corrections", {"field": "full_name", "value": "Kofi Boateng-Ansah"},
                        format="json")
    assert r.status_code == 200 and r.json()["status"] == "in_progress"
    ev = AuditEvent.objects.filter(action="person.corrected").latest("seq")
    assert ev.data["old"] == "Kofi Boateng" and ev.data["new"] == "Kofi Boateng-Ansah"
    assert api(admin).post(f"/v1/dpr/requests/{rid}/complete").json()["status"] == "completed"


def test_client_cannot_file_for_someone_else(seeded, api, people):
    r = api(people["client"]).post("/v1/dpr/requests", {"subject": str(people["client2"].pk), "type": "access"},
                                   format="json")
    assert r.status_code == 403


def test_overdue_requests_alert_the_dpo(seeded, people):
    from notifications.models import Message

    DataRequest.objects.update(due_on=timezone.localdate() - timedelta(days=1))
    assert services.alert_overdue_requests() >= 1
    assert Message.objects.filter(person=people["admin3"], template="dpr_request_overdue").exists()


def test_deletion_preview_lists_deleted_kept_and_why(seeded, api, people):
    """US-APP-004 AC1, TC-APP-004-01."""
    r = api(people["client2"]).get("/v1/me/deletion-requests/preview")
    d = r.json()
    assert r.status_code == 200 and d["can_complete_now"] is True and d["deleted"]
    kept = {k["data_class"]: k for k in d["kept"]}
    assert "case" in kept and kept["case"]["why"] and "[TO VERIFY]" in kept["case"]["until"]


def test_delete_account_with_nothing_open(seeded, api, people):
    """US-APP-004 AC2: sign-in, sessions and tokens end at once; personal
    data anonymised; held records kept."""
    kofi = people["client2"]
    raw, _ = ApiToken.issue(kofi, "access", timedelta(minutes=10))
    c = api()
    c.credentials(HTTP_AUTHORIZATION="Bearer " + raw)
    r = c.post("/v1/me/deletion-requests", {"confirm": True, "source": "app"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["status"] == "completed" and r.json()["source"] == "app"
    kofi.refresh_from_db()
    assert kofi.status == "anonymised" and kofi.email.endswith("@anonymised.invalid") and kofi.phone == ""
    assert c.get("/v1/me").status_code == 401
    assert api().post("/v1/auth/login", {"identifier": "kofi@example.com",
                                         "password": "tenmina-dev-123"}).status_code == 401
    assert OutboxEvent.objects.filter(topic="account.deletion_requested").exists()


def test_deletion_needs_the_second_factor_when_mfa_is_on(seeded, api, people, mfa):
    """TC-APP-004-04."""
    ama = people["client"]
    Person.objects.filter(pk=ama.pk).update(mfa_enabled=True, mfa_secret="JBSWY3DPEHPK3PXP")
    ama.refresh_from_db()
    c = api(ama)
    r = c.post("/v1/me/deletion-requests", {"confirm": True}, format="json")
    assert r.status_code == 401 and r.json()["code"] == "mfa-required"
    c.post("/v1/auth/mfa/step-up", {"code": pyotp.TOTP(ama.mfa_secret).now()}, format="json")
    assert c.post("/v1/me/deletion-requests", {"confirm": False}, format="json").status_code == 422


def test_open_escrow_or_hold_makes_deletion_wait(seeded, api, people):
    """US-APP-004 AC3, TC-APP-004-03: request recorded, account closed to new
    orders, user told what stays open, held records kept; completes later."""
    from accounts.selectors import can_place_orders

    ama = people["client"]
    state = {"open": True}

    def open_escrow(person):
        if person.pk == ama.pk and state["open"]:
            return [{"kind": "escrow", "id": "e1", "title": "Escrow for plot 12, East Legon",
                     "reason": "Money is held at the bank."}]
        return []

    registry.open_matters(open_escrow)
    try:
        r = api(ama).post("/v1/me/deletion-requests", {"confirm": True}, format="json")
        assert r.status_code == 201 and r.json()["status"] == "waiting"
        assert r.json()["open_matters"][0]["kind"] == "escrow"
        ama.refresh_from_db()
        assert ama.status == "closing" and not can_place_orders(ama)
        assert FamilyMember.objects.filter(client=ama, status="active").exists()
        assert api(ama).get("/v1/home").status_code == 200  # can still follow the escrow
        assert services.process_waiting_deletions() == 1
        assert DataRequest.objects.get(pk=r.json()["id"]).status == "waiting"
        state["open"] = False
        services.place_hold(people["lawyer"], subject_type="person", subject_id=ama.pk, reason="Claim expected")
        services.process_waiting_deletions()
        assert DataRequest.objects.get(pk=r.json()["id"]).status == "waiting"  # the hold keeps it open
        assert LegalHold.objects.filter(subject_id=ama.pk, status="active").exists()
    finally:
        registry._open_matters.remove(open_escrow)


def test_erasure_by_staff(seeded, api, people):
    admin = people["admin"]
    r = api(admin).post("/v1/dpr/requests", {"subject": str(people["client2"].pk), "type": "erasure"},
                        format="json")
    r = api(admin).post(f"/v1/dpr/requests/{r.json()['id']}/erase")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert Person.objects.get(pk=people["client2"].pk).status == "anonymised"


def test_reject_request_needs_a_reason(seeded, api, people):
    req = DataRequest.objects.filter(status="open").first()
    c = api(people["admin"])
    assert c.post(f"/v1/dpr/requests/{req.pk}/reject", {}, format="json").status_code == 400
    r = c.post(f"/v1/dpr/requests/{req.pk}/reject", {"reason": "Identity not confirmed"}, format="json")
    assert r.json()["status"] == "rejected"
