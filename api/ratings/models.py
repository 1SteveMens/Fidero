"""RAT Track records and ratings (01 C4.13, 02 section 6.8).

- An opportunity is created when a case, release, milestone or dispute the client was part of closes. Only
  then can the client rate the people or organisation that did the work (FR-RAT-002, once per item).
- A comment shows publicly only after a reviewer moderates it; a reviewer can hide it with a reason without
  touching the score (FR-RAT-004; the score cannot be updated, dbsql).
- Outcomes are facts recorded from events (deals completed, tasks on time, milestone results, disputes lost).
  A track record is computed from them and the ratings (FR-RAT-001).
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel

SUBJECT_TYPES = ["person", "organisation"]
CONTEXT_TYPES = ["case", "release_instruction", "milestone", "dispute", "listing", "escrow"]


class RatingOpportunity(BaseModel):
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    context_type = models.TextField(choices=[(c, c) for c in CONTEXT_TYPES])
    context_id = models.UUIDField()
    context_label = models.TextField(blank=True, default="")
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    subject_role = models.TextField(blank=True, default="")  # seller, developer, contractor, LW, SV, IN, vendor
    subject_name = models.TextField(blank=True, default="")

    class Meta:
        db_table = "rat_rating_opportunity"
        constraints = [models.UniqueConstraint(fields=["rater", "context_type", "context_id", "subject_type",
                                                       "subject_id"], name="rat_opportunity_once")]


class Rating(BaseModel):
    COMMENT_STATUSES = ["none", "pending", "published", "hidden"]
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    opportunity = models.OneToOneField(RatingOpportunity, on_delete=models.PROTECT, related_name="rating")
    rater = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    context_type = models.TextField()
    context_id = models.UUIDField()
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    subject_role = models.TextField(blank=True, default="")
    score = models.PositiveSmallIntegerField()
    comment = models.TextField(blank=True, default="")
    comment_status = models.TextField(default="none", choices=[(s, s) for s in COMMENT_STATUSES])
    hidden_reason = models.TextField(blank=True, default="")
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    moderated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rat_rating"
        indexes = [models.Index(fields=["subject_type", "subject_id"], name="rat_rating_subject_idx")]
        constraints = [
            models.CheckConstraint(condition=Q(score__gte=1) & Q(score__lte=5), name="rat_rating_score_1_5"),
            models.UniqueConstraint(fields=["rater", "context_type", "context_id", "subject_type", "subject_id"],
                                    name="rat_rating_once"),
            models.CheckConstraint(condition=~Q(comment_status="hidden") | ~Q(hidden_reason=""),
                                   name="rat_hidden_has_reason"),
        ]


COMMENT = state.register("rating_comment", "rat_rating", {
    "pending": {"published", "hidden"},
    "published": {"hidden"},
    "hidden": {"published"},
}, field="comment_status")


class Outcome(BaseModel):
    """One fact about a subject's work, recorded once per source (append-only)."""

    KINDS = ["deal_completed", "case_task_completed", "milestone_completed", "milestone_defects", "milestone_failed",
             "dispute_closed", "dispute_lost", "dispute_won"]
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    subject_role = models.TextField(blank=True, default="")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    source_type = models.TextField()
    source_id = models.UUIDField()
    on_time = models.BooleanField(null=True, blank=True)
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "rat_outcome"
        indexes = [models.Index(fields=["subject_type", "subject_id"], name="rat_outcome_subject_idx")]
        constraints = [models.UniqueConstraint(fields=["kind", "source_type", "source_id", "subject_type",
                                                       "subject_id"], name="rat_outcome_once")]


class TrackRecord(BaseModel):
    country = models.ForeignKey("countries.Country", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    subject_type = models.TextField(choices=[(s, s) for s in SUBJECT_TYPES])
    subject_id = models.UUIDField()
    display_name = models.TextField(blank=True, default="")
    roles = models.JSONField(default=list)
    deals_completed = models.PositiveIntegerField(default=0)
    tasks_completed = models.PositiveIntegerField(default=0)
    tasks_on_time = models.PositiveIntegerField(default=0)
    milestones_completed = models.PositiveIntegerField(default=0)
    milestones_with_defects = models.PositiveIntegerField(default=0)
    milestones_failed = models.PositiveIntegerField(default=0)
    disputes_total = models.PositiveIntegerField(default=0)
    disputes_lost = models.PositiveIntegerField(default=0)
    ratings_count = models.PositiveIntegerField(default=0)
    average_score = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True)
    on_time_pct = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)
    enough_history = models.BooleanField(default=False)
    computed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "rat_track_record"
        constraints = [models.UniqueConstraint(fields=["subject_type", "subject_id"], name="rat_track_record_uq")]
