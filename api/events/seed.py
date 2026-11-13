"""EVT demo data through the real services: a funeral with verified vendors, a funded event escrow, a deposit
paid against a signed quote and a balance waiting for the client's approval after the family confirmed the
delivery; a vendor still being checked; and a naming ceremony being planned. Amounts are synthetic working
figures [TO VERIFY]."""
from datetime import timedelta

from django.utils import timezone


def _doc(gh, by, name, data=None, content_type="text/plain"):
    from evidence.services import store

    return store(data=data or f"Demo document: {name} [demo]".encode(), country=gh, uploaded_by=by,
                 content_type=content_type, original_name=name, description=name, data_class="escrow_payment")


def _photo(gh, by, name):
    from mobile.devtools import jpeg

    return _doc(gh, by, f"{name}.jpg", data=jpeg(f"evt-seed-{name}"), content_type="image/jpeg")


def _approve(req, *approvers):
    from core import approvals

    for a in approvers:
        req.refresh_from_db()
        if req.status == "open":
            approvals.decide(req, a, mfa_at=timezone.now(), note="Seed approval")


def _close_case(case, cm, rv):
    from cases import services as cs
    from evidence.services import link

    case.refresh_from_db()
    for t in case.tasks.filter(review_step=False).exclude(status__in=["done", "cancelled"]).order_by("position"):
        for kind in t.required_evidence:
            link(_doc(case.country, cm, f"{kind}-{case.reference}.txt"), "task", t.pk, role=kind, by=cm)
        cs.complete_task(t, cm, note="Checked [demo]")
    case.refresh_from_db()
    if case.status == "in_progress":
        cs.decide_verification(case, rv, outcome="verified")


def _vendor(e, people, *, kind, name, quote, number, account, signatory, nid_number, verify=True):
    from . import services

    cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
    gh = e.country
    v = services.add_vendor(e, e.client, kind=kind, name=name, registration_number=number,
                            registration_evidence_id=_doc(gh, e.client, f"registration-{number}.txt").pk,
                            contact_name=signatory, contact_phone="", quote={"amount": quote, "currency": "GHS"},
                            quote_evidence_id=_doc(gh, e.client, f"signed-quote-{number}.txt").pk)
    if not verify:
        return v
    p = services.register_vendor_payee(v, cm, legal_name=name, bank_name="Demo Commercial Bank [TO VERIFY]",
                                       account_number=account, account_name_source="bank_name_check",
                                       signatory_name=signatory, signatory_id_number=nid_number)
    if p.approval_request_id:
        _approve(p.approval_request, rv, rv2)
    _close_case(v.verification_case, cm, rv)
    v.refresh_from_db()
    return v


def _funeral(gh, people, ctx):
    from escrow import services as esc

    from . import services

    client, cm, rv = people["client"], people["cm"], people["reviewer"]
    mother = ctx["family_members"]["mother"]
    e = services.create_event(client, country=gh, kind="funeral", name="Funeral of Opanyin Kwame Mensah",
                              event_date=timezone.localdate() + timedelta(days=24), locality="Aburi",
                              budget={"amount": "60000.00", "currency": "GHS"},
                              confirmer_family_member_id=mother.pk)
    home = _vendor(e, people, kind="funeral_home", name="Accra Funeral Home Ltd", quote="18000.00", number="CS-1001",
                   account="1100810081008", signatory="Kofi Adjei", nid_number="GHA-700000051-1")
    food = _vendor(e, people, kind="caterer", name="Mama Esi Catering Services", quote="15000.00", number="BN-2002",
                   account="1100820082008", signatory="Esi Arthur", nid_number="GHA-700000052-2")
    _vendor(e, people, kind="tent_and_chairs", name="Royal Tents and Chairs", quote="6500.00", number="BN-3003",
            account="1100830083008", signatory="Nana Royal", nid_number="GHA-700000053-3", verify=False)
    escrow = services.open_escrow(e, client)
    for party in escrow.parties.filter(must_accept=True, role="tenmina"):
        esc.accept_terms(escrow, cm, party=party)
    esc.record_virtual_account(escrow, cm, virtual_account_ref="VA-GH-EVT-0001")
    ev = esc.record_bank_event(escrow, kind="deposit", amount="45000.00", bank_reference="DEP-EVT-0001", by=cm,
                               source="manual", proof_evidence=_doc(gh, cm, "credit-advice-evt-0001.txt"),
                               source_bank_name="NatWest [demo]", source_account_number="GB29NWBK60161331926819",
                               source_account_name="AMA MENSAH")
    esc.check_bank_event(ev, rv)
    # Deposit to the funeral home against its signed quote, paid by the bank.
    dep = services.propose_payment(e, cm, vendor_id=home.pk, kind="deposit", amount={"amount": "9000.00",
                                                                                     "currency": "GHS"},
                                   description="Deposit: mortuary and hearse")
    services.client_approve(dep, client, mfa_at=timezone.now())
    dep.refresh_from_db()
    ins = dep.release_instruction
    esc.staff_approve(ins, people["reviewer"], mfa_at=timezone.now())
    esc.staff_approve(ins, people["reviewer2"], mfa_at=timezone.now())
    ins.refresh_from_db()
    if ins.status == "sent":
        bev = esc.record_bank_event(escrow, kind="release_confirmed", amount=ins.amount, bank_reference="BANK-EVT-0001",
                                    by=cm, source="manual", instruction=ins,
                                    proof_evidence=_doc(gh, cm, "debit-advice-evt-0001.txt"))
        esc.check_bank_event(bev, rv)
    # The caterer's balance: invoice and photos in, the family confirmed; waiting for the client (orange).
    bal = services.propose_payment(e, cm, vendor_id=food.pk, kind="full", amount={"amount": "15000.00",
                                                                                  "currency": "GHS"},
                                   invoice_evidence_id=_doc(gh, cm, "invoice-mama-esi.txt").pk,
                                   delivery_evidence_ids=[_photo(gh, cm, "food-served").pk],
                                   description="Food for 300 guests")
    from notifications import services as ntf

    conf = ntf.confirmation_status("event_vendor_payment", bal.pk)
    conf = ntf.record_call(conf, by=cm, outcome="confirm", note="Called Akosua Mensah: the food was served. [demo]")
    ntf.check_call(conf, by=rv)
    bal.refresh_from_db()
    ntf.resolve_action(bal)  # demo inbox: the home screen still shows it in orange from its state
    return e


def _naming(gh, people):
    from . import services

    e = services.create_event(people["client"], country=gh, kind="naming", name="Naming ceremony for baby Adwoa",
                              event_date=timezone.localdate() + timedelta(days=60), locality="Madina",
                              budget={"amount": "8000.00", "currency": "GHS"})
    services.add_vendor(e, people["client"], kind="caterer", name="Madina Small Chops",
                        quote={"amount": "3000.00", "currency": "GHS"})
    return e


def run(ctx):
    from administration import flags

    from .models import Event

    gh, people = ctx.get("gh"), ctx.get("people", {})
    if gh is None or "cm" not in people or "family_members" not in ctx or not flags.enabled("lines.evt", gh) \
            or not (ctx.get("escrow") or {}).get("programme_accounts"):
        return
    existing = {e.name: e for e in Event.objects.filter(country=gh)}
    if existing:
        ctx["evt"] = {"events": existing}
        return
    funeral = _funeral(gh, people, ctx)
    ctx["evt"] = {"events": {funeral.name: funeral, "Naming ceremony for baby Adwoa": _naming(gh, people)}}
