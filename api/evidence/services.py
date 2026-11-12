import hashlib

from django.utils import timezone

from audit.services import record
from core.adapters import get_adapter
from core.errors import Invalid
from core.events import publish
from core.ids import uuid7

from .models import Evidence, EvidenceLink

MAX_BYTES = 200 * 1024 * 1024


def store(*, data: bytes, country, uploaded_by=None, content_type="application/octet-stream", original_name="",
          source="upload", expected_sha256=None, description="", **meta) -> Evidence:
    """Hash, scan and store a file write-once. Returns the Evidence record."""
    if len(data) > MAX_BYTES:
        raise Invalid("The file is too large.", code="evidence-rejected")
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 and expected_sha256.lower() != digest:
        raise Invalid("The file changed on the way. Upload it again.", code="evidence-rejected")
    verdict = get_adapter("malware_scan").scan(data)
    if verdict != "clean":
        raise Invalid("The file failed the safety scan.", code="evidence-rejected")
    eid = uuid7()
    key = f"{country.code}/{timezone.now():%Y/%m}/{eid}"
    get_adapter("evidence_store").put(key, data)
    ev = Evidence.objects.create(id=eid, country=country, sha256=digest, size_bytes=len(data),
                                 content_type=content_type, original_name=original_name, storage_key=key,
                                 source=source, uploaded_by=uploaded_by, scan_status="clean",
                                 description=description, **meta)
    record(actor=uploaded_by, action="evidence.stored", entity="evidence", entity_id=ev.pk,
           data={"sha256": digest, "size": len(data), "source": source}, country=country)
    publish("evidence.stored", ev.pk, {"evidence_id": ev.pk, "sha256": digest})
    return ev


def link(evidence: Evidence, subject_type: str, subject_id, role="supporting", by=None) -> EvidenceLink:
    return EvidenceLink.objects.create(evidence=evidence, country=evidence.country, subject_type=subject_type,
                                       subject_id=subject_id, role=role, linked_by=by)


def for_subject(subject_type: str, subject_id):
    return Evidence.objects.filter(links__subject_type=subject_type, links__subject_id=subject_id).distinct()


def verify(evidence: Evidence) -> bool:
    data = get_adapter("evidence_store").get(evidence.storage_key)
    return hashlib.sha256(data).hexdigest() == evidence.sha256
