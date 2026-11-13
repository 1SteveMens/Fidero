"""FR-NTF-003: remind owners 2 working days before a due date and alert the
case manager when an item is overdue. Each reminder goes once.

Modules with due dates register a provider:

    from notifications import reminders

    @reminders.provider("case_task")
    def open_tasks(today):
        for t in Task.objects.filter(status__in=OPEN):
            yield reminders.DueItem(subject_type="case_task", subject_id=t.pk, title=t.title,
                                    due_on=t.due_at.date(), owner=t.assignee, manager=t.case.manager,
                                    country=t.case.country, case_ref=t.case.reference,
                                    link=f"/cases/{t.case_id}/tasks/{t.pk}")
"""
from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

REMIND_WORKING_DAYS = 2  # FR-NTF-003
_providers: dict = {}


@dataclass
class DueItem:
    subject_type: str
    subject_id: object
    title: str
    due_on: date
    owner: object = None
    manager: object = None
    country: object = None
    case_ref: str = ""
    link: str = ""


def provider(name):
    def deco(fn):
        _providers[name] = fn
        return fn

    return deco


def register(name, fn):
    _providers[name] = fn


def _once(item: DueItem, kind: str, recipient) -> bool:
    from .models import Reminder

    try:
        with transaction.atomic():
            Reminder.objects.create(subject_type=item.subject_type, subject_id=str(item.subject_id), kind=kind,
                                    due_on=item.due_on, recipient=recipient)
        return True
    except IntegrityError:
        return False


def run(today: date | None = None, items=None) -> dict:
    """The daily job (notifications.due_reminders). `items` lets a caller pass
    due items directly instead of the registered providers."""
    from countries.selectors import working_days_between

    from .services import notify

    today = today or timezone.localdate()
    if items is None:
        items = []
        for fn in _providers.values():
            items.extend(fn(today))
    sent = {"due_soon": 0, "overdue": 0}
    for it in items:
        if it.due_on < today:
            to = it.manager or it.owner
            if to is not None and _once(it, "overdue", to):
                notify(to, "task_overdue", channels=("in_app", "email"), category="task",
                       context={"task_title": it.title, "case_ref": it.case_ref,
                                "due_date": f"{it.due_on:%d %B %Y}",
                                "assignee_name": getattr(it.owner, "full_name", "") or "nobody"},
                       link=it.link, subject_type=it.subject_type, subject_id=str(it.subject_id),
                       country=it.country, needs_action=True)
                sent["overdue"] += 1
            continue
        country = it.country
        left = working_days_between(country, today, it.due_on) if country is not None else (it.due_on - today).days
        if left <= REMIND_WORKING_DAYS and it.owner is not None and _once(it, "due_soon", it.owner):
            notify(it.owner, "task_due_soon", channels="preferred", category="reminder",
                   context={"task_title": it.title, "case_ref": it.case_ref, "due_date": f"{it.due_on:%d %B %Y}"},
                   link=it.link, subject_type=it.subject_type, subject_id=str(it.subject_id), country=country)
            sent["due_soon"] += 1
    return sent
