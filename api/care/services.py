"""CARE Care visits: the public interface other modules may call.

Panel (FR-CARE-002)
    add_carer(by, *, person, vetting=None, pay_route, payee=None, agency_org=None) -> Carer
    suspend_carer / reinstate_carer / remove_carer(carer, by, *, reason, replacement=None)
    carer_blockers(carer) -> [reason], track_record(carer) -> dict
Plans (FR-CARE-001)
    create_plan(by, *, client, family_member_id, items, schedule, visit_fee, confirmers, ...) -> CarePlan
    update_plan(plan, by, data) -> CarePlan       # a new version: future visits follow it, past keep theirs
    assign_carer(plan, by, carer) -> CarePlan     # only an active, vetted carer; the family is told who to expect
    activate_plan(plan, client, *, terms_version, scope_version, mfa_at) -> CarePlan
    approve_carer(plan, client, *, mfa_at)         # the client agrees a new carer as payee (RUL-28)
    pause_plan / resume_plan / end_plan
    generate_visits(plan, now=None) -> [Visit]
Visits (FR-CARE-003 to FR-CARE-005, RUL-23, ADR-20)
    on_checkin(payload) / on_checkout(payload)    # from MOB checkin.recorded / checkout.recorded
    record_item(visit, person, key, *, outcome, reason="", reading=None, evidence_id=None) -> VisitItem
    confirm_with_code(visit, person, *, code, method="code") -> Visit
    record_call(visit, by, *, family_member, note) / check_call(visit, by, agree=True)
    reviewer_decide(visit, by, *, decision, note) -> Visit
    missed_and_unconfirmed(now=None) -> dict     # job care.missed_and_unconfirmed
    visit_reminders(now=None) -> dict             # job care.visit_reminders
Concerns (FR-CARE-006)
    raise_concern(person, *, visit=None, plan=None, kind, severity, narrative, evidence_id=None) -> Concern
    acknowledge_concern / action_concern / close_concern
Pay (FR-CARE-004, RUL-23, RUL-27)
    prepare_payment(visit, by) -> ReleaseInstruction   # held funds route only
    payment_batch(by=None, now=None) -> dict            # job care.weekly_payment_batch
    payable_blockers(visit) -> [reason]                 # registered with escrow.registry

Events published: visit.scheduled, visit.checked_out, visit.submitted, visit.confirmed, visit.unconfirmed,
visit.missed, visit.disputed, visit.late, concern.raised, care_plan.created, care_plan.activated,
care_plan.carer_assigned, carer.added, carer.removed, work.accepted (PRO route).
Events consumed: checkin.recorded, checkout.recorded, checkout.missing, flags.cleared,
family_confirmation.confirmed, family_confirmation.disputed, family_confirmation.locked, release.confirmed,
release.withdrawn, release.rejected, release.rejected_by_bank, vetting.completed, vetting.expired,
vetting.revoked, order.paid.
"""
import secrets
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from administration import flags
from audit.services import record, security_event
from core import state
from core.errors import DomainError, Forbidden, Invalid, MfaRequired, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from .models import (ITEM_KINDS, WEEKDAYS, CarePlan, CarePlanItem, Carer, Concern, Confirmation, Visit,
                     VisitItem)

READINGS = {
    "blood_pressure": ("systolic", "diastolic"),
    "blood_sugar": ("value",),
    "temperature": ("value",),
    "weight": ("value",),
    "pulse": ("value",),
}
OPEN_VISIT = ("scheduled", "checked_in", "checked_out", "unconfirmed", "disputed", "missed")
AWAITING_CONFIRMATION = ("checked_out", "unconfirmed", "disputed")
REVIEW_AFTER = timedelta(hours=72)  # fixed by FR-CARE-004, not a setting


# --------------------------------------------------------------------------- helpers

def _now():
    return timezone.now()


def _uuid(value):
    """An event payload's id, or None when it is not one of ours (other modules publish test ids)."""
    import uuid

    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _on(country):
    flags.require("lines.care", country)
    flags.read_only_guard()


def _cfg(country, key, default=None):
    from countries.selectors import config

    return config(country, key, default)


def _setting(key, country, default):
    from administration.selectors import setting

    v = setting(key, country, default)
    return default if v in (None, "") else v


def _staff(by, country, *roles):
    if not has_role(by, *(roles or ("CM", "RV", "AD")), country=country):
        raise Forbidden("Only Tenmina staff can do this.")


def _tz(country):
    try:
        return ZoneInfo(country.timezone or "UTC")
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _local(dt, country):
    return timezone.localtime(dt, _tz(country))


def _when(dt, country):
    return f"{_local(dt, country):%a %d %b, %H:%M}"


def _reference(prefix, country):
    return f"{prefix}-{country.code}-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}"


def _notify(person, template, body, *, subject="", obj=None, needs_action=False, link="", channels=("in_app",),
            category=None, to_address="", country=None):
    from notifications.services import notify

    return notify(person, template, body=body, subject=subject, subject_obj=obj, needs_action=needs_action,
                  link=link, channels=channels, category=category, to_address=to_address, country=country)


def _staff_in(country, *roles):
    from accounts.models import Person

    return list(Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                      role_grants__role__in=roles, role_grants__revoked_at__isnull=True,
                                      is_active=True).distinct().order_by("created_at"))


def _alert_staff(country, roles, template, body, *, obj=None, link="", needs_action=True, exclude=()):
    for p in _staff_in(country, *roles):
        if p.pk in exclude:
            continue
        _notify(p, template, body, obj=obj, link=link, needs_action=needs_action, category="safety")


def _audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=obj._meta.db_table, entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None))


def _family(pk):
    from accounts.models import FamilyMember

    return FamilyMember.objects.filter(pk=pk).first()


def _fm_label(fm):
    return f"{fm.full_name} ({fm.relationship})" if fm else ""


# --------------------------------------------------------------------------- panel (FR-CARE-002)

def carer_blockers(carer: Carer, on=None) -> list[dict]:
    """Why this carer cannot take a visit now (US-CARE-002 AC2)."""
    on = on or timezone.localdate()
    out = []
    if carer.status != "active":
        out.append({"rule": "FR-CARE-002", "code": "carer-not-active",
                    "message": f"{carer.person.full_name} is {carer.status} on the panel."})
    v = carer.vetting
    v.refresh_from_db()
    if v.status != "vetted" or v.valid_until is None or v.valid_until < on:
        out.append({"rule": "FR-CARE-002", "code": "carer-not-vetted",
                    "message": f"{carer.person.full_name}'s vetting is {v.status if v.status != 'vetted' else 'expired'}."})
    if carer.pay_route == "held_funds":
        p = carer.payee
        if p is None or p.verification_status != "verified" or p.name_match != "matched":
            out.append({"rule": "RUL-22", "code": "payee-not-verified",
                        "message": "The account the carer is paid to is not verified."})
    return out


def _check_payee(person, pay_route, payee, agency_org):
    if pay_route not in Carer.PAY_ROUTES:
        raise Invalid("Choose how the carer is paid: held_funds or tenmina.")
    if pay_route == "tenmina":
        if payee is not None:
            raise Invalid("A carer Tenmina contracts is paid by Tenmina under professional pay, never from a "
                          "client's held funds (RUL-27). Leave the payee empty.")
        return
    if payee is None:
        raise Invalid("Name the verified account the carer or their agency is paid to.")
    if payee.kind not in ("carer", "agency"):
        raise RuleBlocked("A care visit pays a carer or a care agency only.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "message": f"A {payee.kind} cannot be paid for "
                                                                          "a care visit."}])
    if payee.verification_status != "verified" or payee.name_match != "matched":
        raise RuleBlocked("The payee is not verified.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "message": f"{payee.legal_name} is not verified."}])
    if payee.kind == "carer" and payee.person_id != person.pk:
        raise RuleBlocked("A carer's own account must be in the carer's name.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "message": "The payee is another person."}])
    if payee.kind == "agency" and agency_org is not None and payee.organisation_id != agency_org.pk:
        raise RuleBlocked("The agency payee belongs to another organisation.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "message": "The agency's account is not on record."}])


@transaction.atomic
def add_carer(by, *, person, vetting=None, pay_route="held_funds", payee=None, agency_org=None, languages=(),
              areas="") -> Carer:
    """US-CARE-002 AC1: only a person whose carer vetting is complete joins the panel."""
    from accounts.selectors import live_vetting

    vetting = vetting or live_vetting(person, "carer")
    if vetting is None:
        raise RuleBlocked("This person has no completed carer vetting.", code="carer-not-vetted",
                          blocking_reasons=[{"rule": "FR-CARE-002", "message": "Identity, references and a "
                                                                               "background check are needed."}])
    country = vetting.country
    _on(country)
    _staff(by, country, "CM", "RV")
    if vetting.person_id != person.pk or vetting.kind != "carer":
        raise Invalid("The vetting must be this person's carer vetting.")
    if vetting.status != "vetted" or vetting.valid_until is None or vetting.valid_until < timezone.localdate():
        raise RuleBlocked("This person's carer vetting is not complete or has expired.", code="carer-not-vetted",
                          blocking_reasons=[{"rule": "FR-CARE-002", "message": f"Vetting is {vetting.status}."}])
    if by.pk == person.pk:
        raise Forbidden("You cannot add yourself to the panel.")
    if person.has_tenmina_role("CM", "RV", "AD", "RN"):
        raise RuleBlocked("Tenmina staff and runners cannot be carers paid from client money.",
                          code="separation-of-duties", blocking_reasons=[{"rule": "RUL-22", "message": "Staff"}])
    _check_payee(person, pay_route, payee, agency_org)
    if Carer.objects.filter(person=person).exists():
        raise StateConflict("This person is already on the carer panel.")
    if not person.has_tenmina_role("CE"):
        from accounts.services import grant_role

        grant_role(person, "CE", country=country, granted_by=by)
    c = Carer.objects.create(country=country, person=person, vetting=vetting, agency_org=agency_org,
                             pay_route=pay_route, payee=payee, languages=list(languages or []), areas=areas or "",
                             added_by=by)
    _audit(by, "carer.added", c, {"pay_route": pay_route, "vetting_id": str(vetting.pk)})
    publish("carer.added", c.pk, {"carer_id": c.pk, "person_id": person.pk, "country": country.code})
    return c


@transaction.atomic
def update_carer(carer: Carer, by, *, pay_route=None, payee=None, agency_org=None, languages=None, areas=None):
    _staff(by, carer.country, "CM", "RV")
    route = pay_route or carer.pay_route
    new_payee = payee if pay_route is not None or payee is not None else carer.payee
    if route == "tenmina":
        new_payee = None
    _check_payee(carer.person, route, new_payee, agency_org or carer.agency_org)
    carer.pay_route, carer.payee = route, new_payee
    if agency_org is not None:
        carer.agency_org = agency_org
    if languages is not None:
        carer.languages = list(languages)
    if areas is not None:
        carer.areas = areas
    carer.save()
    _audit(by, "carer.updated", carer, {"pay_route": route})
    for plan in CarePlan.objects.filter(carer=carer, status__in=["active", "paused"]):
        plan.carer_approved_at = None  # a new account needs the client's agreement again (RUL-28)
        plan.save(update_fields=["carer_approved_at"])
    return carer


@transaction.atomic
def suspend_carer(carer: Carer, by, *, reason, system=False) -> Carer:
    if not system:
        _staff(by, carer.country, "CM", "RV")
    if not (reason or "").strip():
        raise Invalid("Give the reason.")
    carer.status_reason = reason.strip()
    state.transition(carer, "care_carer", "suspended", actor=by, reason=reason, extra_fields=["status_reason"],
                     event="carer.suspended", payload={"carer_id": carer.pk, "person_id": carer.person_id})
    for plan in CarePlan.objects.filter(carer=carer, status="active"):
        _alert_staff(plan.country, ("CM",), "care_carer_suspended",
                     f"{carer.person.full_name} is suspended ({reason}). Assign another carer to plan "
                     f"{plan.reference} so visits go on.", obj=plan, link=f"/back-office/care-plans/{plan.pk}")
    return carer


@transaction.atomic
def reinstate_carer(carer: Carer, by) -> Carer:
    from accounts.selectors import live_vetting

    _staff(by, carer.country, "CM", "RV")
    v = live_vetting(carer.person, "carer")
    if v is None:
        raise RuleBlocked("The carer's vetting is not current.", code="carer-not-vetted",
                          blocking_reasons=[{"rule": "FR-CARE-002", "message": "Renew the vetting first."}])
    carer.vetting, carer.status_reason = v, ""
    return state.transition(carer, "care_carer", "active", actor=by, extra_fields=["vetting", "status_reason"],
                            event="carer.reinstated", payload={"carer_id": carer.pk})


@transaction.atomic
def remove_carer(carer: Carer, by, *, reason, replacement: Carer | None = None) -> Carer:
    """US-CARE-002 AC3: removal for cause reassigns every future visit; the reason feeds the track record."""
    _staff(by, carer.country, "CM", "RV")
    if not (reason or "").strip():
        raise Invalid("Give the reason for removal.")
    if replacement is not None:
        if replacement.pk == carer.pk:
            raise Invalid("Choose a different carer.")
        reasons = carer_blockers(replacement)
        if reasons:
            raise RuleBlocked("The replacement carer cannot take visits.", code="carer-not-vetted",
                              blocking_reasons=reasons)
    now = _now()
    carer.status_reason, carer.removed_at, carer.removed_by = reason.strip(), now, by
    state.transition(carer, "care_carer", "removed", actor=by, reason=reason, event="carer.removed",
                     extra_fields=["status_reason", "removed_at", "removed_by"],
                     payload={"carer_id": carer.pk, "person_id": carer.person_id,
                              "replacement_id": replacement.pk if replacement else None})
    for plan in CarePlan.objects.filter(carer=carer).exclude(status="ended"):
        if replacement is not None:
            _set_carer(plan, replacement, by, reason=f"{carer.person.full_name} was removed from the panel.")
        else:
            future = plan.visits.filter(status="scheduled", window_start__gt=now)
            for v in future:
                _cancel_visit(v, by, "The carer was removed from the panel.")
            if plan.status == "active":
                plan.status_reason = "The carer was removed. Tenmina is assigning a new carer."
                state.transition(plan, "care_plan", "paused", actor=by, extra_fields=["status_reason"],
                                 reason=plan.status_reason)
            _notify(plan.client, "care_carer_changed",
                    f"The carer for {plan.family_member.full_name} can no longer visit. Tenmina is choosing a new "
                    "vetted carer and will tell you who.", obj=plan, link=f"/care/plans/{plan.pk}")
    return carer


def track_record(carer: Carer) -> dict:
    """FR-CARE-002: the carer's record, built from their visits."""
    qs = Visit.objects.filter(carer=carer)
    done = qs.filter(status__in=["confirmed", "instructed", "paid"]).count()
    counted = qs.exclude(status__in=["scheduled", "cancelled", "checked_in"]).count()
    return {
        "visits_confirmed": done,
        "visits_missed": qs.filter(status="missed").count(),
        "visits_unconfirmed": qs.filter(status__in=["unconfirmed", "disputed"]).count(),
        "visits_late": qs.filter(late_minutes__gt=0).count(),
        "confirmation_rate": f"{(Decimal(done) / counted * 100):.0f}" if counted else None,
        "concerns_raised": Concern.objects.filter(raised_by=carer.person).count(),
        "status": carer.status,
        "status_reason": carer.status_reason,
        "removed_at": carer.removed_at.isoformat() if carer.removed_at else None,
    }


# --------------------------------------------------------------------------- plans (FR-CARE-001)

def _parse_schedule(schedule) -> dict:
    if not isinstance(schedule, dict):
        raise Invalid("Give the schedule as {\"weekly\": [\"tue\", \"fri\"], \"window\": \"09:00-12:00\"}.")
    days = [str(d).lower()[:3] for d in (schedule.get("weekly") or [])]
    if not days or any(d not in WEEKDAYS for d in days):
        raise Invalid("Choose at least one visit day (mon to sun).",
                      extra={"errors": [{"pointer": "/schedule/weekly", "message": "At least one day."}]})
    window = str(schedule.get("window") or "")
    try:
        a, b = window.split("-")
        start, end = time.fromisoformat(a.strip()), time.fromisoformat(b.strip())
    except ValueError:
        raise Invalid("Give the visit window as HH:MM-HH:MM.",
                      extra={"errors": [{"pointer": "/schedule/window", "message": "HH:MM-HH:MM"}]}) from None
    if end <= start:
        raise Invalid("The window must end after it starts.")
    return {"weekly": sorted(set(days), key=WEEKDAYS.index), "window": f"{start:%H:%M}-{end:%H:%M}"}


def _clean_items(items) -> list[dict]:
    if not items:
        raise Invalid("Add at least one task for the carer.",
                      extra={"errors": [{"pointer": "/items", "message": "At least one task."}]})
    out, keys = [], set()
    for n, it in enumerate(items):
        key = str(it.get("key") or "").strip().lower().replace(" ", "_")
        if not key:
            raise Invalid(f"Task {n + 1} needs a key.")
        if key in keys:
            raise Invalid(f"The task key '{key}' is used twice.")
        keys.add(key)
        kind = it.get("kind") or "other"
        if kind not in ITEM_KINDS:
            raise Invalid(f"Task '{key}': kind must be one of {', '.join(ITEM_KINDS)}.")
        reading_required = bool(it.get("reading_required"))
        reading_kind = str(it.get("reading_kind") or "")
        if reading_required and reading_kind not in READINGS:
            raise Invalid(f"Task '{key}': choose the reading ({', '.join(READINGS)}).")
        photo_required = bool(it.get("photo_required"))
        out.append({"key": key, "kind": kind, "label": str(it.get("label") or key.replace("_", " ").capitalize()),
                    "instructions": str(it.get("instructions") or ""), "photo_required": photo_required,
                    "photo_allowed": photo_required or bool(it.get("photo_allowed")),
                    "reading_required": reading_required, "reading_kind": reading_kind if reading_required else "",
                    "position": n})
    return out


def _clean_confirmers(client, ids, carer=None) -> list:
    from accounts.models import FamilyMember

    ids = [str(i) for i in (ids or [])]
    if not ids:
        raise Invalid("Name at least one family member who may confirm visits.",
                      extra={"errors": [{"pointer": "/confirmers", "message": "At least one confirmer."}]})
    out = []
    for i in ids:
        fm = FamilyMember.objects.filter(pk=i, client=client).first()
        if fm is None:
            raise Invalid("A confirmer is not one of your family members.")
        if fm.status != "active" or not fm.may_confirm_visits:
            raise Invalid(f"{fm.full_name} is not marked as someone who may confirm visits.",
                          code="confirmer-not-allowed")
        if not fm.phone and fm.person_id is None:
            raise Invalid(f"{fm.full_name} has no phone number for the confirmation code.")
        out.append(fm.pk)
    if carer is not None:
        _confirmers_not_carer(out, carer)
    return out


def _confirmers_not_carer(confirmer_ids, carer):
    """RUL-23, ADR-20: the carer can never be a confirmer, by account or by phone."""
    from accounts.models import FamilyMember
    from accounts.normalise import normalise_phone

    cp = normalise_phone(carer.person.phone) if carer.person.phone else ""
    for fm in FamilyMember.objects.filter(pk__in=confirmer_ids):
        if fm.person_id == carer.person_id or (cp and fm.phone and normalise_phone(fm.phone) == cp):
            raise RuleBlocked("The carer cannot confirm their own visits.", code="confirmer-is-carer",
                              blocking_reasons=[{"rule": "RUL-23", "message": f"{fm.full_name} uses the carer's "
                                                                              "account or phone."}])


def _money(value, country):
    if isinstance(value, dict):
        amount, currency = value.get("amount"), value.get("currency") or country.currency
    else:
        amount, currency = value, country.currency
    try:
        amount = q(amount)
    except Exception:  # noqa: BLE001
        raise Invalid("Give the visit fee as {\"amount\": \"150.00\", \"currency\": \"GHS\"}.") from None
    if amount <= 0:
        raise Invalid("The visit fee must be more than zero.")
    return amount, str(currency).upper()


def _template_version(country):
    try:
        from administration.selectors import current_config

        return current_config("care_plan_template", country, "care")
    except Exception:  # noqa: BLE001
        return None


@transaction.atomic
def create_plan(by, *, client, family_member_id, items, schedule, visit_fee, confirmers, address="",
                point=None, confirm_channel="sms", notes="") -> CarePlan:
    """US-CARE-001 AC1, TC-CARE-001-01, TC-CARE-001-02."""
    from accounts.selectors import active_family_member

    fm = active_family_member(client, family_member_id)
    country = fm.country
    _on(country)
    if by.pk != client.pk:
        _staff(by, country, "CM")
    elif not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client creates a care plan.")
    lat, lng = (point or {}).get("lat"), (point or {}).get("lng")
    if lat is None or lng is None:
        lat, lng = fm.latitude, fm.longitude
    address = (address or fm.address or "").strip()
    if not address or lat is None or lng is None:
        raise Invalid("A care plan needs the registered address and its map position.",
                      code="address-required", extra={"errors": [{"pointer": "/address", "message": "Required."}]})
    if confirm_channel not in CarePlan.CHANNELS:
        raise Invalid("Codes go by sms, whatsapp or app.")
    sched = _parse_schedule(schedule)
    clean = _clean_items(items)
    conf_ids = _clean_confirmers(client, confirmers)
    amount, currency = _money(visit_fee, country)
    plan = CarePlan.objects.create(
        country=country, reference=_reference("CARE", country), client=client, family_member=fm,
        template_version=_template_version(country), address=address, point_lat=Decimal(str(lat)),
        point_lng=Decimal(str(lng)), schedule=sched, visit_fee_amount=amount, visit_fee_currency=currency,
        confirmers=conf_ids, confirm_channel=confirm_channel, notes=notes or "")
    for it in clean:
        CarePlanItem.objects.create(plan=plan, **it)
    _audit(by, "care_plan.created", plan, {"family_member_id": str(fm.pk), "items": len(clean),
                                           "schedule": sched})
    publish("care_plan.created", plan.pk, {"plan_id": plan.pk, "client_id": client.pk, "country": country.code,
                                           "family_member_id": fm.pk})
    for fmid in conf_ids:
        f = _family(fmid)
        if f and f.phone:
            _notify(None, "care_confirmer_named",
                    f"{client.full_name} named you on Tenmina to confirm care visits to {fm.full_name}. After each "
                    "visit you get a one-time code. Never share it with the carer.", channels=("sms",),
                    to_address=f.phone, country=country)
    _alert_staff(country, ("CM",), "care_plan_new", f"New care plan {plan.reference} for {fm.full_name}. Assign a "
                 "vetted carer.", obj=plan, link=f"/back-office/care-plans/{plan.pk}")
    return plan


def _editable_by(plan, by):
    if by.pk == plan.client_id:
        return
    _staff(by, plan.country, "CM")


def _visit_items(visit, plan):
    VisitItem.objects.filter(visit=visit).delete()
    for it in plan.items.filter(active=True):
        VisitItem.objects.create(visit=visit, plan_item=it, key=it.key, kind=it.kind, label=it.label,
                                 photo_required=it.photo_required, photo_allowed=it.photo_allowed,
                                 reading_required=it.reading_required, reading_kind=it.reading_kind)


@transaction.atomic
def update_plan(plan: CarePlan, by, data: dict) -> CarePlan:
    """US-CARE-001 AC2: a change makes a new version; future visits follow it and past visits keep theirs."""
    _on(plan.country)
    _editable_by(plan, by)
    if plan.status == "ended":
        raise StateConflict("This plan has ended.")
    changed, schedule_changed = [], False
    if "schedule" in data and data["schedule"] is not None:
        sched = _parse_schedule(data["schedule"])
        if sched != plan.schedule:
            plan.schedule, schedule_changed = sched, True
            changed.append("schedule")
    if data.get("visit_fee") is not None:
        plan.visit_fee_amount, plan.visit_fee_currency = _money(data["visit_fee"], plan.country)
        changed.append("visit_fee")
    if data.get("confirmers") is not None:
        plan.confirmers = _clean_confirmers(plan.client, data["confirmers"], plan.carer)
        changed.append("confirmers")
    if data.get("confirm_channel"):
        if data["confirm_channel"] not in CarePlan.CHANNELS:
            raise Invalid("Codes go by sms, whatsapp or app.")
        plan.confirm_channel = data["confirm_channel"]
        changed.append("confirm_channel")
    if data.get("address"):
        plan.address = data["address"].strip()
        changed.append("address")
    if data.get("point"):
        plan.point_lat, plan.point_lng = Decimal(str(data["point"]["lat"])), Decimal(str(data["point"]["lng"]))
        changed.append("point")
    if "notes" in data and data["notes"] is not None:
        plan.notes = data["notes"]
    items_changed = False
    if data.get("items") is not None:
        clean = {i["key"]: i for i in _clean_items(data["items"])}
        current = {i.key: i for i in plan.items.filter(active=True)}
        fields = ("kind", "label", "instructions", "photo_required", "photo_allowed", "reading_required",
                  "reading_kind")
        new_version = plan.version + 1
        for key, it in current.items():
            new = clean.get(key)
            if new is None or any(getattr(it, f) != new[f] for f in fields):
                it.active, it.removed_in_version = False, new_version
                it.save(update_fields=["active", "removed_in_version"])
                items_changed = True
        for key, new in clean.items():
            if not plan.items.filter(active=True, key=key).exists():
                CarePlanItem.objects.create(plan=plan, added_in_version=new_version, **new)
                items_changed = True
            else:
                plan.items.filter(active=True, key=key).update(position=new["position"])
        if items_changed:
            changed.append("items")
    if not changed:
        plan.save()
        return plan
    plan.version += 1
    plan.save()
    now = _now()
    future = plan.visits.filter(status="scheduled", window_start__gt=now)
    if schedule_changed:
        for v in future:
            _cancel_visit(v, by, "The visit days changed.")
        if plan.status == "active":
            generate_visits(plan)
    else:
        for v in future:
            v.plan_version = plan.version
            v.fee_amount, v.fee_currency = plan.visit_fee_amount, plan.visit_fee_currency
            v.save(update_fields=["plan_version", "fee_amount", "fee_currency"])
            if items_changed:
                _visit_items(v, plan)
    _audit(by, "care_plan.updated", plan, {"version": plan.version, "changed": changed})
    publish("care_plan.updated", plan.pk, {"plan_id": plan.pk, "version": plan.version, "changed": changed})
    return plan


def _set_carer(plan, carer, by, reason=""):
    old = plan.carer
    plan.carer, plan.carer_approved_at = carer, None
    if by is not None and has_role(by, "CM", country=plan.country):
        plan.case_manager = by
    plan.save(update_fields=["carer", "carer_approved_at", "case_manager"])
    now = _now()
    for v in plan.visits.filter(status__in=["scheduled", "missed"], window_start__gt=now):
        v.carer = carer
        v.save(update_fields=["carer"])
        publish("visit.scheduled", v.pk, _visit_payload(v))
    _audit(by, "care_plan.carer_assigned", plan, {"carer_id": str(carer.pk), "previous": str(old.pk) if old else None,
                                                  "reason": reason})
    publish("care_plan.carer_assigned", plan.pk, {"plan_id": plan.pk, "carer_id": carer.pk,
                                                  "carer_person_id": carer.person_id, "person_id": carer.person_id})
    days = ", ".join(d.capitalize() for d in plan.schedule.get("weekly", []))
    who = f"{carer.person.full_name}, a vetted carer from Tenmina"
    for fmid in plan.confirmers:
        f = _family(fmid)
        if f and f.phone:
            _notify(None, "care_who_to_expect",
                    f"{who}, will visit {plan.family_member.full_name} on {days}, {plan.schedule.get('window')}. "
                    "After each visit you will get a code to confirm it.", channels=("sms",), to_address=f.phone,
                    country=plan.country)
    if plan.family_member.phone and plan.family_member.pk not in plan.confirmers:
        _notify(None, "care_who_to_expect", f"{who}, will visit you on {days}, {plan.schedule.get('window')}.",
                channels=("sms",), to_address=plan.family_member.phone, country=plan.country)
    needs = carer.pay_route == "held_funds"
    _notify(plan.client, "care_carer_assigned",
            f"{carer.person.full_name} will visit {plan.family_member.full_name}. "
            + ("Please approve the carer so visits can be paid from your held funds." if needs
               and plan.status != "draft" else ""),
            obj=plan, link=f"/care/plans/{plan.pk}", needs_action=needs and plan.status != "draft")


@transaction.atomic
def assign_carer(plan: CarePlan, by, carer: Carer) -> CarePlan:
    """US-CARE-002 AC2, TC-CARE-002-01, TC-CARE-002-02: only an active carer with a current vetting."""
    _on(plan.country)
    _staff(by, plan.country, "CM")
    if plan.status == "ended":
        raise StateConflict("This plan has ended.")
    if carer.country_id != plan.country_id:
        raise Invalid("The carer works in another country.")
    reasons = carer_blockers(carer)
    if reasons:
        raise RuleBlocked("This carer cannot be assigned: " + "; ".join(r["message"] for r in reasons),
                          code="carer-not-vetted", blocking_reasons=reasons)
    _confirmers_not_carer(plan.confirmers, carer)
    if plan.carer_id == carer.pk:
        return plan
    _set_carer(plan, carer, by)
    plan.refresh_from_db()
    return plan


def _require_fresh_mfa(mfa_at):
    from django.conf import settings

    if mfa_at is None or _now() - mfa_at > settings.TENMINA["MFA_FRESHNESS"]:
        raise MfaRequired()


def _lock_carer_payee(plan, at):
    from escrow import services as esc

    if plan.carer.pay_route != "held_funds" or plan.escrow is None:
        return
    esc.lock_payee(plan.escrow, plan.carer.payee, client_approved_at=at, source="client_approved_payment")


@transaction.atomic
def activate_plan(plan: CarePlan, client, *, terms_version="", scope_version="", mfa_at=None) -> CarePlan:
    """US-CARE-001 AC3: the client accepts the terms (Tenmina's fee order) and agrees the carer before the
    first visit. Visit payments come from the client's held funds at the partner bank (FR-ESC-014)."""
    from escrow import services as esc
    from orders.services import create_line_order

    _on(plan.country)
    if plan.client_id != client.pk:
        raise NotFound()
    if plan.status != "draft":
        raise StateConflict("Only a draft plan is started this way.")
    if plan.carer is None:
        raise StateConflict("Tenmina has not assigned a carer yet.")
    reasons = carer_blockers(plan.carer)
    if reasons:
        raise RuleBlocked("The carer cannot start visits.", code="carer-not-vetted", blocking_reasons=reasons)
    if plan.carer.pay_route == "held_funds":
        _require_fresh_mfa(mfa_at)
    now = _now()
    if plan.fee_order_id is None:
        order = create_line_order(client=client, kind="care_plan", country=plan.country, subject_type="care_plan",
                                  subject_id=plan.pk, details={"plan_reference": plan.reference},
                                  accepted_terms=(terms_version, scope_version))
        plan.fee_order_id = order.pk
    plan.terms_accepted_at = now
    if plan.escrow_id is None:
        plan.escrow = esc.open_held_funds(client, plan.country, plan.visit_fee_currency, by=client)
    plan.save(update_fields=["fee_order_id", "terms_accepted_at", "escrow"])
    if plan.carer.pay_route == "held_funds":
        _lock_carer_payee(plan, now)
        plan.carer_approved_at = now
        plan.save(update_fields=["carer_approved_at"])
    state.transition(plan, "care_plan", "active", actor=client, event="care_plan.activated",
                     payload={"plan_id": plan.pk, "client_id": client.pk})
    generate_visits(plan)
    return plan


@transaction.atomic
def approve_carer(plan: CarePlan, client, *, mfa_at=None) -> CarePlan:
    """RUL-28: a new carer is paid from held funds only after the client agrees them, with a fresh step-up."""
    _on(plan.country)
    if plan.client_id != client.pk:
        raise NotFound()
    if plan.carer is None:
        raise StateConflict("No carer is assigned.")
    if plan.carer.pay_route != "held_funds":
        return plan
    _require_fresh_mfa(mfa_at)
    if plan.escrow is None:
        from escrow import services as esc

        plan.escrow = esc.open_held_funds(client, plan.country, plan.visit_fee_currency, by=client)
    now = _now()
    _lock_carer_payee(plan, now)
    plan.carer_approved_at = now
    plan.save(update_fields=["escrow", "carer_approved_at"])
    _audit(client, "care_plan.carer_approved", plan, {"carer_id": str(plan.carer_id)})
    from notifications.services import resolve_action

    resolve_action(plan)
    return plan


@transaction.atomic
def pause_plan(plan: CarePlan, by, *, reason) -> CarePlan:
    _editable_by(plan, by)
    if not (reason or "").strip():
        raise Invalid("Give the reason.")
    for v in plan.visits.filter(status="scheduled", window_start__gt=_now()):
        _cancel_visit(v, by, f"Plan paused: {reason}")
    plan.status_reason = reason.strip()
    return state.transition(plan, "care_plan", "paused", actor=by, reason=reason, extra_fields=["status_reason"])


@transaction.atomic
def resume_plan(plan: CarePlan, by) -> CarePlan:
    _on(plan.country)
    _editable_by(plan, by)
    if plan.carer is None or carer_blockers(plan.carer):
        raise StateConflict("Assign an active, vetted carer before visits resume.")
    plan.status_reason = ""
    state.transition(plan, "care_plan", "active", actor=by, extra_fields=["status_reason"])
    generate_visits(plan)
    return plan


@transaction.atomic
def end_plan(plan: CarePlan, by, *, reason="") -> CarePlan:
    _editable_by(plan, by)
    for v in plan.visits.filter(status="scheduled", window_start__gt=_now()):
        _cancel_visit(v, by, "The plan ended.")
    plan.status_reason, plan.ended_at = reason or "", _now()
    state.transition(plan, "care_plan", "ended", actor=by, reason=reason, extra_fields=["status_reason", "ended_at"])
    from escrow.services import standing_approval_for, withdraw_standing_approval

    sa = standing_approval_for("care_plan", plan.pk)
    if sa is not None:
        withdraw_standing_approval(sa, plan.client)
    return plan


@transaction.atomic
def give_standing_approval(plan: CarePlan, client, *, monthly_max, mfa_at=None, code=None):
    """US-CARE-001 AC4, RUL-11: visit payments up to a stated amount per month, withdrawable at any time."""
    from escrow import services as esc

    _on(plan.country)
    if plan.client_id != client.pk:
        raise NotFound()
    if plan.escrow is None:
        plan.escrow = esc.open_held_funds(client, plan.country, plan.visit_fee_currency, by=client)
        plan.save(update_fields=["escrow"])
    return esc.create_standing_approval(plan.escrow, client, subject_kind="care_plan", subject_id=plan.pk,
                                        monthly_max=monthly_max, mfa_at=mfa_at, code=code)


@transaction.atomic
def withdraw_standing_approval(plan: CarePlan, client):
    from escrow import services as esc

    if plan.client_id != client.pk:
        raise NotFound()
    sa = esc.standing_approval_for("care_plan", plan.pk)
    if sa is None:
        raise NotFound("There is no standing approval on this plan.")
    return esc.withdraw_standing_approval(sa, client)


# --------------------------------------------------------------------------- visits

def _visit_payload(v: Visit, **extra):
    return {"visit_id": v.pk, "plan_id": v.plan_id, "client_id": v.plan.client_id, "carer_id": v.carer_id,
            "carer_person_id": v.carer.person_id, "person_id": v.carer.person_id,
            "window_start": v.window_start, "window_end": v.window_end, "country": v.country.code, **extra}


def _window(plan):
    a, b = plan.schedule["window"].split("-")
    return time.fromisoformat(a), time.fromisoformat(b)


@transaction.atomic
def generate_visits(plan: CarePlan, now=None, days=None) -> list[Visit]:
    """Visits from the plan's schedule for the coming days (job care.visit_reminders)."""
    now = now or _now()
    if plan.status != "active" or plan.carer is None or plan.carer.status != "active":
        return []
    days = int(days or _cfg(plan.country, "care.schedule_horizon_days", 14))
    tz = _tz(plan.country)
    start_t, end_t = _window(plan)
    today = _local(now, plan.country).date()
    out = []
    for n in range(days + 1):
        d = today + timedelta(days=n)
        if WEEKDAYS[d.weekday()] not in plan.schedule.get("weekly", []):
            continue
        ws = datetime.combine(d, start_t, tzinfo=tz)
        we = datetime.combine(d, end_t, tzinfo=tz)
        if we <= now:
            continue
        if plan.visits.filter(window_start=ws).exclude(status="cancelled").exists():
            continue
        v = Visit.objects.create(country=plan.country, plan=plan, carer=plan.carer, plan_version=plan.version,
                                 window_start=ws, window_end=we, fee_amount=plan.visit_fee_amount,
                                 fee_currency=plan.visit_fee_currency)
        _visit_items(v, plan)
        publish("visit.scheduled", v.pk, _visit_payload(v))
        out.append(v)
    return out


def _cancel_visit(v: Visit, by, reason):
    v.cancel_reason = reason
    state.transition(v, "care_visit", "cancelled", actor=by, reason=reason, extra_fields=["cancel_reason"])


@transaction.atomic
def cancel_visit(v: Visit, by, *, reason) -> Visit:
    _editable_by(v.plan, by)
    if v.status not in ("scheduled", "missed"):
        raise StateConflict("Only a visit that has not started can be cancelled.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.")
    _cancel_visit(v, by, reason.strip())
    return v


def _visit_for_checkin(payload) -> tuple[Visit | None, object]:
    from mobile.models import CheckIn

    if payload.get("subject_type") != "care_visit":
        return None, None
    v = Visit.objects.select_for_update().filter(pk=_uuid(payload.get("subject_id"))).first()
    ci = CheckIn.objects.filter(pk=_uuid(payload.get("checkin_id"))).first()
    if v is None or ci is None or ci.person_id != v.carer.person_id:
        return None, None
    return v, ci


@transaction.atomic
def on_checkin(payload: dict):
    """checkin.recorded (FR-MOB-012): the visit starts. A late check-in alerts the client (FR-CARE-005)."""
    v, ci = _visit_for_checkin(payload)
    if v is None or v.status not in ("scheduled", "missed"):
        return None
    late = int((ci.device_time - v.window_start).total_seconds() // 60)
    grace = int(_cfg(v.country, "care.late_grace_minutes", 30))
    v.checkin = ci
    v.late_minutes = late if late > grace else None
    if not ci.within_radius:
        v.needs_review_reason = "The check-in was not at the registered address."
    state.transition(v, "care_visit", "checked_in", event="visit.checked_in",
                     extra_fields=["checkin", "late_minutes", "needs_review_reason"],
                     payload={**_visit_payload(v), "within_radius": ci.within_radius})
    if v.late_minutes and v.late_alert_sent_at is None:
        v.late_alert_sent_at = _now()
        v.save(update_fields=["late_alert_sent_at"])
        publish("visit.late", v.pk, _visit_payload(v, late_minutes=v.late_minutes))
        _notify(v.plan.client, "care_visit_late",
                f"{v.carer.person.full_name} arrived {v.late_minutes} minutes late for "
                f"{v.plan.family_member.full_name}'s visit.", obj=v, link=f"/care/visits/{v.pk}", category="safety")
        if v.plan.case_manager:
            _notify(v.plan.case_manager, "care_visit_late",
                    f"Late check-in on {v.plan.reference}: {v.late_minutes} minutes.", obj=v,
                    link=f"/back-office/care-visits/{v.pk}")
    return v


@transaction.atomic
def on_checkout(payload: dict):
    """checkout.recorded: the visit is checked out; the family's code goes out once every item is answered."""
    v, ci = _visit_for_checkin(payload)
    if v is None or v.status != "checked_in":
        return None
    v.checkout = ci
    if not ci.within_radius and not v.needs_review_reason:
        v.needs_review_reason = "The check-out was not at the registered address."
    state.transition(v, "care_visit", "checked_out", event="visit.checked_out",
                     extra_fields=["checkout", "needs_review_reason"],
                     payload={**_visit_payload(v), "duration_minutes": ci.duration_minutes})
    _maybe_submit(v)
    return v


def _app_evidence(person, visit, evidence_id, key):
    """RUL-08: an item's photo is taken in Tenmina Field for this visit."""
    from evidence.models import Evidence
    from mobile.models import SignedManifest

    ev = Evidence.objects.filter(pk=evidence_id).first()
    if ev is None or ev.uploaded_by_id != person.pk:
        raise Invalid(f"The photo for '{key}' was not found.")
    if not ev.is_release_grade:
        raise Invalid(f"The photo for '{key}' must be taken in Tenmina Field with its own camera.",
                      code="evidence-rejected", blocking_reasons=[{"rule": "RUL-08", "message": "Not app-captured."}],
                      extra={"reason": "not_app_captured"})
    m = SignedManifest.objects.filter(evidence=ev).first()
    if m is None or m.subject_type != "care_visit" or str(m.subject_id) != str(visit.pk):
        raise Invalid(f"The photo for '{key}' was taken for a different visit.")
    if not ev.content_type.startswith("image/"):
        raise Invalid(f"'{key}' needs a photo.")
    return ev


def _clean_reading(kind, reading):
    if not isinstance(reading, dict):
        raise Invalid("Give the reading as numbers, for example {\"systolic\": 130, \"diastolic\": 85}.")
    out = {}
    for f in READINGS.get(kind, ("value",)):
        try:
            out[f] = float(reading[f])
        except (KeyError, TypeError, ValueError):
            raise Invalid(f"The reading needs '{f}' as a number.") from None
    if reading.get("unit"):
        out["unit"] = str(reading["unit"])[:16]
    return out


@transaction.atomic
def record_item(visit: Visit, person, key, *, outcome, reason="", reading=None, evidence_id=None) -> VisitItem:
    """US-CARE-003 AC1, AC2, TC-CARE-003-02, TC-CARE-003-03: done (with the agreed photo or reading), not done
    with a reason, or not applicable."""
    _on(visit.country)
    if visit.carer.person_id != person.pk:
        raise NotFound()
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if visit.status not in ("checked_in", "checked_out") or visit.submitted_at:
        raise StateConflict("Plan items are recorded between check-in and the family's confirmation.")
    item = visit.items.filter(key=key).first()
    if item is None:
        raise NotFound("This task is not on the plan for this visit.")
    if outcome not in ("done", "not_done", "not_applicable"):
        raise Invalid("Mark the task done, not_done (with a reason) or not_applicable.")
    if outcome == "not_done" and not (reason or "").strip():
        raise Invalid("Say why the task was not done.")
    ev = None
    if evidence_id:
        if not item.photo_allowed:
            raise Invalid("Photos are only taken for the tasks agreed with the family. This protects their "
                          "privacy.", code="photo-not-agreed")
        ev = _app_evidence(person, visit, evidence_id, key)
    clean_reading = None
    if outcome == "done":
        if item.photo_required and ev is None:
            raise Invalid(f"'{item.label}' needs a photo taken in the app.", code="photo-required")
        if item.reading_required:
            if reading is None:
                raise Invalid(f"'{item.label}' needs the {item.reading_kind.replace('_', ' ')} reading.",
                              code="reading-required")
            clean_reading = _clean_reading(item.reading_kind, reading)
    elif reading is not None:
        clean_reading = _clean_reading(item.reading_kind or "value", reading)
    item.outcome, item.reason = outcome, (reason or "").strip()
    item.reading, item.evidence = clean_reading, ev
    item.recorded_at, item.recorded_by = _now(), person
    item.save()
    if ev is not None:
        from evidence.services import link

        link(ev, "care_visit", visit.pk, role=f"item:{key}", by=person)
    _audit(person, "care_visit.item_recorded", visit, {"key": key, "outcome": outcome,
                                                       "evidence_id": str(ev.pk) if ev else None})
    _maybe_submit(visit)
    return item


def _pick_confirmer(plan):
    for fmid in plan.confirmers:
        fm = _family(fmid)
        if fm and fm.status == "active" and fm.may_confirm_visits and (fm.phone or fm.person_id):
            return fm
    return None


def _channel_for(plan, fm):
    if plan.confirm_channel == "app" and fm.person_id:
        return "app", "in_app"
    if not fm.phone and fm.person_id:
        return "app", "in_app"
    return plan.confirm_channel if plan.confirm_channel != "app" else "sms", \
        plan.confirm_channel if plan.confirm_channel != "app" else "sms"


def _summary(v):
    return (f"{v.carer.person.full_name}'s visit to {v.plan.family_member.full_name}, "
            f"{_local(v.window_start, v.country):%a %d %b %H:%M}")


@transaction.atomic
def send_code(visit: Visit, by=None) -> Confirmation:
    """ADR-20: a one-time code and a one-tap link to a named confirmer only. Never returned to the caller."""
    from notifications import services as ntf

    fm = _pick_confirmer(visit.plan)
    if fm is None:
        raise StateConflict("No named confirmer can receive a code. Add a phone number or record a call.")
    ours, theirs = _channel_for(visit.plan, fm)
    conf = ntf.send_confirmation_code(
        subject_type="care_visit", subject_id=visit.pk, country=visit.country, purpose="care_visit",
        to_address=fm.phone if theirs != "in_app" else "", channel=theirs, recipient_name=fm.full_name,
        recipient_person=fm.person, summary=_summary(visit), created_by=by)
    c, _ = Confirmation.objects.get_or_create(visit=visit, defaults={"sent_to_family_member": fm,
                                                                     "sent_channel": ours})
    c.sent_to_family_member, c.sent_channel = fm, ours
    c.ntf_confirmation_id, c.code_expires_at, c.sent_at = conf.pk, conf.expires_at, _now()
    c.attempts, c.locked_at = 0, None
    c.save()
    _audit(by, "care_visit.code_sent", visit, {"family_member_id": str(fm.pk), "channel": ours})
    return c


def _maybe_submit(v: Visit):
    if v.status != "checked_out" or v.submitted_at or v.items.filter(outcome="pending").exists():
        return
    v.submitted_at = _now()
    v.save(update_fields=["submitted_at"])
    publish("visit.submitted", v.pk, _visit_payload(v, items_done=v.items.filter(outcome="done").count()))
    try:
        send_code(v)
    except StateConflict:
        _alert_staff(v.country, ("CM",), "care_confirm_by_call",
                     f"Visit on {v.plan.reference} has no confirmer reachable by code. Call the family.", obj=v,
                     link=f"/back-office/care-visits/{v.pk}")


def _ntf_conf(visit):
    from notifications.services import confirmation_status

    return confirmation_status("care_visit", visit.pk)


def _require_confirmable(visit):
    if visit.status not in AWAITING_CONFIRMATION or visit.submitted_at is None:
        raise StateConflict("This visit is not waiting for the family's confirmation.",
                            extra={"visit_status": visit.status})
    c = getattr(visit, "confirmation", None)
    if c is not None and c.reviewer_decision == "not_confirmed":
        raise StateConflict("A reviewer decided this visit was not confirmed.")


def _carer_tried_to_confirm(visit, person, channel):
    """TC-RUL-23-02: the carer's own attempt is refused, logged as a security event, flagged for a reviewer and
    the client is told. Written after the refused request, so the rollback keeps it."""
    from audit import context

    def write():
        security_event("care.carer_self_confirmation", actor=person, entity="care_visit", entity_id=str(visit.pk),
                       country=visit.country, data={"channel": channel},
                       summary="A carer tried to confirm their own visit")
        v = Visit.objects.get(pk=visit.pk)
        v.needs_review_reason = "The carer tried to confirm this visit themselves."
        v.save(update_fields=["needs_review_reason"])
        _notify(v.plan.client, "care_self_confirmation",
                f"Someone tried to confirm {v.plan.family_member.full_name}'s visit from the carer's account. It was "
                "refused and a Tenmina reviewer is checking it.", obj=v, link=f"/care/visits/{v.pk}",
                category="safety")
        _alert_staff(v.country, ("RV",), "care_self_confirmation",
                     f"The carer tried to confirm visit {v.pk} on {v.plan.reference}. Review it.", obj=v,
                     link=f"/back-office/care-visits/{v.pk}")

    context.defer(write)


def confirmer_for(plan, person):
    from accounts.models import FamilyMember

    return FamilyMember.objects.filter(pk__in=plan.confirmers, person=person, status="active",
                                       may_confirm_visits=True).first()


@transaction.atomic
def confirm_with_code(visit: Visit, person, *, code, method="code") -> Visit:
    """US-CARE-004 AC1, AC6, ADR-20: a named confirmer enters the code in the app (or from the link). Wrong codes
    count; the 5th locks it; the carer can never confirm."""
    from notifications.services import attempt_code, ConfirmationCodeInvalid, _failure_text

    _on(visit.country)
    if method not in ("code", "link", "app"):
        raise Invalid("method must be code, link or app.")
    if person.pk == visit.carer.person_id or Visit.objects.filter(carer__person=person, plan=visit.plan).exists():
        _carer_tried_to_confirm(visit, person, method)
        raise Forbidden("A carer cannot confirm a visit. Only the family member Tenmina sent the code to can.")
    fm = confirmer_for(visit.plan, person)
    if fm is None:
        raise Forbidden("Only a family member named to confirm visits can do this.")
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    _require_confirmable(visit)
    c = visit.confirmation
    c.attempt_family_member, c.attempt_method = fm, method
    c.save(update_fields=["attempt_family_member", "attempt_method"])
    res = attempt_code(subject_type="care_visit", subject_id=visit.pk, code=code, via=method, actor=person)
    if not res["ok"]:
        raise ConfirmationCodeInvalid(_failure_text(res), extra={"attempts_left": res["attempts_left"],
                                                                 "reason": res["status"],
                                                                 "other_ways": ["app", "call"]})
    visit.refresh_from_db()
    return visit


@transaction.atomic
def record_call(visit: Visit, by, *, family_member, note) -> Confirmation:
    """US-CARE-004 AC2, TC-CARE-004-05: a staff member records the family's confirmation by phone. It counts
    only after a second staff member checks it."""
    from notifications import services as ntf

    _on(visit.country)
    _staff(by, visit.country, "CM", "RV")
    if by.pk == visit.carer.person_id:
        raise Forbidden("The carer cannot record a confirmation.")
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    _require_confirmable(visit)
    if family_member is None or family_member.pk not in visit.plan.confirmers:
        raise Invalid("The person called must be a family member named to confirm visits.",
                      code="confirmer-not-allowed")
    if not (note or "").strip():
        raise Invalid("Say who was called and what they said.")
    _confirmers_not_carer([family_member.pk], visit.carer)
    conf = _ntf_conf(visit)
    if conf is None:
        raise StateConflict("No confirmation was started for this visit.")
    conf = ntf.record_call(conf, by=by, outcome="confirm", note=note.strip())
    c = visit.confirmation
    c.recorded_by_staff, c.call_family_member, c.call_note = by, family_member, note.strip()
    c.ntf_confirmation_id = conf.pk
    c.save(update_fields=["recorded_by_staff", "call_family_member", "call_note", "ntf_confirmation_id"])
    _audit(by, "care_visit.call_recorded", visit, {"family_member_id": str(family_member.pk)})
    for p in _staff_in(visit.country, "CM", "RV"):
        if p.pk != by.pk:
            _notify(p, "care_call_check", f"A call confirming a visit on {visit.plan.reference} needs a second "
                    "check.", obj=visit, needs_action=True, link=f"/back-office/care-visits/{visit.pk}")
    return c


@transaction.atomic
def check_call(visit: Visit, by, *, agree=True) -> Visit:
    from notifications import services as ntf

    _on(visit.country)
    _staff(by, visit.country, "CM", "RV")
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    c = getattr(visit, "confirmation", None)
    if c is None or c.recorded_by_staff_id is None:
        raise StateConflict("No call is waiting for a check.")
    if by.pk in (c.recorded_by_staff_id, visit.carer.person_id):
        from core.errors import SameApprover

        raise SameApprover("A different staff member must check the call.")
    conf = _ntf_conf(visit)
    if conf is None:
        raise StateConflict("No call is waiting for a check.")
    ntf.check_call(conf, by=by, agree=agree)
    if not agree:
        c.recorded_by_staff, c.call_family_member, c.call_note = None, None, ""
        c.save(update_fields=["recorded_by_staff", "call_family_member", "call_note"])
    visit.refresh_from_db()
    return visit


def checkin_problems(visit: Visit) -> list[str]:
    """RUL-23: check-in and check-out at the address, or every flag on them cleared by a reviewer."""
    from mobile.models import FraudFlag

    out = []
    for ci, what in ((visit.checkin, "check-in"), (visit.checkout, "check-out")):
        if ci is None:
            out.append(f"There is no {what}.")
            continue
        flags = FraudFlag.objects.filter(checkin=ci)
        if flags.filter(status__in=["open", "upheld"]).exists():
            out.append(f"The {what} has a flag a reviewer has not cleared.")
        elif not ci.within_radius and not flags.filter(status="cleared").exists():
            out.append(f"The {what} was not at the registered address.")
    return out


def _confirm(visit: Visit, actor=None):
    now = _now()
    c = visit.confirmation
    c.confirmed_at = c.confirmed_at or now
    c.save(update_fields=["confirmed_at"])
    visit.confirmed_at, visit.needs_review_reason = now, ""
    state.transition(visit, "care_visit", "confirmed", actor=actor, event="visit.confirmed",
                     extra_fields=["confirmed_at", "needs_review_reason"],
                     payload=_visit_payload(visit, method=c.method,
                                            family_member_id=c.confirmed_by_family_member_id))
    who = _fm_label(c.confirmed_by_family_member) if c.confirmed_by_family_member_id else "a Tenmina reviewer"
    _notify(visit.plan.client, "care_visit_confirmed",
            f"{visit.plan.family_member.full_name}'s visit was confirmed by {who}.", obj=visit,
            link=f"/care/visits/{visit.pk}")
    from notifications.services import resolve_action

    resolve_action(visit)
    if visit.carer.pay_route == "tenmina" and visit.work_accepted_at is None:
        visit.work_accepted_at = now
        visit.save(update_fields=["work_accepted_at"])
        publish("work.accepted", visit.pk, {
            "work_kind": "care_visit", "work_type": "care_visit", "work_ref": visit.pk, "subject_type": "care_visit",
            "subject_id": visit.pk, "person_id": visit.carer.person_id, "role": "CE",
            "assigned_at": visit.window_start, "accepted_at": now, "quantity": 1, "country": visit.country.code})
    return visit


def _queue_review(visit, reason):
    if visit.review_queued_at is None:
        visit.review_queued_at = _now()
    visit.needs_review_reason = reason
    visit.save(update_fields=["review_queued_at", "needs_review_reason"])
    _alert_staff(visit.country, ("RV",), "care_visit_review",
                 f"Visit on {visit.plan.reference} needs a reviewer's decision: {reason}", obj=visit,
                 link=f"/back-office/care-visits/{visit.pk}")


@transaction.atomic
def try_confirm(visit: Visit, actor=None) -> Visit:
    """The family said yes. Confirmed if the check-in evidence holds; otherwise to a reviewer (TC-RUL-23-03)."""
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    c = getattr(visit, "confirmation", None)
    if c is None or c.family_confirmed_at is None or visit.status not in AWAITING_CONFIRMATION:
        return visit
    if c.reviewer_decision == "not_confirmed":
        return visit
    problems = checkin_problems(visit)
    if not problems:
        return _confirm(visit, actor)
    reason = "Confirmed by the family, but " + problems[0][0].lower() + problems[0][1:]
    if visit.status == "checked_out":
        state.transition(visit, "care_visit", "unconfirmed", actor=actor, event="visit.unconfirmed",
                         payload=_visit_payload(visit, reason=reason))
    _queue_review(visit, reason)
    _notify(visit.plan.client, "care_visit_needs_review",
            f"The family confirmed {visit.plan.family_member.full_name}'s visit, but the carer's check-in needs a "
            "reviewer's check before the visit is paid.", obj=visit, link=f"/care/visits/{visit.pk}",
            category="safety")
    return visit


@transaction.atomic
def on_family_confirmed(payload: dict):
    """family_confirmation.confirmed from NTF (code, link, reply or a checked staff call)."""
    from notifications.models import ConfirmationCode

    if payload.get("subject_type") != "care_visit":
        return None
    v = Visit.objects.filter(pk=_uuid(payload.get("subject_id"))).first()
    c = getattr(v, "confirmation", None) if v else None
    if v is None or c is None or c.family_confirmed_at is not None:
        return None
    via = payload.get("via") or ""
    ntf = ConfirmationCode.objects.filter(pk=payload.get("confirmation_id")).first()
    if via == "staff_call":
        c.method = "call"
        c.confirmed_by_family_member = c.call_family_member or c.sent_to_family_member
        if ntf is not None:
            c.recorded_by_staff = c.recorded_by_staff or ntf.call_recorded_by
            c.call_checked_by = ntf.call_checked_by
            c.call_note = c.call_note or ntf.call_note
    else:
        c.method = c.attempt_method or {"code": "code", "link": "link", "reply": "reply"}.get(via, "code")
        c.confirmed_by_family_member = c.attempt_family_member or c.sent_to_family_member
    c.family_confirmed_at = _now()
    c.attempt_family_member, c.attempt_method = None, ""
    c.save()
    _audit(None, "care_visit.family_confirmed", v, {"method": c.method,
                                                    "family_member_id": str(c.confirmed_by_family_member_id)})
    return try_confirm(v)


@transaction.atomic
def on_family_disputed(payload: dict):
    if payload.get("subject_type") != "care_visit":
        return None
    v = Visit.objects.select_for_update().filter(pk=_uuid(payload.get("subject_id"))).first()
    if v is None or v.status not in ("checked_out", "unconfirmed"):
        return None
    c = v.confirmation
    c.disputed_at = _now()
    c.save(update_fields=["disputed_at"])
    state.transition(v, "care_visit", "disputed", event="visit.disputed", payload=_visit_payload(v))
    _queue_review(v, "The family said the visit did not happen as recorded.")
    _notify(v.plan.client, "care_visit_disputed",
            f"The family said {v.plan.family_member.full_name}'s visit did not happen as recorded. It will not be "
            "paid unless a Tenmina reviewer finds otherwise.", obj=v, link=f"/care/visits/{v.pk}", category="safety")
    return v


@transaction.atomic
def on_family_locked(payload: dict):
    """FR-CARE-004: locked at the 5th wrong code; the family is offered the app or a call."""
    if payload.get("subject_type") != "care_visit":
        return None
    v = Visit.objects.filter(pk=_uuid(payload.get("subject_id"))).first()
    c = getattr(v, "confirmation", None) if v else None
    if c is None or c.locked_at:
        return None
    c.locked_at, c.attempts = _now(), 5
    c.save(update_fields=["locked_at", "attempts"])
    fm = c.sent_to_family_member
    if fm.phone:
        _notify(None, "care_code_locked", "Too many wrong codes were entered. Tenmina will call you to confirm the "
                "visit, or you can confirm in the Tenmina app.", channels=("sms",), to_address=fm.phone,
                country=v.country)
    _alert_staff(v.country, ("CM",), "care_code_locked",
                 f"The confirmation code for a visit on {v.plan.reference} locked after 5 wrong tries. Call "
                 f"{fm.full_name} to confirm.", obj=v, link=f"/back-office/care-visits/{v.pk}")
    return v


@transaction.atomic
def on_flags_cleared(payload: dict):
    """A reviewer cleared the flag on a check-in or check-out: a family-confirmed visit can now be confirmed."""
    cid = _uuid(payload.get("checkin_id"))
    if not cid:
        return None
    v = Visit.objects.filter(Q(checkin_id=cid) | Q(checkout_id=cid)).first()
    if v is None:
        return None
    return try_confirm(v)


@transaction.atomic
def reviewer_decide(visit: Visit, by, *, decision, note) -> Visit:
    """US-CARE-004 AC5, TC-CARE-004-06: a reviewer decides from the check-in evidence and a call to the family.
    Only 'confirmed' makes the visit payable."""
    _on(visit.country)
    _staff(by, visit.country, "RV")
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if decision not in ("confirmed", "not_confirmed"):
        raise Invalid("Decide confirmed or not_confirmed.")
    if not (note or "").strip():
        raise Invalid("Note the check-in evidence you looked at and the call to the family.",
                      code="decision-note-required")
    if visit.status not in AWAITING_CONFIRMATION:
        raise StateConflict("This visit is not waiting for a decision.")
    if visit.review_queued_at is None:
        raise StateConflict("A visit goes to a reviewer 72 hours after check-out, or when the family disputes it or "
                            "its check-in needs a check.")
    c = getattr(visit, "confirmation", None)
    if c is None:
        fm = _pick_confirmer(visit.plan)
        if fm is None:
            raise StateConflict("This visit has no confirmer on record.")
        c = Confirmation.objects.create(visit=visit, sent_to_family_member=fm, sent_channel="sms")
    if by.pk in (visit.carer.person_id, c.recorded_by_staff_id):
        from core.errors import SameApprover

        raise SameApprover("The reviewer cannot be the carer or the person who recorded the call.")
    if c.reviewer_decision:
        raise StateConflict("A reviewer already decided this visit.")
    c.reviewer, c.reviewer_decision, c.reviewer_note, c.decided_at = by, decision, note.strip(), _now()
    if decision == "confirmed":
        c.method = "reviewer"
    c.save()
    _audit(by, f"care_visit.reviewer_{decision}", visit, {"note": note.strip()[:200]})
    if decision == "confirmed":
        return _confirm(visit, by)
    if visit.status in ("checked_out", "disputed"):
        state.transition(visit, "care_visit", "unconfirmed", actor=by, event="visit.unconfirmed",
                         payload=_visit_payload(visit, reason="reviewer: not confirmed"))
    _notify(visit.plan.client, "care_visit_not_confirmed",
            f"A Tenmina reviewer could not confirm {visit.plan.family_member.full_name}'s visit. It will not be "
            "paid.", obj=visit, link=f"/care/visits/{visit.pk}")
    return visit


@transaction.atomic
def resend_code(visit: Visit, by) -> Confirmation:
    _staff(by, visit.country, "CM", "RV")
    _require_confirmable(visit)
    c = getattr(visit, "confirmation", None)
    if c is not None and c.family_confirmed_at:
        raise StateConflict("The family already confirmed this visit.")
    return send_code(visit, by)


# --------------------------------------------------------------------------- jobs (FR-CARE-005)

def _welfare_escalation(plan):
    """Two missed visits in a row: a reviewer checks on the person (welfare escalation)."""
    last = list(plan.visits.exclude(status__in=["scheduled", "cancelled"]).order_by("-window_start")[:2])
    if len(last) == 2 and all(v.status == "missed" for v in last):
        _alert_staff(plan.country, ("RV",), "care_welfare_check",
                     f"Two visits in a row were missed for {plan.family_member.full_name} ({plan.reference}). "
                     "Check on their welfare today.", obj=plan, link=f"/back-office/care-plans/{plan.pk}")
        publish("care.welfare_escalated", plan.pk, {"plan_id": plan.pk, "client_id": plan.client_id})


def missed_and_unconfirmed(now=None) -> dict:
    """Job care.missed_and_unconfirmed (every 15 minutes). Alerts only; it never confirms anything (RUL-11)."""
    now = now or _now()
    out = {"missed": 0, "unconfirmed": 0, "to_review": 0}
    for v in Visit.objects.filter(status="scheduled", window_end__lt=now).select_related("plan", "carer"):
        with transaction.atomic():
            v.alert_sent_at = now
            state.transition(v, "care_visit", "missed", event="visit.missed", extra_fields=["alert_sent_at"],
                             payload=_visit_payload(v))
            name = v.plan.family_member.full_name
            _notify(v.plan.client, "care_visit_missed",
                    f"The carer did not check in for {name}'s visit ({_when(v.window_start, v.country)}). Tenmina "
                    "is following up today.", obj=v, link=f"/care/visits/{v.pk}", category="safety",
                    channels=("in_app", "email"))
            cms = [v.plan.case_manager] if v.plan.case_manager else _staff_in(v.country, "CM")
            for cm in cms:
                _notify(cm, "care_visit_missed", f"Missed visit on {v.plan.reference} for {name}. Call the carer "
                        "and the family.", obj=v, needs_action=True, link=f"/back-office/care-visits/{v.pk}")
            _welfare_escalation(v.plan)
        out["missed"] += 1
    for v in Visit.objects.filter(status="checked_out", submitted_at__isnull=False).select_related("checkout"):
        hours = int(_setting("visit_confirm_hours", v.country, 24))
        if v.checkout.device_time + timedelta(hours=hours) > now:
            continue
        with transaction.atomic():
            v.alert_sent_at = now
            state.transition(v, "care_visit", "unconfirmed", event="visit.unconfirmed",
                             extra_fields=["alert_sent_at"], payload=_visit_payload(v, reason="no confirmation"))
            name = v.plan.family_member.full_name
            _notify(v.plan.client, "care_visit_unconfirmed",
                    f"{name}'s visit has not been confirmed by the family after {hours} hours. It is not paid until "
                    "it is confirmed.", obj=v, link=f"/care/visits/{v.pk}", category="safety",
                    channels=("in_app", "email"))
            _alert_staff(v.country, ("CM",), "care_visit_unconfirmed",
                         f"Visit on {v.plan.reference} unconfirmed after {hours} hours. Call the family.", obj=v,
                         link=f"/back-office/care-visits/{v.pk}")
            c = getattr(v, "confirmation", None)
            if c is not None and c.sent_to_family_member.phone and c.reminded_at is None:
                _notify(None, "care_confirm_reminder",
                        f"Please confirm {v.carer.person.full_name}'s visit to {name} with the code Tenmina sent "
                        "you, or reply to that message.", channels=("sms",), to_address=c.sent_to_family_member.phone,
                        country=v.country)
                c.reminded_at = now
                c.save(update_fields=["reminded_at"])
        out["unconfirmed"] += 1
    for v in Visit.objects.filter(status__in=["checked_out", "unconfirmed", "disputed"], review_queued_at__isnull=True,
                                  checkout__isnull=False).select_related("checkout"):
        if v.checkout.device_time + REVIEW_AFTER > now:
            continue
        c = getattr(v, "confirmation", None)
        if c is not None and c.reviewer_decision:
            continue
        with transaction.atomic():
            _queue_review(v, "Still unconfirmed 72 hours after check-out.")
        out["to_review"] += 1
    return out


def visit_reminders(now=None) -> dict:
    """Job care.visit_reminders: create visits from plan schedules; remind the carer and tell the family who to
    expect about 2 hours before the window."""
    now = now or _now()
    created = 0
    for plan in CarePlan.objects.filter(status="active"):
        created += len(generate_visits(plan, now=now))
    reminded = 0
    lead = timedelta(hours=2)  # 02 7.12: 2 hours before a window (assumption)
    for v in Visit.objects.filter(status="scheduled", reminder_sent_at__isnull=True, window_start__gt=now,
                                  window_start__lte=now + lead).select_related("plan", "carer"):
        with transaction.atomic():
            v.reminder_sent_at = now
            v.save(update_fields=["reminder_sent_at"])
            _notify(v.carer.person, "care_visit_reminder",
                    f"Visit {v.plan.family_member.full_name} at {_local(v.window_start, v.country):%H:%M}. Check in "
                    "at the house in Tenmina Field.", channels=("in_app", "push"), obj=v)
            fm = v.plan.family_member
            if fm.phone:
                _notify(None, "care_who_to_expect", f"{v.carer.person.full_name} from Tenmina visits today at "
                        f"{_local(v.window_start, v.country):%H:%M}.", channels=("sms",), to_address=fm.phone,
                        country=v.country)
        reminded += 1
    return {"created": created, "reminded": reminded}


@transaction.atomic
def on_checkout_missing(payload: dict):
    """checkout.missing from MOB's end-of-day job: the client and Tenmina are told (FR-CARE-005)."""
    if payload.get("subject_type") != "care_visit":
        return None
    v = Visit.objects.filter(pk=_uuid(payload.get("subject_id"))).first()
    if v is None or v.checkout_missing_at:
        return None
    v.checkout_missing_at = _now()
    v.needs_review_reason = v.needs_review_reason or "The carer did not check out."
    v.save(update_fields=["checkout_missing_at", "needs_review_reason"])
    _notify(v.plan.client, "care_checkout_missing",
            f"The carer checked in for {v.plan.family_member.full_name} but did not check out. Tenmina is "
            "following up.", obj=v, link=f"/care/visits/{v.pk}", category="safety")
    _alert_staff(v.country, ("CM",), "care_checkout_missing", f"No check-out on {v.plan.reference}.", obj=v,
                 link=f"/back-office/care-visits/{v.pk}")
    return v


# --------------------------------------------------------------------------- concerns (FR-CARE-006)

def _pager():
    from core.adapters import get_adapter

    return get_adapter("care_oncall_pager", default="care.adapters.ConsolePager")


def _reviewer_for(country):
    rvs = _staff_in(country, "RV")
    if not rvs:
        return None
    return min(rvs, key=lambda p: Concern.objects.filter(routed_to_reviewer=p, status__in=["open",
                                                                                        "acknowledged"]).count())


@transaction.atomic
def raise_concern(person, *, kind, severity, narrative, visit: Visit | None = None, plan: CarePlan | None = None,
                  evidence_id=None) -> Concern:
    """US-CARE-006 AC1: the client and a reviewer are told at once; the concern sits in the restricted log."""
    if visit is not None:
        plan = visit.plan
    if plan is None:
        raise Invalid("Say which visit or plan the concern is about.")
    _on(plan.country)
    is_carer = (visit is not None and visit.carer.person_id == person.pk) or (
        visit is None and plan.carer is not None and plan.carer.person_id == person.pk)
    if not is_carer and not has_role(person, "CM", "RV", country=plan.country):
        raise NotFound()
    if kind not in Concern.KINDS:
        raise Invalid("Choose health, safety or welfare.")
    if severity not in Concern.SEVERITIES:
        raise Invalid("Choose low, medium, high or urgent.")
    if not (narrative or "").strip():
        raise Invalid("Describe what you saw.")
    ev = None
    if evidence_id:
        from evidence.models import Evidence

        ev = Evidence.objects.filter(pk=evidence_id, uploaded_by=person).first()
        if ev is None:
            raise Invalid("The photo was not found.")
    rv = _reviewer_for(plan.country)
    now = _now()
    c = Concern.objects.create(country=plan.country, reference=_reference("CON", plan.country), visit=visit,
                               plan=plan, raised_by=person, kind=kind, severity=severity, narrative=narrative.strip(),
                               evidence=ev, routed_to_reviewer=rv)
    if ev is not None:
        from evidence.services import link

        link(ev, "care_concern", c.pk, role="concern_photo", by=person)
    name = plan.family_member.full_name
    _notify(plan.client, "care_concern_raised",
            f"The carer raised a {kind} concern about {name}. A Tenmina reviewer is looking at it today and will "
            "tell you what is done.", obj=c, link=f"/care/concerns/{c.pk}", category="safety",
            channels=("in_app", "email", "sms") if severity in ("high", "urgent") else ("in_app", "email"))
    c.client_notified_at = now
    if rv is not None:
        _notify(rv, "care_concern_review", f"{severity.capitalize()} {kind} concern on {plan.reference} ({name}). "
                "Open it in the back office.", obj=c, needs_action=True, link=f"/back-office/concerns/{c.pk}",
                category="safety")
        c.reviewer_notified_at = now
    if severity == "urgent":
        _pager().page(country=plan.country, summary=f"Urgent {kind} concern on {plan.reference}", concern_id=c.pk)
        c.paged_at = now
    c.save(update_fields=["client_notified_at", "reviewer_notified_at", "paged_at"])
    _audit(person, "concern.raised", c, {"kind": kind, "severity": severity})
    publish("concern.raised", c.pk, {"concern_id": c.pk, "plan_id": plan.pk, "visit_id": visit.pk if visit else None,
                                     "kind": kind, "severity": severity, "client_id": plan.client_id,
                                     "country": plan.country.code})
    return c


def _concern_staff(c, by):
    _staff(by, c.country, "RV", "CM")


@transaction.atomic
def acknowledge_concern(c: Concern, by) -> Concern:
    _concern_staff(c, by)
    c.acknowledged_by, c.acknowledged_at = by, _now()
    return state.transition(c, "care_concern", "acknowledged", actor=by,
                            extra_fields=["acknowledged_by", "acknowledged_at"])


@transaction.atomic
def action_concern(c: Concern, by, *, action_taken, client_outcome) -> Concern:
    """US-CARE-006 AC2: the client sees the outcome, not the carer's private notes."""
    _concern_staff(c, by)
    if not (action_taken or "").strip() or not (client_outcome or "").strip():
        raise Invalid("Record the action taken and what the client is told.")
    if c.acknowledged_at is None:
        c.acknowledged_by, c.acknowledged_at = by, _now()
    c.action_taken, c.client_outcome = action_taken.strip(), client_outcome.strip()
    c.actioned_by, c.actioned_at = by, _now()
    state.transition(c, "care_concern", "actioned", actor=by, event="concern.actioned",
                     extra_fields=["action_taken", "client_outcome", "actioned_by", "actioned_at", "acknowledged_by",
                                   "acknowledged_at"], payload={"concern_id": c.pk})
    _notify(c.plan.client, "care_concern_outcome", f"About the concern for {c.plan.family_member.full_name}: "
            f"{c.client_outcome}", obj=c, link=f"/care/concerns/{c.pk}", category="safety")
    return c


@transaction.atomic
def close_concern(c: Concern, by) -> Concern:
    _concern_staff(c, by)
    c.closed_at = _now()
    return state.transition(c, "care_concern", "closed", actor=by, extra_fields=["closed_at"])


# --------------------------------------------------------------------------- pay (FR-CARE-004, RUL-23, RUL-27)

def visit_evidence_ids(v: Visit) -> list:
    ids = [ci.evidence_id for ci in (v.checkin, v.checkout) if ci is not None]
    ids += list(v.items.exclude(evidence__isnull=True).values_list("evidence_id", flat=True))
    return ids


def payable_blockers(v: Visit, payee=None, amount=None) -> list[dict]:
    """RUL-23 for the escrow subject check: paid only when confirmed by check-in evidence and the family."""
    out = []
    if v.status not in ("confirmed", "instructed", "paid") or v.confirmed_at is None:
        c = getattr(v, "confirmation", None)
        msg = "The family has not confirmed this visit."
        if c is not None and c.family_confirmed_at and v.needs_review_reason:
            msg = "The family confirmed, but a reviewer must check the check-in first."
        out.append({"rule": "RUL-23", "code": "visit-not-confirmed", "message": msg})
    if v.carer.pay_route != "held_funds":
        out.append({"rule": "RUL-27", "code": "payee-not-verified",
                    "message": "This carer is paid by Tenmina, never from the client's held funds."})
    elif payee is not None and v.carer.payee_id != payee.pk:
        out.append({"rule": "RUL-22", "code": "payee-not-verified",
                    "message": "A visit is paid only to its carer's or agency's verified account."})
    if amount is not None and q(amount) != v.fee_amount:
        out.append({"rule": "RUL-23", "code": "visit-amount",
                    "message": f"A visit pays its agreed fee of {v.fee_amount:.2f} {v.fee_currency}."})
    return out


@transaction.atomic
def prepare_payment(visit: Visit, by):
    """US-CARE-004 AC3, AC7: the instruction for one confirmed visit, to the carer's or agency's verified payee.
    A standing approval within its month replaces the client's per-payment approval; evidence and two staff
    approvals are always required."""
    from escrow import services as esc
    from mobile.services import evidence_blockers

    _on(visit.country)
    _staff(by, visit.country, "CM", "RV")
    flags.require("escrow.enabled", visit.country)
    visit = Visit.objects.select_for_update().get(pk=visit.pk)
    if visit.carer.pay_route != "held_funds":
        raise StateConflict("This carer is paid by Tenmina under professional pay, not from the client's money.")
    reasons = payable_blockers(visit)
    if visit.status == "instructed" or visit.instruction_id:
        raise StateConflict("This visit already has a payment instruction.")
    if reasons:
        raise RuleBlocked("This visit cannot be paid: " + reasons[0]["message"], code="visit-not-confirmed",
                          blocking_reasons=reasons)
    plan = visit.plan
    if plan.escrow is None:
        raise StateConflict("The client has no held funds for this plan.")
    ids = visit_evidence_ids(visit)
    ev_reasons = evidence_blockers(ids)
    if ev_reasons:
        raise RuleBlocked("The visit evidence is not cleared.", code="release-blocked", blocking_reasons=ev_reasons)
    sa = esc.standing_approval_for("care_plan", plan.pk)
    if sa is not None and sa.escrow_id != plan.escrow_id:
        sa = None
    ins = esc.request_release(
        plan.escrow, payee=visit.carer.payee, amount=visit.fee_amount, currency=visit.fee_currency,
        subject_type="care_visit", subject_id=visit.pk, requested_by=by, evidence_ids=ids,
        reason=f"Care visit {_when(visit.window_start, visit.country)}", subject_label=label(visit),
        family_member_id=plan.family_member_id, standing_approval=sa)
    visit.instruction_id = ins.pk
    state.transition(visit, "care_visit", "instructed", actor=by, extra_fields=["instruction_id"],
                     payload={"instruction_id": ins.pk})
    return ins


def payment_batch(by=None, now=None) -> dict:
    """Job care.weekly_payment_batch (US-CARE-004 AC3, AC4): instructions for confirmed visits only; unconfirmed
    visits are excluded and listed as awaiting confirmation."""
    out = {"prepared": [], "blocked": [], "awaiting_confirmation": [], "paid_by_tenmina": []}
    for v in Visit.objects.filter(status="confirmed", instruction_id__isnull=True).select_related("plan", "carer"):
        if v.carer.pay_route != "held_funds":
            out["paid_by_tenmina"].append(str(v.pk))
            continue
        actor = by or v.plan.case_manager or next(iter(_staff_in(v.country, "CM")), None)
        try:
            with transaction.atomic():
                ins = prepare_payment(v, actor)
            out["prepared"].append({"visit_id": str(v.pk), "instruction_id": str(ins.pk)})
        except DomainError as exc:
            out["blocked"].append({"visit_id": str(v.pk), "reason": exc.detail,
                                   "blocking_reasons": exc.blocking_reasons})
    for v in Visit.objects.filter(status__in=["checked_out", "unconfirmed", "disputed"]):
        out["awaiting_confirmation"].append({"visit_id": str(v.pk), "status": v.status})
    return out


def label(v: Visit) -> str:
    return f"Care visit to {v.plan.family_member.full_name}, {_local(v.window_start, v.country):%d %b %Y}"


@transaction.atomic
def on_release(payload: dict, topic: str):
    if payload.get("subject_type") != "care_visit":
        return None
    v = Visit.objects.select_for_update().filter(pk=_uuid(payload.get("subject_id"))).first()
    if v is None or str(v.instruction_id) != str(payload.get("instruction_id")):
        return None
    if topic == "release.confirmed" and v.status == "instructed":
        v.paid_at = _now()
        state.transition(v, "care_visit", "paid", event="visit.paid", extra_fields=["paid_at"],
                         payload={"instruction_id": v.instruction_id})
        _notify(v.carer.person, "care_visit_paid", f"Your visit on {_when(v.window_start, v.country)} was paid.",
                obj=v, channels=("in_app", "push"))
    elif topic in ("release.withdrawn", "release.rejected", "release.rejected_by_bank") and v.status == "instructed":
        v.instruction_id = None
        state.transition(v, "care_visit", "confirmed", extra_fields=["instruction_id"],
                         reason=f"Instruction {topic.split('.')[-1].replace('_', ' ')}")
    return v


# --------------------------------------------------------------------------- vetting changes (FR-CARE-002)

@transaction.atomic
def on_vetting_lapsed(payload: dict):
    """TC-CARE-002-02: existing assignments are suspended when a check expires or is revoked."""
    if payload.get("kind") != "carer":
        return
    for c in Carer.objects.filter(person_id=payload.get("person_id"), status="active"):
        suspend_carer(c, None, reason="The carer's vetting expired or was revoked.", system=True)


@transaction.atomic
def on_vetting_completed(payload: dict):
    from accounts.models import Vetting

    if payload.get("kind") != "carer":
        return
    v = Vetting.objects.filter(pk=payload.get("vetting_id")).first()
    for c in Carer.objects.filter(person_id=payload.get("person_id")).exclude(status="removed"):
        c.vetting = v or c.vetting
        c.save(update_fields=["vetting"])
        if c.status == "suspended" and "vetting" in c.status_reason and not carer_blockers(c):
            c.status_reason = ""
            state.transition(c, "care_carer", "active", extra_fields=["status_reason"],
                             reason="Vetting renewed")


@transaction.atomic
def on_order_paid(payload: dict):
    if payload.get("kind") != "care_plan" or not payload.get("subject_id"):
        return
    CarePlan.objects.filter(pk=_uuid(payload["subject_id"]), fee_paid_at__isnull=True).update(fee_paid_at=_now())
