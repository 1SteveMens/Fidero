"""TSK demo data (J-12), built through the real services: a complete Ghana errand catalogue in the country's
configuration, a vetted agent with an agreement, an official agency as a verified payee, and errands in several
states. Every fee, charge and target time is a working assumption [TO VERIFY], not a published tariff."""
import hashlib
import uuid

from django.utils import timezone

NS = uuid.UUID("6f5a3c1e-8b2d-4f0a-9c3e-2d1b0a9e8f71")

CATALOGUE = [
    {"code": "ghana_card_renewal", "name": "Ghana Card renewal", "agency": "National Identification Authority",
     "description": "Renew or replace a Ghana Card for you or a relative.",
     "checklist": [{"key": "old_card", "label": "Current Ghana Card, both sides"},
                   {"key": "passport_photo", "label": "Passport photo, white background"},
                   {"key": "birth_cert", "label": "Birth certificate", "required": False}],
     "official_fees": {"amount": "100.00", "currency": "GHS"}, "tenmina_charge": "35.00", "target_days": 21,
     "steps": [{"key": "lodge", "description": "Lodge the renewal at the NIA office", "official_fee": "100.00",
                "documents": ["old_card", "passport_photo"]},
               {"key": "collect", "description": "Collect the new card", "official_fee": "0.00"}],
     "office": {"address": "NIA head office, Accra [demo]", "lat": 5.5600, "lng": -0.2050}},
    {"code": "birth_cert", "name": "Birth certificate copy", "agency": "Births and Deaths Registry",
     "checklist": [{"key": "parent_id", "label": "A parent's Ghana Card"},
                   {"key": "hospital_record", "label": "Hospital birth record or weighing card"}],
     "official_fees": {"amount": "120.00", "currency": "GHS"}, "tenmina_charge": "40.00", "target_days": 14,
     "steps": [{"key": "lodge", "description": "Lodge the application at the registry", "official_fee": "120.00",
                "documents": ["parent_id", "hospital_record"]},
               {"key": "collect", "description": "Collect the certified copy", "official_fee": "0.00"}],
     "office": {"address": "Births and Deaths Registry, Accra [demo]", "lat": 5.5560, "lng": -0.1969}},
    {"code": "passport_renewal", "name": "Passport renewal support", "agency": "Passport Office",
     "checklist": [{"key": "old_passport", "label": "Current passport, photo page"},
                   {"key": "ghana_card", "label": "Ghana Card"},
                   {"key": "photos", "label": "Two passport photos"}],
     "official_fees": {"amount": "500.00", "currency": "GHS"}, "tenmina_charge": "60.00", "target_days": 30,
     "steps": [{"key": "book", "description": "Book the appointment", "official_fee": "0.00"},
               {"key": "lodge", "description": "Lodge the application and pay the fee", "official_fee": "500.00",
                "documents": ["old_passport", "ghana_card", "photos"]},
               {"key": "collect", "description": "Collect the passport", "official_fee": "0.00"}]},
    {"code": "land_search", "name": "Official land search", "agency": "Lands Commission",
     "checklist": [{"key": "site_plan", "label": "Site plan"},
                   {"key": "indenture", "label": "Indenture, if you have one", "required": False}],
     "official_fees": {"amount": "200.00", "currency": "GHS"}, "tenmina_charge": "50.00", "target_days": 21,
     "steps": [{"key": "lodge", "description": "Lodge the search request", "official_fee": "200.00",
                "documents": ["site_plan"]},
               {"key": "collect", "description": "Collect the search report", "official_fee": "0.00"}]},
    {"code": "business_reg", "name": "Business registration", "agency": "Office of the Registrar of Companies",
     "checklist": [{"key": "ghana_card", "label": "Ghana Card of each owner"},
                   {"key": "business_name", "label": "Proposed business name and activity"}],
     "official_fees": {"amount": "250.00", "currency": "GHS"}, "tenmina_charge": "80.00", "target_days": 21,
     "steps": [{"key": "file", "description": "File the registration", "official_fee": "250.00",
                "documents": ["ghana_card", "business_name"]},
               {"key": "collect", "description": "Collect the certificate", "official_fee": "0.00"}]},
    {"code": "utility_transfer", "name": "Utility account transfer", "agency": "ECG / Ghana Water",
     "checklist": [{"key": "ghana_card", "label": "Ghana Card"},
                   {"key": "title_or_tenancy", "label": "Title, indenture or tenancy agreement"}],
     "official_fees": {"amount": "0.00", "currency": "GHS"}, "tenmina_charge": "25.00", "target_days": 10,
     "steps": [{"key": "apply", "description": "Submit the transfer form", "official_fee": "0.00",
                "documents": ["ghana_card", "title_or_tenancy"]},
               {"key": "confirm", "description": "Get the new account confirmation", "official_fee": "0.00"}]},
    {"code": "land_title_application", "name": "Land title application", "agency": "Lands Commission",
     "checklist": [{"key": "site_plan", "label": "Site plan signed by a licensed surveyor"},
                   {"key": "indenture", "label": "Stamped indenture"},
                   {"key": "ghana_card", "label": "Ghana Card"}],
     "official_fees": {"amount": "800.00", "currency": "GHS"}, "tenmina_charge": "120.00", "target_days": 90,
     "steps": [{"key": "lodge", "description": "Lodge the title application", "official_fee": "800.00",
                "documents": ["site_plan", "indenture", "ghana_card"]},
               {"key": "follow_up", "description": "Follow up at the Commission", "official_fee": "0.00"},
               {"key": "collect", "description": "Collect the land title certificate", "official_fee": "0.00"}]},
]


def demo_id(name):
    return uuid.uuid5(NS, name)


def _publish_catalogue(gh, admin):
    from countries.selectors import current_config
    from countries.services import seed_publish

    cur = current_config(gh)
    items = (cur.data or {}).get("errand_catalogue") or []
    if items and all(isinstance(i, dict) and i.get("checklist") for i in items):
        return
    seed_publish(gh, dict(cur.data, errand_catalogue=CATALOGUE), by=admin)
    gh.refresh_from_db()


def _ev(gh, by, name, data_class="identity_documents"):
    from evidence.services import store

    return store(data=f"%PDF-1.4\n% Demo document: {name} [demo]\n".encode(), country=gh, uploaded_by=by,
                 content_type="application/pdf", original_name=f"{name}.pdf", data_class=data_class)


def _agent_person(gh, people):
    from accounts.models import Person, RoleGrant, Vetting
    from accounts.seed import DEV_PASSWORD
    from accounts.services import complete_vetting, create_vetting, request_national_id_check

    p = Person.objects.filter(email="kofi.agent@example.com").first()
    if p is None:
        p = Person.objects.create_user("kofi.agent@example.com", DEV_PASSWORD, full_name="Kofi Mensah-Bonsu",
                                       home_country=gh, residence_country="GH", email_verified_at=timezone.now())
        p.phone, p.phone_verified_at = "+233240000071", timezone.now()
        p.save(update_fields=["phone", "phone_verified_at"])
        RoleGrant.objects.create(person=p, role="CE")
    v = Vetting.objects.filter(person=p, kind="errand_agent").first()
    if v is None:
        cm, rv = people["cm"], people["reviewer"]
        chk = request_national_id_check(by=cm, country=gh, subject_role="errand_agent", subject_name=p.full_name,
                                        id_number="GHA-700000051-5", person=p)
        v = create_vetting(cm, p, kind="errand_agent", country=gh, national_id_check=chk,
                           references_evidence=_ev(gh, cm, "agent-references", "account"),
                           background_check_evidence=_ev(gh, cm, "agent-police-report", "account"))
        complete_vetting(v, rv)
    return p


def _agency_payee(gh, people, name, number, id_number):
    from accounts.models import Organisation
    from accounts.services import request_national_id_check
    from core import approvals
    from escrow import services as esc
    from escrow.models import Payee

    cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
    org, _ = Organisation.objects.get_or_create(name=name, kind="agency", country=gh)
    p = Payee.objects.filter(subject_type="organisation", subject_id=org.pk, kind="agency").first()
    if p is None:
        chk = request_national_id_check(by=cm, country=gh, subject_role="signatory",
                                        subject_name=f"Finance officer, {name}", id_number=id_number)
        p = esc.create_payee(cm, country=gh, kind="agency", subject_type="organisation", subject_id=org.pk,
                             legal_name=name, legal_name_evidence=_ev(gh, cm, f"registration-{number}", "payee"),
                             bank_name="Bank of Ghana revenue account [TO VERIFY]", account_number=number,
                             account_name_source="bank_name_check", organisation=org, national_id_check=chk)
    if p.verification_status == "pending" and p.name_match == "matched":
        esc.prepare_verification(p, cm)
        p.refresh_from_db()
        for a in (rv, rv2):
            req = p.approval_request
            req.refresh_from_db()
            if req.status == "open":
                approvals.decide(req, a, mfa_at=timezone.now(), note="Seed approval")
        p.refresh_from_db()
    return p


def _phone(person, name):
    from mobile import crypto
    from mobile.devtools import FakePhone
    from mobile.models import Device, SignedManifest

    phone = FakePhone(person, seed=f"tenmina-seed-{name}", key_security="strongbox", model="SM-A145F")
    fp = hashlib.sha256(crypto.b64decode_any(phone.public_key)).hexdigest()
    dev = Device.objects.filter(key_fingerprint=fp).first()
    if dev:
        phone.device = dev
        last = SignedManifest.objects.filter(device=dev).order_by("-received_at").first()
        phone.previous = last.item_sha256 if last else None
    else:
        phone.register()
    return phone


def _photo(phone, subject_type, subject_id, key, lat=5.5560, lng=-0.1969):
    from mobile.devtools import jpeg
    from mobile.services import complete_item, register_item

    data = jpeg(f"errand-seed-{subject_id}-{key}", model=phone.model)
    m, _ = register_item(phone.person, phone.capture(subject_type, subject_id, data, requirement_key=key, lat=lat,
                                                     lng=lng), app_version="1.0.0")
    m, _ = complete_item(m, phone.person, data)
    return m.evidence_id


def _ready(e, client, cm, terms):
    """Upload every document, submit, Tenmina accepts them, the charge is paid."""
    from orders.services import mark_paid

    from . import services

    for d in e.documents.all():
        services.upload_document(e, client, d.key, evidence=_ev(e.country, client, f"{e.catalogue_key}-{d.key}"))
    services.submit_errand(e, client, **terms)
    for d in e.documents.all():
        services.review_document(d, cm, accept=True)
    e.refresh_from_db()
    mark_paid(e.fee_order_id, payment_id=demo_id(f"pay:{e.pk}"), method="card")
    e.refresh_from_db()
    return e


def run(ctx):
    from orders import legal

    from . import services
    from .models import Agent, Errand

    gh, people = ctx.get("gh"), ctx.get("people", {})
    if gh is None or not people:
        return
    admin, cm, client = people["admin"], people["cm"], people["client"]
    _publish_catalogue(gh, admin)
    refs = ctx.setdefault("errands", {})
    agent_person = _agent_person(gh, people)
    people["agent2"] = agent_person
    agent = Agent.objects.filter(person=agent_person).first() or services.add_agent(
        cm, person=agent_person, pro_agreement_id=demo_id("pro-agreement:kofi"))
    refs["agent"] = agent
    if not (ctx.get("escrow") or {}).get("payees"):
        return  # escrow is off in this database; errands still order, but no fee can be paid
    refs["agency_payee"] = bd = _agency_payee(gh, people, "Births and Deaths Registry (demo)", "2010101010101",
                                              "GHA-700000061-6")
    refs["nia_payee"] = _agency_payee(gh, people, "National Identification Authority (demo)", "2020202020202",
                                      "GHA-700000062-7")
    if Errand.objects.filter(client=client).exists():
        refs["errands"] = {e.catalogue_key: e for e in Errand.objects.filter(client=client)}
        return
    cur = legal.current(gh)
    terms = {"terms_version": cur["terms_version"], "scope_version": cur["scope_version"]}
    fams = ctx.get("family_members") or {}
    phone = _phone(agent_person, "agent-kofi")
    out = refs["errands"] = {}

    # 1. Ghana Card renewal: ordered, one document still missing (the client must act).
    e1 = services.create_errand(client, country=gh, code="ghana_card_renewal")
    services.upload_document(e1, client, "old_card", evidence=_ev(gh, client, "ghana-card-front-back"))
    out["ghana_card_renewal"] = e1

    # 2. Passport renewal: submitted, a photo rejected (documents pending).
    e2 = services.create_errand(client, country=gh, code="passport_renewal")
    for d in e2.documents.all():
        services.upload_document(e2, client, d.key, evidence=_ev(gh, client, f"passport-{d.key}"))
    services.submit_errand(e2, client, **terms)
    services.review_document(e2.documents.get(key="photos"), cm, accept=False,
                             reason="The photos have a coloured background. The Passport Office needs white.")
    out["passport_renewal"] = e2

    # 3. Birth certificate for the nephew: funded, assigned, step 1 acknowledged, its fee instructed (waiting for
    #    the client's approval; official fees go only to the registry's verified account).
    e3 = services.create_errand(client, country=gh, code="birth_cert",
                                for_family_member_id=fams["nephew"].pk if fams.get("nephew") else None)
    e3 = _ready(e3, client, cm, terms)
    if e3.status == "funded":
        services.assign(e3, cm, agent=agent, agency_payee=bd)
        s1 = e3.steps.get(seq=1)
        services.record_step_proof(s1, agent_person, kind="acknowledgement",
                                   evidence_id=_photo(phone, "errand_step", s1.pk, "acknowledgement"))
        services.prepare_step_fee(s1, cm)
    out["birth_cert"] = e3

    # 4. Utility transfer (no official fee): every step done, the result checked, handed to a courier.
    e4 = services.create_errand(client, country=gh, code="utility_transfer")
    e4 = _ready(e4, client, cm, terms)
    if e4.status == "funded":
        services.assign(e4, cm, agent=agent, agency_payee=None)
        for s in e4.steps.all():
            kind = "acknowledgement" if s.seq == 1 else "receipt"
            services.record_step_proof(s, agent_person, kind=kind,
                                       evidence_id=_photo(phone, "errand_step", s.pk, kind))
            services.complete_step(s, agent_person)
        services.upload_result(e4, agent_person, evidence_id=_photo(phone, "errand", e4.pk, "result"))
        services.check_result(e4, people["reviewer"], accept=True, note="ECG letter matches the client's name.")
        e4.refresh_from_db()
        from evidence.models import Evidence

        waybill = Evidence.objects.get(pk=_photo(phone, "errand", e4.pk, "handover"))
        services.record_handover(e4, agent_person, method="courier", proof_kind="photo", evidence=waybill,
                                 courier_name="DHL Ghana [demo]", tracking_reference="DHL-GH-0042-DEMO")
    out["utility_transfer"] = e4
    services.target_watch()
