"""RAT read-only queries other modules may use.

- summary(subject_type, subject_id) -> dict   FR-RAT-003: shown on listings and when a client chooses a contractor
- summaries(subject_type, ids) -> {id: dict}  for comparing contractors side by side
- published_comments(subject_type, subject_id, limit)
"""
from .models import Rating, TrackRecord

TOO_LITTLE = "Not enough history yet to show a track record."


def _plain(tr, subject_type, subject_id) -> dict:
    if tr is None:
        return {"subject_type": subject_type, "subject_id": subject_id, "enough_history": False,
                "summary": TOO_LITTLE, "deals_completed": 0, "disputes_lost": 0, "average_score": None,
                "ratings_count": 0}
    if not tr.enough_history:
        text = TOO_LITTLE
    else:
        parts = [f"{tr.deals_completed + tr.milestones_completed + tr.tasks_completed} jobs completed"]
        if tr.on_time_pct is not None:
            parts.append(f"{tr.on_time_pct}% on time")
        parts.append(f"{tr.disputes_lost} disputes lost")
        if tr.average_score is not None:
            parts.append(f"rated {tr.average_score} from {tr.ratings_count} ratings")
        text = ", ".join(parts) + "."
    return {"subject_type": subject_type, "subject_id": subject_id, "enough_history": tr.enough_history,
            "summary": text, "deals_completed": tr.deals_completed, "disputes_lost": tr.disputes_lost,
            "average_score": tr.average_score if tr.enough_history else None, "ratings_count": tr.ratings_count}


def summary(subject_type, subject_id) -> dict:
    tr = TrackRecord.objects.filter(subject_type=subject_type, subject_id=subject_id).first()
    return _plain(tr, subject_type, subject_id)


def summaries(subject_type, ids) -> dict:
    found = {str(t.subject_id): t for t in TrackRecord.objects.filter(subject_type=subject_type, subject_id__in=ids)}
    return {str(i): _plain(found.get(str(i)), subject_type, i) for i in ids}


def track_record(subject_type, subject_id):
    return TrackRecord.objects.filter(subject_type=subject_type, subject_id=subject_id).first()


def published_comments(subject_type, subject_id, limit=10):
    return Rating.objects.filter(subject_type=subject_type, subject_id=subject_id,
                                 comment_status="published").order_by("-created_at")[:limit]
