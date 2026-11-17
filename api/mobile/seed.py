"""Demo field work, and the phone helpers the line modules' seeds use (`_phone`, `_item`).

Field work is always on a real subject from the module that owns it, so every inbox item opens: BLD's seed
captures and submits the builders' milestones and the inspector's inspection, CARE's seed checks the carer in
and out (one check-in 2 km from the house, flagged, then cleared by a reviewer), TSK's seed the errand
agent's steps, and CASE's the runner's site visit. This seed adds one photo the runner took far from the plot
on that real site visit: flagged outside the plot buffer and waiting for a reviewer.
Phones use deterministic keys so the seed is repeatable.
"""
import hashlib
import uuid
from datetime import timedelta

from django.utils import timezone

from core import samples

from . import crypto
from .devtools import FakePhone
from .models import CheckIn, Device, FraudFlag, SignedManifest

NS = uuid.UUID("0b9c3e6e-8a3c-4a65-a1b1-5c3e2f0d7a11")


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


def run(ctx):
    """Nothing before the line modules have seeded: see run_late."""


def run_late(ctx):
    """The runner's photo of the gate, taken in central Accra instead of at Kofi's plot in Dawhenya: stored,
    flagged outside the plot buffer and left open for a reviewer (FR-MOB-004). Late, once the plot has its
    surveyed boundary and position (REC's seed)."""
    from cases.models import Task

    case = (ctx.get("cases") or {}).get("kofi_land_offline_paid")
    runner = ctx["people"].get("runner")
    if case is None or runner is None:
        return
    task = Task.objects.filter(case=case, step_key="site_visit", assignee=runner,
                               status__in=["open", "in_progress"]).first()
    if task is None:
        return
    phone = _phone(runner, "runner", platform="android", key_security="strongbox", model="SM-A145F")
    key = task.required_evidence[0] if task.required_evidence else "site_photo"
    m = _item(phone, str(sid(f"runner-far-{task.pk}")), "task", task.pk,
              samples.photo("gate", "seed-runner-far", caption="Gate and beacon", model=phone.model),
              lat=5.6037, lng=-0.1870, requirement_key=key, captured_at=timezone.now() - timedelta(minutes=40))
    ctx["mobile"] = {"runner_task": task, "far_photo": m,
                     "flag": FraudFlag.objects.filter(evidence_id=m.evidence_id, kind="outside_buffer").first()}
