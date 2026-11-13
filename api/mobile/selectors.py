"""MOB Field app server: read-only queries other modules may use."""
from .models import CheckIn, FraudFlag, Submission


def checkins_for(subject_type: str, subject_id):
    """{'checkin': CheckIn|None, 'checkout': CheckIn|None} for a visit, inspection or errand step (RUL-23)."""
    rows = {c.kind: c for c in CheckIn.objects.filter(subject_type=subject_type, subject_id=subject_id)}
    return {"checkin": rows.get("checkin"), "checkout": rows.get("checkout")}


def open_flags(*, evidence_ids=None, subject_type=None, subject_id=None):
    qs = FraudFlag.objects.filter(status="open")
    if evidence_ids is not None:
        qs = qs.filter(evidence_id__in=list(evidence_ids))
    if subject_type:
        qs = qs.filter(subject_type=subject_type)
    if subject_id:
        qs = qs.filter(subject_id=subject_id)
    return qs


def latest_submission(subject_type: str, subject_id):
    return Submission.objects.filter(subject_type=subject_type, subject_id=subject_id).order_by("-received_at") \
        .first()


def submission_evidence(submission) -> list:
    return [i.evidence for i in submission.items.select_related("evidence") if i.evidence_id]
