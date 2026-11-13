import uuid
from datetime import timedelta

import pytest
from django.db import DatabaseError, IntegrityError, transaction
from django.utils import timezone

from administration.models import FeatureFlag
from core.events import publish
from core.models import OutboxEvent
from evidence import services as evd
from evidence.models import Evidence
from mobile import crypto, inbox, services
from mobile.devtools import FakePhone, jpeg, mp4
from mobile.models import CheckIn, Device, FraudFlag, SignedManifest, Submission

ON_SITE = dict(lat=5.6499, lng=-0.1801)


def send(c, phone, sid, data, *, subject_type="milestone", media_type="image/jpeg", **kw):
    payload = phone.capture(subject_type, sid, data, media_type=media_type, **kw)
    r = c.post("/v1/mobile/evidence", payload, format="json")
    assert r.status_code == 201, r.content
    item = r.json()
    put = c.put(item["upload"]["url"], data=data, content_type="application/octet-stream")
    assert put.status_code == 200, put.content
    done = c.post(f"/v1/mobile/evidence/{item['id']}/complete", {}, format="json")
    return item, done


def topics(*names):
    return list(OutboxEvent.objects.filter(topic__in=names).values_list("topic", flat=True))


# --------------------------------------------------------------------------- devices and attestation (FR-MOB-004)

def test_android_and_iphone_register_for_the_same_person(people, field_api):
    """FR-MOB-004, US-MOB-001 AC4, TC-MOB-001-04: both phones registered; revoking one leaves the other."""
    c = field_api(people["contractor"])
    android, iphone = FakePhone(people["contractor"]), FakePhone(people["contractor"], platform="ios")
    ids = []
    for ph in (android, iphone):
        ch = c.post("/v1/mobile/devices/challenge").json()["challenge"]
        r = c.post("/v1/mobile/devices", {"challenge": ch, "platform": ph.platform, "app_id": "com.tenmina.field",
                                          "public_key": ph.public_key, "attestation": ph.attestation(ch),
                                          "model": ph.model}, format="json")
        assert r.status_code == 201, r.content
        ids.append(r.json()["id"])
    devs = {d["platform"]: d for d in c.get("/v1/mobile/devices").json()["items"] if d["id"] in ids}
    assert devs["ios"]["key_security"] == "secure_enclave" and devs["android"]["key_security"] == "tee"
    assert c.post(f"/v1/mobile/devices/{ids[0]}/revoke", {"reason": "Phone lost"}, format="json").status_code == 200
    statuses = {d["id"]: d["status"] for d in c.get("/v1/mobile/devices").json()["items"] if d["id"] in ids}
    assert statuses == {ids[0]: "revoked", ids[1]: "active"}


@pytest.mark.parametrize("platform,override,reason", [
    ("android", {"build": "sideloaded"}, "not_a_store_build"),
    ("android", {"build": "resigned"}, "not_a_store_build"),
    ("android", {"emulator": True}, "emulator"),
    ("android", {"device_integrity": "NO_INTEGRITY"}, "device_integrity"),
    ("ios", {"build": "development"}, "not_a_store_build"),
    ("ios", {"environment": "development"}, "development_environment"),
    ("ios", {"key_sha256": "0" * 64}, "key_not_attested"),
    ("android", {"challenge": "made-up"}, "challenge_mismatch"),
])
def test_attestation_failures_refuse_registration(people, field_api, platform, override, reason):
    """FR-MOB-004, 8.2 step 5, TC-MOB-004-04, TC-MOB-004-05: only store builds on real devices register."""
    c = field_api(people["inspector"])
    before = Device.objects.filter(person=people["inspector"]).count()
    ph = FakePhone(people["inspector"], platform=platform)
    ch = c.post("/v1/mobile/devices/challenge").json()["challenge"]
    r = c.post("/v1/mobile/devices", {"challenge": ch, "platform": platform, "app_id": "com.tenmina.field",
                                      "public_key": ph.public_key, "attestation": ph.attestation(ch, **override)},
               format="json")
    assert r.status_code == 422 and r.json()["code"] == "attestation-failed"
    assert reason in r.json()["reasons"]
    assert Device.objects.filter(person=people["inspector"]).count() == before


def test_challenge_is_single_use_and_only_for_field_roles(people, field_api, api):
    """8.2 steps 1 and 3: a challenge works once; clients cannot register field devices."""
    c = field_api(people["runner"])
    ph = FakePhone(people["runner"])
    ch = c.post("/v1/mobile/devices/challenge").json()["challenge"]
    body = {"challenge": ch, "platform": "android", "app_id": "com.tenmina.field", "public_key": ph.public_key,
            "attestation": ph.attestation(ch)}
    assert c.post("/v1/mobile/devices", body, format="json").status_code == 201
    other = FakePhone(people["runner"])
    body2 = {**body, "public_key": other.public_key, "attestation": other.attestation(ch)}
    r = c.post("/v1/mobile/devices", body2, format="json")
    assert r.status_code == 422 and "challenge_invalid" in r.json()["reasons"]
    assert api(people["client"]).post("/v1/mobile/devices/challenge").status_code == 403
    ch2 = c.post("/v1/mobile/devices/challenge").json()["challenge"]
    clone = FakePhone(people["runner"])
    r = c.post("/v1/mobile/devices", {**body, "challenge": ch2, "app_id": "com.example.clone",
                                      "public_key": clone.public_key, "attestation": clone.attestation(ch2)},
               format="json")
    assert r.status_code == 422 and "wrong_app" in r.json()["reasons"]
    same = c.post("/v1/mobile/devices", body, format="json")  # the registered key again: same device
    assert same.status_code == 200


def test_ed25519_keys_are_accepted(people, milestone, field_api):
    """8.4: Ed25519 signatures verify like ES256."""
    ph = FakePhone(people["contractor"], alg="EdDSA")
    ph.register()
    sid = milestone()
    _, done = send(field_api(people["contractor"]), ph, sid, jpeg("ed"), **ON_SITE)
    assert done.status_code == 200 and done.json()["status"] == "stored"


# --------------------------------------------------------------------------- inbox and sync (FR-MOB-001)

def test_sync_shows_only_assigned_work_and_removals(gh, people, milestone, visit, field_api):
    """FR-MOB-001, TC-MOB-001-01, TC-MOB-001-03, US-MOB-001 AC2: only assigned work; a removed
    assignment disappears at the next sync."""
    m1, m2 = milestone(), milestone(project="proj-2")
    milestone(person="inspector")
    v = visit()
    c = field_api(people["contractor"])
    first = c.get("/v1/mobile/sync").json()
    assert first["full"] is True
    assert {i["subject_id"] for i in first["items"]} == {str(m1), str(m2)}
    assert first["items"][0]["required_evidence"][0]["key"] == "front"
    carer = field_api(people["carer"]).get("/v1/mobile/inbox").json()
    assert [i["subject_id"] for i in carer] == [str(v)] and carer[0]["point"] == {"lat": 5.5515, "lng": -0.2628}
    from mobile.models import Assignment

    a = Assignment.objects.get(subject_id=m2)
    r = field_api(people["cm"]).post(f"/v1/mobile/assignments/{a.pk}/revoke", {"reason": "Moved"}, format="json")
    assert r.status_code == 200
    delta = c.get(f"/v1/mobile/sync?since={first['token']}").json()
    assert delta["full"] is False and delta["items"] == []
    assert delta["removed"] == [{"subject_type": "milestone", "subject_id": str(m2)}]
    assert c.get("/v1/mobile/assignments").status_code == 200
    assert field_api(people["contractor"]).post(f"/v1/mobile/assignments/{a.pk}/revoke", {},
                                                format="json").status_code == 404


def test_inbox_registry_takes_providers_from_other_modules(gh, people, field_api):
    """FR-MOB-001, ADR-19: line modules register their own work into the field inbox."""
    sid = uuid.uuid4()

    def visits(person):
        if person.pk == people["carer"].pk:
            yield inbox.InboxItem(subject_type="care_visit", subject_id=sid, title="Morning visit", country=gh,
                                  point=(5.55, -0.26), radius_m=100, kind="care_visit")

    def broken(person):
        raise RuntimeError("boom")

    inbox.register(visits)
    inbox.register(broken)
    try:
        items = field_api(people["carer"]).get("/v1/mobile/inbox").json()
        assert [i["subject_id"] for i in items] == [str(sid)]
        assert field_api(people["agent"]).get("/v1/mobile/inbox").json() == []
    finally:
        inbox.unregister(visits)
        inbox.unregister(broken)


def test_staff_assign_and_non_field_people_cannot_be_assigned(gh, people, field_api):
    """FR-MOB-001: case managers assign field work to field roles only."""
    c = field_api(people["cm"])
    body = {"country": "GH", "person": str(people["runner"].pk), "subject_type": "task",
            "subject_id": str(uuid.uuid4()), "title": "Photograph beacons", "kind": "task",
            "required_evidence": [{"key": "beacon", "media": "photo"}]}
    r = c.post("/v1/mobile/assignments", body, format="json")
    assert r.status_code == 201, r.content
    assert c.post("/v1/mobile/assignments", {**body, "person": str(people["client"].pk),
                                             "subject_id": str(uuid.uuid4())}, format="json").status_code == 422
    assert field_api(people["runner"]).post("/v1/mobile/assignments", body, format="json").status_code == 404


# --------------------------------------------------------------------------- signed items (FR-MOB-011)

def test_evidence_journey_is_signed_stored_and_idempotent(people, phone, milestone, field_api):
    """FR-MOB-004, FR-MOB-005, FR-MOB-011, FR-EVD-006, TC-MOB-011-01, TC-MOB-005-03: valid items are
    stored as app-captured with server time; retries never duplicate."""
    ph, sid = phone(), milestone()
    c = field_api(people["contractor"])
    data = jpeg("journey", model=ph.model)
    payload = ph.capture("milestone", sid, data, requirement_key="front", **ON_SITE)
    r = c.post("/v1/mobile/evidence", payload, format="json")
    assert r.status_code == 201
    item = r.json()
    assert item["upload"]["method"] == "PUT" and item["signature_valid"] is True
    again = c.post("/v1/mobile/evidence", payload, format="json")
    assert again.status_code == 200 and again.json()["id"] == item["id"]
    c.put(item["upload"]["url"], data=data[:10], content_type="application/octet-stream")  # dropped upload
    c.put(item["upload"]["url"], data=data, content_type="application/octet-stream")  # resumed
    done = c.post(f"/v1/mobile/evidence/{item['id']}/complete", {}, format="json")
    assert done.status_code == 200 and done.json() == {"status": "stored", "evidence_id": item["evidence_id"],
                                                       "flags": []}
    assert c.post(f"/v1/mobile/evidence/{item['id']}/complete", {}, format="json").json()["status"] == "stored"
    ev = Evidence.objects.get(pk=item["evidence_id"])
    assert ev.provenance == "app_captured" and ev.signature_valid and ev.is_release_grade
    assert ev.device_id == ph.device.pk and ev.received_at and ev.captured_at
    assert SignedManifest.objects.filter(device=ph.device).count() == 1
    assert evd.for_subject("milestone", sid).get() == ev
    assert c.get("/v1/mobile/evidence").json()["items"][0]["status"] == "stored"


def test_conflicting_reuse_of_a_client_item_id_is_refused(people, phone, milestone, field_api):
    """8.5: client_item_id identifies one item; a different item under the same id is a conflict."""
    ph, sid = phone(), milestone()
    c = field_api(people["contractor"])
    p1 = ph.capture("milestone", sid, jpeg("a"), client_item_id="same", **ON_SITE)
    p2 = ph.capture("milestone", sid, jpeg("b"), client_item_id="same", **ON_SITE)
    assert c.post("/v1/mobile/evidence", p1, format="json").status_code == 201
    assert c.post("/v1/mobile/evidence", p2, format="json").status_code == 409


def test_bad_signature_is_rejected_and_flagged(people, phone, milestone, field_api):
    """FR-MOB-011, US-MOB-011a AC2, TC-RUL-08-04: a forged signature is rejected as evidence and flagged."""
    ph, sid = phone(), milestone()
    forger = FakePhone(people["contractor"])
    forger.device = ph.device  # claims the registered device, signs with another key
    payload = forger.capture("milestone", sid, jpeg("forged"), **ON_SITE)
    r = field_api(people["contractor"]).post("/v1/mobile/evidence", payload, format="json")
    assert r.status_code == 422 and r.json()["reason"] == "bad_signature"
    m = SignedManifest.objects.get(pk=r.json()["manifest_id"])
    assert m.status == "rejected" and not m.signature_valid
    assert FraudFlag.objects.get(manifest=m).kind == "bad_signature"
    assert "evidence.flagged" in topics("evidence.flagged")
    # Tampering with the signed manifest after signing breaks the signature too.
    good = ph.capture("milestone", sid, jpeg("t"), **ON_SITE)
    good["manifest"]["location"]["lat"] = 5.7
    assert field_api(people["contractor"]).post("/v1/mobile/evidence", good, format="json").status_code == 422


def test_file_changed_after_capture_is_rejected(people, phone, milestone, field_api):
    """FR-MOB-004 AC2, TC-MOB-004-02: a different file than the one signed is rejected and flagged."""
    ph, sid = phone(), milestone()
    c = field_api(people["contractor"])
    item = c.post("/v1/mobile/evidence", ph.capture("milestone", sid, jpeg("orig"), **ON_SITE), format="json").json()
    c.put(item["upload"]["url"], data=jpeg("edited"), content_type="application/octet-stream")
    r = c.post(f"/v1/mobile/evidence/{item['id']}/complete", {}, format="json")
    assert r.status_code == 422 and r.json()["reason"] == "hash_mismatch"
    assert SignedManifest.objects.get(pk=item["id"]).status == "rejected"
    assert FraudFlag.objects.filter(manifest_id=item["id"], kind="hash_mismatch").exists()
    assert not Evidence.objects.filter(pk=item["evidence_id"]).exists()


def test_revoked_device_cannot_upload_and_its_evidence_is_reflagged(people, phone, milestone, field_api):
    """FR-MOB-011, TC-MOB-011-03: revoking a key stops new items and sends everything it signed to review."""
    ph, sid = phone(), milestone()
    c = field_api(people["contractor"])
    _, d1 = send(c, ph, sid, jpeg("r1"), requirement_key="front", **ON_SITE)
    _, d2 = send(c, ph, sid, mp4("r2"), media_type="video/mp4", requirement_key="walk", **ON_SITE)
    sub = c.post("/v1/mobile/submissions", {"client_submission_id": str(uuid.uuid4()), "subject_type": "milestone",
                                            "subject_id": str(sid), "items": [
                                                {"requirement_key": "front", "evidence_id": d1.json()["evidence_id"]},
                                                {"requirement_key": "walk", "evidence_id": d2.json()["evidence_id"]}]},
                 format="json").json()
    assert sub["status"] == "received"
    r = field_api(people["reviewer"]).post(f"/v1/mobile/devices/{ph.device.pk}/revoke",
                                           {"reason": "Misconduct report"}, format="json")
    assert r.status_code == 200
    assert FraudFlag.objects.filter(device=ph.device, kind="device_revoked", status="open").count() == 2
    assert Submission.objects.get(pk=sub["id"]).status == "held_for_review"
    r = c.post("/v1/mobile/evidence", ph.capture("milestone", sid, jpeg("r3"), **ON_SITE), format="json")
    assert r.status_code == 422 and r.json()["reason"] == "device_revoked"


def test_each_fraud_check_raises_its_flag(gh, people, phone, milestone, field_api):
    """FR-MOB-011, US-MOB-011b, TC-MOB-011-02: distance, accuracy, mock, time gap, early capture,
    reused hash, metadata, emulator and software key flags."""
    ph = phone()
    soft = phone("inspector", key_security="software")
    sid = milestone(previous_pass_at=timezone.now() - timedelta(days=1))
    other = milestone(project="proj-other")
    c = field_api(people["contractor"])
    now = timezone.now()

    def kinds(done):
        return {(f["kind"], f["detail"].get("reason", f["detail"].get("field", f["detail"].get("match"))))
                for f in done.json()["flags"]}

    assert kinds(send(c, ph, sid, jpeg("far"), lat=5.6037, lng=-0.187)[1]) == {("outside_buffer", "distance")}
    assert kinds(send(c, ph, sid, jpeg("acc"), lat=5.6499, lng=-0.1801, accuracy=120)[1]) == \
        {("outside_buffer", "accuracy")}
    assert kinds(send(c, ph, sid, jpeg("mock"), mock=True, **ON_SITE)[1]) == {("outside_buffer", "mock")}
    assert kinds(send(c, ph, sid, jpeg("ahead"), captured_at=now + timedelta(hours=2), **ON_SITE)[1]) == \
        {("time_gap", "device_clock_ahead")}
    old = send(c, ph, sid, jpeg("old"), captured_at=now - timedelta(days=8), **ON_SITE)[1]
    assert ("time_gap", "captured_long_before_upload") in kinds(old)
    assert ("before_previous_pass", None) in kinds(old)
    dup = jpeg("dup")
    send(c, ph, other, dup, **ON_SITE)
    assert kinds(send(c, ph, sid, dup, **ON_SITE)[1]) == {("duplicate_hash", "exact")}
    assert kinds(send(c, ph, sid, jpeg("exif", model="Pixel 8"), **ON_SITE)[1]) == {("metadata_mismatch", "model")}
    assert kinds(send(c, ph, sid, jpeg("emu"), emulator=True, **ON_SITE)[1]) == {("emulator", None)}
    insp_ms = milestone(person="inspector")
    flags = send(field_api(people["inspector"]), soft, insp_ms, jpeg("soft"), **ON_SITE)[1].json()["flags"]
    assert [f["kind"] for f in flags] == ["software_key"]


def test_chain_break_is_flagged(people, phone, milestone, field_api):
    """8.4: previous_item_sha256 chains items on one device; a missing link is detectable."""
    ph, sid = phone(), milestone()
    c = field_api(people["contractor"])
    send(c, ph, sid, jpeg("c1"), **ON_SITE)
    ph.previous = "f" * 64  # an item the server never received
    _, done = send(c, ph, sid, jpeg("c2"), **ON_SITE)
    assert [f["kind"] for f in done.json()["flags"]] == ["chain_break"]


def test_unassigned_capture_uploads_but_cannot_be_submitted(gh, people, phone, field_api):
    """8.6: after an assignment is revoked, queued items still upload, flagged, and cannot be submitted."""
    ph = phone()
    sid = uuid.uuid4()
    c = field_api(people["contractor"])
    _, done = send(c, ph, sid, jpeg("u1"), **ON_SITE)
    assert done.status_code == 200 and "unassigned_capture" in [f["kind"] for f in done.json()["flags"]]
    r = c.post("/v1/mobile/submissions", {"client_submission_id": "x1", "subject_id": str(sid), "items": [
        {"requirement_key": "front", "evidence_id": done.json()["evidence_id"]}]}, format="json")
    assert r.status_code == 404


# --------------------------------------------------------------------------- submissions (FR-MOB-006, FR-MOB-010)

def test_submission_is_blocked_until_every_required_item_is_attached(gh, people, phone, milestone, field_api):
    """FR-MOB-006, TC-MOB-006-02, RUL-08, TC-RUL-08-03, US-EVD-006 AC2: missing items and uploaded files
    block the submission; complete app evidence is accepted once."""
    ph, sid = phone(), milestone()
    c = field_api(people["contractor"])
    _, front = send(c, ph, sid, jpeg("front", model=ph.model), requirement_key="front", **ON_SITE)
    front_id = front.json()["evidence_id"]
    body = {"client_submission_id": str(uuid.uuid4()), "milestone_id": str(sid),
            "items": [{"requirement_key": "front", "evidence_id": front_id}]}
    r = c.post("/v1/mobile/submissions", body, format="json")
    assert r.status_code == 422 and r.json()["missing"] == ["walk"]
    uploaded = evd.store(data=mp4("gallery"), country=gh, uploaded_by=people["contractor"],
                         content_type="video/mp4")
    body["items"].append({"requirement_key": "walk", "evidence_id": str(uploaded.pk)})
    r = c.post("/v1/mobile/submissions", body, format="json")
    assert r.status_code == 422 and r.json()["blocking_reasons"][0]["rule"] == "RUL-08"
    body["items"][1] = {"requirement_key": "walk", "evidence_id": front_id}
    r = c.post("/v1/mobile/submissions", body, format="json")
    assert r.status_code == 422  # a photo cannot stand in for the video
    _, walk = send(c, ph, sid, mp4("walk"), media_type="video/mp4", requirement_key="walk", **ON_SITE)
    body["items"][1] = {"requirement_key": "walk", "evidence_id": walk.json()["evidence_id"]}
    r = c.post("/v1/mobile/submissions", body, format="json", HTTP_IDEMPOTENCY_KEY=body["client_submission_id"])
    assert r.status_code == 202 and r.json()["status"] == "received"
    replay = c.post("/v1/mobile/submissions", body, format="json")
    assert replay.status_code == 202 and replay.json()["id"] == r.json()["id"]
    assert Submission.objects.filter(subject_id=sid).count() == 1
    ev = OutboxEvent.objects.filter(topic="submission.received").latest("created_at")
    assert ev.payload["flagged"] is False and len(ev.payload["items"]) == 2


def test_flagged_submission_goes_to_a_reviewer_who_clears_it(gh, people, phone, milestone, field_api):
    """FR-MOB-011, US-MOB-011b AC4: a flagged submission is held for review; clearing every flag publishes
    flags.cleared so the inspection can be scheduled. Upholding is recorded too."""
    ph, sid = phone(), milestone(required_evidence=[{"key": "front", "media": "photo"}])
    c = field_api(people["contractor"])
    _, d = send(c, ph, sid, jpeg("off"), requirement_key="front", lat=5.6037, lng=-0.187)
    r = c.post("/v1/mobile/submissions", {"client_submission_id": "s-flag", "subject_type": "milestone",
                                          "subject_id": str(sid), "items": [
                                              {"requirement_key": "front", "evidence_id": d.json()["evidence_id"]}]},
               format="json")
    assert r.status_code == 202 and r.json()["status"] == "held_for_review" and r.json()["open_flags"] == 1
    from notifications.models import Message

    assert Message.objects.filter(person=people["reviewer"], template="field_flags_review").exists()
    rv = field_api(people["reviewer"])
    queue = rv.get(f"/v1/mobile/fraud-flags?status=open&submission={r.json()['id']}").json()["items"]
    assert len(queue) == 1
    flag_id = queue[0]["id"]
    assert rv.post(f"/v1/mobile/fraud-flags/{flag_id}/clear", {}, format="json").status_code == 400
    assert c.get("/v1/mobile/fraud-flags").status_code == 403
    done = rv.post(f"/v1/mobile/fraud-flags/{flag_id}/clear", {"note": "Photo taken at the supplier's yard, "
                                                                       "confirmed by call"}, format="json")
    assert done.status_code == 200 and done.json()["status"] == "cleared"
    assert Submission.objects.get(pk=r.json()["id"]).status == "cleared"
    ev = OutboxEvent.objects.filter(topic="flags.cleared").latest("created_at")
    assert ev.payload["outcome"] == "cleared" and ev.payload["submission_id"] == r.json()["id"]
    assert rv.post(f"/v1/mobile/fraud-flags/{flag_id}/uphold", {"note": "x"}, format="json").status_code == 409


def test_upheld_flag_marks_the_submission_and_blocks_release(gh, people, phone, milestone, field_api):
    """FR-MOB-011: an upheld flag is reported to the owning module and blocks release evidence."""
    ph, sid = phone(), milestone(required_evidence=[{"key": "front", "media": "photo"}])
    c = field_api(people["contractor"])
    _, d = send(c, ph, sid, jpeg("up"), requirement_key="front", lat=5.6037, lng=-0.187)
    eid = d.json()["evidence_id"]
    c.post("/v1/mobile/submissions", {"client_submission_id": "s-up", "subject_id": str(sid), "items": [
        {"requirement_key": "front", "evidence_id": eid}]}, format="json")
    assert services.evidence_blockers([eid])[0]["rule"] == "FR-MOB-011"
    f = FraudFlag.objects.get(evidence_id=eid)
    services.review_flag(f, people["reviewer"], "uphold", "Photo is of another site")
    assert Submission.objects.get(client_submission_id="s-up").status == "upheld"
    assert OutboxEvent.objects.filter(topic="flags.cleared", payload__outcome="upheld").exists()
    assert OutboxEvent.objects.filter(topic="flag.upheld").exists()
    assert any("upheld" in b["message"] for b in services.evidence_blockers([eid]))


def test_reviewer_cannot_review_their_own_evidence(gh, people, phone, milestone):
    """FR-MOB-011: the person who captured the evidence never reviews its flags.
    A case manager may review flags and, holding no payment rights, may also inspect
    (seeded reviewers hold payment rights, so they cannot hold a field role)."""
    from accounts.models import RoleGrant

    RoleGrant.objects.create(person=people["cm"], role="IN")
    ph, sid = phone("cm"), milestone(person="cm")
    m, _ = services.register_item(people["cm"], ph.capture("milestone", sid, jpeg("own"), lat=5.0, lng=0.0))
    m, flags = services.complete_item(m, people["cm"], jpeg("own"))
    from core.errors import Forbidden

    with pytest.raises(Forbidden):
        services.review_flag(flags[0], people["cm"], "clear", "Fine")


def test_returned_milestone_refuses_submission_with_state_conflict(gh, people, phone, milestone, field_api):
    """8.6: if the milestone changed while offline, the submission gets 409 state-conflict."""
    ph, sid = phone(), milestone(required_evidence=[{"key": "front", "media": "photo"}])
    c = field_api(people["contractor"])
    _, d = send(c, ph, sid, jpeg("ret"), requirement_key="front", **ON_SITE)
    publish("milestone.status_changed", sid, {"entity": "milestone", "id": str(sid), "from": "in_progress",
                                              "to": "returned"})
    r = c.post("/v1/mobile/submissions", {"client_submission_id": "s-ret", "subject_id": str(sid), "items": [
        {"requirement_key": "front", "evidence_id": d.json()["evidence_id"]}]}, format="json")
    assert r.status_code == 409 and "returned" in r.json()["detail"]
    publish("milestone.status_changed", sid, {"entity": "milestone", "id": str(sid), "from": "returned",
                                              "to": "in_progress"})
    r = c.post("/v1/mobile/submissions", {"client_submission_id": "s-ret2", "subject_id": str(sid), "items": [
        {"requirement_key": "front", "evidence_id": d.json()["evidence_id"]}]}, format="json")
    assert r.status_code == 202  # stored evidence is reused in the next submission


def test_runner_carer_and_agent_capture_the_same_way(gh, people, phone, visit, field_api):
    """FR-MOB-010, TC-MOB-010-01, TC-MOB-010-02: task, visit and errand evidence is app-captured, signed
    and linked; form items (readings, ticks) travel in the same submission."""
    from mobile.services import assign

    task = uuid.uuid4()
    assign(person=people["runner"], subject_type="task", subject_id=task, title="Beacons", country=gh,
           by=people["cm"], boundary=[[5.6502, -0.1805], [5.6502, -0.1797], [5.6496, -0.1797], [5.6496, -0.1805]],
           required_evidence=[{"key": "beacon", "media": "photo"}])
    rn = phone("runner")
    _, d = send(field_api(people["runner"]), rn, task, jpeg("beacon"), subject_type="task", requirement_key="beacon",
                **ON_SITE)
    assert Evidence.objects.get(pk=d.json()["evidence_id"]).links.get().subject_type == "task"
    v = visit(required_evidence=[{"key": "bp", "media": "reading"}, {"key": "kitchen", "media": "photo"}])
    cr = phone("carer")
    cc = field_api(people["carer"])
    _, k = send(cc, cr, v, jpeg("kitchen"), subject_type="care_visit", requirement_key="kitchen", lat=5.5515,
                lng=-0.2628)
    r = cc.post("/v1/mobile/submissions", {"client_submission_id": "visit-items", "subject_type": "care_visit",
                                           "subject_id": str(v), "items": [
                                               {"requirement_key": "bp", "value": {"systolic": 128, "diastolic": 82}},
                                               {"requirement_key": "kitchen", "evidence_id": k.json()["evidence_id"]}]},
                format="json")
    assert r.status_code == 202, r.content
    assert {i["kind"] for i in r.json()["items"]} == {"form", "evidence"}
    step = visit(person="agent", subject_type="errand_step")
    ag = phone("agent")
    _, rc = send(field_api(people["agent"]), ag, step, jpeg("receipt"), subject_type="errand_step",
                 requirement_key="receipt", lat=5.5515, lng=-0.2628)
    assert Evidence.objects.get(pk=rc.json()["evidence_id"]).is_release_grade
    other = field_api(people["agent"]).post("/v1/mobile/submissions", {
        "client_submission_id": "steal", "subject_type": "care_visit", "subject_id": str(v), "items": []},
        format="json")
    assert other.status_code == 404  # TC-MOB-010-03: another worker's visit is not found


# --------------------------------------------------------------------------- inspections (FR-MOB-007)

def test_inspection_results_follow_the_rules(gh, people, phone, field_api):
    """FR-MOB-007, TC-MOB-007-01, TC-MOB-007-02, RUL-09: every checklist item answered; each defect has
    photos and a value; a fail has a reason."""
    sid = uuid.uuid4()
    services.assign(person=people["inspector"], subject_type="milestone_inspection", subject_id=sid,
                    title="Inspect foundation", country=gh, by=people["cm"], point_lat="5.649900",
                    point_lng="-0.180100", checklist=[{"key": "depth"}, {"key": "rebar"}])
    ph = phone("inspector", platform="ios")
    c = field_api(people["inspector"])
    _, photo = send(c, ph, sid, jpeg("defect", model=ph.model, make="Apple"), subject_type="milestone_inspection",
                    requirement_key="defect_1", **ON_SITE)
    pid = photo.json()["evidence_id"]
    full = [{"key": "depth", "result": "ok"}, {"key": "rebar", "result": "not_ok"}]
    base = {"subject_id": str(sid), "checklist": full}

    def post(**kw):
        return c.post("/v1/mobile/inspections", {"client_submission_id": str(uuid.uuid4()), **base, **kw},
                      format="json")

    assert post(outcome="pass", checklist=full[:1]).status_code == 422
    assert post(outcome="pass_with_defects").status_code == 422
    assert post(outcome="pass_with_defects", defects=[{"description": "Thin cover", "evidence_ids": [pid],
                                                       "value": {"amount": "0", "currency": "GHS"}}]).status_code == 422
    no_photo = [{"description": "Thin cover", "evidence_ids": [], "value": {"amount": "500", "currency": "GHS"}}]
    assert post(outcome="pass_with_defects", defects=no_photo).status_code == 422
    assert post(outcome="fail").status_code == 422
    assert post(outcome="pass", defects=[{"description": "x"}]).status_code == 422
    r = post(outcome="pass_with_defects", defects=[{"description": "Thin cover", "evidence_ids": [pid],
                                                    "value": {"amount": "500", "currency": "GHS"}}])
    assert r.status_code == 202, r.content
    assert r.json()["defects"][0]["value"] == {"amount": "500.00", "currency": "GHS"}
    ev = OutboxEvent.objects.filter(topic="submission.received").latest("created_at")
    assert ev.payload["kind"] == "inspection" and ev.payload["outcome"] == "pass_with_defects"
    assert post(outcome="fail", reason="Trench too shallow").status_code == 202


# --------------------------------------------------------------------------- check-in and check-out (FR-MOB-012)

def test_checkin_and_checkout_at_the_registered_address(people, phone, visit, field_api):
    """FR-MOB-012, RUL-23, TC-MOB-012-01: both stored with position, accuracy and time, signed as app evidence;
    duration computed; checkin.recorded and checkout.recorded published."""
    v, ph = visit(), phone("carer")
    c = field_api(people["carer"])
    start = timezone.now() - timedelta(minutes=50)
    r = c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", v, lat=5.5516, lng=-0.2627,
                                                captured_at=start), format="json")
    assert r.status_code == 201, r.content
    ci = r.json()
    assert ci["within_radius"] is True and float(ci["distance_m"]) < 20 and ci["flags"] == []
    out = c.post("/v1/mobile/check-outs", ph.check("checkout", "care_visit", v, lat=5.5515, lng=-0.2628,
                                                   captured_at=start + timedelta(minutes=45)), format="json")
    assert out.status_code == 201 and out.json()["duration_minutes"] == 45 and out.json()["checkin"] == ci["id"]
    published = OutboxEvent.objects.filter(topic__in=["checkin.recorded", "checkout.recorded"],
                                           payload__subject_id=str(v)).order_by("created_at")
    assert list(published.values_list("topic", flat=True)) == ["checkin.recorded", "checkout.recorded"]
    ev = Evidence.objects.get(pk=ci["evidence"])
    assert ev.provenance == "app_captured" and ev.content_type == "application/json"
    assert ev.links.get().role == "checkin"
    listed = c.get(f"/v1/mobile/check-ins?subject_id={v}").json()
    assert {x["kind"] for x in listed} == {"checkin", "checkout"}


def test_checkin_far_away_or_imprecise_is_recorded_and_flagged(people, phone, visit, field_api):
    """FR-MOB-012 AC2, TC-MOB-012-02: 2 km away or 300 m accuracy is recorded, flagged and shown."""
    ph, c = phone("carer"), field_api(people["carer"])
    r = c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", visit(), lat=5.5690, lng=-0.2560),
               format="json")
    assert r.status_code == 201 and r.json()["within_radius"] is False
    assert r.json()["flags"][0]["kind"] == "outside_address_radius"
    assert r.json()["flags"][0]["detail"]["reason"] == "distance"
    r = c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", visit(), lat=5.5515, lng=-0.2628,
                                                accuracy=300), format="json")
    assert r.json()["flags"][0]["detail"]["reason"] == "accuracy"


def test_checkout_needs_a_checkin_and_a_long_enough_visit(gh, people, phone, visit, field_api):
    """FR-MOB-012, 8.8: no check-out without a check-in (service and database); too short is flagged."""
    v, ph, c = visit(), phone("carer"), field_api(people["carer"])
    prev = ph.previous
    r = c.post("/v1/mobile/check-outs", ph.check("checkout", "care_visit", v, lat=5.5515, lng=-0.2628),
               format="json")
    assert r.status_code == 409
    ph.previous = prev
    now = timezone.now()
    c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", v, lat=5.5515, lng=-0.2628,
                                            captured_at=now - timedelta(minutes=10)), format="json")
    out = c.post("/v1/mobile/check-outs", ph.check("checkout", "care_visit", v, lat=5.5515, lng=-0.2628,
                                                   captured_at=now), format="json")
    assert [f["kind"] for f in out.json()["flags"]] == ["checkout_too_soon"]
    dup = c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", v, lat=5.5515, lng=-0.2628),
                 format="json")
    assert dup.status_code == 409
    first = CheckIn.objects.get(subject_id=v, kind="checkin")
    with pytest.raises(IntegrityError), transaction.atomic():
        CheckIn.objects.create(country=gh, device=first.device, person=first.person, subject_type="care_visit",
                               subject_id=uuid.uuid4(), kind="checkout", manifest=SignedManifest.objects.filter(
                                   kind="evidence").first() or first.manifest, evidence=first.evidence,
                               latitude=0, longitude=0, accuracy_m=1, registered_lat=0, registered_lng=0,
                               distance_m=0, radius_m=100, within_radius=True, device_time=now,
                               signature_valid=True)


def test_checkin_without_gps_is_blocked_and_offline_checkin_is_flagged_late(people, phone, visit, field_api):
    """FR-MOB-012 AC3, TC-MOB-012-03: no position is refused with an instruction; an offline check-in
    keeps its original time and is flagged when uploaded long after."""
    ph, c = phone("carer"), field_api(people["carer"])
    prev = ph.previous
    r = c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", visit(), lat=None, lng=None),
               format="json")
    assert r.status_code == 422 and "location" in r.json()["detail"]
    ph.previous = prev  # the app never queues a check-in without a position
    when = timezone.now() - timedelta(hours=3)
    r = c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", visit(), lat=5.5515, lng=-0.2628,
                                                captured_at=when), format="json")
    assert r.status_code == 201
    assert r.json()["device_time"].startswith(when.strftime("%Y-%m-%dT%H:%M"))
    assert [f["kind"] for f in r.json()["flags"]] == ["time_gap"]


def test_missing_checkout_is_reported_once(people, phone, visit, field_api):
    """TC-MOB-012-04: a check-in left without a check-out is reported once and the worker told."""
    from notifications.models import Message

    v, ph, c = visit(), phone("carer"), field_api(people["carer"])
    c.post("/v1/mobile/check-ins", ph.check("checkin", "care_visit", v, lat=5.5515, lng=-0.2628,
                                            captured_at=timezone.now() - timedelta(minutes=30)), format="json")
    assert v not in [ci.subject_id for ci in services.missing_checkouts()]
    later = timezone.now() + timedelta(hours=13)
    assert v in [ci.subject_id for ci in services.missing_checkouts(now=later)]
    assert services.missing_checkouts(now=later) == []
    assert OutboxEvent.objects.filter(topic="checkout.missing", payload__subject_id=str(v)).count() == 1
    assert Message.objects.filter(person=people["carer"], template="field_checkout_missing").exists()


def test_checkin_is_idempotent_and_only_for_assigned_visits(people, phone, visit, field_api):
    """FR-MOB-005: a retried check-in returns the same record; another carer's visit is not found."""
    v, ph, c = visit(), phone("carer"), field_api(people["carer"])
    payload = ph.check("checkin", "care_visit", v, lat=5.5515, lng=-0.2628)
    a = c.post("/v1/mobile/check-ins", payload, format="json")
    b = c.post("/v1/mobile/check-ins", payload, format="json")
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    other = phone("agent")
    r = field_api(people["agent"]).post("/v1/mobile/check-ins", other.check("checkin", "care_visit", v,
                                                                            lat=5.5515, lng=-0.2628), format="json")
    assert r.status_code == 404


# --------------------------------------------------------------------------- minimum version (FR-APP-006)

def test_old_app_gets_426_but_queued_evidence_still_uploads(gh, people, phone, milestone, api):
    """FR-APP-006, 8.10: below the minimum the API answers 426; evidence captured before the raise is
    accepted for 30 days; new capture waits for the update."""
    ph, sid = phone(), milestone()
    queued = ph.capture("milestone", sid, jpeg("queued"), captured_at=timezone.now() - timedelta(hours=1),
                        **ON_SITE)
    FeatureFlag.objects.filter(name="app.min_version.field.android").update(value="2.0.0",
                                                                           updated_at=timezone.now())
    c = api(people["contractor"])
    old = {"HTTP_TENMINA_APP": "field/android/1.0.0"}
    r = c.get("/v1/mobile/sync", **old)
    assert r.status_code == 426 and r.json()["code"] == "app-version-unsupported" and r.json()["min_version"] == "2.0.0"
    assert c.post("/v1/mobile/evidence", queued, format="json", **old).status_code == 201
    fresh = ph.capture("milestone", sid, jpeg("fresh"), **ON_SITE)
    assert c.post("/v1/mobile/evidence", fresh, format="json", **old).status_code == 426
    assert c.get("/v1/mobile/sync", HTTP_TENMINA_APP="field/android/2.0.1").status_code == 200
    assert c.get("/v1/mobile/sync").status_code == 200  # the web portal sends no app header
    cfg = api().get("/v1/mobile/app-config?app=field&platform=android&version=1.0.0").json()
    assert cfg["update_required"] is True and cfg["min_version"] == "2.0.0" and cfg["store_url"]


def test_version_middleware_answers_426(rf, seeded):
    """FR-APP-006: the middleware checks the header on every /v1/ call."""
    from mobile.appversion import AppVersionMiddleware

    FeatureFlag.objects.filter(name="app.min_version.client.ios").update(value="3.0.0")
    mw = AppVersionMiddleware(lambda req: "ok")
    assert mw(rf.get("/v1/me", HTTP_TENMINA_APP="client/ios/2.9.9")).status_code == 426
    assert mw(rf.get("/v1/me", HTTP_TENMINA_APP="client/ios/3.0.0")) == "ok"
    assert mw(rf.get("/v1/mobile/app-config", HTTP_TENMINA_APP="client/ios/1.0.0")) == "ok"


# --------------------------------------------------------------------------- integrity and database rules

def test_failed_integrity_check_flags_the_device_and_its_items(people, phone, milestone, field_api):
    """8.2 step 7: a later failed Play Integrity or App Attest check flags the device for a reviewer."""
    ph, sid = phone(platform="ios"), milestone()
    c = field_api(people["contractor"])
    send(c, ph, sid, jpeg("i1", model=ph.model, make="Apple"), **ON_SITE)
    ok = c.post(f"/v1/mobile/devices/{ph.device.pk}/integrity-checks", {"assertion": {"counter": 5}}, format="json")
    assert ok.status_code == 200 and ok.json()["integrity_status"] == "ok"
    bad = c.post(f"/v1/mobile/devices/{ph.device.pk}/integrity-checks", {"assertion": {"counter": 5}}, format="json")
    assert bad.json()["integrity_status"] == "failed"
    assert FraudFlag.objects.filter(device=ph.device, kind="integrity_failed").count() == 1
    _, d = send(c, ph, sid, jpeg("i2", model=ph.model, make="Apple"), **ON_SITE)
    assert "integrity_failed" in [f["kind"] for f in d.json()["flags"]]


def test_signed_manifests_cannot_be_altered_in_the_database(people, phone, milestone, field_api):
    """FR-MOB-004, ADR-02: what was signed, by whom and when never changes."""
    ph, sid = phone(), milestone()
    item, _ = send(field_api(people["contractor"]), ph, sid, jpeg("db"), **ON_SITE)
    for change in ({"signature": "x"}, {"manifest": {}}, {"received_at": timezone.now()}, {"signature_valid": False}):
        with pytest.raises(DatabaseError), transaction.atomic():
            SignedManifest.objects.filter(pk=item["id"]).update(**change)
    with pytest.raises(DatabaseError), transaction.atomic():
        Device.objects.filter(pk=ph.device.pk).update(person=people["runner"])


def test_canonical_json_follows_rfc_8785():
    """8.4: canonical bytes are what the device signs."""
    assert crypto.canonical({"b": 1, "a": [1.5, True, None, "é"], "c": {"z": 1e21, "y": 1e-7, "x": 2.0}}) == \
        '{"a":[1.5,true,null,"é"],"b":1,"c":{"x":2,"y":1e-7,"z":1e+21}}'.encode()
