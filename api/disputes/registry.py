"""What a dispute can be raised against, and who its parties are.

Built in: escrow (ESC), listing (LST), and project or milestone through the escrows that carry the project id.
BLD and PRJ can register a better resolver once they exist:

    from disputes import registry
    registry.register("milestone", resolve_milestone)

A resolver takes (subject_id, hints) and returns a Subject, or None if there is no such subject.
"""
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Subject:
    country: object
    label: str
    parties: list = field(default_factory=list)  # [(person or None, organisation or None, role)]
    escrows: list = field(default_factory=list)  # escrow.Escrow rows to freeze
    project_id: object = None
    milestone_id: object = None
    listing: object = None
    links: list = field(default_factory=list)  # [(subject_type, subject_id, prior_status)]


_RESOLVERS: dict[str, Callable] = {}


def register(subject_type: str, fn: Callable):
    _RESOLVERS[subject_type] = fn


def resolve(subject_type: str, subject_id, hints=None) -> Subject | None:
    fn = _RESOLVERS.get(subject_type)
    return fn(subject_id, hints or {}) if fn else None


def _escrow_parties(e):
    out = [(e.client, None, "buyer")]
    for p in e.parties.exclude(role__in=["tenmina", "buyer"]).select_related("person", "organisation"):
        if p.person_id or p.organisation_id:
            out.append((p.person, p.organisation, p.role))
    return out


def _instruction_links(e):
    from escrow.models import ReleaseInstruction

    return [("release_instruction", i.pk, i.status) for i in ReleaseInstruction.objects.filter(
        escrow=e, status__in=["awaiting_client", "pending_approval", "approved", "sent"])]


def _escrow(subject_id, hints):
    from escrow.models import Escrow

    e = Escrow.objects.filter(pk=subject_id).select_related("country", "client").first()
    if e is None:
        return None
    return Subject(country=e.country, label=f"Escrow {e.reference}", parties=_escrow_parties(e), escrows=[e],
                   project_id=e.project_id, links=[("escrow", e.pk, e.status), *_instruction_links(e)])


def _listing(subject_id, hints):
    from listings.models import Listing

    x = Listing.objects.filter(pk=subject_id).select_related("country", "organisation", "submitted_by").first()
    if x is None:
        return None
    role = "developer" if x.organisation and x.organisation.kind == "developer" else "seller"
    parties = [(None if x.organisation_id else x.submitted_by, x.organisation, role)]
    escrows, links = [], [("listing", x.pk, x.status)]
    for r in x.reservations.select_related("buyer", "escrow").order_by("-created_at"):
        parties.append((r.buyer, None, "buyer"))
        if r.escrow_id and r.escrow.status not in ("released", "cancelled"):
            escrows.append(r.escrow)
            links += [("escrow", r.escrow_id, r.escrow.status), *_instruction_links(r.escrow)]
    return Subject(country=x.country, label=f"Listing {x.reference}", parties=parties, escrows=escrows,
                   listing=x, links=links)


def _project(subject_id, hints):
    from escrow.models import Escrow

    escrows = list(Escrow.objects.filter(project_id=subject_id).exclude(status__in=["released", "cancelled"])
                   .select_related("country", "client"))
    if not escrows:
        return None
    parties, links = [], [("project", subject_id, "active")]
    for e in escrows:
        parties += _escrow_parties(e)
        links += [("escrow", e.pk, e.status), *_instruction_links(e)]
    return Subject(country=escrows[0].country, label=escrows[0].title or "Project", parties=parties,
                   escrows=[], project_id=subject_id, links=links)


def _milestone(subject_id, hints):
    """Until BLD registers its own resolver, a milestone dispute names its project (hints['project_id'])."""
    pid = hints.get("project_id")
    if not pid:
        return None
    s = _project(pid, hints)
    if s is None:
        return None
    s.milestone_id = subject_id
    s.label = f"Milestone of {s.label}"
    s.links.insert(0, ("milestone", subject_id, hints.get("milestone_status") or "unknown"))
    return s


register("escrow", _escrow)
register("listing", _listing)
register("project", _project)
register("milestone", _milestone)
