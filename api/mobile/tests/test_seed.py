from evidence.models import Evidence, IssuedDocument
from mobile.models import CheckIn, FraudFlag, Submission


def test_seed_builds_every_state(seeded):
    """Seeds: field work in several states for every role, and demo evidence."""
    m = seeded["mobile"]
    assert Submission.objects.get(subject_id=m["milestone_a"]).status == "received"
    assert Submission.objects.get(subject_id=m["milestone_b"]).status == "held_for_review"
    assert Submission.objects.get(subject_id=m["inspection_a"]).outcome == "pass_with_defects"
    assert CheckIn.objects.filter(subject_id=m["visit_1"]).count() == 2
    assert FraudFlag.objects.filter(kind="outside_buffer", status="open").exists()
    assert FraudFlag.objects.filter(kind="outside_address_radius", status="cleared").exists()
    assert IssuedDocument.objects.exists()
    assert Evidence.objects.filter(provenance="app_captured").count() >= 6


def test_seed_is_idempotent(seeded):
    """Running every seed again changes nothing."""
    import importlib

    from django.conf import settings

    before = (Evidence.objects.count(), Submission.objects.count(), CheckIn.objects.count(),
              FraudFlag.objects.count())
    ctx = {"people": {}}
    for name in settings.TENMINA_MODULES:
        try:
            mod = importlib.import_module(f"{name}.seed")
        except ModuleNotFoundError:
            continue
        mod.run(ctx)
    assert (Evidence.objects.count(), Submission.objects.count(), CheckIn.objects.count(),
            FraudFlag.objects.count()) == before
