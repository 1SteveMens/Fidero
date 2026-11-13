import hashlib
import os
import uuid
from datetime import date, timedelta

import pytest
from django.core.cache import cache
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.utils import timezone

from audit.models import AuditEvent
from core.errors import DomainError, Forbidden, Invalid, StateConflict
from core.models import OutboxEvent
from evidence import access, services
from evidence.adapters import EICAR
from evidence.models import AccessLog, Evidence, EvidenceLink, IntegrityIncident, Preview, RetentionDeletion, \
    ScanResult
from mobile.devtools import jpeg, mp4
from notifications.models import Message

PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\ntrailer << /Root 1 0 R >>\n%%EOF\n"


@pytest.fixture
def order_policy(people):
    """A client may see and add files to their own 'order' (stands in for ORD's policy)."""
    owners = {}

    def can(user, sid):
        return owners.get(str(sid)) == user.pk

    previous = access.policy("order")  # ORD's own policy, put back afterwards
    access.register("order", can_view=can, can_attach=can, country=lambda sid: people["client"].home_country,
                    owner=lambda sid: ("order", sid))
    yield owners
    _restore("order", previous)


def _restore(subject_type, previous):
    """Put back the module's own policy so later tests see the real registry."""
    if previous is None:
        access.unregister(subject_type)
    else:
        access._POLICIES[subject_type] = previous


def _store(gh, person, data=None, **kw):
    kw.setdefault("content_type", "image/jpeg")
    return services.store(data=data or jpeg(uuid.uuid4().hex), country=gh, uploaded_by=person, **kw)


# --------------------------------------------------------------------------- FR-EVD-001, FR-EVD-002

def test_store_records_hash_uploader_times_position_and_owner(gh, people):
    """FR-EVD-001, TC-EVD-001-01: hash, uploader, capture and server time, position and owner are stored."""
    data = jpeg("x", model="SM-A045F")
    when = timezone.now() - timedelta(minutes=5)
    case_id = uuid.uuid4()
    ev = _store(gh, people["runner"], data, captured_at=when, latitude="5.650000", longitude="-0.180000",
                position_accuracy_m="6.5", owner_type="case", owner_id=case_id, original_name="gate.jpg")
    assert ev.sha256 == hashlib.sha256(data).hexdigest()
    assert ev.uploaded_by == people["runner"] and ev.captured_at == when and ev.received_at
    assert ev.owner_type == "case" and ev.owner_id == case_id and str(ev.latitude) == "5.650000"
    assert ev.provenance == "uploaded" and ev.scan_status == "clean"
    assert ev.retain_until == date(ev.received_at.year + 7, ev.received_at.month, ev.received_at.day)
    assert ev.metadata["exif_model"] == "SM-A045F" and len(ev.phash) == 16
    assert services.verify(ev)
    assert ScanResult.objects.filter(evidence=ev, verdict="clean").exists()
    assert AuditEvent.objects.filter(action="evidence.stored", entity_id=str(ev.pk)).exists()
    assert OutboxEvent.objects.filter(topic="evidence.stored", aggregate_id=ev.pk).exists()


def test_same_name_upload_keeps_both_versions(gh, people):
    """FR-EVD-002, TC-EVD-002-01: a new file with the same name is a new item; the old one is unchanged."""
    a = _store(gh, people["client"], original_name="site-plan.jpg")
    b = _store(gh, people["client"], original_name="site-plan.jpg")
    assert a.pk != b.pk and a.storage_key != b.storage_key
    a.refresh_from_db()
    assert services.verify(a) and services.verify(b)


def test_database_refuses_change_or_delete_of_evidence(gh, people):
    """FR-EVD-002, ADR-04: the hash, key and provenance never change; rows are never deleted."""
    ev = _store(gh, people["client"])
    for change in ({"sha256": "0" * 64}, {"storage_key": "x"}, {"provenance": "app_captured"},
                   {"captured_at": timezone.now()}):
        with pytest.raises(DatabaseError), transaction.atomic():
            Evidence.objects.filter(pk=ev.pk).update(**change)
    with pytest.raises(DatabaseError), transaction.atomic():
        Evidence.objects.filter(pk=ev.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        Evidence.objects.filter(pk=ev.pk).update(retain_until=ev.retain_until - timedelta(days=1))
    with pytest.raises(DatabaseError), transaction.atomic():
        Evidence.objects.filter(pk=ev.pk).update(deleted_at=timezone.now())  # still locked
    # Extending retention is allowed (legal hold).
    Evidence.objects.filter(pk=ev.pk).update(retain_until=ev.retain_until + timedelta(days=30))
    from core.adapters import get_adapter

    with pytest.raises(FileExistsError):
        get_adapter("evidence_store").put(ev.storage_key, b"overwrite")


def test_links_are_append_only_and_once_per_subject(gh, people):
    """FR-EVD-002: links cannot be changed or removed; linking twice returns the same link."""
    ev = _store(gh, people["client"])
    sid = uuid.uuid4()
    a = services.link(ev, "case", sid, role="site_photo", by=people["cm"])
    assert services.link(ev, "case", sid, role="other", by=people["cm"]).pk == a.pk
    with pytest.raises(DatabaseError), transaction.atomic():
        EvidenceLink.objects.filter(pk=a.pk).delete()


def test_retention_sweep_deletes_only_expired_items_and_logs_the_rule(gh, people, monkeypatch):
    """FR-EVD-002, TC-EVD-002-03: deletion follows retention, skips holds, and is logged with the rule."""
    monkeypatch.setattr(services, "retain_until_for", lambda c, d, today=None: date.today() - timedelta(days=1))
    old = _store(gh, people["client"])
    held = _store(gh, people["client"])
    monkeypatch.undo()
    current = _store(gh, people["client"])
    access.register_hold(lambda e: e.pk == held.pk)
    try:
        done = services.retention_sweep(by=people["admin"])
    finally:
        access._HOLDS.clear()
    assert [d.evidence_id for d in done] == [old.pk]
    old.refresh_from_db()
    assert old.deleted_at is not None and not services.verify(old)
    rd = RetentionDeletion.objects.get(evidence=old)
    assert "retention ended" in rd.rule
    assert AuditEvent.objects.filter(action="evidence.retention_deleted", entity_id=str(old.pk)).exists()
    held.refresh_from_db()
    current.refresh_from_db()
    assert held.deleted_at is None and current.deleted_at is None
    with pytest.raises(StateConflict):
        services.issue_link(old, people["cm"])


def test_api_delete_is_refused_and_logged(gh, people, api):
    """FR-EVD-002, TC-EVD-002-02: the API refuses to delete evidence and logs the attempt."""
    ev = _store(gh, people["client"])
    r = api(people["admin"]).delete(f"/v1/evidence/{ev.pk}")
    assert r.status_code == 403 and r.json()["code"] == "evidence-immutable"
    assert AccessLog.objects.filter(evidence=ev, action="delete_refused").exists()
    assert Evidence.objects.filter(pk=ev.pk).exists()


# --------------------------------------------------------------------------- FR-EVD-003

def test_signed_links_expire_and_bind_to_the_person(gh, people, api, monkeypatch):
    """FR-EVD-003, TC-EVD-003-01, TC-EVD-003-02: link of 15 minutes or less; expired, altered or
    other-account use is refused; each use is logged."""
    data = PDF
    ev = _store(gh, people["client"], data, content_type="application/pdf")
    cm = api(people["cm"])
    r = cm.get(f"/v1/evidence/{ev.pk}/link")
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] <= 900 and body["variant"] == "original"
    anon = api()
    got = anon.get(body["url"])
    assert got.status_code == 200 and got.content == data and got["Cache-Control"] == "private, no-store"
    # Altered token
    token = body["token"]
    bad = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert anon.get(f"/v1/evidence-files/{bad}").status_code == 403
    # Another signed-in account
    r2 = api(people["reviewer"]).get(body["url"])
    assert r2.status_code == 403
    # Expired
    later = timezone.now() + timedelta(minutes=16)
    monkeypatch.setattr(timezone, "now", lambda: later)
    assert anon.get(body["url"]).status_code == 403
    actions = list(AccessLog.objects.filter(evidence=ev).values_list("action", "detail"))
    assert ("link_issued", "") in actions and ("downloaded", "") in actions
    assert ("refused", "other_account") in actions and ("refused", "expired") in actions


def test_link_needs_permission(gh, people, api):
    """FR-EVD-003: a client who cannot see the subject gets 404 and the refusal is logged."""
    ev = _store(gh, people["client2"])
    assert api(people["client"]).get(f"/v1/evidence/{ev.pk}/link").status_code == 404
    assert api(people["client2"]).get(f"/v1/evidence/{ev.pk}/link").status_code == 200
    assert AccessLog.objects.filter(evidence=ev, action="refused").exists()


def test_link_ttl_never_exceeds_15_minutes(gh, people, monkeypatch):
    """FR-EVD-003: a country setting cannot lengthen links beyond 15 minutes."""
    monkeypatch.setattr(services, "_cfg", lambda c, k, d: 3600 if k == "evidence.link_ttl_seconds" else d)
    assert services.link_ttl(gh) == 900


# --------------------------------------------------------------------------- FR-EVD-004

def test_image_preview_is_default_and_original_on_request(gh, people, api):
    """FR-EVD-004, TC-EVD-004-01: a resized preview is made and served by default."""
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (2400, 1600), (120, 30, 200)).save(buf, "JPEG")
    ev = _store(gh, people["client"], buf.getvalue())
    p = Preview.objects.get(evidence=ev)
    assert p.status == "ready" and max(p.width, p.height) == 640
    c = api(people["client"])
    link = c.get(f"/v1/evidence/{ev.pk}/link").json()
    assert link["variant"] == "preview"
    small = c.get(link["url"]).content
    assert len(small) < len(buf.getvalue())
    orig = c.get(f"/v1/evidence/{ev.pk}/link?variant=original").json()
    assert c.get(orig["url"]).content == buf.getvalue()


def test_video_preview_and_failed_preview_keeps_original(gh, people):
    """FR-EVD-004, TC-EVD-004-02: video gets a compressed preview; a failed preview never loses the original."""
    ev = _store(gh, people["client"], mp4("v"), content_type="video/mp4")
    assert Preview.objects.get(evidence=ev).status == "placeholder"
    bad = _store(gh, people["client"], jpeg("ok")[:40] + b"\x00" * 200)  # starts like a JPEG, then garbage
    p = Preview.objects.get(evidence=bad)
    assert p.status == "failed" and services.verify(bad)
    assert OutboxEvent.objects.filter(topic="evidence.preview_failed", aggregate_id=bad.pk).exists()


# --------------------------------------------------------------------------- FR-EVD-005

@pytest.mark.parametrize("data,ctype,reason", [
    (b"prefix " + EICAR, "text/plain", "malware"),
    (b"MZ\x90\x00 executable renamed", "image/jpeg", "executable"),
    (b"GIF89a not really a jpeg", "image/jpeg", "not_what_it_claims"),
    (b"%PDF-1.4\n/OpenAction << /S /JavaScript /JS (app.alert(1)) >>\n%%EOF", "application/pdf",
     "pdf_active_content"),
])
def test_unsafe_files_are_rejected_and_logged(gh, people, data, ctype, reason):
    """FR-EVD-005, TC-EVD-005-02: malware, disguised executables and PDFs with scripts are rejected."""
    with pytest.raises(Invalid) as e:
        services.store(data=data, country=gh, uploaded_by=people["client"], content_type=ctype)
    assert e.value.code == "evidence-rejected" and e.value.extra["reason"] == reason
    assert not Evidence.objects.filter(sha256=hashlib.sha256(data).hexdigest()).exists()
    assert ScanResult.objects.filter(verdict="rejected", detail=reason).exists()


def test_clean_pdf_is_accepted(gh, people):
    """FR-EVD-005, TC-EVD-005-01."""
    assert _store(gh, people["client"], PDF, content_type="application/pdf").scan_status == "clean"


def test_pending_scan_holds_access_until_clean(gh, people, settings):
    """FR-EVD-005, US-EVD-005 AC2: a file waiting for its scan cannot be opened."""
    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                         "malware_scan": "evidence.adapters.DeferredScanner"}}
    ev = _store(gh, people["client"])
    assert ev.scan_status == "pending" and not Preview.objects.filter(evidence=ev).exists()
    with pytest.raises(StateConflict):
        services.issue_link(ev, people["client"])
    services.record_scan(ev, "clean", by=people["admin"])
    assert services.issue_link(ev, people["client"])["variant"] == "preview"
    with pytest.raises(DatabaseError), transaction.atomic():
        Evidence.objects.filter(pk=ev.pk).update(scan_status="pending")


def test_late_scan_rejection_tells_the_uploader(gh, people, settings):
    """FR-EVD-005: an asynchronous rejection keeps the file unservable and tells the uploader."""
    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                         "malware_scan": "evidence.adapters.DeferredScanner"}}
    ev = _store(gh, people["client"])
    services.record_scan(ev, "rejected", detail="Trojan.Test")
    with pytest.raises(Invalid):
        services.issue_link(ev, people["client"])
    assert Message.objects.filter(person=people["client"], template="evidence_rejected").exists()


# --------------------------------------------------------------------------- upload slots (API journey)

def test_upload_slot_journey_hashes_and_ignores_forged_provenance(people, api, order_policy):
    """FR-EVD-001, FR-EVD-005, FR-EVD-006, TC-EVD-006-02: slot, bytes, server hash; marked uploaded."""
    oid = uuid.uuid4()
    order_policy[str(oid)] = people["client"].pk
    data = PDF
    c = api(people["client"])
    r = c.post("/v1/uploads", {"subject_type": "order", "subject_id": str(oid), "role": "site_plan",
                               "content_type": "application/pdf", "size_bytes": len(data),
                               "sha256": hashlib.sha256(data).hexdigest(), "original_name": "plan.pdf",
                               "provenance": "app_captured", "source": "field_app"}, format="json")
    assert r.status_code == 201, r.content
    slot = r.json()
    assert slot["upload"]["url"] == f"/v1/uploads/{slot['id']}/content"
    up = c.put(slot["upload"]["url"], data=data, content_type="application/octet-stream")
    assert up.status_code == 201, up.content
    ev = up.json()
    assert ev["provenance"] == "uploaded" and ev["source"] == "upload" and ev["release_grade"] is False
    assert ev["owner_type"] == "order" and ev["links"][0]["role"] == "site_plan"
    listed = c.get(f"/v1/evidence?subject_type=order&subject_id={oid}").json()["items"]
    assert [e["id"] for e in listed] == [ev["id"]]
    again = c.put(slot["upload"]["url"], data=data, content_type="application/octet-stream")
    assert again.status_code == 409


def test_upload_with_wrong_hash_is_rejected(people, api, order_policy):
    """FR-EVD-001: the server re-hashes; a different file is rejected and the slot closed."""
    oid = uuid.uuid4()
    order_policy[str(oid)] = people["client"].pk
    c = api(people["client"])
    slot = c.post("/v1/uploads", {"subject_type": "order", "subject_id": str(oid), "content_type": "application/pdf",
                                  "size_bytes": 10, "sha256": "a" * 64}, format="json").json()
    r = c.put(slot["upload"]["url"], data=PDF, content_type="application/octet-stream")
    assert r.status_code == 422 and r.json()["code"] == "evidence-rejected"
    assert c.get(f"/v1/uploads/{slot['id']}").json()["status"] == "rejected"


def test_upload_to_a_subject_you_cannot_reach_is_refused(people, api, order_policy):
    """TC-EVD-001-02: no slot for an object the user cannot access, nor for an unknown subject type."""
    oid = uuid.uuid4()
    order_policy[str(oid)] = people["client2"].pk
    body = {"subject_type": "order", "subject_id": str(oid), "content_type": "application/pdf", "size_bytes": 10,
            "sha256": "b" * 64}
    assert api(people["client"]).post("/v1/uploads", body, format="json").status_code == 404
    assert api(people["client"]).post("/v1/uploads", {**body, "subject_type": "case"},
                                      format="json").status_code == 404
    bad_type = {**body, "content_type": "application/x-msdownload"}
    assert api(people["client2"]).post("/v1/uploads", bad_type, format="json").status_code == 422


# --------------------------------------------------------------------------- RUL-08 and RUL-30

def test_gallery_uploads_cannot_be_milestone_evidence(gh, people, api):
    """RUL-08, FR-EVD-006, US-EVD-006 AC2, TC-RUL-08-03: an uploaded item offered as release evidence is
    refused; generated documents and an exempt role are allowed."""
    ms = uuid.uuid4()
    body = {"subject_type": "milestone", "subject_id": str(ms), "content_type": "image/jpeg", "size_bytes": 10,
            "sha256": "c" * 64, "country": "GH"}
    r = api(people["cm"]).post("/v1/uploads", body, format="json")
    assert r.status_code == 422 and r.json()["blocking_reasons"][0]["rule"] == "RUL-08"
    ev = _store(gh, people["contractor"])
    with pytest.raises(Invalid) as e:
        services.link(ev, "milestone", ms, role="trench_depth_photo", by=people["cm"])
    assert e.value.blocking_reasons[0]["rule"] == "RUL-08"
    services.link(ev, "milestone", ms, role="invoice", by=people["cm"])  # exempt document role
    gen = _store(gh, people["cm"], PDF, content_type="application/pdf", source="generated")
    assert gen.provenance == "system_generated"
    services.link(gen, "inspection", uuid.uuid4(), role="inspection_report", by=people["cm"])


def test_rul08_applies_only_when_field_capture_is_on(gh, people, settings):
    """RUL-08 from R2: with mobile.capture off, uploads are still accepted (manual phase)."""
    settings.TENMINA_FLAG_OVERRIDES = {"mobile.capture": False}
    ev = _store(gh, people["contractor"])
    services.link(ev, "milestone", uuid.uuid4(), role="trench_depth_photo", by=people["cm"])


def test_official_search_results_only_from_staff(gh, people):
    """RUL-30, FR-CASE-016: only case managers or reviewers handle official search results, in the service
    and in the database."""
    sr = uuid.uuid4()
    from_runner = _store(gh, people["runner"], PDF, content_type="application/pdf")
    with pytest.raises(Invalid) as e:
        services.link(from_runner, "search_request", sr, role="official_search_result", by=people["cm"])
    assert e.value.blocking_reasons[0]["rule"] == "RUL-30"
    good = _store(gh, people["cm"], PDF + b"%x", content_type="application/pdf", source="official_channel")
    with pytest.raises(Invalid):
        services.link(good, "case", uuid.uuid4(), role="official_search_result", by=people["cm"])
    services.link(good, "search_request", sr, role="official_search_result", by=people["reviewer"])
    with pytest.raises(IntegrityError), transaction.atomic():
        EvidenceLink.objects.create(evidence=from_runner, country=gh, subject_type="search_request",
                                    subject_id=uuid.uuid4(), role="official_search_result", linked_by=people["cm"])


# --------------------------------------------------------------------------- fingerprints and access logs

def test_fingerprint_check_is_public_and_says_only_yes_or_no(gh, people, api):
    """FR-RPT-008 by hash: anyone with a released report can confirm it; nothing else is revealed."""
    cache.clear()
    ev = _store(gh, people["reviewer"], PDF, content_type="application/pdf", source="generated")
    rid = uuid.uuid4()
    from core.events import publish

    publish("report.released", rid, {"report_id": rid, "pdf_evidence_id": ev.pk,
                                     "released_at": "2026-11-10T09:00:00+00:00"})
    anon = api()
    r = anon.post("/v1/fingerprint-checks", {"sha256": ev.sha256.upper()}, format="json")
    assert r.status_code == 200 and r.json() == {"match": True, "released_on": "2026-11-10"}
    assert anon.post("/v1/fingerprint-checks", {"sha256": "d" * 64}, format="json").json() == \
        {"match": False, "released_on": None}
    assert anon.post("/v1/fingerprint-checks", {"sha256": "nothex"}, format="json").status_code == 422


def test_fingerprint_check_is_rate_limited(db, api):
    """Abuse protection: the public check is rate-limited (429 rate-limited)."""
    cache.clear()
    anon = api()
    codes = [anon.post("/v1/fingerprint-checks", {"sha256": "e" * 64}, format="json").status_code
             for _ in range(22)]
    assert codes[0] == 200 and codes[-1] == 429
    r = anon.post("/v1/fingerprint-checks", {"sha256": "e" * 64}, format="json")
    assert r.json()["code"] == "rate-limited"
    cache.clear()


def test_access_log_for_a_released_report_folder(gh, people, api):
    """Released report folder: the client's view of who opened which file, through the subject policy."""
    rid = uuid.uuid4()
    ev = _store(gh, people["reviewer"], PDF, content_type="application/pdf", source="generated")
    services.link(ev, "report", rid, role="released_report", by=people["reviewer"])
    previous = access.policy("report")  # RPT's own policy, put back afterwards
    access.register("report", can_view=lambda u, s: u.pk == people["client"].pk)
    try:
        api(people["client"]).get(f"/v1/evidence/{ev.pk}/link")
        rows = api(people["client"]).get(f"/v1/evidence-access-logs?subject_type=report&subject_id={rid}").json()
        assert rows[0]["person_name"] == people["client"].full_name and rows[0]["action"] == "link_issued"
        assert api(people["client2"]).get(
            f"/v1/evidence-access-logs?subject_type=report&subject_id={rid}").status_code == 404
    finally:
        _restore("report", previous)


# --------------------------------------------------------------------------- integrity sampling

def test_integrity_sampling_raises_an_incident_on_mismatch(gh, people, api, mfa, settings):
    """02 10.7 step 7: a re-hash mismatch is a security incident; admins are told; resolution is noted."""
    good = _store(gh, people["client"])
    bad = _store(gh, people["client"])
    path = os.path.join(settings.MEDIA_ROOT, "evidence", bad.storage_key)
    os.chmod(path, 0o640)
    with open(path, "ab") as f:
        f.write(b"tampered")
    run = services.integrity_sample(size=1000, seed="t", by=people["admin"])
    assert run.checked == run.population and run.mismatches == 1
    inc = IntegrityIncident.objects.get(run=run)
    assert inc.evidence_id == bad.pk and inc.actual_sha256 != bad.sha256
    assert good.pk != inc.evidence_id
    assert OutboxEvent.objects.filter(topic="evidence.integrity_failed").exists()
    assert Message.objects.filter(person=people["admin"], template="evidence_integrity_incident").exists()
    c = api(people["admin"])
    assert c.get("/v1/integrity-incidents?status=open").json()["items"][0]["id"] == str(inc.pk)
    assert c.post(f"/v1/integrity-incidents/{inc.pk}/resolve", {}, format="json").status_code == 400
    r = c.post(f"/v1/integrity-incidents/{inc.pk}/resolve", {"note": "Restored from replica; root cause logged"},
               format="json")
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    assert api(people["client"]).get("/v1/integrity-incidents").status_code == 403


def test_admin_can_start_an_integrity_run(people, api):
    """10.7: administrators may run a sample on demand; reviewers may only read."""
    r = api(people["admin"]).post("/v1/integrity-runs", {"size": 5}, format="json")
    assert r.status_code == 201 and r.json()["mismatches"] == 0
    assert api(people["reviewer"]).post("/v1/integrity-runs", {}, format="json").status_code == 404
    assert api(people["reviewer"]).get("/v1/integrity-runs").status_code == 200


def test_manual_scan_verdict_endpoint(gh, people, api, settings):
    """FR-EVD-005: the manual adapter for an asynchronous scanner records the verdict."""
    settings.TENMINA = {**settings.TENMINA, "ADAPTERS": {**settings.TENMINA["ADAPTERS"],
                                                         "malware_scan": "evidence.adapters.DeferredScanner"}}
    ev = _store(gh, people["client"])
    assert api(people["client"]).post(f"/v1/evidence/{ev.pk}/scan-results", {"verdict": "clean"},
                                      format="json").status_code == 403
    r = api(people["admin"]).post(f"/v1/evidence/{ev.pk}/scan-results", {"verdict": "clean"}, format="json")
    assert r.status_code == 200 and r.json()["scan_status"] == "clean" and r.json()["preview"]["status"] == "ready"


def test_store_errors_are_domain_errors(gh, people):
    """FR-EVD-001: an empty file is refused with evidence-rejected."""
    with pytest.raises(DomainError):
        services.store(data=b"", country=gh, uploaded_by=people["client"])
    with pytest.raises(Forbidden):
        services.open_link("garbage", user=None)


def test_db_trigger_installed(db):
    with connection.cursor() as c:
        c.execute("SELECT count(*) FROM pg_trigger WHERE tgname IN ('trg_evd_immutable', "
                  "'trg_evd_official_search_link', 'trg_evd_no_delete')")
        assert c.fetchone()[0] == 3
