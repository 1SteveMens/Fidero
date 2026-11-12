"""State machines (document 02, 4.1 rule 5; 6.3 core_allowed_transition).

Each module registers its entities once, in models.py or states.py:

    from core import state
    CASE = state.register("case", "case_case", {
        "new": {"assigned", "cancelled"},
        "assigned": {"in_progress"},
        ...
    })

and changes status only through state.transition(), which checks the
transition, saves, writes the audit entry and publishes the event in the
same transaction. A database trigger rejects any other status change.
"""
from dataclasses import dataclass

from django.db import transaction

from .errors import StateConflict

REGISTRY: dict[str, "Machine"] = {}


@dataclass
class Machine:
    entity: str
    table: str
    transitions: dict
    field: str = "status"

    def allowed(self, frm, to):
        return to in self.transitions.get(frm, set())

    def targets(self, frm):
        return sorted(self.transitions.get(frm, set()))


def register(entity: str, table: str, transitions: dict, field: str = "status") -> Machine:
    m = Machine(entity, table, {k: set(v) for k, v in transitions.items()}, field)
    REGISTRY[entity] = m
    return m


def transition(obj, entity: str, to: str, *, actor=None, event: str | None = None, payload=None,
               reason: str = "", extra_fields=None):
    """Move obj to status `to`. Publishes `event` (default '<entity>.status_changed')."""
    from audit.services import record  # lazy: core depends on no module at import time

    m = REGISTRY[entity]
    frm = getattr(obj, m.field)
    if frm == to:
        return obj
    if not m.allowed(frm, to):
        raise StateConflict(
            f"A {entity.replace('_', ' ')} cannot go from '{frm}' to '{to}'.",
            extra={"from_status": frm, "to_status": to, "allowed": m.targets(frm)},
        )
    with transaction.atomic():
        setattr(obj, m.field, to)
        fields = [m.field, *(extra_fields or [])]
        obj.save(update_fields=fields)
        data = {"from": frm, "to": to, **(payload or {})}
        if reason:
            data["reason"] = reason
        record(actor=actor, action=f"{entity}.{to}", entity=entity, entity_id=obj.pk, data=data,
               country=getattr(obj, "country", None) if hasattr(obj, "country_id") else None)
        from .events import publish

        publish(event or f"{entity}.status_changed", obj.pk, {"entity": entity, "id": obj.pk, **data})
    return obj
