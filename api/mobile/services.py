"""MOB Field app server: the public interface other modules may call.

Devices and attestation (8.2), signed items (8.4), sync (8.5), conflicts (8.6),
fraud checks (8.7), check-in and check-out (8.8, FR-MOB-012), submissions and
inspection results (FR-MOB-006, FR-MOB-007), flag review (FR-MOB-011).
"""
import hashlib
import json
import secrets
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from audit.services import record
from core import state
from core.adapters import get_adapter
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict
from core.events import publish
from core.ids import uuid7

from . import crypto, fraud, inbox
from .models import (
    CHECKIN_SUBJECTS, FIELD_ROLES, Assignment, CheckIn, Device, DeviceChallenge, FraudFlag, SignedManifest,
    Submission, SubmissionItem, SyncCursor,
)

CHALLENGE_TTL = timedelta(minutes=5)
EVIDENCE_SCHEMA = "tenmina.evidence.v1"
CHECKIN_SCHEMA = "tenmina.checkin.v1"
MAX_MEDIA_BYTES = 200 * 1024 * 1024
UPLOAD_URL_TTL = 900


def _attestation():
    return get_adapter("mobile_attestation", default="mobile.adapters.FakeAttestation")


def _staging():
    return get_adapter("mobile_upload_staging", default="mobile.adapters.LocalUploadStaging")


def is_field_worker(person) -> bool:
    return person.is_authenticated and person.has_tenmina_role(*FIELD_ROLES)


def _require_field_worker(person):
    if not is_field_worker(person):
        raise Forbidden("Tenmina Field is for contractors, inspectors, runners, surveyors, lawyers, quantity "
                        "surveyors, carers and errand agents.")


def _reject(message, reason, **extra):
    return Invalid(message, code="evidence-rejected", extra={"reason": reason, **extra})


# --------------------------------------------------------------------------- devices (8.2)

def issue_challenge(person) -> DeviceChallenge:
    _require_field_worker(person)
    return DeviceChallenge.objects.create(person=person, nonce=secrets.token_urlsafe(32),
                                          expires_at=timezone.now() + CHALLENGE_TTL)


def register_device(person, *, challenge, platform, app_id, public_key, attestation, model="", os_version="",
                    app_version="") -> tuple[Device, bool]:
    """Store builds only. A failed attestation is refused with attestation-failed (422)."""
    _require_field_worker(person)
    if platform not in Device.PLATFORMS:
        raise Invalid("Platform must be android or ios.")
    try:
        key = crypto.load_public_key(public_key)
        alg = crypto.key_algorithm(key)
        spki = crypto.spki_b64(key)
    except Exception:  # noqa: BLE001
        raise Invalid("The public key must be a P-256 ECDSA or Ed25519 key in SubjectPublicKeyInfo form.") from None
    fingerprint = hashlib.sha256(crypto.b64decode_any(spki)).hexdigest()
    existing = Device.objects.filter(key_fingerprint=fingerprint).first()
    if existing:
        if existing.person_id == person.pk and existing.status == "active":
            return existing, False
        raise Invalid("This key is already registered. Restart the app to make a new key.")
    with transaction.atomic():
        ch = DeviceChallenge.objects.select_for_update().filter(nonce=challenge, person=person).first()
        reasons = []
        if ch is None or ch.used_at is not None or ch.expires_at < timezone.now():
            reasons.append("challenge_invalid")
        if ch is not None and ch.used_at is None:
            ch.used_at = timezone.now()
            ch.save(update_fields=["used_at"])
        result = _attestation().verify(platform=platform, challenge=challenge, public_key=spki,
                                       attestation=attestation, app_id=app_id)
        reasons += result.get("reasons", []) if not result.get("ok") else []
        if reasons:
            record(actor=person, action="device.attestation_failed", entity="person", entity_id=person.pk,
                   data={"platform": platform, "reasons": reasons, "model": model})
    if reasons:
        raise DomainError("This copy of Tenmina Field could not be verified. Install it from the App Store or "
                          "Google Play and try again.", code="attestation-failed", status=422,
                          title="Device attestation failed", extra={"reasons": reasons})
    with transaction.atomic():
        d = Device.objects.create(
            person=person, platform=platform, app_id=app_id, public_key=spki, key_alg=alg,
            key_fingerprint=fingerprint, key_security=result["key_security"],
            attestation_kind="app_attest" if platform == "ios" else "android_key_attestation",
            attestation=attestation or {}, app_attest_key_id=result.get("app_attest_key_id", ""),
            app_attest_counter=result.get("counter"), integrity_verdict=result.get("verdict", {}),
            app_signing_digest=result.get("signing_digest", ""), model=model, os_version=os_version,
            app_version=app_version, last_seen_at=timezone.now())
        record(actor=person, action="device.registered", entity="mob_device", entity_id=d.pk,
               data={"platform": platform, "key_security": d.key_security, "model": model, "alg": alg})
        publish("device.registered", d.pk, {"device_id": d.pk, "person_id": person.pk, "platform": platform,
                                            "key_security": d.key_security})
    return d, True


def _flag(*, kind, detail, country, evidence=None, manifest=None, checkin=None, device=None, subject_type="",
          subject_id=None) -> FraudFlag:
    return FraudFlag.objects.create(kind=kind, detail=detail, country=country, evidence=evidence, manifest=manifest,
                                    checkin=checkin, device=device, subject_type=subject_type,
                                    subject_id=subject_id)


def _hold_submissions_for(evidence_ids, actor=None):
    for sub in Submission.objects.filter(items__evidence_id__in=evidence_ids,
                                         status__in=["received", "cleared"]).distinct():
        state.transition(sub, "mob_submission", "held_for_review", actor=actor, event="submission.held",
                         payload={"submission_id": sub.pk, "subject_type": sub.subject_type,
                                  "subject_id": sub.subject_id})


def _publish_flagged(manifest, evidence, flags):
    publish("evidence.flagged", evidence.pk if evidence else manifest.pk, {
        "evidence_id": evidence.pk if evidence else None, "manifest_id": manifest.pk if manifest else None,
        "subject_type": manifest.subject_type if manifest else "", "subject_id": manifest.subject_id if manifest
        else None, "person_id": manifest.person_id if manifest else None,
        "flags": [{"id": f.pk, "kind": f.kind} for f in flags]})


def revoke_device(device: Device, by, reason: str) -> Device:
    """Lost phone or misconduct. New items stop; everything it signed goes back to a reviewer (TC-MOB-011-03)."""
    if not reason:
        raise Invalid("Say why the device is revoked.")
    with transaction.atomic():
        device.revoked_at, device.revoked_by, device.revoke_reason = timezone.now(), by, reason
        state.transition(device, "mob_device", "revoked", actor=by, event="device.revoked", reason=reason,
                         extra_fields=["revoked_at", "revoked_by", "revoke_reason"],
                         payload={"device_id": device.pk, "person_id": device.person_id})
        ids = []
        for m in device.manifests.filter(status="stored", evidence__isnull=False).select_related("evidence"):
            f = _flag(kind="device_revoked", detail={"reason": reason, "revoked_by": str(by.pk)},
                      country=m.country, evidence=m.evidence, manifest=m, device=device,
                      subject_type=m.subject_type, subject_id=m.subject_id)
            ids.append(m.evidence_id)
            _publish_flagged(m, m.evidence, [f])
        _hold_submissions_for(ids, actor=by)
    return device


def integrity_check(device: Device, payload: dict, by=None) -> Device:
    """A later Play Integrity or App Attest check (8.2 step 7). A failure flags the device and its items."""
    result = _attestation().check(device, payload)
    with transaction.atomic():
        device.integrity_verdict = result.get("verdict", {})
        if result.get("counter") is not None and result["ok"]:
            device.app_attest_counter = result["counter"]
        device.last_seen_at = timezone.now()
        if not result["ok"] and device.integrity_status != "failed":
            device.integrity_status = "failed"
            ids = []
            for m in device.manifests.filter(status="stored", evidence__isnull=False).select_related("evidence"):
                f = _flag(kind="integrity_failed", detail={"reasons": result["reasons"]}, country=m.country,
                          evidence=m.evidence, manifest=m, device=device, subject_type=m.subject_type,
                          subject_id=m.subject_id)
                ids.append(m.evidence_id)
                _publish_flagged(m, m.evidence, [f])
            _hold_submissions_for(ids, actor=by)
            record(actor=by, action="device.integrity_failed", entity="mob_device", entity_id=device.pk,
                   data={"reasons": result["reasons"]})
        device.save(update_fields=["integrity_verdict", "app_attest_counter", "last_seen_at", "integrity_status"])
    return device


# --------------------------------------------------------------------------- assignments (manual inbox adapter)

def assign(*, person, subject_type, subject_id, title, country, by=None, **fields) -> Assignment:
    if not person.has_tenmina_role(*FIELD_ROLES):
        raise Invalid("Only field workers can be assigned field work.")
    with transaction.atomic():
        a = Assignment.objects.filter(person=person, subject_type=subject_type, subject_id=subject_id,
                                      status="active").first()
        if a:
            for k, v in fields.items():
                setattr(a, k, v)
            a.title = title
            a.save()
        else:
            a = Assignment.objects.create(person=person, subject_type=subject_type, subject_id=subject_id,
                                          title=title, country=country, created_by=by, **fields)
        record(actor=by, action="mob_assignment.assigned", entity="mob_assignment", entity_id=a.pk,
               data={"person": str(person.pk), "subject_type": subject_type, "subject_id": str(subject_id)},
               country=country)
        publish("field.assigned", a.pk, {"assignment_id": a.pk, "person_id": person.pk,
                                         "subject_type": subject_type, "subject_id": subject_id})
    from notifications.services import notify

    notify(person, "field_assignment", subject="New work in Tenmina Field",
           body=f"You have new work: {title}. Open Tenmina Field to see it.", channels=("in_app", "push"),
           subject_obj=a)
    return a


def revoke_assignment(a: Assignment, by, reason="") -> Assignment:
    a.revoked_at = timezone.now()
    return state.transition(a, "mob_assignment", "revoked", actor=by, event="field.unassigned", reason=reason,
                            extra_fields=["revoked_at"],
                            payload={"person_id": a.person_id, "subject_type": a.subject_type,
                                     "subject_id": a.subject_id})


def set_submission_state(subject_type, subject_id, *, accepts: bool, reason="", previous_pass_at=None):
    """For line modules using manual assignments: close or reopen submissions (8.6)."""
    qs = Assignment.objects.filter(subject_type=subject_type, subject_id=subject_id, status="active")
    upd = {"accepts_submissions": accepts, "state_reason": reason, "updated_at": timezone.now()}
    if previous_pass_at is not None:
        upd["previous_pass_at"] = previous_pass_at
    qs.update(**upd)


# --------------------------------------------------------------------------- sync (8.5 step 1)

def _digest(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def client_settings(country) -> dict:
    return {
        "plot_buffer_m": fraud.setting(country, "plot_buffer_m"),
        "checkin_radius_m": fraud.setting(country, "checkin_radius_m"),
        "max_accuracy_m": fraud.setting(country, "max_accuracy_m"),
        "photo_long_edge_px": 2048, "photo_jpeg_quality": 80,  # FR-MOB-008, assumptions
        "video_max_seconds": 60, "video_max_height": 720,
        "multipart_threshold_bytes": 8 * 1024 * 1024,
    }


def sync(person, *, since: str | None = None, device: Device | None = None) -> dict:
    _require_field_worker(person)
    items = inbox.items_for(person)
    current = {it.key: it for it in items}
    digests = {k: _digest(it.as_dict()) for k, it in current.items()}
    prev = None
    if since:
        try:
            prev = SyncCursor.objects.filter(pk=since, person=person).first()
        except Exception:  # noqa: BLE001 - not a valid token: send everything
            prev = None
    if prev is None:
        changed, removed = list(current.values()), []
    else:
        changed = [it for k, it in current.items() if prev.digests.get(k) != digests[k]]
        removed = [{"subject_type": k.split(":", 1)[0], "subject_id": k.split(":", 1)[1]}
                   for k in prev.keys if k not in current]
    cursor = SyncCursor.objects.create(person=person, device=device, keys=sorted(current), digests=digests)
    if device is not None:
        Device.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
    devices = list(Device.objects.filter(person=person).values("id", "status", "platform", "model"))
    return {"token": str(cursor.pk), "server_time": timezone.now(), "full": prev is None,
            "items": [it.as_dict() for it in changed], "removed": removed,
            "settings": client_settings(person.home_country), "devices": devices}


# --------------------------------------------------------------------------- signed items (8.4, 8.5)

def _parse_time(value, field):
    dt = parse_datetime(value) if isinstance(value, str) else None
    if dt is None or dt.tzinfo is None:
        raise Invalid(f"{field} must be an ISO 8601 time with a time zone.")
    return dt


def _read_manifest(person, payload: dict, schema: str):
    """Common checks for a signed item. Returns (device, manifest dict, canonical bytes, valid)."""
    if not isinstance(payload, dict) or not isinstance(payload.get("manifest"), dict):
        raise Invalid("Send {manifest, signature, signature_alg}.")
    m = payload["manifest"]
    sig, alg = payload.get("signature") or "", payload.get("signature_alg") or ""
    if m.get("schema") != schema:
        raise Invalid(f"The manifest schema must be {schema}.")
    for f in ("client_item_id", "device_id", "subject", "captured_at_device"):
        if not m.get(f):
            raise Invalid(f"The manifest needs {f}.")
    device = Device.objects.filter(pk=m.get("device_id")).first() if _is_uuid(m.get("device_id")) else None
    if device is None or device.person_id != person.pk:
        raise _reject("This phone is not registered to you. Sign in again on this phone.", "unknown_device")
    canon = crypto.canonical(m)
    valid = alg in crypto.ALGORITHMS and alg == device.key_alg and crypto.verify(device.public_key, alg, canon, sig)
    return device, m, canon, valid, sig, alg


def _is_uuid(v) -> bool:
    import uuid

    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False


def _location(m):
    loc = m.get("location") or {}
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None, None, None, False
    acc = loc.get("accuracy_m")
    return (Decimal(str(round(float(lat), 6))), Decimal(str(round(float(lng), 6))),
            Decimal(str(round(float(acc), 2))) if acc is not None else None, bool(loc.get("mock")))


def _corrected(m, captured):
    sync_info = m.get("last_server_time_sync") or {}
    try:
        offset = int(sync_info.get("offset_ms", 0))  # server time minus device time at the last sync
    except (TypeError, ValueError):
        offset = 0
    return captured + timedelta(milliseconds=offset)


def _check_chain(device, m_obj, previous):
    """previous_item_sha256 chains items on one device: an item whose predecessor never arrived is flagged."""
    if not previous:
        if SignedManifest.objects.filter(device=device).exclude(pk=m_obj.pk).exists():
            return {"reason": "missing_previous"}
        return None
    if not SignedManifest.objects.filter(device=device, item_sha256=previous).exclude(pk=m_obj.pk).exists():
        return {"reason": "previous_not_received", "previous_item_sha256": previous}
    return None


def _country_for(person, item):
    return (item.country if item and item.country is not None else None) or person.home_country


def _create_manifest(*, person, device, m, canon, valid, sig, alg, kind, app_version, item_sha, media=None):
    subject = m.get("subject") or {}
    st, sid = subject.get("type"), subject.get("id")
    if not st or not _is_uuid(sid):
        raise Invalid("The manifest subject needs a type and an id.")
    captured = _parse_time(m.get("captured_at_device"), "captured_at_device")
    item = inbox.find(person, st, sid)
    country = _country_for(person, item)
    if country is None:
        raise Invalid("Your account has no country. Contact Tenmina.")
    lat, lng, acc, mock = _location(m)
    media = media or {}
    obj = SignedManifest.objects.create(
        country=country, device=device, person=person, client_item_id=str(m["client_item_id"]), kind=kind,
        schema=m["schema"], manifest=m, canonical_sha256=crypto.sha256_hex(canon), item_sha256=item_sha,
        signature=sig, signature_alg=alg, signature_valid=valid, subject_type=st, subject_id=sid,
        requirement_key=subject.get("requirement_key", "") or "", project_key=item.project_key if item else "",
        media_type=media.get("type", ""), media_sha256=(media.get("sha256") or "").lower(),
        media_size=media.get("size_bytes"), captured_at_device=captured, corrected_capture_at=_corrected(m, captured),
        latitude=lat, longitude=lng, accuracy_m=acc, location_mock=mock,
        previous_item_sha256=(m.get("previous_item_sha256") or "").lower(), app_version=app_version,
        status="registered" if valid else "rejected", reserved_evidence_id=uuid7(),
        unassigned_capture=item is None, rejection_reason="" if valid else "bad_signature")
    return obj, item


def _bad_signature(obj, device):
    f = _flag(kind="bad_signature", detail={"alg": obj.signature_alg}, country=obj.country, manifest=obj,
              device=device, subject_type=obj.subject_type, subject_id=obj.subject_id)
    record(actor=obj.person, action="field_item.bad_signature", entity="mob_signed_manifest", entity_id=obj.pk,
           data={"device": str(device.pk), "client_item_id": obj.client_item_id}, country=obj.country)
    _publish_flagged(obj, None, [f])


def register_item(person, payload: dict, *, app_version="") -> tuple[SignedManifest, bool]:
    """POST /v1/mobile/evidence: verify the signed manifest now and return an upload slot (8.5 step 2)."""
    _require_field_worker(person)
    device, m, canon, valid, sig, alg = _read_manifest(person, payload, EVIDENCE_SCHEMA)
    existing = SignedManifest.objects.filter(person=person, client_item_id=str(m["client_item_id"])).first()
    if existing:
        if existing.signature == sig and existing.canonical_sha256 == crypto.sha256_hex(canon):
            return existing, False
        raise StateConflict("This item id was already used for a different item.",
                            extra={"manifest_id": str(existing.pk)})
    if device.status != "active":
        raise _reject("This phone was removed from your account. New evidence cannot be sent from it.",
                      "device_revoked")
    media = m.get("media") or {}
    sha = (media.get("sha256") or "").lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise Invalid("media.sha256 must be the file's SHA-256 in hex.")
    if not str(media.get("type", "")).startswith(("image/", "video/")):
        raise Invalid("Evidence must be a photo or a video taken in the app.")
    if not media.get("size_bytes") or int(media["size_bytes"]) <= 0 or int(media["size_bytes"]) > MAX_MEDIA_BYTES:
        raise Invalid("media.size_bytes must be between 1 byte and 200 MB.")
    with transaction.atomic():
        obj, item = _create_manifest(person=person, device=device, m=m, canon=canon, valid=valid, sig=sig, alg=alg,
                                     kind="evidence", app_version=app_version, item_sha=sha, media=media)
        if valid:
            chain = _check_chain(device, obj, obj.previous_item_sha256)
            if chain:  # points at the evidence once it is stored
                _flag(kind="chain_break", detail=chain, country=obj.country, manifest=obj, device=device,
                      subject_type=obj.subject_type, subject_id=obj.subject_id)
            Device.objects.filter(pk=device.pk).update(last_seen_at=timezone.now())
            record(actor=person, action="field_item.registered", entity="mob_signed_manifest", entity_id=obj.pk,
                   data={"subject_type": obj.subject_type, "subject_id": str(obj.subject_id), "sha256": sha},
                   country=obj.country)
        else:
            _bad_signature(obj, device)
    if not valid:
        raise _reject("The signature on this item is not valid, so it cannot be used as evidence. It has been "
                      "sent to a reviewer.", "bad_signature", manifest_id=str(obj.pk))
    return obj, True


def upload_instruction(manifest: SignedManifest) -> dict:
    import base64

    return {"method": "PUT", "url": f"/v1/mobile/evidence/{manifest.pk}/content", "expires_in": UPLOAD_URL_TTL,
            "headers": {"Content-Type": manifest.media_type,
                        "X-Checksum-SHA256": base64.b64encode(bytes.fromhex(manifest.media_sha256)).decode()}}


def _own(manifest, person):
    if manifest.person_id != person.pk:
        raise NotFound("Item not found.")


def stage_content(manifest: SignedManifest, person, data: bytes) -> SignedManifest:
    """8.5 step 3: the bytes. Re-sending after a dropped connection replaces the staged copy."""
    _own(manifest, person)
    if manifest.status not in ("registered", "uploaded"):
        raise StateConflict(f"This item is already {manifest.status}.", extra={"item_status": manifest.status})
    if not data:
        raise Invalid("The file is empty.")
    key = f"{manifest.pk}"
    _staging().put(key, data)
    manifest.staged_key = key
    if manifest.status == "registered":
        state.transition(manifest, "mob_item", "uploaded", actor=person, event="field_item.uploaded",
                         extra_fields=["staged_key"])
    else:
        manifest.save(update_fields=["staged_key"])
    return manifest


def _reject_item(manifest, person, reason, kind=None, detail=None):
    manifest.rejection_reason = reason
    state.transition(manifest, "mob_item", "rejected", actor=person, event="field_item.rejected", reason=reason,
                     extra_fields=["rejection_reason"], payload={"manifest_id": manifest.pk})
    if kind:
        f = _flag(kind=kind, detail=detail or {}, country=manifest.country, manifest=manifest,
                  device=manifest.device, subject_type=manifest.subject_type, subject_id=manifest.subject_id)
        _publish_flagged(manifest, None, [f])


def complete_item(manifest: SignedManifest, person, data: bytes | None = None) -> tuple[SignedManifest, list]:
    """8.5 step 4: re-hash, scan and store; run the fraud checks. Returns (manifest, flags)."""
    from evidence import services as evd

    _own(manifest, person)
    if manifest.status == "stored":
        return manifest, list(manifest.flags.all())
    if manifest.status == "rejected":
        raise StateConflict("This item was rejected.", extra={"reason": manifest.rejection_reason})
    if data:
        stage_content(manifest, person, data)
    if not manifest.staged_key:
        raise Invalid("Upload the file before completing the item.")
    blob = _staging().get(manifest.staged_key)
    if hashlib.sha256(blob).hexdigest() != manifest.media_sha256:
        with transaction.atomic():
            _reject_item(manifest, person, "hash_mismatch", kind="hash_mismatch",
                         detail={"expected": manifest.media_sha256,
                                 "received": hashlib.sha256(blob).hexdigest()})
        _staging().delete(manifest.staged_key)
        raise _reject("The file does not match what the phone signed. It has been sent to a reviewer.",
                      "hash_mismatch", manifest_id=str(manifest.pk))
    device = manifest.device
    item = inbox.find(person, manifest.subject_type, manifest.subject_id)
    cam = manifest.manifest.get("camera") or {}
    try:
        ev = evd.store(
            data=blob, country=manifest.country, uploaded_by=person, content_type=manifest.media_type,
            original_name=f"{manifest.requirement_key or manifest.kind}-{manifest.client_item_id}",
            source="field_app", expected_sha256=manifest.media_sha256, evidence_id=manifest.reserved_evidence_id,
            owner_type=manifest.subject_type, owner_id=manifest.subject_id, device_id=device.pk,
            signature_valid=True, captured_at=manifest.captured_at_device, latitude=manifest.latitude,
            longitude=manifest.longitude, position_accuracy_m=manifest.accuracy_m,
            capture_device=cam.get("model") or device.model, device_signature=manifest.signature)
    except DomainError as exc:
        with transaction.atomic():
            _reject_item(manifest, person, str(exc.extra.get("reason", "rejected")))
        _staging().delete(manifest.staged_key)
        raise
    with transaction.atomic():
        if item is not None and not manifest.unassigned_capture:
            evd.link(ev, manifest.subject_type, manifest.subject_id,
                     role=manifest.requirement_key or "field_capture", by=person)
        manifest.evidence, manifest.stored_at = ev, timezone.now()
        state.transition(manifest, "mob_item", "stored", actor=person, event="field_item.stored",
                         extra_fields=["evidence", "stored_at"],
                         payload={"manifest_id": manifest.pk, "evidence_id": ev.pk})
        found = fraud.evidence_flags(manifest, ev, item, device)
        flags = [_flag(kind=k, detail=d, country=manifest.country, evidence=ev, manifest=manifest, device=device,
                       subject_type=manifest.subject_type, subject_id=manifest.subject_id) for k, d in found]
        # flags raised at registration (chain) now point at the stored evidence
        FraudFlag.objects.filter(manifest=manifest, evidence__isnull=True).update(evidence=ev)
        flags += list(FraudFlag.objects.filter(manifest=manifest).exclude(pk__in=[f.pk for f in flags]))
        if flags:
            _publish_flagged(manifest, ev, flags)
    _staging().delete(manifest.staged_key)
    return manifest, flags


# --------------------------------------------------------------------------- submissions (FR-MOB-006, FR-MOB-007)

def _evidence_for_item(person, subject_type, subject_id, evidence_id, key):
    from evidence.models import Evidence

    ev = Evidence.objects.filter(pk=evidence_id).first() if _is_uuid(evidence_id) else None
    if ev is None or ev.uploaded_by_id != person.pk:
        raise Invalid(f"Evidence for '{key}' was not found.", extra={"requirement_key": key})
    if not ev.is_release_grade:
        raise Invalid(f"'{key}' must be taken in Tenmina Field with its own camera. Uploaded files are not "
                      "accepted.", code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-08", "message": f"'{key}' is not app-captured."}],
                      extra={"reason": "not_app_captured", "requirement_key": key})
    m = SignedManifest.objects.filter(evidence=ev).first()
    if m is None or m.subject_type != subject_type or str(m.subject_id) != str(subject_id):
        raise Invalid(f"The evidence for '{key}' was captured for different work.",
                      extra={"requirement_key": key})
    if m.unassigned_capture:
        raise StateConflict(f"The evidence for '{key}' was captured while the work was not assigned to you. "
                            "A reviewer will look at it.", extra={"requirement_key": key})
    return ev, m


def _reviewers(country):
    from accounts.models import Person
    from django.db.models import Q

    return Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                 role_grants__role="RV", role_grants__revoked_at__isnull=True,
                                 is_active=True).distinct()


def _finish_submission(sub, evidence_ids, person):
    open_flags = FraudFlag.objects.filter(evidence_id__in=evidence_ids, status="open")
    flagged = open_flags.exists()
    if flagged:
        state.transition(sub, "mob_submission", "held_for_review", actor=person, event="submission.held",
                         payload={"submission_id": sub.pk})
    record(actor=person, action="submission.received", entity="mob_submission", entity_id=sub.pk,
           data={"subject_type": sub.subject_type, "subject_id": str(sub.subject_id), "kind": sub.kind,
                 "flagged": flagged}, country=sub.country)
    publish("submission.received", sub.pk, {
        "submission_id": sub.pk, "kind": sub.kind, "subject_type": sub.subject_type, "subject_id": sub.subject_id,
        "person_id": person.pk, "flagged": flagged, "flag_count": open_flags.count(), "outcome": sub.outcome,
        "defects": sub.defects, "reason": sub.reason, "note": sub.note,
        "items": [{"requirement_key": i.requirement_key, "evidence_id": i.evidence_id, "value": i.value,
                   "kind": i.kind} for i in sub.items.all()]})
    if flagged:
        from notifications.services import notify

        for rv in _reviewers(sub.country):
            notify(rv, "field_flags_review", subject="Field evidence needs review",
                   body="A field submission has flagged evidence. Review the flags before anything is scheduled.",
                   subject_obj=sub)


def _assigned(person, subject_type, subject_id):
    item = inbox.find(person, subject_type, subject_id)
    if item is None:
        raise NotFound("This work is not assigned to you.")
    if not item.accepts_submissions:
        raise StateConflict(item.state_reason or "This work cannot take a submission now.",
                            extra={"reason": item.state_reason or "closed"})
    return item


def _replay(client_submission_id, person, subject_type, subject_id):
    existing = Submission.objects.filter(client_submission_id=str(client_submission_id)).first()
    if existing is None:
        return None
    if existing.person_id != person.pk or existing.subject_type != subject_type \
            or str(existing.subject_id) != str(subject_id):
        raise StateConflict("This submission id was already used for different work.")
    return existing


def submit(person, *, client_submission_id, subject_type, subject_id, items, note="") -> tuple[Submission, bool]:
    """POST /v1/mobile/submissions. Blocked until every required item is attached (FR-MOB-006)."""
    from administration import flags

    _require_field_worker(person)
    existing = _replay(client_submission_id, person, subject_type, subject_id)
    if existing:
        return existing, False
    flags.read_only_guard()
    item = _assigned(person, subject_type, subject_id)
    rows, given = [], set()
    for it in items or []:
        key = (it.get("requirement_key") or "").strip()
        if not key:
            raise Invalid("Each item needs a requirement_key.")
        if it.get("evidence_id"):
            ev, m = _evidence_for_item(person, subject_type, subject_id, it["evidence_id"], key)
            rows.append(dict(requirement_key=key, kind="evidence", evidence=ev, manifest=m, value=it.get("value")))
        elif it.get("value") is not None:
            rows.append(dict(requirement_key=key, kind="form", value=it["value"]))
        else:
            raise Invalid(f"Item '{key}' needs evidence or a value.")
        given.add(key)
    required = [r for r in item.required_evidence if r.get("required", True)]
    missing = [r for r in required if r["key"] not in given]
    if missing:
        names = ", ".join(r.get("label") or r["key"] for r in missing)
        raise Invalid(f"Add the missing items before you submit: {names}.",
                      extra={"missing": [r["key"] for r in missing],
                             "errors": [{"pointer": "/items", "message": f"Missing {r['key']}"} for r in missing]})
    media = {r["key"]: r.get("media", "photo") for r in item.required_evidence}
    for r in rows:
        want = media.get(r["requirement_key"])
        if want in ("photo", "video") and r["kind"] != "evidence":
            raise Invalid(f"'{r['requirement_key']}' needs a {want} from the app camera.")
        if want == "photo" and r["kind"] == "evidence" and not r["evidence"].content_type.startswith("image/"):
            raise Invalid(f"'{r['requirement_key']}' needs a photo.")
        if want == "video" and r["kind"] == "evidence" and not r["evidence"].content_type.startswith("video/"):
            raise Invalid(f"'{r['requirement_key']}' needs a video.")
    with transaction.atomic():
        sub = Submission.objects.create(country=item.country or person.home_country, person=person,
                                        client_submission_id=str(client_submission_id), kind="evidence_set",
                                        subject_type=subject_type, subject_id=subject_id, note=note or "")
        for r in rows:
            SubmissionItem.objects.create(submission=sub, **r)
        _finish_submission(sub, [r["evidence"].pk for r in rows if r.get("evidence")], person)
    return sub, True


def submit_inspection(person, *, client_submission_id, subject_type, subject_id, outcome, checklist, defects=(),
                      reason="", note="") -> tuple[Submission, bool]:
    """POST /v1/mobile/inspections (FR-MOB-007, RUL-09): pass, pass with defects (each with photos and a
    value) or fail (with a reason). Every checklist item must be answered."""
    from administration import flags
    from core.money import q

    _require_field_worker(person)
    existing = _replay(client_submission_id, person, subject_type, subject_id)
    if existing:
        return existing, False
    flags.read_only_guard()
    item = _assigned(person, subject_type, subject_id)
    if outcome not in Submission.OUTCOMES:
        raise Invalid("Choose pass, pass_with_defects or fail.")
    answers = {}
    for c in checklist or []:
        if c.get("result") not in ("ok", "not_ok", "na"):
            raise Invalid(f"Checklist item '{c.get('key')}' needs a result: ok, not_ok or na.")
        answers[c.get("key")] = c
    expected = [c["key"] for c in item.checklist]
    unknown = [k for k in answers if k not in expected]
    missing = [k for k in expected if k not in answers]
    if missing or unknown:
        raise Invalid("Answer every checklist item before you submit.", extra={"missing": missing,
                                                                               "unknown": unknown})
    defects = list(defects or [])
    if outcome == "fail" and not (reason or "").strip():
        raise Invalid("Say why the work failed inspection.")
    if outcome == "pass" and defects:
        raise Invalid("A pass has no defects. Choose pass_with_defects instead.")
    if outcome == "pass_with_defects" and not defects:
        raise Invalid("Add at least one defect, or choose pass.")
    rows, clean_defects = [], []
    for n, d in enumerate(defects):
        desc = (d.get("description") or "").strip()
        val = d.get("value") or {}
        try:
            amount = q(val.get("amount"))
            currency = str(val.get("currency", "")).upper()
        except Exception:  # noqa: BLE001
            amount, currency = None, ""
        if not desc or amount is None or amount <= 0 or len(currency) != 3:
            raise Invalid(f"Defect {n + 1} needs a description and a value.")
        photos = d.get("evidence_ids") or []
        if not photos:
            raise Invalid(f"Defect {n + 1} needs at least one photo.")
        for eid in photos:
            ev, m = _evidence_for_item(person, subject_type, subject_id, eid, f"defect_{n + 1}")
            rows.append(dict(requirement_key=f"defect_{n + 1}", kind="defect_photo", evidence=ev, manifest=m,
                             value={"defect_index": n}))
        clean_defects.append({"description": desc, "value": {"amount": f"{amount:.2f}", "currency": currency},
                              "evidence_ids": [str(e) for e in photos]})
    with transaction.atomic():
        sub = Submission.objects.create(
            country=item.country or person.home_country, person=person,
            client_submission_id=str(client_submission_id), kind="inspection", subject_type=subject_type,
            subject_id=subject_id, outcome=outcome, checklist=[answers[k] for k in expected],
            defects=clean_defects, reason=(reason or "").strip(), note=note or "")
        for r in rows:
            SubmissionItem.objects.create(submission=sub, **r)
        _finish_submission(sub, [r["evidence"].pk for r in rows], person)
    return sub, True


# --------------------------------------------------------------------------- check-in and check-out (FR-MOB-012)

def record_checkin(person, payload: dict, kind: str, *, app_version="") -> tuple[CheckIn, bool]:
    """Signed check-in or check-out at the registered address. Outside the radius is recorded and
    flagged, not blocked (ADR-19)."""
    from evidence import services as evd

    _require_field_worker(person)
    device, m, canon, valid, sig, alg = _read_manifest(person, payload, CHECKIN_SCHEMA)
    existing = SignedManifest.objects.filter(person=person, client_item_id=str(m["client_item_id"])).first()
    if existing:
        ci = CheckIn.objects.filter(manifest=existing).first()
        if ci and existing.signature == sig:
            return ci, False
        raise StateConflict("This item id was already used for a different item.")
    if m.get("kind") != kind:
        raise Invalid(f"The manifest kind must be {kind}.")
    if device.status != "active":
        raise _reject("This phone was removed from your account.", "device_revoked")
    subject = m.get("subject") or {}
    if subject.get("type") not in CHECKIN_SUBJECTS:
        raise Invalid("Check-in is for care visits, inspections and errand steps.")
    lat, lng, acc, mock = _location(m)
    if lat is None or acc is None:
        raise Invalid("Turn on location to check in. Tenmina needs your position and its accuracy.",
                      extra={"errors": [{"pointer": "/manifest/location", "message": "Position is required."}]})
    item = inbox.find(person, subject.get("type"), subject.get("id"))
    if item is None:
        raise NotFound("This visit or inspection is not assigned to you.")
    point = fraud.registered_point(item)
    if point is None:
        raise StateConflict("This work has no registered address to check in at.")
    item_sha = crypto.sha256_hex(canon)
    st, sid = subject["type"], subject.get("id")
    captured = _parse_time(m.get("captured_at_device"), "captured_at_device")
    first = None
    if valid:
        if CheckIn.objects.filter(subject_type=st, subject_id=sid, kind=kind).exists():
            raise StateConflict(f"There is already a {kind.replace('check', 'check-')} for this work.")
        if kind == "checkout":
            first = CheckIn.objects.filter(subject_type=st, subject_id=sid, kind="checkin").first()
            if first is None:
                raise StateConflict("Check in before you check out.")
            if captured < first.device_time:
                raise Invalid("The check-out time is before the check-in time.")
    if not valid:
        with transaction.atomic():
            obj, _ = _create_manifest(person=person, device=device, m=m, canon=canon, valid=False, sig=sig,
                                      alg=alg, kind=kind, app_version=app_version, item_sha=item_sha)
            _bad_signature(obj, device)
        raise _reject("The signature on this check-in is not valid. It has been sent to a reviewer.",
                      "bad_signature", manifest_id=str(obj.pk))
    country = _country_for(person, item)
    radius = item.radius_m or fraud.setting(country, "checkin_radius_m")
    dist = fraud.haversine(lat, lng, point[0], point[1])
    max_acc = fraud.setting(country, "checkin_max_accuracy_m")
    within = dist <= radius and float(acc) <= max_acc and not mock
    blob = crypto.canonical({"manifest": m, "signature": sig, "signature_alg": alg})
    with transaction.atomic():
        obj, _ = _create_manifest(person=person, device=device, m=m, canon=canon, valid=True, sig=sig, alg=alg,
                                  kind=kind, app_version=app_version, item_sha=item_sha)
        country = obj.country
        ev = evd.store(data=blob, country=country, uploaded_by=person, content_type="application/json",
                       original_name=f"{kind}-{obj.client_item_id}.json", source="field_app",
                       evidence_id=obj.reserved_evidence_id, owner_type=st, owner_id=sid, device_id=device.pk,
                       signature_valid=True, captured_at=obj.captured_at_device, latitude=lat, longitude=lng,
                       position_accuracy_m=acc, capture_device=device.model, device_signature=sig,
                       description=f"Signed {kind} at the registered address")
        evd.link(ev, st, sid, role=kind, by=person)
        obj.evidence, obj.stored_at = ev, timezone.now()
        state.transition(obj, "mob_item", "stored", actor=person, event="field_item.stored",
                         extra_fields=["evidence", "stored_at"], payload={"manifest_id": obj.pk,
                                                                          "evidence_id": ev.pk})
        duration = None
        if first is not None:
            duration = max(0, int((obj.captured_at_device - first.device_time).total_seconds() // 60))
        ci = CheckIn.objects.create(
            country=country, device=device, person=person, subject_type=st, subject_id=sid, kind=kind,
            manifest=obj, evidence=ev, latitude=lat, longitude=lng, accuracy_m=acc, registered_lat=point[0],
            registered_lng=point[1], distance_m=Decimal(str(round(dist, 2))), radius_m=radius, within_radius=within,
            device_time=obj.captured_at_device, received_at=obj.received_at, signature_valid=True, checkin=first,
            duration_minutes=duration)
        found = fraud.device_flags(device)
        if not within:
            found.append(("outside_address_radius", {"distance_m": round(dist, 1), "radius_m": radius,
                                                     "accuracy_m": float(acc), "mock": mock,
                                                     "reason": "mock" if mock else (
                                                         "distance" if dist > radius else "accuracy")}))
        gap = fraud.setting(country, "checkin_time_gap_s")
        lag = (obj.received_at - obj.corrected_capture_at).total_seconds()
        if lag > gap or -lag > fraud.setting(country, "device_time_gap_s"):
            found.append(("time_gap", {"seconds": int(lag), "reason": "late_upload" if lag > 0 else
                                       "device_clock_ahead"}))
        if kind == "checkout":
            minimum = item.min_visit_minutes or fraud.setting(country, "checkout_min_minutes")
            if duration is not None and duration < minimum:
                found.append(("checkout_too_soon", {"minutes": duration, "minimum": minimum}))
        chain = _check_chain(device, obj, obj.previous_item_sha256)
        if chain:
            found.append(("chain_break", chain))
        flags = [_flag(kind=k, detail=d, country=country, evidence=ev, manifest=obj, checkin=ci, device=device,
                       subject_type=st, subject_id=sid) for k, d in found]
        record(actor=person, action=f"mob_checkin.{kind}", entity="mob_checkin", entity_id=ci.pk,
               data={"subject_type": st, "subject_id": str(sid), "distance_m": round(dist, 1), "within": within},
               country=country)
        publish(f"{kind}.recorded", ci.pk, {
            "checkin_id": ci.pk, "kind": kind, "subject_type": st, "subject_id": sid, "person_id": person.pk,
            "device_time": ci.device_time, "received_at": ci.received_at, "within_radius": within,
            "distance_m": float(ci.distance_m), "duration_minutes": duration, "evidence_id": ev.pk,
            "checkin_of": first.pk if first else None, "flags": [f.kind for f in flags]})
        if flags:
            _publish_flagged(obj, ev, flags)
    return ci, True


# --------------------------------------------------------------------------- flag review (FR-MOB-011)

def review_flag(flag: FraudFlag, by, decision: str, note: str) -> FraudFlag:
    """Clear or uphold a flag. Audited. When a submission has no open flags left, `flags.cleared` tells
    the owning module it may go on (or that a flag was upheld)."""
    if decision not in ("clear", "uphold"):
        raise Invalid("Decision must be clear or uphold.")
    if not (note or "").strip():
        raise Invalid("Add a note that explains the decision.")
    if flag.manifest_id and flag.manifest.person_id == by.pk:
        raise Forbidden("You cannot review flags on your own evidence.")
    to = "cleared" if decision == "clear" else "upheld"
    with transaction.atomic():
        flag.reviewed_by, flag.reviewed_at, flag.review_note = by, timezone.now(), note.strip()
        state.transition(flag, "mob_fraud_flag", to, actor=by, event=f"flag.{to}", reason=note.strip(),
                         extra_fields=["reviewed_by", "reviewed_at", "review_note"],
                         payload={"flag_id": flag.pk, "kind": flag.kind, "evidence_id": flag.evidence_id,
                                  "subject_type": flag.subject_type, "subject_id": flag.subject_id})
        subs = list(Submission.objects.filter(items__evidence_id=flag.evidence_id, status="held_for_review")
                    .distinct()) if flag.evidence_id else []
        for sub in subs:
            ev_ids = list(sub.items.exclude(evidence__isnull=True).values_list("evidence_id", flat=True))
            if FraudFlag.objects.filter(evidence_id__in=ev_ids, status="open").exists():
                continue
            upheld = FraudFlag.objects.filter(evidence_id__in=ev_ids, status="upheld").exists()
            outcome = "upheld" if upheld else "cleared"
            sub.reviewed_at = timezone.now()
            state.transition(sub, "mob_submission", outcome, actor=by, event="submission.reviewed",
                             extra_fields=["reviewed_at"], payload={"submission_id": sub.pk})
            publish("flags.cleared", sub.pk, {"submission_id": sub.pk, "subject_type": sub.subject_type,
                                              "subject_id": sub.subject_id, "outcome": outcome,
                                              "kind": sub.kind, "person_id": sub.person_id})
        if not subs:
            others_open = FraudFlag.objects.filter(evidence_id=flag.evidence_id, status="open").exists() \
                if flag.evidence_id else False
            if not others_open:
                publish("flags.cleared", flag.pk, {"submission_id": None, "subject_type": flag.subject_type,
                                                   "subject_id": flag.subject_id, "evidence_id": flag.evidence_id,
                                                   "checkin_id": flag.checkin_id,
                                                   "outcome": "upheld" if FraudFlag.objects.filter(
                                                       evidence_id=flag.evidence_id, status="upheld").exists()
                                                   else "cleared"})
    return flag


# --------------------------------------------------------------------------- for other modules

def evidence_blockers(evidence_ids) -> list[dict]:
    """Reasons evidence cannot back a release: not app-captured (RUL-08), or open or upheld flags (FR-MOB-011).
    Line modules call this before a milestone, visit or step release."""
    from evidence.models import Evidence

    out = []
    for ev in Evidence.objects.filter(pk__in=list(evidence_ids)):
        if not ev.is_release_grade:
            out.append({"rule": "RUL-08", "message": f"Evidence {ev.pk} was not captured in Tenmina Field."})
        for f in FraudFlag.objects.filter(evidence=ev, status__in=["open", "upheld"]):
            out.append({"rule": "FR-MOB-011", "message": f"Evidence {ev.pk} has a {f.status} '{f.kind}' flag."})
    return out


def missing_checkouts(now=None) -> list[CheckIn]:
    """End-of-day job (TC-MOB-012-04): a check-in with no check-out after `checkout_missing_hours` is
    published once as `checkout.missing` (CARE alerts the client, FR-CARE-005) and the worker is told."""
    from core.models import OutboxEvent
    from notifications.services import notify

    now = now or timezone.now()
    out = []
    for ci in CheckIn.objects.filter(kind="checkin", checkout__isnull=True).select_related("country", "person"):
        if ci.device_time > now - timedelta(hours=fraud.setting(ci.country, "checkout_missing_hours")):
            continue
        if OutboxEvent.objects.filter(topic="checkout.missing", aggregate_id=ci.pk).exists():
            continue
        publish("checkout.missing", ci.pk, {"checkin_id": ci.pk, "subject_type": ci.subject_type,
                                            "subject_id": ci.subject_id, "person_id": ci.person_id,
                                            "checked_in_at": ci.device_time})
        notify(ci.person, "field_checkout_missing", subject="Check-out missing",
               body="You checked in but did not check out. Open Tenmina Field to check out or tell Tenmina why.",
               channels=("in_app", "push"), subject_obj=ci)
        out.append(ci)
    return out
