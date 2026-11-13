"""CARE demo data (J-10), built through the real services so every rule runs: the carer panel, an active plan
for the client's mother with visits in several states (missed; confirmed by a checked call and instructed under
a standing approval; checked out and waiting for the family's code; checked in now; scheduled), a second plan
waiting for the client, and concerns. Every fee and threshold is a working assumption [TO VERIFY]."""
import hashlib
from datetime import timedelta

from django.utils import timezone

ITEMS = [
    {"key": "medicines", "kind": "medicine", "label": "Check the morning medicines are taken",
     "photo_allowed": True, "instructions": "Use the pill organiser on the kitchen shelf."},
    {"key": "blood_pressure", "kind": "reading", "label": "Take her blood pressure", "reading_required": True,
     "reading_kind": "blood_pressure"},
    {"key": "groceries", "kind": "groceries", "label": "Deliver the groceries", "photo_required": True,
     "instructions": "Photo of the groceries on the table only, never of her."},
    {"key": "company", "kind": "companionship", "label": "Sit and talk for 20 minutes"},
    {"key": "hospital", "kind": "hospital_visit", "label": "Go with her to Ridge Hospital when booked"},
]


def _phone(person, name):
    from mobile import crypto
    from mobile.devtools import FakePhone
    from mobile.models import Device, SignedManifest

    phone = FakePhone(person, seed=f"tenmina-seed-{name}", key_security="tee", model="SM-A145F")
    fp = hashlib.sha256(crypto.b64decode_any(phone.public_key)).hexdigest()
    dev = Device.objects.filter(key_fingerprint=fp).first()
    if dev:
        phone.device = dev
        last = SignedManifest.objects.filter(device=dev).order_by("-received_at").first()
        phone.previous = last.item_sha256 if last else None
    else:
        phone.register()
    return phone


def _visit(plan, start, hours=2):
    from . import services
    from .models import Visit

    v = Visit.objects.create(country=plan.country, plan=plan, carer=plan.carer, plan_version=plan.version,
                             window_start=start, window_end=start + timedelta(hours=hours),
                             fee_amount=plan.visit_fee_amount, fee_currency=plan.visit_fee_currency)
    services._visit_items(v, plan)
    return v


def _check(phone, kind, v, at):
    from mobile.services import record_checkin

    p = v.plan
    record_checkin(phone.person, phone.check(kind, "care_visit", v.pk, lat=float(p.point_lat),
                                             lng=float(p.point_lng), accuracy=6.0, captured_at=at), kind)


def _photo(phone, v, key, at):
    from mobile.devtools import jpeg
    from mobile.services import complete_item, register_item

    data = jpeg(f"care-seed-{v.pk}-{key}", model=phone.model, when=at)
    p = v.plan
    m, _ = register_item(phone.person, phone.capture("care_visit", v.pk, data, requirement_key=key,
                                                     lat=float(p.point_lat), lng=float(p.point_lng), captured_at=at),
                         app_version="1.0.0")
    m, _ = complete_item(m, phone.person, data)
    return m.evidence_id


def _items(v, carer, phone, at, *, all_items=True):
    from . import services

    services.record_item(v, carer, "medicines", outcome="done")
    services.record_item(v, carer, "blood_pressure", outcome="done",
                         reading={"systolic": 138, "diastolic": 86, "unit": "mmHg"})
    if not all_items:
        return
    services.record_item(v, carer, "groceries", outcome="done",
                         evidence_id=_photo(phone, v, "groceries", at))
    services.record_item(v, carer, "company", outcome="done")
    services.record_item(v, carer, "hospital", outcome="not_applicable")


def _clear_flags(v, reviewer):
    from mobile.models import FraudFlag
    from mobile.services import review_flag

    for f in FraudFlag.objects.filter(subject_type="care_visit", subject_id=v.pk, status="open"):
        review_flag(f, reviewer, "clear", "Uploaded from the offline queue the next morning; times match the "
                                          "family's account [demo].")


def run(ctx):
    from orders import legal

    from . import services
    from .models import CarePlan, Carer

    gh, people = ctx.get("gh"), ctx.get("people", {})
    payee = ((ctx.get("escrow") or {}).get("payees") or {}).get("carer")
    mother = (ctx.get("family_members") or {}).get("mother")
    if gh is None or payee is None or mother is None or payee.verification_status != "verified":
        return
    client, cm, rv, rv2 = people["client"], people["cm"], people["reviewer"], people["reviewer2"]
    carer_person = people["carer"]
    refs = ctx.setdefault("care", {})
    carer = Carer.objects.filter(person=carer_person).first() or services.add_carer(
        cm, person=carer_person, pay_route="held_funds", payee=payee, languages=["en", "tw"],
        areas="East Legon, Madina, Adenta")
    refs["carer"] = carer
    plan = CarePlan.objects.filter(client=client, family_member=mother, notes__startswith="Main plan").first()
    if plan is not None:
        refs["plan"] = plan
        refs["draft_plan"] = CarePlan.objects.filter(client=client, status="draft").first()
        return
    now = timezone.now()
    plan = services.create_plan(client, client=client, family_member_id=mother.pk, items=ITEMS,
                                schedule={"weekly": ["tue", "fri"], "window": "09:00-12:00"},
                                visit_fee={"amount": "150.00", "currency": "GHS"}, confirmers=[mother.pk],
                                notes="Main plan. Mama likes to talk about church; she takes tea without sugar.")
    services.assign_carer(plan, cm, carer)
    cur = legal.current(gh)
    services.activate_plan(plan, client, terms_version=cur["terms_version"], scope_version=cur["scope_version"],
                           mfa_at=now)
    services.give_standing_approval(plan, client, monthly_max="1200.00", mfa_at=now)
    plan.refresh_from_db()
    refs["plan"] = plan
    phone = _phone(carer_person, "care-afia")

    # Missed: no check-in by the end of the window (FR-CARE-005).
    missed = _visit(plan, now - timedelta(hours=52))
    # A: two days ago, uploaded late, flags cleared, confirmed by a call checked by a second person, instructed.
    a = _visit(plan, now - timedelta(hours=30))
    _check(phone, "checkin", a, a.window_start + timedelta(minutes=5))
    _items(a, carer_person, phone, a.window_start + timedelta(minutes=30))
    _check(phone, "checkout", a, a.window_start + timedelta(minutes=70))
    a.refresh_from_db()
    services.record_call(a, cm, family_member=mother, note="Called Akosua Mensah. She confirmed Afia came, took "
                                                           "her blood pressure and brought the groceries [demo].")
    services.check_call(a, rv)
    _clear_flags(a, rv2)
    a.refresh_from_db()
    if a.status == "confirmed":
        services.prepare_payment(a, cm)
    # B: yesterday, checked out, every item answered; the family's code has gone out.
    b = _visit(plan, now - timedelta(hours=20))
    _check(phone, "checkin", b, b.window_start + timedelta(minutes=4))
    _items(b, carer_person, phone, b.window_start + timedelta(minutes=25))
    _check(phone, "checkout", b, b.window_start + timedelta(minutes=66))
    _clear_flags(b, rv2)
    # C: now, checked in, two tasks done.
    c = _visit(plan, now - timedelta(minutes=30), hours=3)
    _check(phone, "checkin", c, now - timedelta(minutes=25))
    _items(c, carer_person, phone, now - timedelta(minutes=10), all_items=False)
    services.missed_and_unconfirmed(now)
    refs["visits"] = {"missed": missed, "confirmed": a, "awaiting": b, "in_progress": c}

    # Concerns (FR-CARE-006): one actioned, one open.
    c1 = services.raise_concern(carer_person, visit=a, kind="welfare", severity="medium",
                                narrative="The fridge was nearly empty and she said she skipped lunch twice this "
                                          "week [demo].")
    services.action_concern(c1, rv, action_taken="Called the client and the nephew; agreed a weekly grocery order.",
                            client_outcome="We agreed a weekly grocery delivery with you. Afia brings it on Fridays.")
    services.raise_concern(carer_person, visit=c, kind="health", severity="high",
                           narrative="Blood pressure 165/100 on the second reading. She has a headache. Advised her "
                                     "to rest; asking the family about a doctor's visit [demo].")

    # A second plan the client still has to accept (US-CARE-001 AC3).
    draft = services.create_plan(client, client=client, family_member_id=mother.pk,
                                 items=[{"key": "escort", "kind": "hospital_visit",
                                         "label": "Go with her to her monthly check-up"}],
                                 schedule={"weekly": ["wed"], "window": "08:00-13:00"},
                                 visit_fee={"amount": "200.00", "currency": "GHS"}, confirmers=[mother.pk],
                                 notes="Monthly hospital escort")
    services.assign_carer(draft, cm, carer)
    refs["draft_plan"] = draft
