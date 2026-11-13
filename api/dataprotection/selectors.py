"""DPR read-only queries other modules may use: the current privacy notice,
consents (RUL-16 partner sharing, FR-DPR-002 video, FR-RPT-011 case
studies) and legal holds."""
from django.db.models import Q

from .models import Consent, LegalHold, PrivacyAcceptance, PrivacyNotice


def current_notice(country=None) -> PrivacyNotice | None:
    qs = PrivacyNotice.objects.filter(status="published")
    if country is not None:
        own = qs.filter(country=country).order_by("-published_at").first()
        if own:
            return own
    return qs.filter(country__isnull=True).order_by("-published_at").first()


def pending_notice_version(person) -> str | None:
    """US-DPR-001 AC2: the version a person must accept, or None."""
    notice = current_notice(getattr(person, "home_country", None))
    if notice is None:
        return None
    if PrivacyAcceptance.objects.filter(person=person, notice=notice).exists():
        return None
    return notice.version


def active_consents(person=None, purpose=None):
    qs = Consent.objects.filter(withdrawn_at__isnull=True)
    if person is not None:
        qs = qs.filter(person=person)
    if purpose:
        qs = qs.filter(purpose=purpose)
    return qs


def has_consent(person, purpose, *, partner_client_id=None, report_id=None) -> bool:
    """RUL-16: a full report goes to a partner only with the client's
    recorded consent for that partner and that report."""
    qs = active_consents(person, purpose)
    if partner_client_id is not None:
        qs = qs.filter(partner_client_id=partner_client_id)
    if report_id is not None:
        qs = qs.filter(report_id=report_id)
    return qs.exists()


def recording_has_consent(evidence_id) -> bool:
    """FR-DPR-002: a consent video is attached only with a consent record."""
    return Consent.objects.filter(purpose="video_recording", recording_evidence_id=evidence_id,
                                  withdrawn_at__isnull=True).exists()


def is_held(subject_type, subject_id) -> bool:
    return LegalHold.objects.filter(subject_type=subject_type, subject_id=subject_id,
                                    status__in=["active", "lift_pending"]).exists()


def holds_on(pairs) -> list[LegalHold]:
    q = Q()
    for st, sid in pairs:
        q |= Q(subject_type=st, subject_id=sid)
    if not q:
        return []
    return list(LegalHold.objects.filter(q, status__in=["active", "lift_pending"]))
