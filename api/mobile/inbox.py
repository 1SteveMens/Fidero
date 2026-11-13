"""The field worker's inbox: every assigned milestone, inspection, case task, care
visit and errand step, from every module (FR-MOB-001, 8.5, 8.8).

Line modules register a provider once, like a home feed:

    from mobile import inbox

    @inbox.register
    def my_visits(person):
        for v in Visit.objects.filter(carer__person=person, ...):
            yield inbox.InboxItem(subject_type="care_visit", subject_id=v.pk, title=..., kind="care_visit",
                                  country=v.country, point=(lat, lng), radius_m=100, ...)

What a provider returns is what the device sees: only assigned work, and only
what the worker needs (NFR-PRIV-02). The same list decides whether a capture
is assigned, which evidence a submission needs and where the site is.
"""
import logging
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class InboxItem:
    subject_type: str
    subject_id: str
    title: str
    kind: str = "task"
    country: object = None  # countries.Country
    status: str = "active"
    address: str = ""
    point: tuple | None = None  # (lat, lng) of the registered address or plot centre
    radius_m: int | None = None  # check-in radius
    boundary: list = field(default_factory=list)  # [[lat, lng], ...] plot boundary
    buffer_m: int | None = None  # plot buffer for captures
    required_evidence: list = field(default_factory=list)  # [{key, label, media, required}]
    checklist: list = field(default_factory=list)  # [{key, label}] for inspections
    plan_items: list = field(default_factory=list)  # care plan items: [{key, label, needs}]
    previous_pass_at: datetime | None = None  # when the previous milestone passed
    project_key: str = ""  # duplicate-hash checks compare across projects
    accepts_submissions: bool = True
    state_reason: str = ""  # why submissions are closed (returned, frozen by dispute)
    due_at: datetime | None = None
    min_visit_minutes: int | None = None
    details: dict = field(default_factory=dict)
    updated_at: datetime | None = None
    source: str = ""

    @property
    def key(self) -> str:
        return f"{self.subject_type}:{self.subject_id}"

    def as_dict(self) -> dict:
        d = {f.name: getattr(self, f.name) for f in fields(self)}
        d["subject_id"] = str(self.subject_id)
        d["country"] = getattr(self.country, "code", self.country)
        d["point"] = {"lat": float(self.point[0]), "lng": float(self.point[1])} if self.point else None
        return d


_PROVIDERS: list[Callable] = []


def register(fn: Callable) -> Callable:
    """fn(person) -> iterable of InboxItem (or dicts with the same keys)."""
    if fn not in _PROVIDERS:
        _PROVIDERS.append(fn)
    return fn


def unregister(fn: Callable):
    if fn in _PROVIDERS:
        _PROVIDERS.remove(fn)


def items_for(person) -> list[InboxItem]:
    seen, out = set(), []
    for fn in list(_PROVIDERS):
        try:
            produced = list(fn(person) or [])
        except Exception:  # noqa: BLE001 - one broken provider never empties the inbox
            log.exception("inbox provider %s failed", getattr(fn, "__name__", fn))
            continue
        for it in produced:
            if isinstance(it, dict):
                it = InboxItem(**it)
            it.subject_id = str(it.subject_id)
            it.source = it.source or getattr(fn, "__module__", "")
            if it.key in seen or it.status != "active":
                continue
            seen.add(it.key)
            out.append(it)
    return out


def find(person, subject_type: str, subject_id) -> InboxItem | None:
    sid = str(subject_id)
    for it in items_for(person):
        if it.subject_type == subject_type and it.subject_id == sid:
            return it
    return None


@register
def manual_assignments(person):
    """Built-in provider: assignments staff made in mob_assignment."""
    from .models import Assignment

    for a in Assignment.objects.filter(person=person, status="active").select_related("country"):
        yield InboxItem(
            subject_type=a.subject_type, subject_id=str(a.subject_id), title=a.title, kind=a.kind,
            country=a.country, address=a.address,
            point=(a.point_lat, a.point_lng) if a.point_lat is not None and a.point_lng is not None else None,
            radius_m=a.radius_m, boundary=a.boundary or [], buffer_m=a.buffer_m,
            required_evidence=a.required_evidence or [], checklist=a.checklist or [], plan_items=a.plan_items or [],
            previous_pass_at=a.previous_pass_at, project_key=a.project_key,
            accepts_submissions=a.accepts_submissions, state_reason=a.state_reason, due_at=a.due_at,
            min_visit_minutes=a.min_visit_minutes, details=a.details or {}, updated_at=a.updated_at,
            source="mobile.assignment")
