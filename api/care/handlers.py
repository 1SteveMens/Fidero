"""CARE event subscribers and registry hooks. Idempotent: each acts only on visits still in the state it expects,
and core.events delivers each event once per consumer."""
from datetime import timedelta

from django.utils import timezone

from accounts import home
from core.events import subscribe
from dataprotection import registry as dpr
from escrow import registry as esc_registry
from evidence import access
from mobile import inbox

from . import services


# --------------------------------------------------------------------------- events

@subscribe("checkin.recorded")
def on_checkin(ev):
    services.on_checkin(ev.payload)


@subscribe("checkout.recorded")
def on_checkout(ev):
    services.on_checkout(ev.payload)


@subscribe("checkout.missing")
def on_checkout_missing(ev):
    services.on_checkout_missing(ev.payload)


@subscribe("flags.cleared")
def on_flags_cleared(ev):
    services.on_flags_cleared(ev.payload)


@subscribe("family_confirmation.confirmed")
def on_family_confirmed(ev):
    services.on_family_confirmed(ev.payload)


@subscribe("family_confirmation.disputed")
def on_family_disputed(ev):
    services.on_family_disputed(ev.payload)


@subscribe("family_confirmation.locked")
def on_family_locked(ev):
    services.on_family_locked(ev.payload)


@subscribe("release.confirmed", "release.withdrawn", "release.rejected", "release.rejected_by_bank")
def on_release(ev):
    services.on_release(ev.payload, ev.topic)


@subscribe("vetting.expired", "vetting.revoked")
def on_vetting_lapsed(ev):
    services.on_vetting_lapsed(ev.payload)


@subscribe("vetting.completed")
def on_vetting_completed(ev):
    services.on_vetting_completed(ev.payload)


@subscribe("order.paid")
def on_order_paid(ev):
    services.on_order_paid(ev.payload)


# --------------------------------------------------------------------------- escrow: RUL-23 before money moves

def visit_payable(instruction) -> list[dict]:
    """esc.release_blockers() for a care visit (02 6.5): confirmed by the family and the check-in evidence,
    paid to the visit's own carer or agency, at the visit's fee."""
    from .models import Visit

    v = Visit.objects.filter(pk=instruction.subject_id).select_related("carer").first()
    if v is None:
        return [{"rule": "RUL-23", "code": "visit-not-confirmed", "message": "There is no such care visit."}]
    return services.payable_blockers(v, payee=instruction.payee, amount=instruction.amount)


esc_registry.register_subject_check("care_visit", visit_payable)


def _visit_label(subject_id):
    from .models import Visit

    v = Visit.objects.filter(pk=subject_id).first()
    return services.label(v) if v else ""


esc_registry.subject_label("care_visit", _visit_label)


# --------------------------------------------------------------------------- field inbox (FR-MOB-001, FR-CARE-003)

def _radius(country):
    from administration.selectors import setting

    try:
        return int(setting("checkin_radius_m", country, 100) or 100)
    except (TypeError, ValueError):
        return 100


@inbox.register
def care_visits(person):
    """Today's and the coming week's visits for an active carer; nothing for anyone else (NFR-PRIV-02)."""
    from .models import Visit

    now = timezone.now()
    qs = Visit.objects.filter(carer__person=person, carer__status="active",
                              status__in=["scheduled", "missed", "checked_in", "checked_out"],
                              window_start__lte=now + timedelta(days=7), window_end__gte=now - timedelta(days=2),
                              plan__status="active").select_related("plan__family_member", "country")
    for v in qs:
        if v.status == "checked_out" and v.submitted_at:
            continue
        plan = v.plan
        items = list(v.items.all())
        yield inbox.InboxItem(
            subject_type="care_visit", subject_id=v.pk, kind="care_visit", country=v.country,
            title=f"Visit {plan.family_member.full_name}", address=plan.address,
            point=(plan.point_lat, plan.point_lng), radius_m=_radius(v.country),
            plan_items=[{"key": i.key, "label": i.label, "kind": i.kind, "outcome": i.outcome,
                         "needs": [n for n, on in (("photo", i.photo_required), ("reading", i.reading_required))
                                   if on], "photo_allowed": i.photo_allowed, "reading_kind": i.reading_kind}
                        for i in items],
            required_evidence=[{"key": i.key, "label": i.label, "media": "photo", "required": True}
                               for i in items if i.photo_required],
            project_key=f"care_plan:{plan.pk}", accepts_submissions=True,
            due_at=v.window_end, details={"window_start": v.window_start.isoformat(),
                                          "window_end": v.window_end.isoformat(), "status": v.status,
                                          "plan_reference": plan.reference},
            updated_at=v.updated_at)


# --------------------------------------------------------------------------- client home (FR-ACC-012)

@home.register
def care_home(person):
    from .models import CarePlan, Concern

    out = []
    for plan in CarePlan.objects.filter(client=person).exclude(status="ended").select_related("family_member",
                                                                                              "carer__person"):
        name = plan.family_member.full_name
        nxt = plan.visits.filter(status="scheduled", window_start__gte=timezone.now()).order_by("window_start").first()
        needs, text = False, ""
        if plan.status == "draft" and plan.carer_id:
            needs, text = True, f"{plan.carer.person.full_name} is ready to visit. Accept the terms to start."
        elif plan.status == "draft":
            text = "Tenmina is choosing a vetted carer."
        elif plan.carer_id and plan.carer.pay_route == "held_funds" and plan.carer_approved_at is None:
            needs, text = True, f"Approve {plan.carer.person.full_name} as the new carer."
        elif plan.status == "paused":
            text = plan.status_reason or "Visits are paused."
        elif nxt:
            text = f"Next visit {services._when(nxt.window_start, plan.country)}"
        out.append(home.item(kind="care_plan", id=plan.pk, title=f"Care visits for {name}", status=plan.status,
                             status_text=text, next_date=nxt.window_start if nxt else None, needs_action=needs,
                             link=f"/care/plans/{plan.pk}", family_member_id=plan.family_member_id, line="care"))
        for v in plan.visits.filter(status__in=["missed", "unconfirmed", "disputed"]).order_by("-window_start")[:3]:
            out.append(home.item(kind="care_visit", id=v.pk, title=f"Visit to {name}", status=v.status,
                                 status_text={"missed": "The carer did not come.",
                                              "unconfirmed": "Waiting for the family to confirm.",
                                              "disputed": "The family disputed this visit."}[v.status],
                                 next_date=v.window_start, link=f"/care/visits/{v.pk}",
                                 family_member_id=plan.family_member_id, line="care"))
    for c in Concern.objects.filter(plan__client=person, status__in=["open", "acknowledged", "actioned"]):
        out.append(home.item(kind="care_concern", id=c.pk, title=f"Concern about {c.plan.family_member.full_name}",
                             status=c.status, status_text=c.client_outcome or "A reviewer is looking at it.",
                             link=f"/care/concerns/{c.pk}", family_member_id=c.plan.family_member_id, line="care"))
    return out


# --------------------------------------------------------------------------- evidence access

def _visit(sid):
    from .models import Visit

    return Visit.objects.select_related("plan", "carer").get(pk=sid)


def _can_view_visit(user, sid):
    from .selectors import visible_visits

    return visible_visits(user).filter(pk=sid).exists()


def _can_attach_visit(user, sid):
    v = _visit(sid)
    return v.carer.person_id == user.pk and v.status in ("scheduled", "missed", "checked_in", "checked_out")


access.register("care_visit", can_view=_can_view_visit, can_attach=_can_attach_visit,
                country=lambda sid: _visit(sid).country, owner=lambda sid: ("care_plan", _visit(sid).plan_id))


def _concern_country(sid):
    from .models import Concern

    return Concern.objects.get(pk=sid).country


# Concern photos: staff in the country only (the restricted log); the carer who uploaded keeps their own view.
access.register("care_concern", can_view=lambda user, sid: False, can_attach=lambda user, sid: False,
                country=_concern_country)


# --------------------------------------------------------------------------- owner checks and data protection

def _owns_plan(person, sid):
    from .models import CarePlan

    return CarePlan.objects.filter(pk=sid, client=person).exists()


def _register_owner_check():
    from accounts.services import register_owner_check

    register_owner_check("care_plan", _owns_plan)


_register_owner_check()


@dpr.open_matters
def care_open_matters(person):
    from .models import Visit

    out = []
    for v in Visit.objects.filter(plan__client=person, status="instructed"):
        out.append({"kind": "care_visit_payment", "id": str(v.pk), "title": services.label(v),
                    "reason": "A visit payment is being made by the bank."})
    return out


@dpr.exporter("care")
def export_care(person):
    from .models import CarePlan, Concern, Visit

    plans = [{"reference": p.reference, "family_member": p.family_member.full_name, "status": p.status,
              "schedule": p.schedule, "address": p.address,
              "items": [{"key": i.key, "label": i.label} for i in p.items.filter(active=True)]}
             for p in CarePlan.objects.filter(client=person)]
    visits = [{"plan": v.plan.reference, "window_start": v.window_start.isoformat(), "status": v.status,
               "items": [{"key": i.key, "outcome": i.outcome, "reading": i.reading} for i in v.items.all()]}
              for v in Visit.objects.filter(plan__client=person)]
    as_carer = [{"plan": v.plan.reference, "window_start": v.window_start.isoformat(), "status": v.status}
                for v in Visit.objects.filter(carer__person=person)]
    concerns = [{"reference": c.reference, "kind": c.kind, "status": c.status, "outcome": c.client_outcome}
                for c in Concern.objects.filter(plan__client=person)]
    return {"care_plans": plans, "care_visits": visits, "visits_as_carer": as_carer, "concerns": concerns}


@dpr.retention("health_care")
def expired_care(scope, cutoff):
    """Ended plans past the health and care period: readings and concern narratives are removed."""
    from .models import CarePlan

    for plan in scope.filter(CarePlan.objects.filter(status="ended", ended_at__lt=cutoff)):
        def apply(plan=plan):
            from .models import Concern, VisitItem

            VisitItem.objects.filter(visit__plan=plan).update(reading=None, reason="")
            Concern.objects.filter(plan=plan).update(narrative="[removed under the retention rule]",
                                                     action_taken="")
            plan.notes, plan.address = "", "[removed]"
            plan.save(update_fields=["notes", "address"])

        yield dpr.Candidate("care_plan", plan.pk, apply=apply, related=[("person", plan.client_id)],
                            label=plan.reference)
