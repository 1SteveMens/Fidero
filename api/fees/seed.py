"""FEE demo data: institutions in every state and family payments on both routes, built through the real
services so every rule runs. Every amount is a synthetic figure [TO VERIFY], not real data.

- Accra Hills School (demo): verified, paid from held funds (the bills escrow's seed already instructed).
- Komfo Anokye Teaching Hospital (demo): verified, verify and confirm (client_direct): bills waiting for the
  client's approval, for the client's transfer, for the hospital's confirmation, and paid waiting for a receipt.
- Tema Community Clinic (demo): pending verification, with a runner collecting a bill.
- Mama Esi Chemist (demo): not eligible for direct payment (cash only). No cash route exists.
- Accra Hilis School (demo): a look-alike name waiting for a reviewer.
"""
from datetime import timedelta

from django.utils import timezone


def _demo_id(name):
    from escrow.seed import demo_id

    return demo_id(name)


def _doc(gh, by, name, ct="application/pdf"):
    from core.ids import uuid7
    from evidence.services import store

    head = b"\xff\xd8\xff\xe0 " if ct == "image/jpeg" else b"%PDF-1.4 "
    return store(data=head + f"Demo document: {name} ".encode() + uuid7().bytes, country=gh, uploaded_by=by,
                 content_type=ct, original_name=f"{name}.{'jpg' if ct == 'image/jpeg' else 'pdf'}",
                 description=name, data_class="family_payment")


def complete_case(case, cm, rv, outcome="verified", note="Registered with the regulator [demo]."):
    """Do every check of a verification case with evidence, then the reviewer decides (CASE)."""
    from cases import services as cases

    gh = case.country
    for t in case.tasks.filter(review_step=False).order_by("position"):
        t.refresh_from_db()
        if t.status in ("done", "cancelled"):
            continue
        if t.site_visit:
            cases.record_risk_screen(case, cm, task=t, outcome="proceed", people_required=1)
        for k in t.required_evidence:
            ct = "image/jpeg" if "photo" in k else "application/pdf"
            cases.attach_task_evidence(t, cm, _doc(gh, cm, f"{case.reference}-{k}", ct), k)
        cases.complete_task(t, cm)
    case.refresh_from_db()
    return cases.decide_verification(case, rv, outcome=outcome, note=note)


def verify_payee(payee, cm, rv, rv2):
    from core import approvals
    from escrow import services as esc

    payee.refresh_from_db()
    if payee.verification_status == "pending" and payee.name_match == "matched":
        esc.prepare_verification(payee, cm)
        payee.refresh_from_db()
        for a in (rv, rv2):
            req = payee.approval_request
            req.refresh_from_db()
            if req.status == "open":
                approvals.decide(req, a, mfa_at=timezone.now(), note="Seed approval")
        payee.refresh_from_db()
    return payee


def verified_institution(gh, people, *, name, type, reg, account, contact_person=None, contact_name="",
                         contact_phone="", nid="GHA-700000031-4", client=None, returns_confirmation=False,
                         with_contact=True):
    """Register, verify the registration case, record and verify the account, name the contact."""
    from fees import services

    cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
    client = client or people["client"]
    reg_ev = _doc(gh, cm, f"registration-{reg}")
    inst, _ = services.register_institution(cm, country=gh, type=type, legal_name=name, registration_number=reg,
                                            address="Accra [demo]", phone="+233302000000",
                                            returns_confirmation=returns_confirmation,
                                            registration_evidence=reg_ev, client=client)
    complete_case(inst.verification_case, cm, rv)
    p = services.create_payee(inst, cm, bank_name="Demo Commercial Bank [TO VERIFY]", account_number=account,
                              account_name_source="bank_name_check", signatory_name=f"{name} signatory",
                              signatory_id_number=nid)
    verify_payee(p, cm, rv, rv2)
    if with_contact:
        services.add_contact(inst, cm, full_name=contact_name or getattr(contact_person, "full_name", "Accounts office"),
                             phone=contact_phone, person=contact_person, role_title="Accounts officer",
                             evidence=_doc(gh, cm, f"contact-call-{reg}"))
    inst.refresh_from_db()
    return inst


def _invoice(gh, by, inst, fm, ref, amount, **kw):
    from fees import services

    return services.submit_invoice(by, institution=inst, family_member=fm, institution_reference=ref, amount=amount,
                                   currency="GHS", evidence=_doc(gh, by, f"bill-{ref}"),
                                   due_on=timezone.localdate() + timedelta(days=kw.pop("due_in", 14)), **kw)


def _check(inv, cm, contact):
    from fees import services

    return services.check_invoice(inv, cm, outcome="checked", contact=contact, note="Confirmed by phone [demo]")


def _approve(inv, client):
    from fees import services

    return services.client_approve(inv, client, mfa_at=timezone.now(),
                                   confirm_amount={"amount": str(inv.amount), "currency": inv.currency},
                                   confirm_payee_account_name=inv.institution.payee.account_name)


def _school(gh, people, ctx):
    """Accra Hills School (demo): verified; adopts the payee escrow's seed already verified, and ties the two
    fee_invoice instructions escrow seeded to real FEE bills (held_funds route)."""
    from escrow.models import ReleaseInstruction
    from fees import services
    from fees.models import Invoice, Payment

    cm, rv, client = people["cm"], people["reviewer"], people["client"]
    payee = (ctx.get("escrow") or {}).get("payees", {}).get("school")
    inst, _ = services.register_institution(cm, country=gh, type="school", legal_name="Accra Hills School (demo)",
                                            registration_number="GES/DEMO/0042", address="East Legon, Accra",
                                            returns_confirmation=True, client=client,
                                            registration_evidence=_doc(gh, cm, "registration-accra-hills"),
                                            organisation=(ctx.get("orgs") or {}).get("school"))
    complete_case(inst.verification_case, cm, rv)
    if payee is not None and inst.payee_id is None:
        inst.payee = payee
        inst.save(update_fields=["payee"])
    services.add_contact(inst, cm, full_name="School Bursar", person=people["institution"], role_title="Bursar",
                         phone="+233240000011", evidence=_doc(gh, cm, "bursar-confirmation"))
    inst.refresh_from_db()
    mother = (ctx.get("family_members") or {}).get("mother")
    nephew = (ctx.get("family_members") or {}).get("nephew")
    contact = inst.contacts.filter(status="active").first()
    if inst.status == "verified" and mother is not None:
        for key, ref, label, amount in (("invoice:term1", "AHS-2026-T1-0042", "Term 1 fees", "6500.00"),
                                        ("invoice:books", "AHS-2026-BK-0042", "Books and uniform", "1200.00")):
            ins = ReleaseInstruction.objects.filter(subject_type="fee_invoice", subject_id=_demo_id(key)).first()
            if ins is None or Invoice.objects.filter(pk=_demo_id(key)).exists():
                continue
            ev = _doc(gh, client, f"bill-{ref}")
            t = ins.created_at
            inv = Invoice.objects.create(
                id=_demo_id(key), country=gh, client=client, family_member=mother, institution=inst,
                institution_reference=ref, description=label, amount=ins.amount, currency=ins.currency,
                due_on=timezone.localdate(), submitted_by="client", submitted_by_person=client, evidence=ev,
                evidence_sha256=ev.sha256, check_status="checked", contact_confirmed_by=contact,
                contact_confirmed_at=t, checked_by=cm, checked_at=t, route="held_funds", client_approved_at=t,
                client_approval_method="mfa_step_up", status="instructed")
            services._link(ev, "fee_invoice", inv.pk, "invoice", client)
            pay = Payment.objects.create(country=gh, invoice=inv, route="held_funds", amount=inv.amount,
                                         currency=inv.currency, escrow=ins.escrow, release_instruction=ins,
                                         status="instructed")
            if ins.status == "confirmed":
                services._mark_paid(pay, bank_reference=ins.sent_reference or "PAY-HF-0001")
                pay.refresh_from_db()
                services.add_receipt(pay, cm, receipt_evidence=_doc(gh, cm, f"receipt-{ref}"),
                                     confirmation_evidence=_doc(gh, cm, f"enrolment-{ref}"))
    if nephew is not None and inst.status == "verified" and not inst.schedules.exists():
        services.create_schedule(client, institution=inst, family_member=nephew, period="term",
                                 expected_amount="6500.00", currency="GHS",
                                 next_due_on=timezone.localdate() + timedelta(days=10), reminder_lead_days=14,
                                 label="Accra Hills School term fees for Kojo")
        services.schedule_due()
    return inst


def run(ctx):
    from administration import flags
    from fees import services
    from fees.models import Institution

    gh, people = ctx["gh"], ctx["people"]
    if not flags.enabled("lines.fee", gh):
        return
    refs = ctx.setdefault("fees", {})
    if Institution.objects.filter(country=gh).exists():
        for inst in Institution.objects.filter(country=gh):
            refs[inst.legal_name] = inst
        return
    cm, rv, rv2, client = people["cm"], people["reviewer"], people["reviewer2"], people["client"]
    fams = ctx.get("family_members") or {}
    mother, nephew = fams.get("mother"), fams.get("nephew")

    refs["school"] = _school(gh, people, ctx)

    # Verify and confirm (client_direct, the launch model in Ghana).
    hosp = verified_institution(gh, people, name="Komfo Anokye Teaching Hospital (demo)", type="hospital",
                                reg="HEFRA/DEMO/0007", account="1100667788990", contact_name="Grace Owusu",
                                contact_phone="+233322000007")
    refs["hospital"] = hosp
    contact = hosp.contacts.filter(status="active").first()
    if mother is not None:
        # 1. Checked, waiting for the client's approval (orange on the dashboard).
        inv1 = _invoice(gh, client, hosp, mother, "KATH-2026-11-0187", "1850.00", description="Ward bill",
                        name_on_invoice="Akosua Mensah")
        _check(inv1, cm, contact)
        # 2. Approved: the client pays the hospital's verified account directly.
        inv2 = _invoice(gh, client, hosp, mother, "KATH-2026-10-0099", "640.00", description="Pharmacy",
                        due_in=5)
        _check(inv2, cm, contact)
        _approve(inv2, client)
        # 3. The client says they paid; the hospital is confirming.
        inv3 = _invoice(gh, client, hosp, mother, "KATH-2026-10-0042", "420.00", description="Clinic review",
                        due_in=2)
        _check(inv3, cm, contact)
        _approve(inv3, client)
        services.report_client_payment(inv3.payments.get(), client, reference="NATWEST-TRF-55120 [demo]")
        # 4. Paid and confirmed by the hospital; the receipt is late (TC-FEE-004-02).
        inv4 = _invoice(gh, client, hosp, mother, "KATH-2026-09-0311", "2300.00", description="Surgery deposit",
                        due_in=-20)
        _check(inv4, cm, contact)
        _approve(inv4, client)
        pay4 = inv4.payments.get()
        services.report_client_payment(pay4, client, reference="NATWEST-TRF-41007 [demo]")
        services.confirm_received(pay4, cm, method="contact_call", contact=contact,
                                  note="Grace Owusu confirmed the credit on the hospital's statement [demo]")
        pay4.refresh_from_db()
        from fees.models import Payment

        Payment.objects.filter(pk=pay4.pk).update(receipt_due_at=timezone.now() - timedelta(days=1))
        services.receipt_overdue()
        # 5. Fully receipted.
        inv5 = _invoice(gh, client, hosp, mother, "KATH-2026-08-0120", "300.00", description="Lab tests",
                        due_in=-60)
        _check(inv5, cm, contact)
        _approve(inv5, client)
        pay5 = inv5.payments.get()
        services.confirm_received(pay5, cm, method="receipt", note="Receipt handed in [demo]",
                                  evidence=_doc(gh, cm, "receipt-KATH-2026-08-0120"))

    # Pending verification, with a runner collecting a paper bill.
    clinic, _ = services.register_institution(client, country=gh, type="clinic",
                                              legal_name="Tema Community Clinic (demo)",
                                              registration_number="HEFRA/DEMO/0019", address="Community 5, Tema",
                                              proposed_bank_name="Demo Savings Bank", proposed_account_number="2200991100")
    refs["clinic"] = clinic
    if nephew is not None:
        services.create_runner_task(clinic, cm, kind="collect_invoice", runner=people["runner"],
                                    family_member=nephew, due_at=timezone.now() + timedelta(days=2),
                                    instructions="Ask the front desk for Kojo Mensah's bill. Paper only, no money.")

    # Not eligible for direct payment: cash only (FR-FEE-006). No cash route exists.
    chemist, _ = services.register_institution(client, country=gh, type="pharmacy",
                                               legal_name="Mama Esi Chemist (demo)",
                                               registration_number="PC/DEMO/0101", address="Madina market")
    services.propose_not_eligible(chemist, cm, "Takes cash only; has no bank or mobile money account in its own "
                                               "name [demo].")
    services.decide_not_eligible(chemist, rv2, confirm=True)
    refs["chemist"] = chemist

    # A look-alike of a verified school, waiting for a reviewer (TC-SEC-33).
    look, _ = services.register_institution(people["client2"], country=gh, type="school",
                                            legal_name="Accra Hilis School (demo)",
                                            registration_number="GES/DEMO/9042",
                                            proposed_account_number="9990001112")
    refs["look_alike"] = look
    for inst in Institution.objects.filter(country=gh):
        refs[inst.legal_name] = inst
