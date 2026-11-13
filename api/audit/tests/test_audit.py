import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from audit import context, services
from audit.models import AuditAnchor, AuditEvent, ChainCheck, SecurityAlert


def _tamper(sql, params=()):
    with connection.cursor() as c:
        c.execute("ALTER TABLE aud_event DISABLE TRIGGER trg_aud_event_append_only")
        c.execute(sql, params)
        c.execute("ALTER TABLE aud_event ENABLE TRIGGER trg_aud_event_append_only")


def test_write_records_who_what_and_where(seeded, api, people):
    """FR-AUD-001, TC-AUD-001-01: an API write leaves an entry with actor, action, object, time and origin."""
    admin = people["admin"]
    c = api(admin)
    r = c.put("/v1/admin/settings/ntf_amount_threshold", {"value": {"amount": "400.00", "currency": "USD"}},
              format="json", HTTP_USER_AGENT="pytest-agent",
              HTTP_TRACEPARENT="00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
    assert r.status_code == 200, r.content
    e = AuditEvent.objects.filter(action="setting.changed").order_by("-seq").first()
    assert str(e.actor_id) == str(admin.pk) and e.actor_kind == "person"
    assert e.origin_ip == "127.0.0.1" and e.user_agent == "pytest-agent"
    assert e.trace_id == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert e.data["old"]["amount"] == "500.00" and e.data["new"]["amount"] == "400.00"
    assert services.verify_chain()["ok"]


def test_search_filters_and_is_logged(seeded, api, people):
    """FR-AUD-003, TC-AUD-003-01: search by object, user, date and action; the search is logged."""
    rv = people["reviewer"]
    services.record(actor=rv, action="case.note_added", entity="case", entity_id="c-1", data={"x": 1})
    services.record(action="task.created", entity="case_task", entity_id="t-9", data={"case_id": "c-1"})
    c = api(rv)
    r = c.get("/v1/audit-events", {"case_id": "c-1"})
    assert r.status_code == 200
    assert {i["action"] for i in r.json()["items"]} == {"case.note_added", "task.created"}
    r = c.get("/v1/audit-events", {"actor_id": str(rv.pk), "action": "case.*",
                                   "occurred_from": (timezone.now().replace(year=2020)).isoformat()})
    assert [i["action"] for i in r.json()["items"]] == ["case.note_added"]
    assert AuditEvent.objects.filter(action="audit.searched", actor_id=rv.pk).count() == 2


def test_search_refused_for_clients_and_case_managers(seeded, api, people):
    """FR-AUD-003: reviewers and administrators only."""
    assert api(people["client"]).get("/v1/audit-events").status_code == 403
    assert api(people["cm"]).get("/v1/audit-events").status_code == 403


def test_no_api_edits_or_deletes(seeded, api, people):
    """FR-AUD-002, TC-AUD-002-01: no function exists; the API answers 405."""
    c = api(people["admin"])
    for method in (c.put, c.patch, c.delete):
        assert method("/v1/audit-events", {}, format="json").status_code == 405


def test_database_refuses_update_and_delete_even_for_anchors(seeded):
    """FR-AUD-002, TC-AUD-002-02: the trigger refuses UPDATE and DELETE."""
    services.anchor()
    for sql in ("UPDATE aud_event SET action = 'x'", "DELETE FROM aud_event", "DELETE FROM aud_anchor",
                "UPDATE aud_chain_check SET ok = true"):
        with pytest.raises(Exception), transaction.atomic():
            with connection.cursor() as c:
                c.execute(sql)


def test_verification_finds_a_changed_entry_and_raises_an_alert(seeded, api, people, mfa):
    """FR-AUD-004, TC-AUD-004-02: a changed entry is reported at that entry, and an alert raised."""
    services.record(action="test.entry", entity="test", entity_id="1")
    target = AuditEvent.objects.order_by("-seq").first().seq
    _tamper("UPDATE aud_event SET data = '{\"forged\": true}' WHERE seq = %s", [target])
    r = api(people["admin"]).post("/v1/audit-events/verify")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["broken_at"] == target
    assert SecurityAlert.objects.filter(kind="audit.chain_broken", severity="critical").exists()


def test_anchor_detects_a_removed_tail(seeded):
    """FR-AUD-004: removing the newest entries still fails verification thanks to the anchor."""
    services.record(action="test.entry", entity="test", entity_id="2")
    a = services.anchor()
    assert AuditAnchor.objects.filter(seq=a.seq).exists()
    assert services.run_chain_check().ok
    _tamper("DELETE FROM aud_event WHERE seq >= %s", [a.seq])
    assert services.verify_chain()["ok"] is True  # the chain alone cannot see a cut tail
    chk = services.run_chain_check()
    assert chk.ok is False and chk.anchors_ok is False
    assert ChainCheck.objects.filter(ok=False).exists()


def test_trail_export_is_logged_with_digest(seeded, api, people):
    """FR-AUD-001 criterion 2: an export is logged."""
    services.record(action="thing.created", entity="thing", entity_id="abc")
    services.record(action="thing.changed", entity="thing", entity_id="abc")
    r = api(people["reviewer"]).get("/v1/audit-events/trails/thing/abc")
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == 2 and body["entries_intact"] and len(body["sha256"]) == 64
    assert AuditEvent.objects.filter(action="audit.exported", entity="thing", data__sha256=body["sha256"]).exists()
    assert api(people["reviewer"]).get("/v1/audit-events/trails/thing/none").status_code == 404


def test_security_event_thresholds_and_always_rules(seeded):
    """10.10: some events always alert, others only at a threshold (alerted once)."""
    services.security_event("role.granted", entity="person", entity_id="p1")
    assert SecurityAlert.objects.filter(kind="role.granted").count() == 1
    for _ in range(4):
        services.security_event("confirmation_code.failed", entity="care_visit", entity_id="v1")
    assert SecurityAlert.objects.filter(kind="confirmation_code.failed").count() == 1
    services.security_event("signin.failed", entity="person", entity_id="p2")
    assert not SecurityAlert.objects.filter(kind="signin.failed").exists()
    services.security_event("something.new", entity="x", entity_id="y")
    assert SecurityAlert.objects.filter(kind="something.new").exists()


def test_alert_list_and_acknowledge(seeded, api, people):
    """10.10: reviewers see and acknowledge alerts; clients cannot."""
    services.security_event("mfa.removed", entity="person", entity_id="p3")
    c = api(people["reviewer"])
    items = c.get("/v1/security-alerts", {"open": "true", "kind": "mfa.removed"}).json()["items"]
    assert len(items) == 1
    r = c.post(f"/v1/security-alerts/{items[0]['id']}/acknowledge", {"note": "Known change"}, format="json")
    assert r.status_code == 200 and r.json()["acknowledged_by"] == str(people["reviewer"].pk)
    assert api(people["client"]).get("/v1/security-alerts").status_code == 403


def test_deferred_security_event_survives_a_refused_request(seeded):
    """US-CTY-001b criterion 2: a refusal is logged even though the refused request rolls back."""
    context.on_request_started(None, environ={"REMOTE_ADDR": "10.0.0.9"})
    with pytest.raises(RuntimeError), transaction.atomic():
        services.security_event("access.cross_country_refused", entity="case", entity_id="c-ng", defer=True)
        services.record(action="should.vanish", entity="x", entity_id="1")
        raise RuntimeError("refused")
    context.on_request_finished(None)
    assert not AuditEvent.objects.filter(action="should.vanish").exists()
    e = AuditEvent.objects.get(action="security.access.cross_country_refused")
    assert e.origin_ip == "10.0.0.9"


def test_audit_write_failure_blocks_the_action(seeded, monkeypatch):
    """TC-AUD-001-02: nothing changes without its audit entry."""
    from administration import services as adm
    from administration.models import Setting

    def boom(**kw):
        raise IntegrityError("audit store unavailable")

    monkeypatch.setattr(adm, "record", boom)
    with pytest.raises(IntegrityError):
        adm.change_setting(key="ntf_amount_threshold", value={"amount": "1.00", "currency": "USD"},
                           by=seeded["people"]["admin"])
    assert Setting.objects.get(key="ntf_amount_threshold", country=None).value["amount"] == "500.00"
