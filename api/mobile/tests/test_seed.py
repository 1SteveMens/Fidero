from evidence.models import Evidence, IssuedDocument
from mobile.models import CheckIn, FraudFlag, Submission


def test_seed_builds_every_state(seeded):
    """Seeds: field work in several states on real subjects (BLD, CARE, CASE), and demo evidence."""
    m = seeded["mobile"]
    assert m["flag"] is not None and m["flag"].status == "open"
    assert m["flag"].subject_type == "task" and str(m["flag"].subject_id) == str(m["runner_task"].pk)
    assert Submission.objects.filter(subject_type="milestone", status="received").exists()
    assert Submission.objects.filter(subject_type="milestone_inspection", outcome="pass_with_defects").exists()
    assert CheckIn.objects.filter(subject_type="care_visit", kind="checkout").exists()
    assert FraudFlag.objects.filter(kind="outside_buffer", status="open").exists()
    assert FraudFlag.objects.filter(kind="outside_address_radius", status="cleared").exists()
    assert IssuedDocument.objects.exists()
    assert Evidence.objects.filter(provenance="app_captured").count() >= 6


def test_seed_is_idempotent(seeded):
    """Running every seed again changes nothing."""
    from core.seeding import run_all

    before = (Evidence.objects.count(), Submission.objects.count(), CheckIn.objects.count(),
              FraudFlag.objects.count())
    run_all()
    assert (Evidence.objects.count(), Submission.objects.count(), CheckIn.objects.count(),
            FraudFlag.objects.count()) == before
