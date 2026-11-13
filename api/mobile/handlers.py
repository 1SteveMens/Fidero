"""MOB event subscribers (02 section 4.2): new or changed field work reaches the worker's phone.

Payload keys are read defensively because the producing modules name their
assignee differently; each handler is idempotent (a notification per event).
"""
from core.events import subscribe

from . import inbox  # noqa: F401 - registers the built-in inbox provider

ASSIGNEE_KEYS = ("assignee_id", "person_id", "inspector_id", "carer_person_id", "agent_person_id", "carer_id",
                 "agent_id", "contractor_person_id", "runner_person_id")
CLOSED_MILESTONE_STATES = {"returned", "frozen", "disputed", "cancelled", "submitted", "inspected", "approved",
                           "released", "paid"}

TITLES = {
    "task.assigned": "a new case task",
    "visit.scheduled": "a new care visit",
    "errand.assigned": "a new errand step",
    "inspection.scheduled": "a new inspection",
}


def _assignee(payload):
    from accounts.models import Person

    for k in ASSIGNEE_KEYS:
        v = payload.get(k)
        if v:
            p = Person.objects.filter(pk=v).first()
            if p is not None:
                return p
    return None


@subscribe("task.assigned", "visit.scheduled", "errand.assigned", "inspection.scheduled")
def tell_field_worker(ev):
    from notifications.services import notify

    from .services import is_field_worker

    person = _assignee(ev.payload)
    if person is None or not is_field_worker(person):
        return
    what = TITLES.get(ev.topic, "new work")
    notify(person, "field_new_work", subject="New work in Tenmina Field",
           body=f"You have {what}. Open Tenmina Field to see it.", channels=("in_app", "push"))


@subscribe("milestone.status_changed")
def milestone_changed(ev):
    """8.6: when a milestone is returned, frozen or moves on, manual assignments stop taking submissions;
    when it reopens (in_progress) they take them again. A passed milestone sets previous_pass_at for the next."""
    from .services import set_submission_state

    p = ev.payload
    mid, to = p.get("id") or p.get("milestone_id"), p.get("to")
    if not mid or not to:
        return
    if to in ("in_progress", "open", "returned_for_rework"):
        set_submission_state("milestone", mid, accepts=True)
    elif to in CLOSED_MILESTONE_STATES:
        set_submission_state("milestone", mid, accepts=False,
                             reason=f"The milestone is {to.replace('_', ' ')}. Your saved evidence stays linked.")
