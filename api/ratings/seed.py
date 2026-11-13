"""RAT demo data: opportunities come from the events earlier seeds produced (released cases, confirmed
releases). Ama rates some of them: one comment waiting for moderation, one published, one hidden for abuse.
Then every track record is computed (ratings.recompute)."""
import logging

from core.errors import DomainError

log = logging.getLogger(__name__)

PLAN = [(5, "The surveyor explained the boundary clearly and sent photos the same day. [demo]", "publish"),
        (4, "Good work, a little slow on the legal review. [demo]", None),
        (2, "Useless people, total idiots. [demo abusive comment]", "hide"),
        (5, "", None)]


def run(ctx):
    from .models import Rating, RatingOpportunity
    from . import services

    people = ctx["people"]
    client = people["client"]
    try:
        if not Rating.objects.filter(rater=client).exists():
            opps = list(RatingOpportunity.objects.filter(rater=client, rating__isnull=True).order_by("created_at"))
            for opp, (score, comment, mod) in zip(opps, PLAN):
                r = services.rate(client, score=score, comment=comment, opportunity=opp)
                if mod == "publish":
                    services.publish_comment(r, people["reviewer"])
                elif mod == "hide":
                    services.hide_comment(r, people["reviewer"], "Abusive language about named people.")
        services.recompute_all()
    except DomainError as exc:
        log.warning("seed ratings: %s", exc.detail)
    ctx["ratings"] = {"count": Rating.objects.count()}
