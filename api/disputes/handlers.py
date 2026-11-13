"""DSP event subscribers and registrations.

Consumes: approval.approved and approval.rejected for subject_type dispute_decision.
Registers: client home items, evidence access for dispute, data protection open matters and exporter.
"""
from core.events import subscribe


@subscribe("approval.approved", "approval.rejected")
def on_approval(ev):
    p = ev.payload or {}
    if p.get("subject_type") != "dispute_decision":
        return
    from . import services

    services.on_approval(p.get("subject_id"), approved=ev.topic == "approval.approved")


def _home(person):
    from accounts.home import item

    from . import services
    from .models import OPEN_STATUSES

    out = []
    for d in services.visible(person).filter(status__in=OPEN_STATUSES).exclude(opened_by_staff=True,
                                                                                opened_by=person):
        party = services.party_of(person, d)
        if party is None:
            continue
        needs = (d.status == "awaiting_response" and party.side == "respondent" and party.responded_at is None) or \
            (d.status == "evidence" and party.evidence_complete_at is None)
        text = {"awaiting_response": f"Responses are due by {d.response_due:%d %B %Y}." if d.response_due else "",
                "evidence": f"Evidence is due by {d.evidence_due:%d %B %Y}." if d.evidence_due else "",
                "decision": "Tenmina is deciding.", "referred": f"With the mediator {d.mediator}.",
                "open": "Opened."}.get(d.status, "")
        out.append(item(kind="dispute", id=d.pk, title=f"Dispute {d.reference}: {d.subject_label}", status=d.status,
                        status_text=text, needs_action=needs, link=f"/disputes/{d.pk}", line="disputes",
                        next_date=d.response_due if d.status == "awaiting_response" else d.evidence_due
                        if d.status == "evidence" else d.decision_due))
    return out


def _register():
    from accounts import home
    from dataprotection import registry as dpr
    from evidence import access

    from . import services
    from .models import Dispute

    def _d(sid):
        return Dispute.objects.filter(pk=sid).first()

    access.register("dispute",
                    can_view=lambda u, sid: bool(_d(sid)) and services.can_view(u, _d(sid)),
                    can_attach=lambda u, sid: bool(_d(sid)) and services.party_of(u, _d(sid)) is not None
                    and _d(sid).status in services.STATEMENT_STATES,
                    country=lambda sid: getattr(_d(sid), "country", None),
                    owner=lambda sid: ("dispute", sid))
    home.register(_home)

    @dpr.open_matters
    def open_disputes(person):
        from .models import OPEN_STATUSES

        return [{"kind": "dispute", "id": str(d.pk), "title": f"Dispute {d.reference}",
                 "reason": "A dispute you are a party to is open."}
                for d in services.visible(person).filter(status__in=OPEN_STATUSES)
                if services.party_of(person, d) is not None or d.opened_by_id == person.pk]

    @dpr.exporter("disputes")
    def export_disputes(person):
        from .models import Statement

        return {"statements": [{"dispute": s.dispute.reference, "kind": s.kind, "text": s.text,
                                "created_at": s.created_at.isoformat()}
                               for s in Statement.objects.filter(author=person).select_related("dispute")]}


_register()
