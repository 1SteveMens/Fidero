"""TSK event subscribers and registry hooks. Idempotent: each acts only on objects still waiting."""
from django.utils import timezone

from accounts import home
from core.events import subscribe
from dataprotection import registry as dpr
from escrow import registry as esc_registry
from evidence import access
from mobile import inbox

from . import services


@subscribe("order.paid")
def on_order_paid(ev):
    services.on_order_paid(ev.payload)


@subscribe("held_funds.deposit_confirmed")
def on_deposit(ev):
    services.on_deposit(ev.payload)


@subscribe("release.confirmed", "release.withdrawn", "release.rejected", "release.rejected_by_bank")
def on_release(ev):
    services.on_release(ev.payload, ev.topic)


@subscribe("checkin.recorded")
def on_checkin(ev):
    services.on_checkin(ev.payload)


@subscribe("vetting.expired", "vetting.revoked")
def on_vetting_lapsed(ev):
    services.on_vetting_lapsed(ev.payload)


@subscribe("family_confirmation.confirmed")
def on_family_confirmed(ev):
    services.on_family_confirmed(ev.payload)


# --------------------------------------------------------------------------- escrow: RUL-22, RUL-23

def step_payable(instruction) -> list[dict]:
    from .models import ErrandStep

    step = ErrandStep.objects.filter(pk=instruction.subject_id).select_related("errand__agent").first()
    if step is None:
        return [{"rule": "RUL-23", "code": "visit-not-confirmed", "message": "There is no such errand step."}]
    return services.step_payable_blockers(step, payee=instruction.payee, amount=instruction.amount)


esc_registry.register_subject_check("errand_step", step_payable)


def _step_label(subject_id):
    from .models import ErrandStep

    s = ErrandStep.objects.filter(pk=subject_id).first()
    return services.step_label(s) if s else ""


esc_registry.subject_label("errand_step", _step_label)


# --------------------------------------------------------------------------- field inbox (FR-MOB-001)

@inbox.register
def errand_work(person):
    """The agent's open steps, and the errand itself once its steps are done (result and handover photos)."""
    from .models import Errand

    for e in Errand.objects.filter(agent__person=person, agent__status="active",
                                   status__in=["assigned", "in_progress", "result_uploaded", "completed"]
                                   ).select_related("country"):
        office = e.item.get("office") or {}
        point = (office["lat"], office["lng"]) if office.get("lat") is not None and office.get("lng") is not None \
            else None
        steps = list(e.steps.all())
        if e.status in ("assigned", "in_progress"):
            for s in steps:
                if s.status == "done":
                    continue
                yield inbox.InboxItem(
                    subject_type="errand_step", subject_id=s.pk, kind="errand_step", country=e.country,
                    title=f"{e.item.get('name')}: step {s.seq}", address=office.get("address") or e.item.get(
                        "agency", ""), point=point, radius_m=200 if point else None,
                    required_evidence=[{"key": "receipt" if s.official_fee_amount > 0 else "acknowledgement",
                                        "label": "Receipt" if s.official_fee_amount > 0 else
                                        "Receipt or acknowledgement", "media": "photo", "required": True}],
                    project_key=f"errand:{e.pk}", due_at=None,
                    details={"errand_id": str(e.pk), "reference": e.reference, "seq": s.seq,
                             "description": s.description, "status": s.status,
                             "official_fee": {"amount": f"{s.official_fee_amount:.2f}",
                                              "currency": s.official_fee_currency},
                             "documents": s.needs_documents},
                    updated_at=s.updated_at)
        all_done = steps and all(s.status == "done" for s in steps)
        if (e.status in ("assigned", "in_progress") and all_done) or e.status == "completed":
            yield inbox.InboxItem(
                subject_type="errand", subject_id=e.pk, kind="errand", country=e.country,
                title=f"{e.item.get('name')}: " + ("hand over" if e.status == "completed" else "upload the result"),
                address=office.get("address", ""), point=point, project_key=f"errand:{e.pk}",
                required_evidence=[{"key": "handover" if e.status == "completed" else "result",
                                    "label": "Signature or photo" if e.status == "completed" else
                                    "The resulting document", "media": "photo", "required": True}],
                details={"errand_id": str(e.pk), "reference": e.reference, "status": e.status},
                updated_at=e.updated_at)


# --------------------------------------------------------------------------- client home

@home.register
def errand_home(person):
    from .models import Errand

    out = []
    for e in Errand.objects.filter(client=person).exclude(status__in=["handed_over", "cancelled"]):
        needs = (e.status in ("ordered", "documents_pending") and (
            not e.submitted_at or e.documents.filter(status="rejected").exists() or e.fee_paid_at is None)) \
            or services._needs_agency_approval(e)
        out.append(home.item(kind="errand", id=e.pk, title=e.item.get("name") or e.catalogue_key, status=e.status,
                             status_text=services.status_text(e), next_date=e.due_on, needs_action=needs,
                             link=f"/errands/{e.pk}", family_member_id=e.for_family_member_id, line="errands"))
    return out


# --------------------------------------------------------------------------- evidence access

def _doc(sid):
    from .models import ErrandDocument

    return ErrandDocument.objects.select_related("errand__agent").get(pk=sid)


def _can_view_doc(user, sid):
    from .selectors import agent_may_open

    d = _doc(sid)
    if d.status == "deleted":
        return False
    return d.errand.client_id == user.pk or agent_may_open(user, d)


access.register("errand_document", can_view=_can_view_doc,
                can_attach=lambda user, sid: _doc(sid).errand.client_id == user.pk,
                country=lambda sid: _doc(sid).errand.country, owner=lambda sid: ("errand", _doc(sid).errand_id))


def _errand(sid):
    from .models import Errand

    return Errand.objects.select_related("agent").get(pk=sid)


def _can_view_errand(user, sid):
    from .selectors import visible_errands

    return visible_errands(user).filter(pk=sid).exists()


def _agent_can_attach(user, e):
    return e.agent is not None and e.agent.person_id == user.pk and e.status in (
        "assigned", "in_progress", "result_uploaded", "completed")


access.register("errand", can_view=_can_view_errand, can_attach=lambda user, sid: _agent_can_attach(user, _errand(sid)),
                country=lambda sid: _errand(sid).country, owner=lambda sid: ("errand", sid))


def _step(sid):
    from .models import ErrandStep

    return ErrandStep.objects.select_related("errand__agent").get(pk=sid)


access.register("errand_step", can_view=lambda user, sid: _can_view_errand(user, _step(sid).errand_id),
                can_attach=lambda user, sid: _agent_can_attach(user, _step(sid).errand),
                country=lambda sid: _step(sid).errand.country, owner=lambda sid: ("errand", _step(sid).errand_id))


# --------------------------------------------------------------------------- owner checks, data protection

def _owns(person, sid):
    from .models import Errand

    return Errand.objects.filter(pk=sid, client=person).exists()


def _register_owner_check():
    from accounts.services import register_owner_check

    register_owner_check("errand", _owns)


_register_owner_check()


@dpr.open_matters
def errand_open_matters(person):
    from .models import ErrandStep

    return [{"kind": "errand_fee", "id": str(s.pk), "title": services.step_label(s),
             "reason": "An official fee is being paid by the bank."}
            for s in ErrandStep.objects.filter(errand__client=person, status="fee_instructed")]


@dpr.exporter("errands")
def export_errands(person):
    from .models import Errand

    return {"errands": [{"reference": e.reference, "errand": e.item.get("name"), "status": e.status,
                         "documents": [{"key": d.key, "status": d.status} for d in e.documents.all()],
                         "steps": [{"seq": s.seq, "description": s.description, "status": s.status}
                                   for s in e.steps.all()]}
                        for e in Errand.objects.filter(client=person)],
            "errands_as_agent": [{"reference": e.reference, "status": e.status}
                                 for e in Errand.objects.filter(agent__person=person)]}


@dpr.retention("identity_documents")
def expired_errand_documents(scope, cutoff):
    """Identity documents handled in errands, after handover (dpr rule anchor `handover`). Access is withdrawn
    at once; the stored file goes when its write-once lock ends (EVD retention sweep)."""
    from .models import ErrandDocument

    qs = ErrandDocument.objects.filter(errand__status="handed_over", errand__handed_over_at__lt=cutoff,
                                       deleted_at__isnull=True).select_related("errand")
    qs = qs.filter(errand__country=scope.country) if scope.country is not None else (
        qs.exclude(errand__country__in=scope.exclude) if scope.exclude else qs)
    for d in qs:
        def apply(d=d):
            d.status, d.deleted_at = "deleted", timezone.now()
            d.save(update_fields=["status", "deleted_at"])

        yield dpr.Candidate("errand_document", d.pk, apply=apply,
                            related=[("errand", d.errand_id), ("person", d.errand.client_id)], label=d.label)
