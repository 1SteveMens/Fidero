"""TSK Paperwork and errands: read-only queries other modules may use.

Clients see their own errands; the assigned agent sees their errands (and only the documents a step needs);
a representative the client named for an errand sees it; staff see their countries. Everyone else gets 404.
"""
from django.db.models import Q

from accounts.selectors import representative_subject_ids, scope_to_staff_countries
from core.permissions import STAFF_ROLES, has_role

from .models import Agent, Errand, ErrandDocument


def visible_errands(person):
    qs = Errand.objects.select_related("country", "client", "agent__person", "agency_payee", "for_family_member")
    if not person.is_authenticated:
        return qs.none()
    if has_role(person, *STAFF_ROLES):
        return scope_to_staff_countries(qs, person)
    reps = [str(x) for x in representative_subject_ids(person, "errand")]
    return qs.filter(Q(client=person) | Q(agent__person=person) | Q(pk__in=reps)).distinct()


def agent_may_open(person, doc: ErrandDocument) -> bool:
    """TC-TSK-002-03: the agent sees only the documents the open steps need."""
    e = doc.errand
    if e.agent is None or e.agent.person_id != person.pk or doc.status == "deleted":
        return False
    if e.status not in ("assigned", "in_progress", "result_uploaded"):
        return False
    return e.steps.exclude(status="done").filter(needs_documents__contains=[doc.key]).exists()


def agent_panel(person, country=None):
    qs = Agent.objects.select_related("person", "vetting", "agency_org", "country")
    if not has_role(person, *STAFF_ROLES):
        return qs.none()
    qs = scope_to_staff_countries(qs, person)
    return qs.filter(country=country) if country else qs


def errands_for_agent(person):
    return Errand.objects.filter(agent__person=person, agent__status="active",
                                 status__in=["assigned", "in_progress", "result_uploaded", "completed"])
