"""Demo field work in Ghana for every field role, in several states:

- Kobby Builders (contractor): two projects. Foundation evidence submitted and clean; roofing photo taken
  far from the plot, flagged and waiting for a reviewer.
- Kwesi (inspector): foundation inspection recorded as pass with defects.
- Afia (carer): one visit checked in and out at the house; another checked in 2 km away, flagged, then
  cleared by a reviewer with a note.
- Yaa (errand agent), Efua (runner), Kojo (surveyor): assigned work waiting in their inbox.
Phones use deterministic keys so the seed is repeatable.
"""
import hashlib
import uuid
from datetime import timedelta

from django.utils import timezone

from . import crypto
from .devtools import FakePhone, jpeg, mp4
from .models import Assignment, CheckIn, Device, FraudFlag, SignedManifest, Submission

NS = uuid.UUID("0b9c3e6e-8a3c-4a65-a1b1-5c3e2f0d7a11")
EAST_LEGON = [[5.6502, -0.1805], [5.6502, -0.1797], [5.6496, -0.1797], [5.6496, -0.1805]]
KASOA = [[5.5345, -0.4260], [5.5345, -0.4253], [5.5338, -0.4253], [5.5338, -0.4260]]
FOUNDATION_EVIDENCE = [
    {"key": "trench_depth_photo", "label": "Trench depth with tape measure", "media": "photo", "required": True},
    {"key": "rebar_photo", "label": "Rebar before the pour", "media": "photo", "required": True},
    {"key": "trench_walk_video", "label": "Walk along the trench", "media": "video", "required": True},
]


def sid(name):
    return uuid.uuid5(NS, name)


def _phone(person, name, **kw):
    phone = FakePhone(person, seed=f"tenmina-seed-{name}", **kw)
    fp = hashlib.sha256(crypto.b64decode_any(phone.public_key)).hexdigest()
    dev = Device.objects.filter(key_fingerprint=fp).first()
    if dev:
        phone.device = dev
        last = SignedManifest.objects.filter(device=dev).order_by("-received_at").first()
        phone.previous = last.item_sha256 if last else None
    else:
        phone.register()
    return phone


def _assign(person, subject_id, title, country, by, **fields):
    from .services import assign

    a = Assignment.objects.filter(person=person, subject_id=subject_id, status="active").first()
    return a or assign(person=person, subject_id=subject_id, title=title, country=country, by=by, **fields)


def _item(phone, client_item_id, subject_type, subject_id, data, **kw):
    from .services import complete_item, register_item

    m = SignedManifest.objects.filter(person=phone.person, client_item_id=client_item_id).first()
    if m is None:
        payload = phone.capture(subject_type, subject_id, data, client_item_id=client_item_id, **kw)
        m, _ = register_item(phone.person, payload, app_version="1.0.0")
    if m.status != "stored":
        m, _ = complete_item(m, phone.person, data)
    return m


def _check(phone, client_item_id, kind, subject_type, subject_id, **kw):
    from .services import record_checkin

    m = SignedManifest.objects.filter(person=phone.person, client_item_id=client_item_id).first()
    if m is not None:
        return CheckIn.objects.get(manifest=m)
    ci, _ = record_checkin(phone.person, phone.check(kind, subject_type, subject_id,
                                                     client_item_id=client_item_id, **kw), kind)
    return ci


def _flags(ctx):
    from administration.models import FeatureFlag

    for app in ("field", "client"):
        for platform in ("android", "ios"):
            for name, value in ((f"app.min_version.{app}.{platform}", "1.0.0"),
                                (f"app.latest_version.{app}.{platform}", "1.0.0")):
                FeatureFlag.objects.get_or_create(name=name, country=None,
                                                  defaults={"enabled": True, "value": value, "owner": "founder"})


def run(ctx):
    from .services import review_flag, submit, submit_inspection

    _flags(ctx)
    gh, p = ctx["gh"], ctx["people"]
    cm, now = p["cm"], timezone.now()

    # Assignments: the built-in inbox provider (line modules add their own later).
    ms_a, ms_b = sid("milestone-a-foundation"), sid("milestone-b-roofing")
    insp_a = sid("inspection-a-foundation")
    visit_1, visit_2 = sid("care-visit-1"), sid("care-visit-2")
    step_1, task_r, task_s = sid("errand-step-birth-cert"), sid("task-runner-site"), sid("task-surveyor-boundary")
    _assign(p["contractor"], ms_a, "East Legon house: foundation", gh, cm, subject_type="milestone",
            kind="milestone", address="Plot 14, East Legon, Accra", boundary=EAST_LEGON, buffer_m=50,
            required_evidence=FOUNDATION_EVIDENCE, project_key="project-east-legon",
            previous_pass_at=now - timedelta(days=30), due_at=now + timedelta(days=3))
    _assign(p["contractor"], ms_b, "Kasoa shop: roofing", gh, cm, subject_type="milestone", kind="milestone",
            address="Kasoa new town, plot 3", boundary=KASOA, buffer_m=50, project_key="project-kasoa",
            required_evidence=[{"key": "roof_photo", "label": "Roof sheets fixed", "media": "photo",
                                "required": True}], due_at=now + timedelta(days=5))
    _assign(p["inspector"], insp_a, "Inspect foundation, East Legon", gh, cm, subject_type="milestone_inspection",
            kind="inspection", address="Plot 14, East Legon, Accra", point_lat="5.649900", point_lng="-0.180100",
            boundary=EAST_LEGON, radius_m=100, project_key="project-east-legon",
            checklist=[{"key": "trench_depth", "label": "Trench depth as drawn"},
                       {"key": "rebar_spacing", "label": "Rebar spacing"},
                       {"key": "concrete_mix", "label": "Concrete mix and cover"}])
    _assign(p["carer"], visit_1, "Visit Auntie Comfort (morning)", gh, cm, subject_type="care_visit",
            kind="care_visit", address="House 7, Dansoman, Accra", point_lat="5.551500", point_lng="-0.262800",
            radius_m=100, min_visit_minutes=30, details={"family_first_name": "Comfort"},
            plan_items=[{"key": "bp", "label": "Blood pressure", "needs": "reading"},
                        {"key": "meds", "label": "Medicines taken", "needs": "tick"},
                        {"key": "kitchen", "label": "Kitchen stocked", "needs": "photo"}],
            due_at=now - timedelta(hours=1))
    _assign(p["carer"], visit_2, "Visit Auntie Comfort (evening)", gh, cm, subject_type="care_visit",
            kind="care_visit", address="House 7, Dansoman, Accra", point_lat="5.551500", point_lng="-0.262800",
            radius_m=100, min_visit_minutes=30, details={"family_first_name": "Comfort"},
            due_at=now + timedelta(hours=6))
    _assign(p["agent"], step_1, "Collect birth certificate copy", gh, cm, subject_type="errand_step",
            kind="errand_step", address="Births and Deaths Registry, Accra", point_lat="5.556000",
            point_lng="-0.196900", radius_m=150,
            required_evidence=[{"key": "receipt", "label": "Official receipt", "media": "photo", "required": True}])
    _assign(p["runner"], task_r, "Photograph the beacons, East Legon", gh, cm, subject_type="task", kind="task",
            address="Plot 14, East Legon, Accra", boundary=EAST_LEGON, project_key="project-east-legon",
            required_evidence=[{"key": "beacon_photo", "label": "Each corner beacon", "media": "photo",
                                "required": True}])
    _assign(p["surveyor"], task_s, "Boundary survey, Kasoa", gh, cm, subject_type="task", kind="task",
            address="Kasoa new town, plot 3", boundary=KASOA, project_key="project-kasoa")

    # Phones
    ct = _phone(p["contractor"], "contractor", platform="android", key_security="tee")
    _phone(p["contractor"], "contractor-iphone", platform="ios")
    insp = _phone(p["inspector"], "inspector", platform="ios")
    carer = _phone(p["carer"], "carer", platform="android", key_security="software", model="TECNO-KG5")
    for key in ("agent", "runner", "surveyor"):
        _phone(p[key], key, platform="android", key_security="strongbox", model="SM-A145F")

    # Contractor, project A: three clean items, submitted.
    when = now - timedelta(hours=2)
    a1 = _item(ct, str(sid("a1")), "milestone", ms_a, jpeg("seed-a1", model=ct.model), lat=5.6499, lng=-0.1801,
               requirement_key="trench_depth_photo", captured_at=when)
    a2 = _item(ct, str(sid("a2")), "milestone", ms_a, jpeg("seed-a2", model=ct.model), lat=5.6500, lng=-0.1800,
               requirement_key="rebar_photo", captured_at=when + timedelta(minutes=3))
    a3 = _item(ct, str(sid("a3")), "milestone", ms_a, mp4("seed-a3"), media_type="video/mp4", lat=5.6498,
               lng=-0.1802, requirement_key="trench_walk_video", captured_at=when + timedelta(minutes=5))
    submit(p["contractor"], client_submission_id=str(sid("sub-a")), subject_type="milestone", subject_id=ms_a,
           note="Foundation trench dug and rebar placed",
           items=[{"requirement_key": "trench_depth_photo", "evidence_id": str(a1.evidence_id)},
                  {"requirement_key": "rebar_photo", "evidence_id": str(a2.evidence_id)},
                  {"requirement_key": "trench_walk_video", "evidence_id": str(a3.evidence_id)}])

    # Contractor, project B: photo taken in Accra, 25 km from the Kasoa plot. Flagged and held.
    b1 = _item(ct, str(sid("b1")), "milestone", ms_b, jpeg("seed-b1", model=ct.model), lat=5.6037, lng=-0.1870,
               requirement_key="roof_photo", captured_at=now - timedelta(minutes=40))
    submit(p["contractor"], client_submission_id=str(sid("sub-b")), subject_type="milestone", subject_id=ms_b,
           items=[{"requirement_key": "roof_photo", "evidence_id": str(b1.evidence_id)}], note="Roof done")

    # Inspector: one defect photo, then pass with defects.
    d1 = _item(insp, str(sid("d1")), "milestone_inspection", insp_a, jpeg("seed-d1", model=insp.model, make="Apple"),
               lat=5.6499, lng=-0.1801, requirement_key="defect_1", captured_at=now - timedelta(minutes=20))
    submit_inspection(p["inspector"], client_submission_id=str(sid("insp-a")), subject_type="milestone_inspection",
                      subject_id=insp_a, outcome="pass_with_defects",
                      checklist=[{"key": "trench_depth", "result": "ok"}, {"key": "rebar_spacing", "result": "ok"},
                                 {"key": "concrete_mix", "result": "not_ok", "note": "Cover too thin at north wall"}],
                      defects=[{"description": "Concrete cover under 50 mm at the north wall",
                                "value": {"amount": "1200.00", "currency": "GHS"},
                                "evidence_ids": [str(d1.evidence_id)]}])

    # Carer: visit 1 in and out at the house (45 minutes); visit 2 checked in 2 km away.
    _check(carer, str(sid("v1-in")), "checkin", "care_visit", visit_1, lat=5.5516, lng=-0.2627,
           captured_at=now - timedelta(minutes=50))
    _check(carer, str(sid("v1-out")), "checkout", "care_visit", visit_1, lat=5.5514, lng=-0.2629,
           captured_at=now - timedelta(minutes=5))
    far = _check(carer, str(sid("v2-in")), "checkin", "care_visit", visit_2, lat=5.5690, lng=-0.2560,
                 captured_at=now - timedelta(minutes=2))
    f = FraudFlag.objects.filter(checkin=far, kind="outside_address_radius", status="open").first()
    if f:
        review_flag(f, p["reviewer"], "clear", "Called the family: Auntie Comfort was at the clinic with the carer.")

    ctx["mobile"] = {"milestone_a": ms_a, "milestone_b": ms_b, "inspection_a": insp_a, "visit_1": visit_1,
                     "visit_2": visit_2, "errand_step": step_1,
                     "submission_a": Submission.objects.get(client_submission_id=str(sid("sub-a")))}
