"""The CARE demo journeys load through the real services, in several states."""


def test_seed_has_visits_in_several_states(seeded):
    """J-10: missed, confirmed and instructed, waiting for the family, checked in, scheduled."""
    from care.models import CarePlan, Concern, Visit

    refs = seeded["care"]
    plan = CarePlan.objects.get(pk=refs["plan"].pk)
    assert plan.status == "active" and plan.carer_id and plan.carer_approved_at
    states = set(Visit.objects.filter(plan=plan).values_list("status", flat=True))
    assert {"missed", "instructed", "checked_out", "checked_in", "scheduled"} <= states, states
    assert Concern.objects.filter(plan=plan, status="actioned").exists()
    assert Concern.objects.filter(plan=plan, status="open", severity="high").exists()
    assert CarePlan.objects.get(pk=refs["draft_plan"].pk).status == "draft"
