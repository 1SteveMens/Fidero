"""ESC demo data: programme accounts, programme rates, transfer partners, a
verified payee registry and escrows in every state, built through the real
services so every rule runs. Every amount, rate and fee is a working
assumption or a synthetic figure [TO VERIFY], not market data."""
import uuid
from datetime import timedelta

from django.utils import timezone

NS = uuid.UUID("2b9c1f0e-5d1a-4e4b-9a47-8e0a4f6c2d11")


def demo_id(name):
    return uuid.uuid5(NS, name)


def _ev(gh, by, name, text=None):
    from evidence.services import store

    return store(data=(text or f"Demo document: {name}").encode(), country=gh, uploaded_by=by,
                 content_type="text/plain", original_name=f"{name}.txt", description=name, data_class="escrow_payment")


def _approve(req, *approvers):
    from core import approvals

    for a in approvers:
        req.refresh_from_db()
        if req.status == "open":
            approvals.decide(req, a, mfa_at=timezone.now(), note="Seed approval")


def _nid(gh, cm, name, number, role="signatory", person=None):
    from accounts.models import NationalIdCheck
    from accounts.normalise import bidx
    from accounts.services import request_national_id_check

    chk = NationalIdCheck.objects.filter(id_number_bidx=bidx(number), subject_role=role).first()
    return chk or request_national_id_check(by=cm, country=gh, subject_role=role, subject_name=name, id_number=number,
                                            person=person)


def _partners(gh, admin, admin2):
    from administration import services as adm
    from administration.models import Partner

    out = {}
    specs = [("Remit Bridge [demo]", "0.90", "4.99", "0.00", "5000"),
             ("SendHome Transfers [demo]", "1.40", "0.00", "0.00", "10000"),
             ("DiasporaPay [demo]", "0.70", "9.00", "1.50", "3000")]
    for name, margin, fee, pays, limit in specs:
        p = Partner.objects.filter(country=gh, kind="transfer_partner", name=name).first()
        if p is None:
            p, _ = adm.create_partner(country=gh, kind="transfer_partner", name=name, by=admin, details={
                "margin_pct": margin, "fee": fee, "pays_tenmina": pays, "limit_per_transfer": limit,
                "max_transfers_per_day": 3, "corridors": ["USD/GHS", "GBP/GHS"], "licence": "[TO VERIFY]",
                "names_sender_on_credit": False})
        out[name] = p
    providers = [str(p.pk) for p in out.values()]
    _, cr = adm.change_setting(key="fx_comparison_providers", value=providers, by=admin, country=gh,
                               reason="Demo comparison providers [TO VERIFY]")
    if cr is not None:
        _approve(cr.approval_request, admin2)
    adm.change_setting(key="fx_comparison_amounts", value={"USD/GHS": ["1000.00", "10000.00"],
                                                          "GBP/GHS": ["1000.00"]}, by=admin, country=gh)
    return out


def _programme(gh, admin, admin2, bank, rate_source):
    from escrow import services
    from escrow.models import ProgrammeAccount, ProgrammeRate

    accts = {}
    for cur, number in (("GHS", "9040001234567"), ("USD", "9040001234575"), ("GBP", "9040001234583")):
        pa = ProgrammeAccount.objects.filter(country=gh, currency=cur, kind="programme").first()
        if pa is None:
            pa = services.create_programme_account(
                admin, country=gh, bank_partner=bank, currency=cur, account_number=number,
                account_name=f"Partner Bank Escrow Programme {cur} [TO VERIFY]",
                agreement_evidence=_ev(gh, admin, f"three-party-escrow-agreement-{cur}"))
            _approve(pa.approval_request, admin2)
            pa.refresh_from_db()
        accts[cur] = pa
    for cur in ("USD", "GBP"):
        if not ProgrammeRate.objects.filter(country=gh, from_currency=cur, to_currency="GHS").exists():
            pr = services.create_programme_rate(
                admin, country=gh, bank_partner=bank, from_currency=cur, to_currency="GHS", margin_pct="0.50",
                tolerance_pct="0.05", fee_schedule=[{"name": "Conversion fee", "amount": "10.00", "currency": cur,
                                                     "charged_by": bank.name}],
                reference_source=rate_source, valid_from=timezone.localdate() - timedelta(days=30),
                agreement_evidence=_ev(gh, admin, f"programme-rate-{cur}"))
            _approve(pr.approval_request, admin2)
    return accts


def _payee(gh, cm, rv, rv2, *, key, kind, subject_type, subject_id, legal_name, account_number, nid, person=None,
           organisation=None, source="bank_name_check", account_name="", verify=True):
    from escrow import services
    from escrow.models import Payee

    p = Payee.objects.filter(subject_type=subject_type, subject_id=subject_id, kind=kind).first()
    if p is None:
        p = services.create_payee(
            cm, country=gh, kind=kind, subject_type=subject_type, subject_id=subject_id, legal_name=legal_name,
            legal_name_evidence=_ev(gh, cm, f"registration-{key}"), bank_name="Demo Commercial Bank [TO VERIFY]",
            account_number=account_number, account_name=account_name, account_name_source=source,
            account_name_evidence=_ev(gh, cm, f"bank-letter-{key}") if source == "bank_letter" else None,
            person=person, organisation=organisation, national_id_check=nid)
    if verify and p.verification_status == "pending" and p.name_match == "matched":
        services.prepare_verification(p, cm)
        _approve(p.approval_request, rv, rv2)
        p.refresh_from_db()
    return p


def _accept_all(e, people, cm):
    from escrow import services
    from escrow.models import Party

    for party in Party.objects.filter(escrow=e, must_accept=True):
        if party.role == "tenmina":
            services.accept_terms(e, cm, party=party)
        elif party.person_id:
            services.accept_terms(e, party.person, party=party)
        else:
            services.accept_terms(e, cm, party=party, evidence=_ev(e.country, cm, f"signed-terms-{e.reference}"))


def _agree(e, people, cm, ref):
    from escrow import services

    _accept_all(e, people, cm)
    services.record_virtual_account(e, cm, virtual_account_ref=ref)
    e.refresh_from_db()
    return e


def _deposit(e, cm, rv, amount, ref, source_name="AMA MENSAH", source_number="GB29NWBK60161331926819"):
    from escrow import services

    ev = services.record_bank_event(e, kind="deposit", amount=amount, bank_reference=ref, by=cm, source="manual",
                                    proof_evidence=_ev(e.country, cm, f"bank-credit-advice-{ref}"),
                                    source_bank_name="NatWest [demo]", source_account_number=source_number,
                                    source_account_name=source_name)
    return services.check_bank_event(ev, rv)


def _close_all(e, cm):
    from escrow import services

    for c in e.conditions.filter(status="open", release_part="main"):
        services.close_condition(c, cm, evidence_ids=[_ev(e.country, cm, f"condition-{c.pk}").pk],
                                 note="Checked against the original [demo]")


def _release(e, cm, client, rv, rv2, **kw):
    from escrow import services

    ins = services.request_release(e, requested_by=cm, **kw)
    services.client_approve(ins, client, timezone.now())
    services.staff_approve(ins, rv, mfa_at=timezone.now())
    services.staff_approve(ins, rv2, mfa_at=timezone.now())
    ins.refresh_from_db()
    return ins


def _confirm(ins, cm, rv, ref):
    from escrow import services

    kind = "refund_confirmed" if ins.kind == "cancel_refund" else "release_confirmed"
    ev = services.record_bank_event(ins.escrow, kind=kind, amount=ins.amount, bank_reference=ref, by=cm,
                                    source="manual", instruction=ins,
                                    proof_evidence=_ev(ins.country, cm, f"bank-debit-advice-{ref}"))
    return services.check_bank_event(ev, rv)


def run(ctx):
    from administration.models import Partner
    from escrow import services
    from escrow.models import Escrow, ReportSnapshot

    gh, people = ctx["gh"], ctx["people"]
    cm, rv, rv2 = people["cm"], people["reviewer"], people["reviewer2"]
    admin, admin2, client = people["admin"], people["admin2"], people["client"]
    orgs, checks = ctx.get("orgs", {}), ctx.get("national_id_checks", {})
    bank = Partner.objects.filter(country=gh, kind="escrow_bank", status="active").first()
    rate_source = Partner.objects.filter(country=gh, kind="rate_source", status="active").first()
    if bank is None or rate_source is None or not orgs:
        return
    ctx["escrow"] = refs = {}
    if Escrow.objects.filter(country=gh).exists():
        from escrow.models import Payee, ProgrammeAccount

        keys = {"seller": ("ato", "seller"), "school": ("school", "institution"),
                "contractor": ("kobby", "contractor"), "developer": ("developer", "developer"),
                "insurer": ("insurer", "insurer")}
        refs["payees"] = {k: Payee.objects.filter(subject_id=orgs[o].pk, kind=kind).first()
                          for k, (o, kind) in keys.items()}
        refs["payees"]["carer"] = Payee.objects.filter(subject_id=people["carer"].pk, kind="carer").first()
        refs["payees"]["mismatch"] = Payee.objects.filter(subject_id=demo_id("supplier:cement")).first()
        refs["transfer_partners"] = {p.name: p for p in Partner.objects.filter(country=gh, kind="transfer_partner")}
        refs["programme_accounts"] = {a.currency: a for a in ProgrammeAccount.objects.filter(
            country=gh, kind="programme", status="active")}
        for e in Escrow.objects.filter(country=gh):
            refs[e.title] = e
        return
    refs["transfer_partners"] = _partners(gh, admin, admin2)
    refs["programme_accounts"] = _programme(gh, admin, admin2, bank, rate_source)

    # ---- the verified payee registry (ADR-17)
    seller_nid = checks.get("seller") or _nid(gh, cm, "Kwabena Owusu", "GHA-700000001-1", "seller")
    payees = {
        "seller": _payee(gh, cm, rv, rv2, key="ato", kind="seller", subject_type="organisation",
                         subject_id=orgs["ato"].pk, organisation=orgs["ato"], person=people["seller"],
                         legal_name="Ato Estates Ltd", account_number="1100223344556", nid=seller_nid),
        "school": _payee(gh, cm, rv, rv2, key="school", kind="institution", subject_type="organisation",
                         subject_id=orgs["school"].pk, organisation=orgs["school"], person=people["institution"],
                         legal_name="Accra Hills School (demo)", account_number="1100998877665",
                         nid=_nid(gh, cm, "School Bursar", "GHA-700000021-3", person=people["institution"])),
        "contractor": _payee(gh, cm, rv, rv2, key="kobby", kind="contractor", subject_type="organisation",
                             subject_id=orgs["kobby"].pk, organisation=orgs["kobby"], person=people["contractor"],
                             legal_name="Kobby Builders", account_number="1100554433221",
                             nid=_nid(gh, cm, "Kobby Builders", "GHA-700000022-4", person=people["contractor"])),
        "developer": _payee(gh, cm, rv, rv2, key="sunrise", kind="developer", subject_type="organisation",
                            subject_id=orgs["developer"].pk, organisation=orgs["developer"],
                            person=people["developer"], legal_name="Sunrise Homes Developers (demo)",
                            account_number="1100121212121",
                            nid=_nid(gh, cm, "Off-plan Developer", "GHA-700000023-5", person=people["developer"])),
        "carer": _payee(gh, cm, rv, rv2, key="carer", kind="carer", subject_type="person",
                        subject_id=people["carer"].pk, person=people["carer"], legal_name="Afia Carer",
                        account_number="0244000006000", nid=checks.get("carer")),
        "insurer": _payee(gh, cm, rv, rv2, key="insurer", kind="insurer", subject_type="organisation",
                          subject_id=orgs["insurer"].pk, organisation=orgs["insurer"], person=people["insurer"],
                          legal_name="Insurer Partner Ltd (demo)", account_number="1100777788889",
                          nid=_nid(gh, cm, "Insurer Partner", "GHA-700000024-6", person=people["insurer"])),
        # A bank letter in another name: shown red, and nobody can verify it (FR-ESC-015).
        "mismatch": _payee(gh, cm, rv, rv2, key="mismatch", kind="supplier", subject_type="supplier",
                           subject_id=demo_id("supplier:cement"), legal_name="Tema Cement Supplies Ltd",
                           account_number="1100345345345", source="bank_letter",
                           account_name="K. OFORI ENTERPRISE", nid=None, verify=False),
    }
    refs["payees"] = payees

    # ---- a released report (RPT publishes report.released; ESC keeps the facts it needs)
    def report(name, verdict="green"):
        rid = demo_id(f"report:{name}")
        ReportSnapshot.objects.get_or_create(report_id=rid, defaults=dict(
            country=gh, client=client, case_id=demo_id(f"case:{name}"), asset_id=demo_id(f"asset:{name}"),
            verdict=verdict, released_at=timezone.now(), conditions=[
                {"id": str(demo_id(f"cond:{name}:1")), "key": "family_consent", "text": "Family consent recorded"},
                {"id": str(demo_id(f"cond:{name}:2")), "key": "indenture_signed",
                 "text": "Indenture signed by the vendor and witnessed"}]))
        return rid

    seller_party = [{"role": "seller", "person": people["seller"], "organisation": orgs["ato"],
                     "name": "Ato Estates Ltd", "payee": payees["seller"], "national_id_check": seller_nid}]

    def purchase(title, price, name):
        return services.create_escrow(cm, kind="purchase", client=client, country=gh, agreed_amount=price,
                                      title=title, report_id=report(name), parties=seller_party)

    today = timezone.localdate()
    # 1. Proposed: waiting for the seller's acceptance.
    e1 = purchase("Plot at Kwabenya (proposed)", "250000.00", "kwabenya")
    services.accept_terms(e1, client)
    # 2. Funded, one condition still open, fresh search recorded.
    e2 = purchase("Plot at Oyarifa (funded)", "450000.00", "oyarifa")
    _agree(e2, people, cm, "VA-GH-000102")
    _deposit(e2, cm, rv, "450000.00", "DEP-OYA-0001")
    c = e2.conditions.filter(status="open").first()
    services.close_condition(c, cm, evidence_ids=[_ev(gh, cm, "family-consent-oyarifa").pk])
    services.record_fresh_search(e2, cm, case_id=demo_id("case:oyarifa-fresh"), registry_result_date=today,
                                 site_check_date=today)
    # 3. Ready, client approval waiting.
    e3 = purchase("Plot at Aburi (waiting for your approval)", "180000.00", "aburi")
    _agree(e3, people, cm, "VA-GH-000103")
    _deposit(e3, cm, rv, "180000.00", "DEP-ABU-0001")
    _close_all(e3, cm)
    services.record_fresh_search(e3, cm, case_id=demo_id("case:aburi-fresh"), registry_result_date=today,
                                 site_check_date=today - timedelta(days=2))
    services.request_release(e3.__class__.objects.get(pk=e3.pk), requested_by=cm)
    # 4. Released: the full journey J-02.
    e4 = purchase("Plot at Prampram (released)", "380000.00", "prampram")
    _agree(e4, people, cm, "VA-GH-000104")
    _deposit(e4, cm, rv, "380000.00", "DEP-PRA-0001")
    _close_all(e4, cm)
    services.record_fresh_search(e4, cm, case_id=demo_id("case:prampram-fresh"), registry_result_date=today,
                                 site_check_date=today)
    ins4 = _release(Escrow.objects.get(pk=e4.pk), cm, client, rv, rv2)
    if ins4.status == "sent":
        _confirm(ins4, cm, rv, "PAY-PRA-0001")
    # 5. Frozen by a failed re-check (RUL-32).
    e5 = purchase("Plot at Dodowa (on hold)", "150000.00", "dodowa")
    _agree(e5, people, cm, "VA-GH-000105")
    _deposit(e5, cm, rv, "150000.00", "DEP-DOD-0001")
    services.freeze(Escrow.objects.get(pk=e5.pk), kind="incident", source_id=demo_id("incident:dodowa"),
                    reason="A re-check found the site plan does not match the registry record [demo]")
    services.record_bank_position(Escrow.objects.get(pk=e5.pk), as_of=today - timedelta(days=1),
                                  reported_held_amount="149000.00", by=cm,
                                  proof_evidence=_ev(gh, cm, "bank-daily-report-dodowa"))
    from escrow.models import BankPosition

    services.check_bank_position(BankPosition.objects.filter(escrow=e5).first(), rv)
    services.record_bank_position(Escrow.objects.get(pk=e2.pk), as_of=today - timedelta(days=1),
                                  reported_held_amount="450000.00", source="api")

    # 6. Held funds for school fees and care visits (FR-ESC-014).
    hf = services.open_held_funds(client, gh, "GHS", by=client)
    services.record_virtual_account(hf, cm, virtual_account_ref="VA-GH-HF-000201")
    _deposit(Escrow.objects.get(pk=hf.pk), cm, rv, "20000.00", "DEP-HF-0001")
    _deposit(Escrow.objects.get(pk=hf.pk), cm, rv, "8000.00", "DEP-HF-0002")
    hf = Escrow.objects.get(pk=hf.pk)
    mother = ctx.get("family_members", {}).get("mother")
    paid = _release(hf, cm, client, rv, rv2, payee=payees["school"], amount="6500.00", subject_type="fee_invoice",
                    subject_id=demo_id("invoice:term1"), subject_label="Term 1 fees, Accra Hills School",
                    family_member_id=mother.pk if mother else None)
    if paid.status == "sent":
        _confirm(paid, cm, rv, "PAY-HF-0001")
    waiting = services.request_release(hf, requested_by=cm, payee=payees["school"], amount="1200.00",
                                       subject_type="fee_invoice", subject_id=demo_id("invoice:books"),
                                       subject_label="Books and uniform, Accra Hills School",
                                       family_member_id=mother.pk if mother else None)
    services.client_approve(waiting, client, timezone.now())
    services.create_standing_approval(hf, client, subject_kind="care_plan", subject_id=demo_id("care:mother"),
                                      monthly_max="1600.00", mfa_at=timezone.now())

    # 7. Construction, paid by milestone (FR-ESC-010).
    bld = services.open_line_escrow(kind="construction", client=client, country=gh, agreed_amount="600000.00",
                                    by=cm, title="House at Oyarifa (building in stages)",
                                    asset_id=demo_id("asset:oyarifa"), project_id=demo_id("project:oyarifa"),
                                    payees=[payees["contractor"]])
    _agree(bld, people, cm, "VA-GH-000107")
    _deposit(Escrow.objects.get(pk=bld.pk), cm, rv, "600000.00", "DEP-BLD-0001")
    m1 = _release(Escrow.objects.get(pk=bld.pk), cm, client, rv, rv2, payee=payees["contractor"],
                  amount="60000.00", subject_type="milestone", subject_id=demo_id("milestone:mobilisation"),
                  subject_label="Milestone 0: mobilisation")
    if m1.status == "sent":
        _confirm(m1, cm, rv, "PAY-BLD-0001")

    # 8. A payee change in its cooling-off (RUL-28) on the off-plan developer.
    off = services.open_line_escrow(kind="offplan", client=client, country=gh, agreed_amount="320000.00", by=cm,
                                    title="Off-plan house at Sunrise Estate", asset_id=demo_id("asset:sunrise"),
                                    project_id=demo_id("project:sunrise"), payees=[payees["developer"]])
    _agree(off, people, cm, "VA-GH-000108")
    ch = services.request_change(people["developer"], kind="new_account", payee=payees["developer"],
                                 escrow=Escrow.objects.get(pk=off.pk), reason="Moved banks [demo]",
                                 request_source="payee_signed_in", bank_name="Demo Savings Bank [TO VERIFY]",
                                 account_number="2200343434343", account_name_source="bank_name_check")
    services.change_identity_check(ch, cm, id_number="GHA-700000023-5", subject_name="Off-plan Developer")
    ch.refresh_from_db()
    if ch.status == "checks_passed":
        services.client_approve_change(ch, client, mfa_at=timezone.now())
        ch.refresh_from_db()
        _approve(ch.approval_request, rv, rv2)

    # 9. Today's rate comparison and a deposit quote on the funded purchase (RUL-35).
    try:
        services.collect_rates(gh)
        services.issue_quote(Escrow.objects.get(pk=e2.pk), client, purpose="deposit", route="transfer_partner",
                             from_currency="USD", from_amount="1000.00",
                             provider_partner=list(refs["transfer_partners"].values())[0])
    except Exception:  # noqa: BLE001 - demo extras never stop the seed
        import logging

        logging.getLogger("escrow").exception("fx demo data skipped")

    for e in Escrow.objects.filter(country=gh):
        refs[e.title] = e
