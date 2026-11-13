"""RAT: rating once after completion, moderation, track records and where they show (FR-RAT-001 to 004)."""
import uuid

import pytest
from django.db import IntegrityError, transaction

from core.errors import Forbidden, Invalid, StateConflict
from ratings import selectors, services
from ratings.models import Outcome, Rating, RatingOpportunity, TrackRecord


def _open_opportunity(people):
    o = RatingOpportunity.objects.filter(rater=people["client"], rating__isnull=True).first()
    assert o is not None
    return o


def test_rate_once_with_comment_pending_moderation(seeded, api, people):
    """US-RAT-002, TC-RAT-002-01, -02: 1 to 5, once per item; nothing to rate before completion."""
    o = _open_opportunity(people)
    c = api(people["client"])
    for bad in (0, 6):
        assert c.post("/v1/ratings", {"opportunity_id": str(o.pk), "score": bad}, format="json").status_code == 422
    r = c.post("/v1/ratings", {"opportunity_id": str(o.pk), "score": 4, "comment": "Clear and on time."},
               format="json")
    assert r.status_code == 201, r.content
    assert r.json()["comment_status"] == "pending"
    assert c.post("/v1/ratings", {"opportunity_id": str(o.pk), "score": 5}, format="json").status_code == 409
    incomplete = c.post("/v1/ratings", {"context_type": "case", "context_id": str(uuid.uuid4()),
                                        "subject_type": "person", "subject_id": str(people["lawyer"].pk),
                                        "score": 5}, format="json")
    assert incomplete.status_code == 409 and incomplete.json()["code"] == "not-rateable"
    assert api(people["client2"]).post("/v1/ratings", {"opportunity_id": str(o.pk), "score": 3},
                                       format="json").status_code == 404
    pub = api().get(f"/v1/track-records/{o.subject_id}?subject_type={o.subject_type}").json()
    assert "Clear and on time." not in [x["comment"] for x in pub["comments"]]


def test_hide_keeps_score_and_logs_reason(seeded, api, people):
    """US-RAT-004, TC-RAT-004-01: a reviewer hides with a reason; the score never changes."""
    from audit.models import AuditEvent

    r = services.rate(people["client"], score=1, comment="Rude words", opportunity=_open_opportunity(people))
    assert api(people["cm"]).post(f"/v1/ratings/{r.pk}/hide", {"reason": "Abusive"},
                                  format="json").status_code in (403, 404)
    with pytest.raises(Forbidden):
        services.hide_comment(r, people["cm"], "Abusive")
    assert api(people["reviewer"]).post(f"/v1/ratings/{r.pk}/hide", {"reason": ""},
                                        format="json").status_code == 400
    resp = api(people["reviewer"]).post(f"/v1/ratings/{r.pk}/hide", {"reason": "Abusive language"}, format="json")
    assert resp.status_code == 200 and resp.json()["comment_status"] == "hidden"
    r.refresh_from_db()
    assert r.score == 1 and r.hidden_reason == "Abusive language"
    assert AuditEvent.objects.filter(entity_id=str(r.pk), action="rating_comment.hidden").exists()
    with pytest.raises(IntegrityError), transaction.atomic():
        Rating.objects.filter(pk=r.pk).update(score=5)
    with pytest.raises(Forbidden):
        services.publish_comment(r, people["client"])


def test_track_record_figures_and_too_little_history(seeded, people, gh):
    """US-RAT-001, TC-RAT-001-01: figures match the facts; too little history shows a message."""
    from accounts.models import Organisation

    org = Organisation.objects.create(name="New Builders (test)", kind="contractor", country=gh)
    services.add_outcome(subject_type="organisation", subject_id=org.pk, kind="milestone_completed",
                         source_type="milestone", source_id=uuid.uuid4(), on_time=True, country=gh)
    s = selectors.summary("organisation", org.pk)
    assert s["enough_history"] is False and "Not enough history" in s["summary"]
    for on_time in (True, False):
        services.add_outcome(subject_type="organisation", subject_id=org.pk, kind="milestone_completed",
                             source_type="milestone", source_id=uuid.uuid4(), on_time=on_time, country=gh)
    did = uuid.uuid4()
    services.add_outcome(subject_type="organisation", subject_id=org.pk, kind="dispute_lost",
                         source_type="dispute", source_id=did, country=gh)
    assert services.add_outcome(subject_type="organisation", subject_id=org.pk, kind="dispute_lost",
                                source_type="dispute", source_id=did, country=gh) is None  # once per source
    services.recompute_all()
    tr = TrackRecord.objects.get(subject_type="organisation", subject_id=org.pk)
    assert (tr.milestones_completed, tr.disputes_lost, tr.enough_history) == (3, 1, True)
    assert str(tr.on_time_pct) == "66.7"


def test_track_record_public_on_listing_and_compare(seeded, api):
    """US-RAT-003, TC-RAT-003-01: shown on listings and when comparing contractors."""
    from listings.models import Listing

    ato = seeded["orgs"]["ato"]
    tr = api().get(f"/v1/track-records/{ato.pk}?subject_type=organisation")
    assert tr.status_code == 200 and tr.json()["deals_completed"] >= 2
    live = Listing.objects.get(pk=seeded["listings"]["live"].pk)
    assert api().get(f"/v1/listings/{live.pk}").json()["seller_track_record"]["deals_completed"] >= 2
    kobby = seeded["orgs"]["kobby"]
    cmp_ = api().get(f"/v1/track-records?subject_ids={ato.pk},{kobby.pk}&subject_type=organisation").json()
    assert {x["subject_id"] for x in cmp_} == {str(ato.pk), str(kobby.pk)}
    assert api().get(f"/v1/track-records/{uuid.uuid4()}").status_code == 404


def test_outcomes_from_events(seeded, people):
    """FR-RAT-001: released cases and confirmed releases became facts and rating opportunities."""
    assert Outcome.objects.filter(kind="case_task_completed", subject_id=people["lawyer"].pk).exists()
    assert Outcome.objects.filter(kind="deal_completed", subject_id=seeded["orgs"]["ato"].pk).exists()
    assert RatingOpportunity.objects.filter(rater=people["client"], context_type="case").exists()
    services.on_milestone({"milestone_id": str(uuid.uuid4()), "to": "inspected", "outcome": "pass_with_defects",
                           "contractor_organisation_id": str(seeded["orgs"]["kobby"].pk)})
    assert TrackRecord.objects.get(subject_id=seeded["orgs"]["kobby"].pk).milestones_with_defects == 1
    with pytest.raises((Invalid, StateConflict)):
        services.rate(people["client"], score=3)
