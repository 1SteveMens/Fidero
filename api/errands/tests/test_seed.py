"""The TSK demo journeys load through the real services, in several states."""


def test_seed_has_errands_in_several_states(seeded):
    """J-12: documents missing, a document rejected, a step fee instructed, handed over by courier."""
    from errands.models import Errand

    out = {k: Errand.objects.get(pk=e.pk) for k, e in seeded["errands"]["errands"].items()}
    assert out["ghana_card_renewal"].status == "ordered"
    assert out["passport_renewal"].status == "documents_pending"
    e3 = out["birth_cert"]
    assert e3.status == "in_progress" and e3.steps.get(seq=1).status == "fee_instructed"
    e4 = out["utility_transfer"]
    assert e4.status == "handed_over" and e4.handover.tracking_reference and e4.work_accepted_at
