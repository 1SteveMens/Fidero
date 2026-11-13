"""Who may see or add evidence for a subject.

Evidence belongs to subjects owned by other modules (cases, milestones,
visits, invoices). Each module registers a policy for its subject types:

    from evidence import access
    access.register("case", can_view=lambda user, sid: ..., can_attach=lambda user, sid: ...,
                    country=lambda sid: case.country, owner=lambda sid: ("case", sid))

Without a policy, only Tenmina staff in the evidence's country may view or
attach, and an uploader may always view what they uploaded.
"""
from dataclasses import dataclass
from typing import Callable

from core.permissions import STAFF_ROLES, has_role


@dataclass
class Policy:
    can_view: Callable | None = None
    can_attach: Callable | None = None
    country: Callable | None = None
    owner: Callable | None = None  # subject_id -> (owner_type, owner_id) of the case, project or listing


_POLICIES: dict[str, Policy] = {}
_HOLDS: list[Callable] = []


def register(subject_type: str, *, can_view=None, can_attach=None, country=None, owner=None):
    _POLICIES[subject_type] = Policy(can_view, can_attach, country, owner)


def unregister(subject_type: str):
    _POLICIES.pop(subject_type, None)


def policy(subject_type: str) -> Policy | None:
    return _POLICIES.get(subject_type)


def register_hold(fn: Callable):
    """fn(evidence) -> bool. True keeps the evidence past its retention date (legal hold, DPR)."""
    if fn not in _HOLDS:
        _HOLDS.append(fn)


def on_hold(evidence) -> bool:
    return any(fn(evidence) for fn in _HOLDS)


def is_staff_in(user, country) -> bool:
    return has_role(user, *STAFF_ROLES, country=country)


def can_view_subject(user, subject_type, subject_id, country=None) -> bool:
    if country is not None and is_staff_in(user, country):
        return True
    p = _POLICIES.get(subject_type)
    if p and p.can_view:
        try:
            return bool(p.can_view(user, subject_id))
        except Exception:  # noqa: BLE001 - a missing subject is simply not visible
            return False
    return False


def can_attach(user, subject_type, subject_id, country=None) -> bool:
    if country is not None and is_staff_in(user, country):
        return True
    p = _POLICIES.get(subject_type)
    if p and p.can_attach:
        try:
            return bool(p.can_attach(user, subject_id))
        except Exception:  # noqa: BLE001
            return False
    return False


def subject_country(subject_type, subject_id):
    p = _POLICIES.get(subject_type)
    if p and p.country:
        try:
            return p.country(subject_id)
        except Exception:  # noqa: BLE001
            return None
    return None


def subject_owner(subject_type, subject_id):
    p = _POLICIES.get(subject_type)
    if p and p.owner:
        try:
            return p.owner(subject_id)
        except Exception:  # noqa: BLE001
            return None
    return None


def can_view(user, evidence) -> bool:
    """Staff in the country, the uploader, or anyone allowed to see a linked subject."""
    if not user or not user.is_authenticated:
        return False
    if is_staff_in(user, evidence.country):
        return True
    if evidence.uploaded_by_id == user.pk:
        return True
    for link in evidence.links.all():
        if can_view_subject(user, link.subject_type, link.subject_id):
            return True
    return False
