"""Chase the owner of a late task (back office W-13; FR-CASE-005): case staff only, the assignee is told, recorded
on the task and in the audit log, at most once a day per task."""
from datetime import timedelta

from django.utils import timezone

from audit.models import AuditEvent
from cases.models import Task
from cases.tests.helpers import accepted_case, task
from core.models import OutboxEvent
from notifications.models import Message as Notice


def _late_legal_task(api, people, gh):
    case = accepted_case(api, people, gh)
    legal = task(case, "legal_review")
    r = api(people["cm"]).patch(f"/v1/tasks/{legal.pk}", {"assignee_id": str(people["lawyer"].pk)}, format="json")
    assert r.status_code == 200
    Task.objects.filter(pk=legal.pk).update(due_at=timezone.now() - timedelta(days=3))
    return Task.objects.get(pk=legal.pk)


def test_chase_late_task_tells_assignee_and_is_audited(seeded, api, people, gh):
    """Chase the owner: the assignee gets a reminder; the chase is on the task, in the audit log and published."""
    t = _late_legal_task(api, people, gh)
    r = api(people["cm"]).post(f"/v1/tasks/{t.pk}/chase", {"note": "The client is waiting."}, format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["chase_count"] == 1 and body["last_chased_at"]
    t.refresh_from_db()
    assert t.last_chased_by_id == people["cm"].pk
    n = Notice.objects.filter(person=people["lawyer"], template="task_chased", subject_id=str(t.pk)).first()
    assert n is not None and "3 days ago" in n.body and "The client is waiting." in n.body
    a = AuditEvent.objects.get(action="task.chased", entity_id=str(t.pk))
    assert a.actor_id == people["cm"].pk and a.data["to"] == [str(people["lawyer"].pk)]
    assert OutboxEvent.objects.filter(topic="task.chased", aggregate_id=t.pk).exists()


def test_chase_at_most_once_a_day(seeded, api, people, gh):
    """At most one chase a day per task: a second chase the same day is refused (429) and nobody is told twice;
    after a day it is allowed again."""
    t = _late_legal_task(api, people, gh)
    cm = api(people["cm"])
    assert cm.post(f"/v1/tasks/{t.pk}/chase", {}, format="json").status_code == 200
    r = api(people["reviewer"]).post(f"/v1/tasks/{t.pk}/chase", {}, format="json")
    assert r.status_code == 429 and r.json()["code"] == "chased-recently" and r.json()["next_chase_at"]
    sent = Notice.objects.filter(person=people["lawyer"], template="task_chased", subject_id=str(t.pk))
    assert sent.values("group_id").distinct().count() == 1  # one reminder (one message per channel)
    assert AuditEvent.objects.filter(action="task.chased", entity_id=str(t.pk)).count() == 1
    Task.objects.filter(pk=t.pk).update(last_chased_at=timezone.now() - timedelta(days=1, minutes=1))
    r = cm.post(f"/v1/tasks/{t.pk}/chase", {}, format="json")
    assert r.status_code == 200 and r.json()["chase_count"] == 2


def test_chase_refusals(seeded, api, people, gh):
    """Only case staff chase; only a late, open, assigned task can be chased."""
    t = _late_legal_task(api, people, gh)
    assert api(people["lawyer"]).post(f"/v1/tasks/{t.pk}/chase", {}, format="json").status_code == 403
    assert api(people["client"]).post(f"/v1/tasks/{t.pk}/chase", {}, format="json").status_code == 404
    Task.objects.filter(pk=t.pk).update(due_at=timezone.now() + timedelta(days=2))
    r = api(people["cm"]).post(f"/v1/tasks/{t.pk}/chase", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "task-not-late"
    other = task(t.case, "survey") if t.case.tasks.filter(step_key="survey").exists() else \
        t.case.tasks.filter(assignee__isnull=True).exclude(pk=t.pk).first()
    Task.objects.filter(pk=other.pk).update(due_at=timezone.now() - timedelta(days=1), assignee=None)
    r = api(people["cm"]).post(f"/v1/tasks/{other.pk}/chase", {}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "task-unassigned"
    assert not AuditEvent.objects.filter(action="task.chased", entity_id=str(t.pk)).exists()
