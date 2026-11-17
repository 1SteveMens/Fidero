"""RAT demo data: opportunities come from the events earlier seeds produced (released cases, confirmed
releases). Ama rates some of them: one comment waiting for moderation, one published, one hidden for abuse.
Then every track record is computed (ratings.recompute). Satisfaction questions were asked by the same events;
Ama answers the first one (a promoter) and leaves the others open, so both screens have data."""
import logging

from core.errors import DomainError

log = logging.getLogger(__name__)

PLAN = [(5, "The surveyor explained the boundary clearly and sent photos the same day. [demo]", "publish"),
        (4, "Good work, a little slow on the legal review. [demo]", None),
        (2, "Useless people, total idiots. [demo abusive comment]", "hide"),
        (5, "", None)]


def run(ctx):
    from . import services
    from .models import Rating, RatingOpportunity, SatisfactionSurvey

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
        if not SatisfactionSurvey.objects.filter(client=client, answered_at__isnull=False).exists():
            first = SatisfactionSurvey.objects.filter(client=client).order_by("asked_at").first()
            if first is not None:
                services.answer_satisfaction(first, client, score=9,
                                             comment="Clear report and quick answers on WhatsApp. [demo]")
    except DomainError as exc:
        log.warning("seed ratings: %s", exc.detail)
    ctx["ratings"] = {"count": Rating.objects.count(), "satisfaction": SatisfactionSurvey.objects.count()}
