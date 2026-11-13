import uuid

import pytest

from mobile import services
from mobile.devtools import FakePhone

APP = {"HTTP_TENMINA_APP": "field/android/1.0.0"}
PLOT = [[5.6502, -0.1805], [5.6502, -0.1797], [5.6496, -0.1797], [5.6496, -0.1805]]
EVIDENCE = [{"key": "front", "label": "Front", "media": "photo", "required": True},
            {"key": "walk", "label": "Walk", "media": "video", "required": True}]


@pytest.fixture(autouse=True)
def _without_seeded_assignments(request):
    """Tests build their own field work; the seeded assignments are set aside."""
    if request.module.__name__.endswith("test_seed"):
        return
    if "seeded" in request.fixturenames or "people" in request.fixturenames:
        from django.utils import timezone

        from mobile.models import Assignment

        request.getfixturevalue("seeded")
        Assignment.objects.filter(status="active").update(status="revoked", revoked_at=timezone.now())


@pytest.fixture
def phone(people):
    def make(key="contractor", **kw):
        p = FakePhone(people[key], **kw)
        p.register()
        return p

    return make


@pytest.fixture
def milestone(gh, people):
    """A milestone assigned to the contractor, with a plot boundary and two required items."""

    def make(person="contractor", project="proj-1", **kw):
        sid = uuid.uuid4()
        fields = dict(subject_type="milestone", kind="milestone", boundary=PLOT, buffer_m=50,
                      required_evidence=EVIDENCE, project_key=project)
        fields.update(kw)
        services.assign(person=people[person], subject_id=sid, title="Foundation", country=gh, by=people["cm"],
                        **fields)
        return sid

    return make


@pytest.fixture
def visit(gh, people):
    def make(person="carer", subject_type="care_visit", **kw):
        sid = uuid.uuid4()
        fields = dict(subject_type=subject_type, kind=subject_type, point_lat="5.551500", point_lng="-0.262800",
                      radius_m=100, min_visit_minutes=30)
        fields.update(kw)
        services.assign(person=people[person], subject_id=sid, title="Visit", country=gh, by=people["cm"], **fields)
        return sid

    return make


@pytest.fixture
def field_api(api):
    def make(person):
        c = api(person)
        c.defaults.update(APP)
        return c

    return make
