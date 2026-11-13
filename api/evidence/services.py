"""Evidence store services (FR-EVD-001 to FR-EVD-006; ADR-04; 02 sections 6.6 and 10.7).

Other modules call store(), link(), for_subject(), verify() and, for issued
documents, register_issued(). Files are never stored any other way.
"""
import base64
import hashlib
import hmac
import io
import json
import random
import re
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.services import record
from core import state
from core.adapters import get_adapter
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict
from core.events import publish
from core.ids import uuid7

from . import access
from .models import (
    AccessLog, Evidence, EvidenceLink, FingerprintCheck, IntegrityIncident, IntegrityRun, IssuedDocument, Preview,
    RetentionDeletion, ScanResult, UploadSlot,
)

MAX_BYTES = 200 * 1024 * 1024
LINK_TTL_MAX = 900  # FR-EVD-003: never more than 15 minutes
PREVIEW_EDGE = 640  # px, assumption
INTEGRITY_SAMPLE_SIZE = 50  # per daily run, assumption [TO VERIFY]
UPLOAD_SLOT_MINUTES = 60  # assumption
SHA_RE = re.compile(r"^[0-9a-f]{64}$")

ALLOWED_UPLOAD_TYPES = {
    "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif", "video/mp4", "video/quicktime",
    "application/pdf", "text/plain", "text/csv",
}
# RUL-08: from R2 these subjects take only evidence captured in Tenmina Field (country config may change the list).
DEFAULT_APP_CAPTURE_SUBJECTS = [
    "milestone", "inspection", "milestone_inspection", "defect", "care_visit", "care_visit_item", "errand_step",
    "property_inspection", "checkin", "handover",
]
DEFAULT_APP_CAPTURE_EXEMPT_ROLES = ["invoice", "quote", "agreement", "variation_agreement"]
# RUL-30: who may never handle an official search result.
RUL30_EXCLUDED_ROLES = ("RN", "SE", "DV", "CL", "CE")


# --------------------------------------------------------------------------- helpers

def _cfg(country, key, default):
    from countries.selectors import config

    try:
        return config(country, key, default)
    except Exception:  # noqa: BLE001 - unknown country code
        return default


def _ip_hash(request) -> str:
    if request is None:
        return ""
    ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip() or request.META.get("REMOTE_ADDR", "")
    return hmac.new(settings.SECRET_KEY.encode(), ip.encode(), hashlib.sha256).hexdigest()[:32]


def _ua(request) -> str:
    return (request.META.get("HTTP_USER_AGENT", "") if request is not None else "")[:200]


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64url(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def normalise_sha256(value) -> str:
    v = (value or "").strip().lower()
    if not SHA_RE.match(v):
        raise Invalid("Give the SHA-256 as 64 hexadecimal characters.", code="validation-error",
                      extra={"errors": [{"pointer": "/sha256", "message": "Not a SHA-256 hex digest."}]})
    return v


def retain_until_for(country, data_class: str, today: date | None = None) -> date:
    years = _cfg(country, f"retention_years.{data_class}", None) or _cfg(country, "retention_years.evidence", 7)
    today = today or timezone.now().date()
    try:
        return today.replace(year=today.year + int(years))
    except ValueError:  # 29 February
        return today.replace(year=today.year + int(years), day=28)


def content_problem(data: bytes, content_type: str) -> str | None:
    """Rejects executables and files that are not what they claim to be (FR-EVD-005)."""
    head = data[:16]
    if head.startswith((b"MZ", b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa", b"#!")):
        return "executable"
    ct = (content_type or "").lower()
    if ct in ("image/jpeg", "image/jpg") and not head.startswith(b"\xff\xd8\xff"):
        return "not_what_it_claims"
    if ct == "image/png" and not head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "not_what_it_claims"
    if ct == "image/webp" and not (head[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return "not_what_it_claims"
    if ct in ("image/heic", "image/heif") and data[4:8] != b"ftyp":
        return "not_what_it_claims"
    if ct.startswith("video/") and data[4:8] not in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip"):
        return "not_what_it_claims"
    if ct == "application/pdf":
        if not data.lstrip()[:5] == b"%PDF-":
            return "not_what_it_claims"
        if re.search(rb"/(JavaScript|JS|Launch|EmbeddedFile)\b", data):
            return "pdf_active_content"
    return None


def _image_meta(data: bytes):
    """EXIF make, model and time, size, and a 64-bit average hash for near-duplicate checks."""
    try:
        from PIL import Image
    except ImportError:  # pragma: no cover
        return {}, ""
    try:
        img = Image.open(io.BytesIO(data))
        exif = img.getexif()
        meta = {"width": img.width, "height": img.height}
        make, model = exif.get(271), exif.get(272)
        when = exif.get_ifd(0x8769).get(36867) or exif.get(306)
        if make:
            meta["exif_make"] = str(make).strip("\x00 ")
        if model:
            meta["exif_model"] = str(model).strip("\x00 ")
        if when:
            meta["exif_datetime"] = str(when).strip("\x00 ")
        small = img.convert("L").resize((8, 8))
        px = list(small.tobytes())
        avg = sum(px) / 64
        bits = "".join("1" if p >= avg else "0" for p in px)
        return meta, f"{int(bits, 2):016x}"
    except Exception:  # noqa: BLE001 - not an image Pillow can read
        return {}, ""


def phash_distance(a: str, b: str) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _reject(*, country, reason, message, digest="", size=0, content_type="", original_name="", uploaded_by=None,
            scanner="rules"):
    ScanResult.objects.create(country=country, sha256=digest, size_bytes=size, content_type=content_type,
                              original_name=original_name, uploaded_by=uploaded_by, scanner=scanner,
                              verdict="rejected", detail=reason)
    record(actor=uploaded_by, action="evidence.rejected", entity="evidence", entity_id=digest or "none",
           data={"reason": reason, "name": original_name, "size": size}, country=country)
    publish("evidence.rejected", None, {"sha256": digest, "reason": reason,
                                        "uploaded_by": getattr(uploaded_by, "pk", None)})
    raise Invalid(message, code="evidence-rejected", extra={"reason": reason})


# --------------------------------------------------------------------------- store and link

def store(*, data: bytes, country, uploaded_by=None, content_type="application/octet-stream", original_name="",
          source="upload", expected_sha256=None, description="", evidence_id=None, owner_type="", owner_id=None,
          data_class="case", device_id=None, signature_valid=None, position_accuracy_m=None, capture_device="",
          **meta) -> Evidence:
    """Hash, check, scan and store a file write-once. Returns the Evidence record.

    Provenance is app_captured only when MOB passes source="field_app" with the
    device and a verified signature (FR-EVD-006); a client can never claim it.
    """
    size = len(data)
    digest = hashlib.sha256(data).hexdigest()
    common = dict(country=country, digest=digest, size=size, content_type=content_type,
                  original_name=original_name, uploaded_by=uploaded_by)
    if size == 0:
        _reject(reason="empty", message="The file is empty.", **common)
    if size > MAX_BYTES:
        _reject(reason="too_large", message="The file is too large.", **common)
    if expected_sha256 and expected_sha256.lower() != digest:
        _reject(reason="hash_mismatch", message="The file changed on the way. Upload it again.", **common)
    problem = content_problem(data, content_type)
    if problem:
        _reject(reason=problem, message="This file type is not allowed or the file is not what it claims to be.",
                **common)
    scanner = get_adapter("malware_scan")
    verdict = scanner.scan(data)
    scanner_name = getattr(scanner, "name", type(scanner).__name__)
    if verdict not in ("clean", "pending"):
        _reject(reason="malware", message="The file failed the safety scan.", scanner=scanner_name, **common)

    if source == "field_app" and device_id and signature_valid is True:
        provenance = "app_captured"
    elif source == "generated":
        provenance = "system_generated"
    else:
        provenance = "uploaded"
        device_id = device_id if source == "field_app" else None
        signature_valid = None if device_id is None else bool(signature_valid)

    img_meta, phash = _image_meta(data) if (content_type or "").startswith("image/") else ({}, "")
    with transaction.atomic():
        eid = evidence_id or uuid7()
        key = f"{country.code}/{timezone.now():%Y/%m}/{eid}"
        version = get_adapter("evidence_store").put(key, data) or ""
        ev = Evidence.objects.create(
            id=eid, country=country, sha256=digest, size_bytes=size, content_type=content_type,
            original_name=original_name, storage_key=key, object_version=str(version), source=source,
            provenance=provenance, device_id=device_id, signature_valid=signature_valid, uploaded_by=uploaded_by,
            scan_status=verdict, description=description, owner_type=owner_type or "", owner_id=owner_id,
            data_class=data_class, retain_until=retain_until_for(country, data_class),
            position_accuracy_m=position_accuracy_m, capture_device=capture_device or "",
            metadata=img_meta, phash=phash, **meta)
        ScanResult.objects.create(evidence=ev, country=country, sha256=digest, size_bytes=size,
                                  content_type=content_type, original_name=original_name, uploaded_by=uploaded_by,
                                  scanner=scanner_name, verdict=verdict)
        record(actor=uploaded_by, action="evidence.stored", entity="evidence", entity_id=ev.pk,
               data={"sha256": digest, "size": size, "source": source, "provenance": provenance,
                     "scan": verdict}, country=country)
        publish("evidence.stored", ev.pk, {"evidence_id": ev.pk, "sha256": digest, "provenance": provenance,
                                           "scan_status": verdict, "content_type": content_type})
    return ev


def requires_app_capture(country, subject_type: str, role: str = "") -> bool:
    """RUL-08: from R2 (flag mobile.capture) these subjects take only Tenmina Field captures."""
    from administration import flags

    if not flags.enabled("mobile.capture", country):
        return False
    subjects = _cfg(country, "evidence.app_capture_subjects", DEFAULT_APP_CAPTURE_SUBJECTS)
    exempt = _cfg(country, "evidence.app_capture_exempt_roles", DEFAULT_APP_CAPTURE_EXEMPT_ROLES)
    return subject_type in subjects and role not in exempt


def _check_rul08(evidence, subject_type, role):
    if evidence.provenance == "system_generated":
        return
    if not requires_app_capture(evidence.country, subject_type, role):
        return
    if evidence.provenance != "app_captured" or not evidence.signature_valid:
        raise Invalid(
            "This evidence must be taken in the Tenmina Field app with its own camera. Uploaded files are not "
            "accepted here.", code="evidence-rejected",
            blocking_reasons=[{"rule": "RUL-08", "message": "Only app-captured evidence with a verified device "
                                                            "signature is accepted for this item."}],
            extra={"reason": "not_app_captured"})


def _check_rul30(evidence, subject_type, role, by):
    if role != "official_search_result":
        return
    reasons = []
    if subject_type != "search_request":
        reasons.append("An official search result can only be linked to a search request.")
    for who, label in ((by, "The person linking it"), (evidence.uploaded_by, "The person who received it")):
        if who is None or not who.has_tenmina_role("CM", "RV", country=evidence.country) \
                or who.has_tenmina_role(*RUL30_EXCLUDED_ROLES, country=evidence.country):
            reasons.append(f"{label} must be a Tenmina case manager or reviewer.")
    if reasons:
        raise Invalid("Official search results come only from Tenmina's own registry channel.",
                      code="evidence-rejected", extra={"reason": "not_official_channel"},
                      blocking_reasons=[{"rule": "RUL-30", "message": r} for r in reasons])


def link(evidence: Evidence, subject_type: str, subject_id, role="supporting", by=None) -> EvidenceLink:
    """Link evidence to a subject once. Checks RUL-08 (app capture) and RUL-30 (official searches)."""
    existing = EvidenceLink.objects.filter(evidence=evidence, subject_type=subject_type,
                                           subject_id=subject_id).first()
    if existing:
        return existing
    if evidence.deleted_at:
        raise StateConflict("This evidence was removed under its retention rule.")
    if evidence.scan_status == "rejected":
        raise Invalid("This file failed the safety scan.", code="evidence-rejected", extra={"reason": "malware"})
    _check_rul08(evidence, subject_type, role)
    _check_rul30(evidence, subject_type, role, by)
    with transaction.atomic():
        lk = EvidenceLink.objects.create(evidence=evidence, country=evidence.country, subject_type=subject_type,
                                         subject_id=subject_id, role=role, linked_by=by)
        record(actor=by, action="evidence.linked", entity="evidence", entity_id=evidence.pk,
               data={"subject_type": subject_type, "subject_id": str(subject_id), "role": role},
               country=evidence.country)
        publish("evidence.linked", evidence.pk, {"evidence_id": evidence.pk, "subject_type": subject_type,
                                                 "subject_id": subject_id, "role": role,
                                                 "provenance": evidence.provenance})
    return lk


def for_subject(subject_type: str, subject_id):
    return Evidence.objects.filter(links__subject_type=subject_type, links__subject_id=subject_id).distinct()


def verify(evidence: Evidence) -> bool:
    try:
        data = get_adapter("evidence_store").get(evidence.storage_key)
    except (FileNotFoundError, KeyError):
        return False
    return hashlib.sha256(data).hexdigest() == evidence.sha256


def record_scan(evidence: Evidence, verdict: str, *, detail="", scanner="clamav", by=None) -> Evidence:
    """The asynchronous scanner's verdict for a pending file (FR-EVD-005)."""
    if verdict not in ("clean", "rejected"):
        raise Invalid("The verdict must be clean or rejected.")
    with transaction.atomic():
        ScanResult.objects.create(evidence=evidence, country=evidence.country, sha256=evidence.sha256,
                                  size_bytes=evidence.size_bytes, content_type=evidence.content_type,
                                  original_name=evidence.original_name, uploaded_by=evidence.uploaded_by,
                                  scanner=scanner, verdict=verdict, detail=detail)
        state.transition(evidence, "evidence_scan", verdict, actor=by, event="evidence.scanned",
                         payload={"evidence_id": evidence.pk, "verdict": verdict})
        if verdict == "clean":
            make_previews(evidence)
        else:
            publish("evidence.rejected", evidence.pk, {"evidence_id": evidence.pk, "sha256": evidence.sha256,
                                                       "reason": "malware"})
            if evidence.uploaded_by:
                from notifications.services import notify

                notify(evidence.uploaded_by, "evidence_rejected", subject="A file was rejected",
                       body=f"The file '{evidence.original_name or 'upload'}' failed the safety scan and will not "
                            "be used. Please send a clean copy.", needs_action=False, subject_obj=evidence)
    return evidence


# --------------------------------------------------------------------------- upload slots

def request_slot(*, user, subject_type, subject_id, content_type, size_bytes, sha256, role="supporting",
                 original_name="", description="", captured_at=None, latitude=None, longitude=None,
                 position_accuracy_m=None, country_code=None) -> UploadSlot:
    """POST /v1/uploads (FR-EVD-001, FR-EVD-005)."""
    from administration import flags
    from countries.models import Country

    flags.read_only_guard()
    digest = normalise_sha256(sha256)
    if not size_bytes or int(size_bytes) <= 0 or int(size_bytes) > MAX_BYTES:
        raise Invalid("The file size must be between 1 byte and 200 MB.")
    if content_type not in ALLOWED_UPLOAD_TYPES:
        raise Invalid("This file type is not accepted. Use a photo, video, PDF or text file.",
                      code="evidence-rejected", extra={"reason": "type_not_allowed"})
    country = access.subject_country(subject_type, subject_id)
    if country is None and country_code:
        country = Country.objects.filter(code=str(country_code).upper()).first()
    if country is None:
        country = getattr(user, "home_country", None)
    if country is None:
        raise Invalid("Say which country this file belongs to.")
    if not access.can_attach(user, subject_type, subject_id, country):
        raise NotFound("We could not find that item, or you cannot add files to it.")
    if requires_app_capture(country, subject_type, role):
        raise Invalid("This evidence must be taken in the Tenmina Field app with its own camera. Gallery and "
                      "file uploads are not accepted.", code="evidence-rejected",
                      blocking_reasons=[{"rule": "RUL-08", "message": "Capture it in Tenmina Field."}],
                      extra={"reason": "gallery_source"})
    minutes = int(_cfg(country, "evidence.upload_slot_minutes", UPLOAD_SLOT_MINUTES))
    with transaction.atomic():
        slot = UploadSlot.objects.create(
            country=country, requested_by=user, subject_type=subject_type, subject_id=subject_id, role=role,
            expected_sha256=digest, content_type=content_type, size_bytes=int(size_bytes),
            original_name=original_name or "", description=description or "", captured_at=captured_at,
            latitude=latitude, longitude=longitude, position_accuracy_m=position_accuracy_m,
            expires_at=timezone.now() + timedelta(minutes=minutes))
        record(actor=user, action="upload_slot.opened", entity="upload_slot", entity_id=slot.pk,
               data={"subject_type": subject_type, "subject_id": str(subject_id), "sha256": digest},
               country=country)
    return slot


def upload_to_slot(slot: UploadSlot, data: bytes, user) -> Evidence:
    """The bytes for a slot. The server hashes and compares with the declared SHA-256."""
    if slot.requested_by_id != user.pk:
        raise NotFound("Upload slot not found.")
    if slot.status != "open":
        raise StateConflict("This upload slot is already used. Ask for a new one.",
                            extra={"slot_status": slot.status})
    if slot.expires_at < timezone.now():
        state.transition(slot, "upload_slot", "expired", actor=user, event="upload_slot.expired")
        raise StateConflict("This upload slot has expired. Ask for a new one.")
    owner = access.subject_owner(slot.subject_type, slot.subject_id) or (slot.subject_type, slot.subject_id)
    try:
        ev = store(data=data, country=slot.country, uploaded_by=user, content_type=slot.content_type,
                   original_name=slot.original_name, source="upload", expected_sha256=slot.expected_sha256,
                   description=slot.description, owner_type=owner[0], owner_id=owner[1],
                   captured_at=slot.captured_at, latitude=slot.latitude, longitude=slot.longitude,
                   position_accuracy_m=slot.position_accuracy_m)
    except DomainError as exc:
        slot.rejection_reason = str(exc.extra.get("reason", exc.detail))
        state.transition(slot, "upload_slot", "rejected", actor=user, event="upload_slot.rejected",
                         extra_fields=["rejection_reason"], reason=slot.rejection_reason)
        raise
    with transaction.atomic():
        link(ev, slot.subject_type, slot.subject_id, role=slot.role, by=user)
        slot.evidence = ev
        state.transition(slot, "upload_slot", "completed", actor=user, event="upload_slot.completed",
                         extra_fields=["evidence"], payload={"evidence_id": ev.pk})
    return ev


# --------------------------------------------------------------------------- previews

def make_previews(evidence: Evidence) -> Preview | None:
    """FR-EVD-004. Images: resized JPEG. Video: compressed preview from the video_preview port."""
    if Preview.objects.filter(evidence=evidence).exists() or evidence.scan_status != "clean":
        return Preview.objects.filter(evidence=evidence).first()
    ct = (evidence.content_type or "").lower()
    if not (ct.startswith("image/") or ct.startswith("video/")):
        return None
    kind = "image" if ct.startswith("image/") else "video"
    store_ = get_adapter("evidence_store")
    try:
        data = store_.get(evidence.storage_key)
        if kind == "image":
            from PIL import Image, ImageOps

            img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
            img.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, "JPEG", quality=70)
            out, out_ct, w, h, status = buf.getvalue(), "image/jpeg", img.width, img.height, "ready"
        else:
            out, out_ct, w, h, status = get_adapter(
                "video_preview", default="evidence.adapters.FakeVideoPreview").make(data, ct)
        key = f"{evidence.storage_key}.preview"
        if not store_.exists(key):
            store_.put(key, out)
        p = Preview.objects.create(evidence=evidence, kind=kind, status=status, storage_key=key,
                                   content_type=out_ct, width=w, height=h, size_bytes=len(out))
    except Exception as exc:  # noqa: BLE001 - a failed preview never loses the original (TC-EVD-004-02)
        p = Preview.objects.create(evidence=evidence, kind=kind, status="failed", detail=str(exc)[:500])
        record(action="evidence.preview_failed", entity="evidence", entity_id=evidence.pk,
               data={"error": str(exc)[:200]}, country=evidence.country)
        publish("evidence.preview_failed", evidence.pk, {"evidence_id": evidence.pk, "error": str(exc)[:200]})
    return p


def preview_usable(evidence) -> bool:
    p = Preview.objects.filter(evidence=evidence).first()
    return bool(p and p.status in ("ready", "placeholder") and p.storage_key)


# --------------------------------------------------------------------------- signed links (FR-EVD-003)

def _link_key() -> bytes:
    return hashlib.sha256(b"tenmina-evidence-link:" + settings.SECRET_KEY.encode()).digest()


def _sign(payload: dict) -> str:
    body = _b64url(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    sig = _b64url(hmac.new(_link_key(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def _log(evidence, person, action, *, variant="", expires=None, request=None, detail=""):
    AccessLog.objects.create(evidence=evidence, country=evidence.country,
                             person=person if person is not None and person.is_authenticated else None,
                             action=action, variant=variant, link_expires_at=expires, ip_hash=_ip_hash(request),
                             user_agent=_ua(request), detail=detail)


def _servable(evidence):
    if evidence.deleted_at:
        raise StateConflict("This evidence was removed under its retention rule.")
    if evidence.scan_status == "pending":
        raise StateConflict("This file is still being checked for safety. Try again in a few minutes.",
                            extra={"scan_status": "pending"})
    if evidence.scan_status != "clean":
        raise Invalid("This file failed the safety scan and cannot be opened.", code="evidence-rejected")


def link_ttl(country) -> int:
    return min(LINK_TTL_MAX, int(_cfg(country, "evidence.link_ttl_seconds", LINK_TTL_MAX)))


def issue_link(evidence: Evidence, person, *, variant: str | None = None, request=None) -> dict:
    if not access.can_view(person, evidence):
        _log(evidence, person, "refused", request=request, detail="no_permission")
        raise NotFound("Evidence not found.")
    _servable(evidence)
    has_preview = preview_usable(evidence)
    variant = variant or ("preview" if has_preview else "original")
    if variant not in ("preview", "original"):
        raise Invalid("Variant must be preview or original.")
    if variant == "preview" and not has_preview:
        raise Invalid("There is no preview for this file. Ask for the original.")
    ttl = link_ttl(evidence.country)
    exp = timezone.now() + timedelta(seconds=ttl)
    token = _sign({"e": str(evidence.pk), "p": str(person.pk), "v": variant, "x": int(exp.timestamp())})
    _log(evidence, person, "link_issued", variant=variant, expires=exp, request=request)
    ct = Preview.objects.get(evidence=evidence).content_type if variant == "preview" else evidence.content_type
    return {"url": f"/v1/evidence-files/{token}", "token": token, "expires_at": exp, "expires_in": ttl,
            "variant": variant, "content_type": ct}


def open_link(token: str, *, user=None, request=None):
    """Returns (bytes, content_type, filename, evidence) for a valid, unexpired link."""
    try:
        body, sig = token.split(".", 1)
        payload = json.loads(_unb64url(body))
    except Exception:  # noqa: BLE001
        raise Forbidden("This link is not valid.") from None
    evidence = Evidence.objects.filter(pk=payload.get("e")).first() if isinstance(payload, dict) else None
    good = hmac.compare_digest(_b64url(hmac.new(_link_key(), body.encode(), hashlib.sha256).digest()), sig)
    if not good or evidence is None:
        if evidence is not None:
            _log(evidence, user, "refused", request=request, detail="bad_signature")
        raise Forbidden("This link is not valid.")
    if int(payload.get("x", 0)) < int(timezone.now().timestamp()):
        _log(evidence, user, "refused", variant=payload.get("v", ""), request=request, detail="expired")
        raise Forbidden("This link has expired. Open the evidence again to get a new link.")
    if user is not None and user.is_authenticated and str(user.pk) != payload.get("p"):
        _log(evidence, user, "refused", variant=payload.get("v", ""), request=request, detail="other_account")
        raise Forbidden("This link was issued to someone else. Open the evidence from your own account.")
    _servable(evidence)
    variant = payload.get("v", "original")
    store_ = get_adapter("evidence_store")
    if variant == "preview":
        p = Preview.objects.get(evidence=evidence)
        data, ct, name = store_.get(p.storage_key), p.content_type, f"preview-{evidence.pk}.jpg"
    else:
        data, ct, name = store_.get(evidence.storage_key), evidence.content_type, \
            evidence.original_name or str(evidence.pk)
    from accounts.models import Person

    who = Person.objects.filter(pk=payload.get("p")).first()
    _log(evidence, who, "downloaded", variant=variant, request=request)
    return data, ct, name, evidence


def refuse_delete(evidence: Evidence, person, request=None):
    """FR-EVD-002, TC-EVD-002-02: deletion through the API is always refused and logged."""
    _log(evidence, person, "delete_refused", request=request)
    record(actor=person, action="evidence.delete_refused", entity="evidence", entity_id=evidence.pk,
           data={}, country=evidence.country)
    raise Forbidden("Evidence is never deleted or overwritten. It is removed only when its retention period ends.",
                    code="evidence-immutable")


# --------------------------------------------------------------------------- issued documents and fingerprints

def register_issued(evidence: Evidence, subject_type: str, subject_id, *, kind="report_pdf", issued_at=None,
                    by=None) -> IssuedDocument:
    """Record a document Tenmina issued so its fingerprint can be checked by anyone holding it."""
    doc, created = IssuedDocument.objects.get_or_create(
        evidence=evidence, subject_type=subject_type, subject_id=subject_id,
        defaults=dict(country=evidence.country, sha256=evidence.sha256, kind=kind,
                      issued_at=issued_at or timezone.now(), issued_by=by))
    if created:
        record(actor=by, action="evidence.issued", entity="evidence", entity_id=evidence.pk,
               data={"subject_type": subject_type, "subject_id": str(subject_id), "kind": kind},
               country=evidence.country)
    return doc


def check_fingerprint(sha256: str, *, request=None) -> dict:
    """Public. Answers only whether the hash matches a document Tenmina issued, and its release date."""
    digest = normalise_sha256(sha256)
    doc = IssuedDocument.objects.filter(sha256=digest).order_by("issued_at").first()
    FingerprintCheck.objects.create(sha256=digest, matched=doc is not None, ip_hash=_ip_hash(request))
    return {"match": doc is not None, "released_on": doc.issued_at.date() if doc else None}


def access_log_for(subject_type: str, subject_id):
    return AccessLog.objects.filter(evidence__links__subject_type=subject_type,
                                    evidence__links__subject_id=subject_id).select_related("person", "evidence") \
        .order_by("-created_at").distinct()


# --------------------------------------------------------------------------- integrity sampling (10.7 step 7)

def integrity_sample(*, size: int | None = None, seed: str | None = None, by=None) -> IntegrityRun:
    seed = seed or secrets.token_hex(8)
    ids = sorted(str(i) for i in Evidence.objects.filter(deleted_at__isnull=True).values_list("id", flat=True))
    k = min(size or INTEGRITY_SAMPLE_SIZE, len(ids))
    sample = random.Random(seed).sample(ids, k) if k else []
    run = IntegrityRun.objects.create(seed=seed, population=len(ids), sample_size=k, triggered_by=by)
    incidents = []
    store_ = get_adapter("evidence_store")
    for eid in sample:
        ev = Evidence.objects.get(pk=eid)
        try:
            actual = hashlib.sha256(store_.get(ev.storage_key)).hexdigest()
        except (FileNotFoundError, KeyError):
            actual = ""
        run.checked += 1
        if actual != ev.sha256:
            incidents.append(IntegrityIncident.objects.create(run=run, evidence=ev, country=ev.country,
                                                              expected_sha256=ev.sha256, actual_sha256=actual))
    run.mismatches = len(incidents)
    run.finished_at = timezone.now()
    run.save(update_fields=["checked", "mismatches", "finished_at"])
    record(actor=by, action="evidence.integrity_sampled", entity="integrity_run", entity_id=run.pk,
           data={"seed": seed, "population": len(ids), "sample": k, "mismatches": len(incidents)})
    for inc in incidents:
        _raise_incident(inc)
    return run


def _raise_incident(inc: IntegrityIncident):
    from accounts.models import Person
    from notifications.services import notify

    record(action="evidence.integrity_failed", entity="evidence", entity_id=inc.evidence_id,
           data={"incident": str(inc.pk), "expected": inc.expected_sha256, "actual": inc.actual_sha256 or "missing"},
           country=inc.country)
    publish("evidence.integrity_failed", inc.pk, {"incident_id": inc.pk, "evidence_id": inc.evidence_id,
                                                  "expected": inc.expected_sha256,
                                                  "actual": inc.actual_sha256 or None})
    admins = Person.objects.filter(role_grants__role="AD", role_grants__revoked_at__isnull=True,
                                   is_active=True).distinct()
    for a in admins:
        notify(a, "evidence_integrity_incident", subject="Security incident: evidence integrity",
               body="A stored evidence file no longer matches its fingerprint. Open the incident in the back "
                    "office and follow the security incident runbook.", channels=("in_app", "email"),
               subject_obj=inc)


def resolve_incident(inc: IntegrityIncident, by, note: str) -> IntegrityIncident:
    if not note:
        raise Invalid("Say how the incident was resolved.")
    inc.resolved_by, inc.resolved_at, inc.resolution_note = by, timezone.now(), note
    return state.transition(inc, "integrity_incident", "resolved", actor=by, event="evidence.incident_resolved",
                            extra_fields=["resolved_by", "resolved_at", "resolution_note"], reason=note)


# --------------------------------------------------------------------------- retention (FR-EVD-002, 6.10)

def retention_sweep(*, today: date | None = None, by=None) -> list[RetentionDeletion]:
    today = today or timezone.now().date()
    out = []
    store_ = get_adapter("evidence_store")
    for ev in Evidence.objects.filter(deleted_at__isnull=True, retain_until__lt=today).order_by("retain_until"):
        if access.on_hold(ev):
            continue
        rule = f"{ev.data_class}: {ev.country.code} retention ended {ev.retain_until.isoformat()}"
        with transaction.atomic():
            if hasattr(store_, "expire"):
                store_.expire(ev.storage_key, ev.retain_until, today)
                p = Preview.objects.filter(evidence=ev).first()
                if p and p.storage_key:
                    store_.expire(p.storage_key, ev.retain_until, today)
            Evidence.objects.filter(pk=ev.pk).update(deleted_at=timezone.now())
            rd = RetentionDeletion.objects.create(evidence=ev, country=ev.country, rule=rule,
                                                  retain_until=ev.retain_until, run_by=by)
            record(actor=by, action="evidence.retention_deleted", entity="evidence", entity_id=ev.pk,
                   data={"rule": rule, "sha256": ev.sha256}, country=ev.country)
            publish("evidence.deleted", ev.pk, {"evidence_id": ev.pk, "rule": rule})
        out.append(rd)
    return out
