"""PMG demo data, built through the real services so every rule runs: a licensed property inspector, a
vetted contractor panel with verified payees, and properties in several states (onboarding, managed with a
tenancy, rent received and late from the owner's own account statement, a repair paid after an inspection
pass, a repair waiting for the owner's choice of quote). Every amount is a synthetic working figure
[TO VERIFY], not market data."""
import uuid
from datetime import date, timedelta

from django.utils import timezone

NS = uuid.UUID("9d6f2a8e-3c41-4f0b-8a55-2f7c0b1d4e21")


def demo_id(name):
    return uuid.uuid5(NS, name)


def _doc(gh, by, name, text=None, content_type="text/plain", data=None):
    from evidence.services import store

    return store(data=data or (text or f"Demo document: {name} [demo]").encode(), country=gh, uploaded_by=by,
                 content_type=content_type, original_name=name, description=name, data_class="tenancy")


def _photo(gh, by, name):
    from mobile.devtools import jpeg

    return _doc(gh, by, f"{name}.jpg", data=jpeg(f"pmg-seed-{name}"), content_type="image/jpeg")


def _approve(req, *approvers):
    from core import approvals

    for a in approvers:
        req.refresh_from_db()
        if req.status == "open":
            approvals.decide(req, a, mfa_at=timezone.now(), note="Seed approval")


def _person(email, name, role, gh, phone):
    from accounts.models import Person
    from accounts.services import grant_role

    p = Person.objects.filter(email=email).first()
    if p is None:
        p = Person.objects.create_user(email=email, password="tenmina-dev-123", full_name=name, phone=phone,
                                       home_country=gh, residence_country="GH")
        p.email_verified_at = p.phone_verified_at = timezone.now()
        p.save(update_fields=["email_verified_at", "phone_verified_at"])
    if not p.has_tenmina_role(role):
        grant_role(p, role, country=gh)
    return p


def _inspector(gh, people):
    """A property inspector with a verified licence (RUL-20)."""
    from accounts.models import ProfessionalLicence
    from accounts.services import add_licence, verify_licence

    p = _person("property.inspector@example.com", "Akwasi Property Inspector", "IN", gh, "+233240000041")
    if not ProfessionalLicence.objects.filter(person=p, role="IN", status="verified").exists():
        lic = ProfessionalLicence.objects.filter(person=p, role="IN").first() or add_licence(
            people["admin"], p, role="IN", body="Engineering Council [TO VERIFY]", number="EC/DEMO/0041",
            expires_on=date.today() + timedelta(days=500), country=gh)
        verify_licence(lic, people["reviewer"])
    return p


def _nid(gh, cm, name, number, person, role="signatory"):
    from accounts.models import NationalIdCheck
    from accounts.normalise import bidx
    from accounts.services import request_national_id_check

    chk = NationalIdCheck.objects.filter(id_number_bidx=bidx(number), subject_role=role).first()
    return chk or request_national_id_check(by=cm, country=gh, subject_role=role, subject_name=name,
                                            id_number=number, person=person)


def _vet(gh, people, person, nid):
    from accounts.models import Vetting
    from accounts.services import complete_vetting, create_vetting

    v = Vetting.objects.filter(person=person, kind="contractor").first()
    if v is None:
        v = create_vetting(people["cm"], person, kind="contractor", country=gh, national_id_check=nid,
                           references_evidence=_doc(gh, people["cm"], f"references-{person.pk}.txt"),
                           background_check_evidence=_doc(gh, people["cm"], f"background-{person.pk}.txt"))
    if v.status == "pending":
        complete_vetting(v, people["reviewer"])
    return v


def _contractor(gh, people, *, key, email, name, org_name, phone, number, account):
    from accounts.models import Membership, Organisation
    from escrow import services as esc
    from escrow.models import Payee

    cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
    person = _person(email, name, "CT", gh, phone)
    org, _ = Organisation.objects.get_or_create(name=org_name, kind="contractor", country=gh)
    if not Membership.objects.filter(organisation=org, person=person).exists():
        Membership.objects.create(organisation=org, person=person, org_role="admin", added_by=people["admin"])
    nid = _nid(gh, cm, name, number, person)
    p = Payee.objects.filter(subject_type="organisation", subject_id=org.pk, kind="contractor").first()
    if p is None:
        p = esc.create_payee(cm, country=gh, kind="contractor", subject_type="organisation", subject_id=org.pk,
                             legal_name=org_name, legal_name_evidence=_doc(gh, cm, f"registration-{key}.txt"),
                             bank_name="Demo Commercial Bank [TO VERIFY]", account_number=account,
                             account_name_source="bank_name_check", person=person, organisation=org,
                             national_id_check=nid)
    if p.verification_status == "pending" and p.approval_request_id is None:
        esc.prepare_verification(p, cm)
    if p.approval_request_id:
        _approve(p.approval_request, rv, rv2)
    p.refresh_from_db()
    _vet(gh, people, person, nid)
    return person, p


def _panel(gh, people, ctx):
    out = {}
    kobby_payee = (ctx.get("escrow") or {}).get("payees", {}).get("contractor")
    if kobby_payee is not None and kobby_payee.verification_status == "verified":
        _vet(gh, people, people["contractor"], kobby_payee.national_id_check)
        out["kobby"] = (people["contractor"], kobby_payee)
    out["roof"] = _contractor(gh, people, key="roof", email="roofworks@example.com", name="Yaw Roofworks",
                              org_name="Tema Roofworks Ltd", phone="+233240000042", number="GHA-700000042-1",
                              account="1100660066006")
    out["plumb"] = _contractor(gh, people, key="plumb", email="plumbing@example.com", name="Esi Plumbing",
                               org_name="Coastal Plumbing Services", phone="+233240000043", number="GHA-700000043-2",
                               account="1100770077007")
    if "kobby" not in out:
        out["kobby"] = out["plumb"]
    return out


def _phone(person, name):
    import hashlib

    from mobile import crypto
    from mobile.devtools import FakePhone
    from mobile.models import Device, SignedManifest

    phone = FakePhone(person, seed=f"pmg-seed-{name}")
    fp = hashlib.sha256(crypto.b64decode_any(phone.public_key)).hexdigest()
    dev = Device.objects.filter(key_fingerprint=fp).first()
    if dev:
        phone.device = dev
        last = SignedManifest.objects.filter(device=dev).order_by("-received_at").first()
        phone.previous = last.item_sha256 if last else None
    else:
        phone.register()
    return phone


def capture(phone, insp, key, name):
    """An app photo of the inspection, signed by the inspector's phone (RUL-08)."""
    from mobile.devtools import jpeg
    from mobile.services import complete_item, register_item

    data = jpeg(f"pmg-{insp.pk}-{name}", model=phone.model, when=timezone.now())
    m, _ = register_item(phone.person, phone.capture("property_inspection", insp.pk, data, requirement_key=key),
                         app_version="1.0.0")
    m, _ = complete_item(m, phone.person, data)
    return m.evidence


def _close_case(case, cm, rv, outcome="verified"):
    from cases import services as cs
    from evidence.services import link

    case.refresh_from_db()
    for t in case.tasks.filter(review_step=False).exclude(status__in=["done", "cancelled"]).order_by("position"):
        for kind in t.required_evidence:
            ev = _doc(case.country, cm, f"{kind}-{case.reference}.txt")
            link(ev, "task", t.pk, role=kind, by=cm)
        cs.complete_task(t, cm, note="Checked [demo]")
    case.refresh_from_db()
    if case.status == "in_progress":
        cs.decide_verification(case, rv, outcome=outcome, note="" if outcome == "verified" else "Demo refusal")


def _escrow_through(e, people, ref, amount):
    from escrow import services as esc

    cm, rv = people["cm"], people["reviewer"]
    for party in e.parties.filter(must_accept=True, role="tenmina"):
        esc.accept_terms(e, cm, party=party)
    esc.record_virtual_account(e, cm, virtual_account_ref=ref)
    ev = esc.record_bank_event(e, kind="deposit", amount=amount, bank_reference=f"DEP-{ref}", by=cm, source="manual",
                               proof_evidence=_doc(e.country, cm, f"credit-advice-{ref}.txt"),
                               source_bank_name="NatWest [demo]", source_account_number="GB29NWBK60161331926819",
                               source_account_name="AMA MENSAH")
    esc.check_bank_event(ev, rv)


def _pay(ins, people, ref):
    from escrow import services as esc

    client = ins.escrow.client
    esc.client_approve(ins, client, timezone.now())
    esc.staff_approve(ins, people["reviewer"], mfa_at=timezone.now())
    esc.staff_approve(ins, people["reviewer2"], mfa_at=timezone.now())
    ins.refresh_from_db()
    if ins.status == "sent":
        ev = esc.record_bank_event(ins.escrow, kind="release_confirmed", amount=ins.amount, bank_reference=ref,
                                   by=people["cm"], source="manual", instruction=ins,
                                   proof_evidence=_doc(ins.country, people["cm"], f"debit-advice-{ref}.txt"))
        esc.check_bank_event(ev, people["reviewer"])
    return ins


def _statement(acct_number, rows):
    lines = ["account_number,booked_on,kind,amount,currency,bank_reference,counterparty_name,narrative"]
    for r in rows:
        lines.append(",".join([r.get("account", acct_number), r["on"].isoformat(), "credit", r["amount"], "GHS",
                               r["ref"], r.get("who", "KWABENA TENANT"), r.get("text", "")]))
    return ("\n".join(lines) + "\n").encode()


def _first_of_month(d, back):
    y, m = divmod(d.month - 1 - back, 12)
    return date(d.year + y, m + 1, 1)


def _managed_house(gh, people, ctx, inspector, panel):
    from . import services
    from .models import Inspection

    client, cm, rv = people["client"], people["cm"], people["reviewer"]
    prop = services.register_property(client, country=gh, title="House at Tema Community 25",
                                      locality="Tema Community 25", address="Hse 14, Lane 3, Community 25, Tema",
                                      region="Greater Accra", district="Tema Metropolitan",
                                      ownership_evidence_ids=[_doc(gh, client, "indenture-tema-25.txt").pk])
    services.set_rent_account(prop, client, ctx["bank_accounts"]["rent"].pk)
    phone = _phone(inspector, "inspector")
    insp = services.onboarding_inspection(prop)
    services.assign_inspector(insp, cm, inspector)
    front, living = capture(phone, insp, "room_front", "front"), capture(phone, insp, "room_living", "living")
    kitchen = capture(phone, insp, "room_kitchen", "kitchen")
    services.record_inspection(insp, inspector, outcome="pass", condition_rating="good", rooms=[
        {"room": "Front", "condition": "good", "evidence_ids": [str(front.pk)]},
        {"room": "Living room", "condition": "good", "evidence_ids": [str(living.pk)]},
        {"room": "Kitchen", "condition": "fair", "note": "Stain on the ceiling", "evidence_ids": [str(kitchen.pk)]}],
        checklist=[{"key": "roof", "result": "ok"}], notes="Four bedrooms, sound structure. [demo]")
    _close_case(prop.onboarding_case, cm, rv)
    prop.refresh_from_db()
    today = timezone.localdate()
    m = services.record_mandate(prop, client, mandate_evidence_id=_doc(gh, client, "statement-mandate-ama.txt").pk,
                                valid_from=_first_of_month(today, 4))
    services.acknowledge_mandate(m, cm, evidence_id=_doc(gh, cm, "bank-ack-mandate-ama.txt").pk,
                                 statement_ref="RENT-GH-DEMO-TEMA25")
    start = _first_of_month(today, 3)
    t = services.record_tenancy(prop, cm, tenant_email=people["tenant"].email, tenant_name=people["tenant"].full_name,
                                agreement_evidence_id=_doc(gh, cm, "tenancy-agreement-tema-25.txt").pk,
                                rent={"amount": "3500.00", "currency": "GHS"}, period="monthly", due_day=5,
                                starts_on=start, tenant_reference="TEMA25-KWABENA")
    acct = ctx["bank_accounts"]["rent"].account_number
    m0, m1, m3 = _first_of_month(today, 3), _first_of_month(today, 2), _first_of_month(today, 0)
    data = _statement(acct, [
        {"on": m0 + timedelta(days=3), "amount": "3500.00", "ref": "TRF-DEMO-0001", "text": "RENT TEMA25-KWABENA"},
        {"on": m1 + timedelta(days=4), "amount": "3500.00", "ref": "TRF-DEMO-0002", "text": "TEMA25-KWABENA"},
        {"on": m3 + timedelta(days=5), "amount": "3500.00", "ref": "TRF-DEMO-0004", "text": "HOUSE RENT"},
        {"on": m3 + timedelta(days=7), "amount": "120.00", "ref": "TRF-DEMO-0005", "text": "WATER BILL SHARE",
         "who": "UNKNOWN SENDER"},
        {"on": m3 + timedelta(days=2), "amount": "900.00", "ref": "TRF-DEMO-0099", "text": "OTHER ACCOUNT",
         "account": "0099999999999"},
    ])
    services.import_rent_statement(prop, cm, data=data, original_name="tema25-statement.csv", source="file")
    services.rent_watch(today)

    # A repair paid after an inspection pass (FR-PMG-005), from the tenant's report to the bank's confirmation.
    tenant = people["tenant"]
    r = services.report_repair(tenant, prop, title="Leaking roof over the kitchen",
                               description="Water comes through the kitchen ceiling when it rains.",
                               photo_ids=[_photo(gh, tenant, "leak-report").pk])
    (roofer, roof_payee), (kob, kob_payee) = panel["roof"], panel["kobby"]
    q1 = services.add_quote(r, cm, contractor=roofer, payee=roof_payee, amount={"amount": "6400.00",
                                                                                 "currency": "GHS"},
                            evidence_id=_doc(gh, cm, "quote-roofworks.txt").pk,
                            valid_until=today + timedelta(days=30), description="Replace 12 sheets and flashing")
    services.add_quote(r, cm, contractor=kob, payee=kob_payee, amount={"amount": "7900.00", "currency": "GHS"},
                       evidence_id=_doc(gh, cm, "quote-kobby.txt").pk, valid_until=today + timedelta(days=30))
    services.approve_quote(r, client, quote_id=q1.pk, confirm_amount={"amount": "6400.00", "currency": "GHS"},
                           mfa_at=timezone.now())
    r.refresh_from_db()
    _escrow_through(r.escrow, people, "VA-GH-PMG-0001", "6400.00")
    services.record_work_done(r, roofer, evidence_ids=[_photo(gh, roofer, "roof-done").pk], note="Roof replaced")
    rinsp = Inspection.objects.get(repair=r, status="scheduled")
    services.assign_inspector(rinsp, cm, inspector)
    done = capture(phone, rinsp, "work_photo", "roof-check")
    services.record_inspection(rinsp, inspector, outcome="pass", photo_ids=[str(done.pk)],
                               checklist=[{"key": "work_complete", "result": "ok"}], notes="Roof is dry. [demo]")
    ins = services.prepare_instruction(r, cm)
    _pay(ins, people, "BANK-DEMO-PMG-0001")

    # A repair waiting for the owner's choice of quote (needs action, orange).
    r2 = services.report_repair(tenant, prop, title="Broken gate lock", description="The gate lock is broken.",
                                photo_ids=[_photo(gh, tenant, "gate-lock").pk])
    (plumber, plumb_payee) = panel["plumb"]
    services.add_quote(r2, cm, contractor=plumber, payee=plumb_payee, amount={"amount": "450.00", "currency": "GHS"},
                       evidence_id=_doc(gh, cm, "quote-gate-1.txt").pk, valid_until=today + timedelta(days=21))
    services.add_quote(r2, cm, contractor=roofer, payee=roof_payee, amount={"amount": "520.00", "currency": "GHS"},
                       evidence_id=_doc(gh, cm, "quote-gate-2.txt").pk, valid_until=today + timedelta(days=21))
    _quiet(r2)
    # The next periodic inspection, assigned (shows in the inspector's My jobs).
    services.schedule_inspection(prop, cm, kind="periodic", scheduled_for=today + timedelta(days=10),
                                 inspector=inspector)
    return prop, t


def _quiet(obj):
    """Demo messages only: the home screen still shows the item in orange from its state, but the seeded
    inbox keeps only the other modules' demo actions."""
    from notifications.services import resolve_action

    resolve_action(obj)


def _onboarding_flat(gh, people, ctx, inspector):
    from . import services

    client, cm = people["client"], people["cm"]
    prop = services.register_property(client, country=gh, title="Flat at East Legon", locality="East Legon",
                                      address="Flat 2B, Boundary Road, East Legon", region="Greater Accra",
                                      ownership_evidence_ids=[_doc(gh, client, "land-title-east-legon.txt").pk])
    services.set_rent_account(prop, client, ctx["bank_accounts"]["rent"].pk)
    services.assign_inspector(services.onboarding_inspection(prop), cm, inspector)
    return prop


def _new_house(gh, people):
    from . import services

    return services.register_property(people["client"], country=gh, title="Family house in Kumasi",
                                      locality="Ahodwo, Kumasi", region="Ashanti",
                                      ownership_evidence_ids=[_doc(gh, people["client"],
                                                                   "site-plan-kumasi.txt").pk])


def run(ctx):
    from administration import flags

    from .models import ManagedProperty

    gh, people = ctx.get("gh"), ctx.get("people", {})
    if gh is None or "cm" not in people or "bank_accounts" not in ctx or not flags.enabled("lines.pmg", gh):
        return
    inspector = _inspector(gh, people)
    panel = _panel(gh, people, ctx)
    ctx["pmg"] = refs = {"inspector": inspector, "panel": panel}
    existing = {p.title: p for p in ManagedProperty.objects.filter(country=gh)}
    if existing:
        refs["properties"] = existing
        return
    house, tenancy = _managed_house(gh, people, ctx, inspector, panel)
    refs["properties"] = {house.title: house, "Flat at East Legon": _onboarding_flat(gh, people, ctx, inspector),
                          "Family house in Kumasi": _new_house(gh, people)}
    refs["tenancy"] = tenancy
