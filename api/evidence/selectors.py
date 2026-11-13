"""EVD Evidence store: read-only queries other modules may use."""
from .models import Evidence, EvidenceLink, IssuedDocument


def for_subject(subject_type: str, subject_id, role: str | None = None):
    qs = Evidence.objects.filter(links__subject_type=subject_type, links__subject_id=subject_id)
    if role:
        qs = qs.filter(links__role=role)
    return qs.distinct()


def links_for(subject_type: str, subject_id):
    return EvidenceLink.objects.filter(subject_type=subject_type, subject_id=subject_id).select_related("evidence")


def has_role_evidence(subject_type: str, subject_id, role: str, *, release_grade=False) -> bool:
    """FR-CASE-004 style checks: is evidence of this kind attached? With release_grade, only
    app-captured items with a verified signature count (RUL-08)."""
    qs = for_subject(subject_type, subject_id, role).filter(deleted_at__isnull=True).exclude(scan_status="rejected")
    if release_grade:
        qs = qs.filter(provenance="app_captured", signature_valid=True, scan_status="clean")
    return qs.exists()


def by_sha256(sha256: str):
    return Evidence.objects.filter(sha256=sha256.lower())


def issued_for(subject_type: str, subject_id):
    return IssuedDocument.objects.filter(subject_type=subject_type, subject_id=subject_id)
