"""RAT event subscribers and registrations. Idempotent: every outcome is recorded once per source.

Consumes: case.status_changed, release.confirmed, milestone.status_changed, dispute.closed.
Registers: client home items (things to rate), data protection exporter.
"""
import logging

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)


def _safe(fn, payload):
    try:
        with transaction.atomic():
            fn(payload or {})
    except DomainError as exc:
        log.warning("ratings: %s failed: %s", fn.__name__, exc.detail)


@subscribe("case.status_changed")
def on_case(ev):
    from . import services

    if (ev.payload or {}).get("entity") in (None, "case"):
        _safe(services.on_case_closed, ev.payload)


@subscribe("release.confirmed")
def on_release(ev):
    from . import services

    _safe(services.on_release_confirmed, ev.payload)


@subscribe("milestone.status_changed")
def on_milestone(ev):
    from . import services

    _safe(services.on_milestone, ev.payload)


@subscribe("dispute.closed")
def on_dispute_closed(ev):
    from . import services

    _safe(services.on_dispute_closed, ev.payload)


def _home(person):
    from accounts.home import item

    from .models import RatingOpportunity

    return [item(kind="rating_opportunity", id=o.pk, title=f"Rate {o.subject_name or 'the work'}",
                 status="open", status_text=f"How did it go? {o.context_label}".strip(), needs_action=False,
                 link=f"/ratings/new?opportunity={o.pk}", line="ratings")
            for o in RatingOpportunity.objects.filter(rater=person, rating__isnull=True).order_by("-created_at")[:5]]


def _register():
    from accounts import home
    from dataprotection import registry as dpr

    home.register(_home)

    @dpr.exporter("ratings")
    def export_ratings(person):
        from .models import Rating

        return {"ratings_given": [{"subject": r.opportunity.subject_name, "score": r.score, "comment": r.comment,
                                   "created_at": r.created_at.isoformat()}
                                  for r in Rating.objects.filter(rater=person).select_related("opportunity")]}


_register()
