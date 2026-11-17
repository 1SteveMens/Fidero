"""Tenmina Field phones for every field role in Ghana, with deterministic keys so the seed is repeatable.

Field work itself is seeded by the module that owns its subject, on objects that exist, so every assignment,
capture, check-in and flag points at a real milestone, inspection, visit, errand step or case task:

- construction: Kobby's foundation evidence submitted and accepted; Esi's foundation inspection recorded as pass
  with defects; Mensah's blocks photo taken 25 km from the plot, flagged and held for a reviewer.
- care: Afia's visits checked in and out at the house (one uploaded late and cleared), and today's visit checked
  in 2 km away, flagged, then cleared by a reviewer with a note.
- errands: Kofi's acknowledgements, receipts, result and handover photos on real errand steps.
- cases: the runner's site visit and the surveyor's overlay check on Kofi's land case.

The helpers below (`_phone`, `_item`) are what those seeds use to capture through the real services.
"""
import hashlib

from . import crypto
from .devtools import FakePhone
from .models import Device, SignedManifest


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


def run(ctx):
    p = ctx["people"]
    _phone(p["contractor"], "contractor", platform="android", key_security="tee")
    _phone(p["contractor"], "contractor-iphone", platform="ios")
    _phone(p["inspector"], "inspector", platform="ios")
    _phone(p["carer"], "carer", platform="android", key_security="software", model="TECNO-KG5")
    for key in ("agent", "runner", "surveyor"):
        _phone(p[key], key, platform="android", key_security="strongbox", model="SM-A145F")
