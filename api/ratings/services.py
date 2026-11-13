"""RAT Track records and ratings: the public interface other modules may call.

FR-RAT-001 track records per seller, developer, contractor, surveyor, inspector (and other professionals and
           vendors) from deals completed, milestone outcomes, disputes and timeliness; a subject with too
           little history shows a message instead of a score
FR-RAT-002 a client rates a completed case, deal, milestone or dispute from 1 to 5, once per item; a comment
           shows only after moderation
FR-RAT-003 summaries for listings and contractor choices (selectors.summary)
FR-RAT-004 a reviewer hides an abusive comment with a reason; the score never changes

Events consumed: case.status_changed, release.confirmed, milestone.status_changed, dispute.closed.
Events published: rating.created, rating.comment_moderated, track_record.updated.
"""
import logging
from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q
from django.utils import timezone

from audit.services import record
from core import state
from core.errors import Forbidden, Invalid, NotFound, StateConflict
from core.events import publish
from core.permissions import has_role

from .models import Outcome, Rating, RatingOpportunity, TrackRecord

log = logging.getLogger(__name__)

PROFESSIONAL_ROLES = ("LW", "SV", "RN", "IN", "QS", "CE")
RATEABLE_PAYEE_KINDS = ("contractor", "seller", "developer", "vendor", "supplier", "carer", "agency", "professional")
DEFAULT_MIN_HISTORY = 3  # [TO VERIFY] how many completed items before a score is shown
MAX_COMMENT = 1000


def _now():
    return timezone.now()


def _cfg(country, key, default=None):
    if country is None:
        return default
    from countries.selectors import config

    try:
        v = config(country, key, default)
    except Exception:  # noqa: BLE001
        return default
    return default if v in (None, "") else v


def _country(code_or_obj):
    from countries.models import Country

    if code_or_obj is None or isinstance(code_or_obj, Country):
        return code_or_obj
    return Country.objects.filter(code=str(code_or_obj).upper()).first()


def subject_name(subject_type, subject_id) -> str:
    from accounts.models import Organisation, Person

    obj = (Organisation if subject_type == "organisation" else Person).objects.filter(pk=subject_id).first()
    if obj is None:
        return ""
    return getattr(obj, "name", None) or getattr(obj, "full_name", "")


# --------------------------------------------------------------------------- facts and opportunities

def add_outcome(*, subject_type, subject_id, kind, source_type, source_id, role="", on_time=None, country=None,
                occurred_at=None, recompute_now=True) -> Outcome | None:
    if not subject_id:
        return None
    try:
        with transaction.atomic():
            o = Outcome.objects.create(country=_country(country), subject_type=subject_type, subject_id=subject_id,
                                       subject_role=role or "", kind=kind, source_type=source_type,
                                       source_id=source_id, on_time=on_time, occurred_at=occurred_at or _now())
    except IntegrityError:
        return None  # the same fact delivered twice
    if recompute_now:
        recompute(subject_type, subject_id)
    return o


def offer(*, rater, context_type, context_id, subject_type, subject_id, role="", label="", country=None):
    """A client may rate this subject for this completed item. Idempotent."""
    if rater is None or not subject_id or str(getattr(rater, "pk", rater)) == str(subject_id):
        return None
    from accounts.models import Person

    rater = rater if isinstance(rater, Person) else Person.objects.filter(pk=rater).first()
    if rater is None or not rater.has_tenmina_role("CL"):
        return None
    opp, _ = RatingOpportunity.objects.get_or_create(
        rater=rater, context_type=context_type, context_id=context_id, subject_type=subject_type,
        subject_id=subject_id, defaults=dict(country=_country(country), subject_role=role or "", context_label=label,
                                             subject_name=subject_name(subject_type, subject_id)))
    return opp


def on_case_closed(payload: dict):
    """case.status_changed to released or completed: every professional who did a task gets a fact with its
    timeliness, and the client may rate them."""
    if payload.get("to") not in ("released", "completed"):
        return
    from cases.models import Case

    case = Case.objects.filter(pk=payload.get("case_id") or payload.get("id")).select_related("country").first()
    if case is None:
        return
    seen = set()
    for t in case.tasks.filter(status="done", assignee__isnull=False).select_related("assignee"):
        if t.owner_role not in PROFESSIONAL_ROLES:
            continue
        on_time = bool(t.completed_at and t.due_at and t.completed_at <= t.due_at) if t.due_at else None
        add_outcome(subject_type="person", subject_id=t.assignee_id, kind="case_task_completed", role=t.owner_role,
                    source_type="task", source_id=t.pk, on_time=on_time, country=case.country,
                    occurred_at=t.completed_at)
        if t.assignee_id not in seen and case.client_id:
            seen.add(t.assignee_id)
            offer(rater=case.client, context_type="case", context_id=case.pk, subject_type="person",
                  subject_id=t.assignee_id, role=t.owner_role, label=f"Case {case.reference}", country=case.country)


def _payee_subject(payee):
    if payee.organisation_id:
        return "organisation", payee.organisation_id
    if payee.person_id:
        return "person", payee.person_id
    return None, None


def on_release_confirmed(payload: dict):
    """A deal completed for the payee (a seller, developer, contractor, vendor or supplier)."""
    from escrow.models import Payee

    payee = Payee.objects.filter(pk=payload.get("payee_id")).first()
    if payee is None or payee.kind not in RATEABLE_PAYEE_KINDS:
        return
    st, sid = _payee_subject(payee)
    if sid is None:
        return
    iid = payload.get("instruction_id")
    add_outcome(subject_type=st, subject_id=sid, kind="deal_completed", role=payee.kind,
                source_type="release_instruction", source_id=iid, country=payee.country)
    if payload.get("client_id"):
        offer(rater=payload["client_id"], context_type="release_instruction", context_id=iid, subject_type=st,
              subject_id=sid, role=payee.kind, label=payload.get("label") or f"Payment to {payee.legal_name}",
              country=payee.country)


def on_milestone(payload: dict):
    """milestone.status_changed from BLD: paid, returned after a failed inspection, or passed with defects.
    Payload keys used: milestone_id or id, to, contractor_organisation_id or contractor_id, client_id, outcome."""
    mid = payload.get("milestone_id") or payload.get("id")
    org = payload.get("contractor_organisation_id")
    st, sid = ("organisation", org) if org else ("person", payload.get("contractor_id"))
    if not mid or not sid:
        return
    to, outcome = payload.get("to"), payload.get("outcome") or payload.get("inspection_outcome")
    country = payload.get("country")
    if to == "paid":
        add_outcome(subject_type=st, subject_id=sid, kind="milestone_completed", role="contractor",
                    source_type="milestone", source_id=mid, on_time=payload.get("on_time"), country=country)
        if payload.get("client_id"):
            offer(rater=payload["client_id"], context_type="milestone", context_id=mid, subject_type=st,
                  subject_id=sid, role="contractor", label=payload.get("label", "Milestone"), country=country)
    if outcome == "pass_with_defects":
        add_outcome(subject_type=st, subject_id=sid, kind="milestone_defects", role="contractor",
                    source_type="milestone", source_id=mid, country=country)
    if outcome == "fail":
        add_outcome(subject_type=st, subject_id=sid, kind="milestone_failed", role="contractor",
                    source_type="milestone", source_id=mid, country=country)


def on_dispute_closed(payload: dict):
    """dispute.closed from DSP: every party side gets a closed dispute; the side found against loses it.
    The client who raised it may rate the other side."""
    did = payload.get("dispute_id")
    if not did:
        return
    favour = payload.get("in_favour_of")  # raised_by | respondent | split | none
    country = payload.get("country")
    for p in payload.get("parties") or []:
        st, sid = ("organisation", p.get("organisation_id")) if p.get("organisation_id") else \
            ("person", p.get("person_id"))
        if not sid:
            continue
        side = p.get("side")
        add_outcome(subject_type=st, subject_id=sid, kind="dispute_closed", role=p.get("role", ""),
                    source_type="dispute", source_id=did, country=country)
        lost = (favour == "raised_by" and side == "respondent") or (favour == "respondent" and side == "raised_by")
        won = (favour == "raised_by" and side == "raised_by") or (favour == "respondent" and side == "respondent")
        if lost:
            add_outcome(subject_type=st, subject_id=sid, kind="dispute_lost", role=p.get("role", ""),
                        source_type="dispute", source_id=did, country=country)
        elif won:
            add_outcome(subject_type=st, subject_id=sid, kind="dispute_won", role=p.get("role", ""),
                        source_type="dispute", source_id=did, country=country)
        if side == "respondent" and payload.get("raised_by_id"):
            offer(rater=payload["raised_by_id"], context_type="dispute", context_id=did, subject_type=st,
                  subject_id=sid, role=p.get("role", ""), label=f"Dispute {payload.get('reference', '')}".strip(),
                  country=country)


# --------------------------------------------------------------------------- rating (FR-RAT-002, 004)

@transaction.atomic
def rate(rater, *, score, comment="", opportunity=None, context_type=None, context_id=None, subject_type=None,
         subject_id=None) -> Rating:
    from administration import flags

    flags.read_only_guard()
    if opportunity is None:
        opportunity = RatingOpportunity.objects.filter(
            rater=rater, context_type=context_type, context_id=context_id, subject_type=subject_type,
            subject_id=subject_id).first()
    if opportunity is None:
        raise StateConflict("You can rate only work that is complete and that you were the client for.",
                            code="not-rateable")
    if opportunity.rater_id != rater.pk:
        raise NotFound()
    try:
        score = int(score)
    except (TypeError, ValueError):
        raise Invalid("The score must be a whole number from 1 to 5.") from None
    if not 1 <= score <= 5:
        raise Invalid("The score must be from 1 to 5.", extra={"errors": [{"pointer": "/score",
                                                                            "message": "From 1 to 5."}]})
    comment = (comment or "").strip()
    if len(comment) > MAX_COMMENT:
        raise Invalid(f"Keep the comment under {MAX_COMMENT} characters.")
    if Rating.objects.filter(opportunity=opportunity).exists():
        raise StateConflict("You already rated this.", code="already-rated")
    o = opportunity
    try:
        with transaction.atomic():
            r = Rating.objects.create(country=o.country, opportunity=o, rater=rater, context_type=o.context_type,
                                      context_id=o.context_id, subject_type=o.subject_type, subject_id=o.subject_id,
                                      subject_role=o.subject_role, score=score, comment=comment,
                                      comment_status="pending" if comment else "none")
    except IntegrityError:
        raise StateConflict("You already rated this.", code="already-rated") from None
    record(actor=rater, action="rating.created", entity="rating", entity_id=r.pk, country=o.country,
           data={"score": score, "subject_type": o.subject_type, "subject_id": str(o.subject_id),
                 "has_comment": bool(comment)})
    publish("rating.created", r.pk, {"rating_id": r.pk, "subject_type": r.subject_type, "subject_id": r.subject_id,
                                     "score": score, "comment_pending": bool(comment)})
    recompute(r.subject_type, r.subject_id)
    return r


def _moderator(actor, rating):
    if not has_role(actor, "RV", "AD", country=rating.country):
        raise Forbidden("Only a reviewer moderates comments.")


@transaction.atomic
def hide_comment(rating, actor, reason) -> Rating:
    r = Rating.objects.select_for_update().get(pk=rating.pk)
    _moderator(actor, r)
    if not (reason or "").strip():
        raise Invalid("Give the reason for hiding the comment.",
                      extra={"errors": [{"pointer": "/reason", "message": "Required."}]})
    if r.comment_status == "none":
        raise StateConflict("This rating has no comment.")
    r.hidden_reason, r.moderated_by, r.moderated_at = reason.strip(), actor, _now()
    state.transition(r, "rating_comment", "hidden", actor=actor, event="rating.comment_moderated",
                     reason=reason.strip(), payload={"rating_id": r.pk, "score_unchanged": r.score},
                     extra_fields=["hidden_reason", "moderated_by", "moderated_at"])
    return r


@transaction.atomic
def publish_comment(rating, actor) -> Rating:
    r = Rating.objects.select_for_update().get(pk=rating.pk)
    _moderator(actor, r)
    if r.comment_status == "none":
        raise StateConflict("This rating has no comment.")
    r.moderated_by, r.moderated_at = actor, _now()
    state.transition(r, "rating_comment", "published", actor=actor, event="rating.comment_moderated",
                     payload={"rating_id": r.pk}, extra_fields=["moderated_by", "moderated_at"])
    return r


# --------------------------------------------------------------------------- track records (FR-RAT-001)

def min_history(country=None) -> int:
    return int(_cfg(country, "ratings.min_history", DEFAULT_MIN_HISTORY))


def recompute(subject_type, subject_id) -> TrackRecord:
    facts = Outcome.objects.filter(subject_type=subject_type, subject_id=subject_id)
    counts = dict(facts.values_list("kind").annotate(n=Count("id")))
    timed = facts.filter(kind__in=["case_task_completed", "milestone_completed"], on_time__isnull=False)
    on_time = timed.filter(on_time=True).count()
    ratings = Rating.objects.filter(subject_type=subject_type, subject_id=subject_id)
    agg = ratings.aggregate(avg=Avg("score"), n=Count("id"))
    first = facts.exclude(country__isnull=True).first() or ratings.exclude(country__isnull=True).first()
    country = first.country if first else None
    history = counts.get("deal_completed", 0) + counts.get("case_task_completed", 0) + \
        counts.get("milestone_completed", 0)
    roles = sorted({r for r in facts.values_list("subject_role", flat=True) if r} |
                   {r for r in ratings.values_list("subject_role", flat=True) if r})
    tr, _ = TrackRecord.objects.get_or_create(subject_type=subject_type, subject_id=subject_id)
    tr.country = country
    tr.display_name = subject_name(subject_type, subject_id)
    tr.roles = roles
    tr.deals_completed = counts.get("deal_completed", 0)
    tr.tasks_completed = counts.get("case_task_completed", 0)
    tr.tasks_on_time = facts.filter(kind="case_task_completed", on_time=True).count()
    tr.milestones_completed = counts.get("milestone_completed", 0)
    tr.milestones_with_defects = counts.get("milestone_defects", 0)
    tr.milestones_failed = counts.get("milestone_failed", 0)
    tr.disputes_total = counts.get("dispute_closed", 0)
    tr.disputes_lost = counts.get("dispute_lost", 0)
    tr.ratings_count = agg["n"] or 0
    tr.average_score = Decimal(str(agg["avg"])).quantize(Decimal("0.01"), ROUND_HALF_UP) if agg["avg"] else None
    tr.on_time_pct = (Decimal(on_time * 100) / timed.count()).quantize(Decimal("0.1"), ROUND_HALF_UP) \
        if timed.count() else None
    tr.enough_history = history >= min_history(country)
    tr.computed_at = _now()
    tr.save()
    publish("track_record.updated", tr.pk, {"subject_type": subject_type, "subject_id": subject_id,
                                            "enough_history": tr.enough_history})
    return tr


def recompute_all() -> int:
    """ratings.recompute, nightly."""
    subjects = set(Outcome.objects.values_list("subject_type", "subject_id").distinct()) | \
        set(Rating.objects.values_list("subject_type", "subject_id").distinct()) | \
        set(TrackRecord.objects.values_list("subject_type", "subject_id"))
    for st, sid in subjects:
        recompute(st, sid)
    return len(subjects)


def moderation_queue(actor):
    if not has_role(actor, "RV", "AD"):
        raise Forbidden()
    from accounts.selectors import staff_country_codes

    codes = staff_country_codes(actor, ("RV", "AD"))
    qs = Rating.objects.filter(comment_status="pending")
    return qs if codes is None else qs.filter(Q(country__code__in=list(codes)) | Q(country__isnull=True))
