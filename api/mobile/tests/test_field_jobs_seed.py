"""The demo field roles have real work in Tenmina Field (FR-MOB-001): every job in the seeded inboxes is a real
row from BLD or CASE, opens through its own detail endpoint, and was assigned through the line's services."""
from datetime import timedelta

import pytest
from django.utils import timezone

from accounts.models import Person
from core import samples
from evidence.services import store
from mobile.devtools import FakePhone

from .conftest import APP

DETAIL = {"task": "/v1/tasks/{}", "milestone_inspection": "/v1/inspections/{}", "bld_project": "/v1/projects/{}"}


def _inbox(api, person):
    c = api(person)
    c.defaults.update(APP)
    r = c.get("/v1/mobile/inbox")
    assert r.status_code == 200, r.content
    return c, r.json()


@pytest.mark.parametrize("key", ["inspector", "surveyor", "lawyer", "qs"])
def test_each_field_role_has_a_job_that_opens(seeded, api, people, key):
    """FR-MOB-001: the inspector, the surveyor, the lawyer and the quantity surveyor each have at least one job,
    and each job's subject opens for them (200)."""
    c, items = _inbox(api, people[key])
    assert items, f"{key} has no field job"
    for it in items:
        assert it["subject_type"] in DETAIL, it["subject_type"]
        r = c.get(DETAIL[it["subject_type"]].format(it["subject_id"]))
        assert r.status_code == 200, (key, it["title"], r.content)


def test_jobs_come_from_the_line_services(seeded, people):
    """FR-CASE-003, FR-BLD-004, FR-BLD-002, RUL-20: who holds what, and why it is allowed."""
    from accounts.services import require_valid_licence
    from cases.models import Task
    from construction.models import Inspection, Project

    insp = Inspection.objects.get(inspector__person=people["inspector"], status="scheduled")
    assert insp.inspector.status == "active" and require_valid_licence(people["inspector"], "IN")
    assert Inspection.objects.filter(inspector__person=people["inspector"], status="recorded").exists()
    lw = Task.objects.filter(assignee=people["lawyer"], case__status="in_progress")
    assert {"consent_meeting", "land_title_check", "permit_check"} <= set(lw.values_list("step_key", flat=True))
    sv = Task.objects.get(assignee=people["surveyor"], case__status="in_progress")
    assert sv.step_key == "overlay_check" and sv.status == "open"
    wall = Project.objects.get(quantity_surveyor__person=people["qs"], status="setup")
    assert not wall.boqs.exists()


def test_a_waiting_step_says_what_it_waits_for_in_words(seeded, api, people):
    """FR-CASE-002, FR-MOB-001: the surveyor's step waits for the runner's site visit; the phone shows the step's
    title, not its key."""
    _, items = _inbox(api, people["surveyor"])
    job = next(it for it in items if it["subject_type"] == "task")
    assert job["accepts_submissions"] is False
    assert job["state_reason"] == "Opens after: Visit the plot and capture evidence."


def test_finished_jobs_keep_their_field_evidence(seeded, people):
    """FR-CASE-006, RUL-08: the lawyer's permit check was closed by a clean Tenmina Field submission; its photo is
    app-captured and signed. The inspector's recorded inspection has its defect photo."""
    from cases.models import Task
    from evidence.models import EvidenceLink
    from mobile.models import Submission

    permit = Task.objects.get(assignee=people["lawyer"], step_key="permit_check")
    assert permit.status == "done"
    sub = Submission.objects.get(subject_type="task", subject_id=permit.pk)
    assert sub.status == "received" and sub.person_id == people["lawyer"].pk
    link = EvidenceLink.objects.get(subject_type="task", subject_id=permit.pk, role="permit_copy")
    assert link.evidence.provenance == "app_captured" and link.evidence.sha256
    rec = Submission.objects.get(subject_type="milestone_inspection", person=people["inspector"])
    assert rec.outcome == "pass_with_defects" and rec.items.filter(kind="defect_photo").exists()


def test_only_site_visits_are_checked_against_the_plot(seeded, api, people):
    """FR-MOB-004: a step done at an office or a registry carries no plot position, so a lawyer's photo of a
    permit is not flagged for being away from the plot. The runner's site visit keeps it."""
    _, lawyer = _inbox(api, people["lawyer"])
    assert lawyer and all(it["point"] is None for it in lawyer)
    _, runner = _inbox(api, people["runner"])
    visit = next(it for it in runner if it["subject_type"] == "task")
    assert visit["point"] is not None


def test_quantity_surveyor_measures_then_uploads_the_bill(seeded, api, people):
    """FR-BLD-002: the site photos close the job for more photos; the bill of quantities takes it off the list."""
    from construction import projects
    from construction.models import Project
    from mobile.seed import _item

    qs = people["qs"]
    c, items = _inbox(api, qs)
    job = next(it for it in items if it["subject_type"] == "bld_project")
    assert job["kind"] == "boq_visit" and job["accepts_submissions"] is True
    phone = FakePhone(qs, platform="android")
    phone.register()
    at = {}
    if job["boundary"]:
        at = {"lat": job["boundary"][0][0], "lng": job["boundary"][0][1]}
    elif job["point"]:
        at = {"lat": job["point"]["lat"], "lng": job["point"]["lng"]}
    sent = []
    for key in ("site_photo", "measurement_photo"):
        m = _item(phone, f"qs-{key}", "bld_project", job["subject_id"],
                  samples.photo("land", f"qs-test-{key}", caption=key), requirement_key=key, **at,
                  captured_at=timezone.now() - timedelta(minutes=5))
        sent.append({"requirement_key": key, "evidence_id": str(m.evidence_id)})
    r = c.post("/v1/mobile/submissions", {"client_submission_id": "qs-boq-visit-1", "subject_type": "bld_project",
                                          "subject_id": job["subject_id"], "items": sent}, format="json")
    assert r.status_code in (201, 202) and r.json()["open_flags"] == 0, r.content
    _, items = _inbox(api, qs)
    job = next(it for it in items if it["subject_type"] == "bld_project")
    assert job["accepts_submissions"] is False and "bill of quantities" in job["state_reason"]
    p = Project.objects.get(pk=job["subject_id"])
    bill = store(data=samples.pdf("quote", "qs-test-wall", title="Bill of quantities"), country=p.country, uploaded_by=qs,
                 content_type="application/pdf", original_name="boq-wall.pdf")
    projects.submit_boq(p, qs, items=[{"description": "Block wall and gate", "amount": "45000.00"}],
                        evidence_ids=[bill.pk])
    _, items = _inbox(api, qs)
    assert not [it for it in items if it["subject_type"] == "bld_project" and it["subject_id"] == str(p.pk)]


def test_pending_agent_and_pending_inspector_get_no_work(seeded, api, people):
    """FR-TSK-003, RUL-20: Yaa's errand agent vetting is still pending, so she is on no panel and has no job; an
    inspector whose licence is not verified has none either. Their inboxes are empty, not broken."""
    from accounts.models import Vetting
    from errands.models import Agent

    yaa = people["agent"]
    assert Vetting.objects.get(person=yaa, kind="errand_agent").status != "vetted"
    assert not Agent.objects.filter(person=yaa).exists()
    assert _inbox(api, yaa)[1] == []
    assert _inbox(api, Person.objects.get(email="new.inspector@example.com"))[1] == []
