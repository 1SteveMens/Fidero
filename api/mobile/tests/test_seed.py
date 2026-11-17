import pytest
from django.apps import apps

from evidence.models import Evidence, EvidenceLink, IssuedDocument
from mobile.models import Assignment, CheckIn, FraudFlag, SignedManifest, Submission

# Where each Tenmina Field subject lives. A seeded record naming any other subject type fails the test below, so a
# new line module that seeds field work adds its subject here.
SUBJECTS = {
    "milestone": "construction.Milestone",
    "milestone_inspection": "construction.Inspection",
    "care_visit": "care.Visit",
    "errand": "errands.Errand",
    "errand_step": "errands.ErrandStep",
    "task": "cases.Task",
    "fee_runner_task": "fees.RunnerTask",
    "property_inspection": "propertymgmt.Inspection",
}


def test_seed_builds_every_state(seeded):
    """Seeds: field work in several states on real subjects, and demo evidence."""
    inspection = Submission.objects.get(subject_type="milestone_inspection")
    assert inspection.outcome == "pass_with_defects"
    assert Submission.objects.filter(subject_type="milestone", status="received").count() >= 2
    held = Submission.objects.get(subject_type="milestone", status="held_for_review")
    assert FraudFlag.objects.filter(kind="before_previous_pass", status="open", subject_id=held.subject_id).exists()
    assert CheckIn.objects.filter(subject_type="care_visit", kind="checkout").count() >= 2
    assert FraudFlag.objects.filter(kind="outside_address_radius", status="cleared").exists()
    assert IssuedDocument.objects.exists()
    assert Evidence.objects.filter(provenance="app_captured").count() >= 6


@pytest.mark.parametrize("model", [Assignment, CheckIn, SignedManifest, Submission, FraudFlag])
def test_seeded_field_records_name_real_subjects(seeded, model):
    """Every assignment, capture, check-in, submission and flag the seeds make points at an object that exists,
    so the field inbox and the portal's /work pages never open on 'Not found'."""
    missing = []
    for st, sid in model.objects.exclude(subject_id=None).values_list("subject_type", "subject_id").distinct():
        assert st in SUBJECTS, f"{model.__name__}: unknown subject type {st}"
        if not apps.get_model(SUBJECTS[st]).objects.filter(pk=sid).exists():
            missing.append((st, str(sid)))
    assert not missing, f"{model.__name__} names subjects that do not exist: {missing}"


def test_seeded_evidence_links_to_field_subjects_resolve(seeded):
    missing = [(st, str(sid)) for st, sid in EvidenceLink.objects.filter(subject_type__in=SUBJECTS)
               .values_list("subject_type", "subject_id").distinct()
               if not apps.get_model(SUBJECTS[st]).objects.filter(pk=sid).exists()]
    assert not missing, missing


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
