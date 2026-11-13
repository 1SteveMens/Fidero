"""BLD demo data, built through the real services so every rule runs. Every amount, rate and period is a working
assumption or a synthetic figure [TO VERIFY].

Panel: Kobby Builders and Mensah Construction (active contractors with verified payees), Adom Builders
(pending: never offered), Esi Owusu (independent inspector), Kofi Asare (inspector who works for Kobby
Builders: a recorded link, never assigned to Kobby's work), Adjoa (quantity surveyor), Kwesi (inspector whose
licence is not verified yet: pending), Sunrise Homes (developer).

Projects for Ama:
- A. House at Millennium City, Kasoa: the launch route (client_direct). Mobilisation paid directly and
  confirmed by the builder; the foundation inspection is scheduled with Esi.
- B. Boys' quarters at Kasoa: the escrow route. The bank holds the money; mobilisation paid by the bank; the
  foundation passed with a defect held back and waits for Ama's approval; a variation waits for her agreement.
- C. Off-plan house at Sunrise Estate: the developer's off-plan check is in progress.
"""
import logging
import uuid
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.errors import DomainError

log = logging.getLogger("construction.seed")
NS = uuid.UUID("5d0c7e2a-9b1e-4f6a-8c3d-2e7b1a9f4c55")


def demo_id(name):
    return uuid.uuid5(NS, name)


def _ev(gh, by, name, kind="application/pdf"):
    from evidence.services import store

    data = (b"\xff\xd8\xff\xe0" + f"demo {name}".encode()) if kind == "image/jpeg" else f"%PDF-1.4 {name}".encode()
    return store(data=data, country=gh, uploaded_by=by, content_type=kind, original_name=f"{name}.pdf",
                 description=name)


def _person(gh, key, email, name, role, admin):
    from accounts.models import Person, RoleGrant
    from accounts.seed import DEV_MFA_SECRET, DEV_PASSWORD

    p = Person.objects.filter(email=email).first()
    if p is None:
        p = Person.objects.create_user(email, DEV_PASSWORD, full_name=name, home_country=gh, residence_country="GH",
                                       email_verified_at=timezone.now())
        RoleGrant.objects.create(person=p, role=role, granted_by=admin)
        p.mfa_secret, p.mfa_enabled = DEV_MFA_SECRET, True
        p.save(update_fields=["mfa_secret", "mfa_enabled"])
    return p


def _licence(p, role, number, admin, gh):
    from accounts.models import ProfessionalLicence

    if not ProfessionalLicence.objects.filter(person=p, role=role).exists():
        ProfessionalLicence.objects.create(
            person=p, role=role, country=gh, body="Engineering Council [TO VERIFY]", number=number,
            expires_on=timezone.localdate() + timedelta(days=365), status="verified", verified_by=admin,
            verified_on=timezone.localdate())


def _approve(req, *approvers):
    from core import approvals

    for a in approvers:
        req.refresh_from_db()
        if req.status == "open":
            approvals.decide(req, a, mfa_at=timezone.now(), note="Seed approval")


def _payee(gh, cm, rv, rv2, *, member, legal_name, number, nid_number):
    from accounts.models import NationalIdCheck
    from accounts.normalise import bidx
    from accounts.services import request_national_id_check
    from escrow import services as esc
    from escrow.models import Payee

    p = Payee.objects.filter(subject_type="panel_member", subject_id=member.pk).first()
    if p is None:
        nid = NationalIdCheck.objects.filter(id_number_bidx=bidx(nid_number)).first() or request_national_id_check(
            by=cm, country=gh, subject_role="payee", subject_name=legal_name, id_number=nid_number,
            person=member.person)
        p = esc.create_payee(cm, country=gh, kind="contractor", subject_type="panel_member", subject_id=member.pk,
                             legal_name=legal_name, legal_name_evidence=_ev(gh, cm, f"registration-{legal_name}"),
                             bank_name="Demo Commercial Bank [TO VERIFY]", account_number=number,
                             account_name_source="bank_name_check", person=member.person,
                             organisation=member.organisation, national_id_check=nid)
    if p.verification_status == "pending" and p.name_match == "matched":
        esc.prepare_verification(p, cm)
        _approve(p.approval_request, rv, rv2)
        p.refresh_from_db()
    return p


def _member(gh, by, admin, *, kind, name, person=None, organisation=None, docs=True):
    from . import panel
    from .models import PanelMember

    m = PanelMember.objects.filter(country=gh, kind=kind, name=name).first()
    if m is None:
        m = panel.create_member(by, country=gh, kind=kind, name=name, person=person, organisation=organisation,
                                registration_number=f"RGD/{abs(hash(name)) % 100000:05d} [demo]",
                                contact_phone="+233200000999")
        if docs:
            panel.add_documents(m, by, evidence_ids=[_ev(gh, by, f"registration-{name}").pk],
                                kind="registration_certificate")
    return m


def _activate(m, admin, outcome="verified"):
    from . import panel

    if m.kind in ("contractor", "developer") and not m.check_outcome:
        m.check_outcome = outcome
        m.save(update_fields=["check_outcome"])
    if m.status in ("pending", "vetted"):
        panel.approve(m, admin)
    m.refresh_from_db()
    return m


def _panel(ctx, gh, people):
    from accounts.models import Membership

    from . import panel

    cm, admin, rv, rv2 = people["cm"], people["admin"], people["reviewer"], people["reviewer2"]
    orgs = ctx.get("orgs", {})
    esc_payees = (ctx.get("escrow") or {}).get("payees", {})
    out = {}
    # Contractors.
    kobby = _member(gh, cm, admin, kind="contractor", name="Kobby Builders", person=people["contractor"],
                    organisation=orgs.get("kobby"))
    contractor_case = (ctx.get("cases") or {}).get("contractor")
    if contractor_case is not None and not kobby.check_case_id:
        kobby.check_case_id = contractor_case.pk
        kobby.save(update_fields=["check_case_id"])
    kobby = _activate(kobby, admin)
    if kobby.payee_id is None and esc_payees.get("contractor") is not None:
        panel.link_payee(kobby, cm, payee=esc_payees["contractor"])
    out["kobby"] = kobby
    mensah_p = _person(gh, "mensah", "mensah.builders@example.com", "Yaw Mensah (Mensah Construction)", "CT", admin)
    mensah = _activate(_member(gh, cm, admin, kind="contractor", name="Mensah Construction (demo)",
                               person=mensah_p), admin)
    if mensah.payee_id is None:
        panel.link_payee(mensah, cm, payee=_payee(gh, cm, rv, rv2, member=mensah, legal_name="Yaw Mensah",
                                                  number="1100778899001", nid_number="GHA-700000031-2"))
    out["mensah"] = mensah
    adom_p = _person(gh, "adom", "adom.builders@example.com", "Adom Builders (demo)", "CT", admin)
    adom = _member(gh, cm, admin, kind="contractor", name="Adom Builders (demo)", person=adom_p, docs=False)
    if adom.check_case_id is None:
        try:
            panel.start_check(adom, cm)
        except DomainError as exc:
            log.info("seed: Adom check not opened: %s", exc.detail)
    out["adom"] = adom
    # Inspectors and the quantity surveyor.
    esi_p = _person(gh, "esi", "esi.inspector@example.com", "Esi Owusu (inspector)", "IN", admin)
    _licence(esi_p, "IN", "EC/DEMO/0101", admin, gh)
    out["esi"] = _activate(_member(gh, cm, admin, kind="inspector", name="Esi Owusu", person=esi_p), admin)
    asare_p = _person(gh, "asare", "asare.inspector@example.com", "Kofi Asare (inspector)", "IN", admin)
    _licence(asare_p, "IN", "EC/DEMO/0102", admin, gh)
    asare = _activate(_member(gh, cm, admin, kind="inspector", name="Kofi Asare", person=asare_p), admin)
    if orgs.get("kobby") and not Membership.objects.filter(person=asare_p, organisation=orgs["kobby"]).exists():
        Membership.objects.create(organisation=orgs["kobby"], person=asare_p, added_by=admin)
    panel.add_conflict(cm, inspector=asare, contractor=kobby, reason="employee",
                       note="Site engineer at Kobby Builders until 2025 [demo]")
    out["asare"] = asare
    out["qs"] = _activate(_member(gh, cm, admin, kind="quantity_surveyor", name="Adjoa Quantity Surveyor",
                                  person=people["qs"]), admin)
    out["kwesi"] = _member(gh, cm, admin, kind="inspector", name="Kwesi Inspector", person=people["inspector"])
    out["sunrise"] = _activate(_member(gh, cm, admin, kind="developer", name="Sunrise Homes Developers (demo)",
                                       person=people["developer"], organisation=orgs.get("developer")), admin)
    if out["sunrise"].payee_id is None and esc_payees.get("developer") is not None:
        panel.link_payee(out["sunrise"], cm, payee=esc_payees["developer"])
    return out


BOQ_ITEMS = [
    {"description": "Excavation and foundation concrete", "quantity": "1", "rate": "54000.00"},
    {"description": "Sandcrete blocks and blockwork", "quantity": "4200", "rate": "18.00"},
    {"description": "Lintel, columns and ring beam", "quantity": "1", "rate": "36000.00"},
    {"description": "Roof frame and aluminium sheets", "quantity": "1", "rate": "54000.00"},
    {"description": "Plaster, plumbing, wiring, doors and windows", "quantity": "1", "rate": "78400.00"},
    {"description": "Preliminaries and site set-up", "quantity": "1", "rate": "62000.00"},
]


def _set_up(gh, people, panel_, *, title, asset, contractor, route, boq_items=BOQ_ITEMS, inspector=None):
    from . import projects
    from .models import Project

    client, cm = people["client"], people["cm"]
    p = Project.objects.filter(client=client, title=title).first()
    if p is not None:
        return p
    p = projects.create_project(cm, type="construction", title=title, asset_id=asset.pk, budget="300000.00",
                                client=client, payment_route=route)
    projects.assign_quantity_surveyor(p, cm, panel_["qs"].pk)
    projects.submit_boq(p, people["qs"], items=boq_items, evidence_ids=[_ev(gh, people["qs"], f"boq-{title}").pk])
    projects.choose_contractor(p, client, contractor.pk)
    projects.approve_budget(p, client)
    if inspector is not None:
        projects.assign_inspector(p, cm, inspector.pk)
    projects.sign_contract(p, cm, evidence_ids=[_ev(gh, cm, f"contract-{title}").pk])
    p.refresh_from_db()
    return p


def _staff_approve(pay, people):
    from . import payments

    for who in ("reviewer", "reviewer2"):
        pay.refresh_from_db()
        if pay.status == "client_approved":
            payments.staff_decide(pay, people[who], mfa_at=timezone.now())


def _project_a(ctx, gh, people, panel_, asset):
    """The launch route: Tenmina checks the stage, Ama pays the builder's verified account herself."""
    from . import payments, projects
    from .models import Milestone, Payment

    p = _set_up(gh, people, panel_, title="House at Millennium City, Kasoa", asset=asset,
                contractor=panel_["kobby"], route="client_direct", inspector=panel_["esi"])
    if not p.handover_confirmed_at:
        projects.confirm_handover(p, people["cm"], evidence_ids=[_ev(gh, people["cm"], "site-handover-A").pk])
    mob = Milestone.objects.get(project=p, seq=0)
    pay = Payment.objects.filter(milestone=mob, part="main").exclude(status__in=["withdrawn", "rejected"]).first()
    if pay is not None and pay.status == "awaiting_client":
        payments.client_approve(pay, people["client"], mfa_at=timezone.now())
        _staff_approve(pay, people)
        pay.refresh_from_db()
    if pay is not None and pay.status == "release_approved" and pay.client_paid_at is None:
        payments.record_client_payment(pay, people["client"], reference="NWB-FP-2026-118-01",
                                       evidence=_ev(gh, people["client"], "bank-transfer-confirmation-A"))
        payments.confirm_receipt(pay, people["contractor"], note="Received in full [demo]")
    found = Milestone.objects.get(project=p, key="foundation")
    if found.status == "not_started":
        # The builder's evidence is captured in Tenmina Field.
        _field_submit(gh, found, people["contractor"], "kobby-a")
        found.refresh_from_db()
        from . import milestones

        if found.status == "submitted":
            milestones.review_evidence(found, people["cm"], decision="accept")
    return p


def _field_submit(gh, m, person, key):
    """Capture the required evidence with a Tenmina Field phone and submit it."""
    from mobile.devtools import jpeg, mp4
    from mobile.seed import _item, _phone
    from mobile.services import submit

    phone = _phone(person, f"bld-{key}", platform="android")
    items, when = [], timezone.now() - timedelta(hours=3)
    for n, req in enumerate(m.required_evidence):
        data = mp4(f"bld-{key}-{m.key}-{n}") if req["media"] == "video" else jpeg(f"bld-{key}-{m.key}-{n}",
                                                                                   model=phone.model)
        it = _item(phone, str(demo_id(f"{key}-{m.pk}-{n}")), "milestone", m.pk, data, requirement_key=req["key"],
                   media_type="video/mp4" if req["media"] == "video" else "image/jpeg",
                   captured_at=when + timedelta(minutes=n * 2), lat=5.5342, lng=-0.4256)
        items.append({"requirement_key": req["key"], "evidence_id": str(it.evidence_id)})
    submit(person, client_submission_id=str(demo_id(f"sub-{key}-{m.pk}")), subject_type="milestone", subject_id=m.pk,
           items=items, note=f"{m.name} done [demo]")


def _inspect(gh, i, person, key, *, outcome="pass", defects=()):
    from mobile.devtools import jpeg
    from mobile.seed import _item, _phone
    from mobile.services import submit_inspection

    phone = _phone(person, f"bld-insp-{key}", platform="ios")
    clean = []
    for n, (desc, value) in enumerate(defects):
        it = _item(phone, str(demo_id(f"defect-{key}-{n}")), "milestone_inspection", i.pk,
                   jpeg(f"bld-defect-{key}-{n}", model=phone.model, make="Apple"), requirement_key=f"defect_{n + 1}",
                   captured_at=timezone.now() - timedelta(minutes=30), lat=5.5342, lng=-0.4256)
        clean.append({"description": desc, "value": {"amount": value, "currency": "GHS"},
                      "evidence_ids": [str(it.evidence_id)]})
    submit_inspection(person, client_submission_id=str(demo_id(f"insp-{key}-{i.pk}")),
                      subject_type="milestone_inspection", subject_id=i.pk, outcome=outcome,
                      checklist=[{"key": c["key"], "result": "ok" if not defects or n else "not_ok"}
                                 for n, c in enumerate(i.checklist)], defects=clean)


def _project_b(ctx, gh, people, panel_, asset):
    """The escrow route: the partner bank holds the money and pays the builder by stage."""
    from escrow import services as esc
    from escrow.models import Escrow, Party
    from escrow.seed import _confirm, _deposit

    from . import milestones, payments, projects
    from .models import Inspection, Milestone, Payment

    cm, rv, rv2, client = people["cm"], people["reviewer"], people["reviewer2"], people["client"]
    p = _set_up(gh, people, panel_, title="Boys' quarters at Kasoa", asset=asset, contractor=panel_["mensah"],
                route="escrow", inspector=panel_["esi"],
                boq_items=[{"description": "Two-room boys' quarters, complete", "quantity": "1",
                            "rate": "180000.00"}])
    if p.escrow_id is None:
        projects.open_escrow(p, cm)
        p.refresh_from_db()
    e = Escrow.objects.get(pk=p.escrow_id)
    if e.status == "proposed":
        for party in Party.objects.filter(escrow=e, must_accept=True):
            if party.role == "tenmina":
                esc.accept_terms(e, cm, party=party)
            elif party.person_id:
                esc.accept_terms(e, party.person, party=party)
        e.refresh_from_db()
        if e.status == "proposed":
            esc.record_virtual_account(e, cm, virtual_account_ref="VA-GH-BLD-000211")
        e.refresh_from_db()
    if e.status == "agreed":
        _deposit(e, cm, rv, f"{p.budget_amount:.2f}", "DEP-BLD-0211")
    p.refresh_from_db()
    if p.status != "active":
        log.warning("seed: project B did not start (%s)", p.status)
        return p
    if not p.handover_confirmed_at:
        projects.confirm_handover(p, cm, evidence_ids=[_ev(gh, cm, "site-handover-B").pk])
    mob = Milestone.objects.get(project=p, seq=0)
    pay = Payment.objects.filter(milestone=mob, part="main").exclude(status__in=["withdrawn", "rejected"]).first()
    if pay is not None and pay.status == "awaiting_client":
        payments.client_approve(pay, client, mfa_at=timezone.now())
        _staff_approve(pay, people)
        pay.refresh_from_db()
        if pay.instruction and pay.instruction.status == "sent":
            _confirm(pay.instruction, cm, rv, "PAY-BLD-0211-M0")
    found = Milestone.objects.get(project=p, key="foundation")
    if found.status == "not_started":
        _field_submit(gh, found, panel_["mensah"].person, "mensah-b")
        found.refresh_from_db()
        if found.status == "submitted":
            milestones.review_evidence(found, cm, decision="accept")
        found.refresh_from_db()
    i = Inspection.objects.filter(milestone=found, status="scheduled").first()
    if i is not None:
        _inspect(gh, i, panel_["esi"].person, "esi-b",
                 outcome="pass_with_defects", defects=[("Concrete cover under 50 mm at the north wall", "1200.00")])
    blocks = Milestone.objects.get(project=p, key="blocks")
    if not blocks.variations.exists():
        projects.propose_variation(p, panel_["mensah"].person, milestone_id=blocks.pk,
                                   description="Add a store room window on the east wall",
                                   cost_change="2400.00", time_effect_days=2)
    return p


def _project_c(ctx, gh, people, panel_):
    from . import projects
    from .models import Project

    p = Project.objects.filter(client=people["client"], type="offplan").first()
    if p is not None:
        return p
    asset = (ctx.get("geo") or {}).get("assets", {}).get("verified")
    if asset is None:
        return None
    return projects.create_project(people["client"], type="offplan", title="Off-plan house at Sunrise Estate",
                                   asset_id=asset.pk, budget="320000.00", contractor_id=panel_["sunrise"].pk,
                                   payment_route="client_direct")


def quiet(person, since):
    """Demo only: requests the seed raised for a person who already has other demo requests stay in the history
    but leave the orange needs-action list; the home feed still shows what needs them from the live state."""
    from notifications.models import Message

    Message.objects.filter(person=person, needs_action=True, action_done_at__isnull=True,
                           created_at__gte=since).update(action_done_at=timezone.now())


def _extra_inspection(gh, people, p):
    """FR-ORD-007: Ama orders an extra inspection; once paid, BLD gives it to the project's inspector."""
    from orders import legal
    from orders import services as ords
    from orders.models import Order

    if Order.objects.filter(details__seed="ama_extra_inspection").exists():
        return
    t = legal.current(gh)
    ords.order_extra_inspection(actor=people["client"], project_id=p.pk, data={
        "concern": "Cracks in the ring beam after the rains", "details": {"seed": "ama_extra_inspection"},
        "country": gh, "accept_terms": True, "terms_version": t["terms_version"], "scope_version": t["scope_version"]})


def run(ctx):
    from administration import flags
    from geo.models import Asset

    gh, people = ctx["gh"], ctx["people"]
    started = timezone.now()
    if not flags.enabled("building.construction", gh):
        return
    with transaction.atomic():
        panel_ = _panel(ctx, gh, people)
    ctx["construction"] = refs = {"panel": panel_}
    report = ctx.get("report")
    asset = Asset.objects.filter(pk=report.case.asset_id).first() if report is not None else None
    if asset is None:
        log.warning("seed: no verified plot for Ama; construction projects not seeded")
        return
    for key, fn in (("house", _project_a), ("quarters", _project_b)):
        try:
            with transaction.atomic():
                refs[key] = fn(ctx, gh, people, panel_, asset)
        except DomainError as exc:
            log.warning("seed: project %s not seeded: %s %s", key, exc.detail, getattr(exc, "blocking_reasons", ""))
    try:
        with transaction.atomic():
            refs["offplan"] = _project_c(ctx, gh, people, panel_)
    except DomainError as exc:
        log.warning("seed: off-plan project not seeded: %s", exc.detail)
    if refs.get("house") is not None:
        ctx["project"] = refs["house"]
        try:
            with transaction.atomic():
                _extra_inspection(gh, people, refs["house"])
        except DomainError as exc:
            log.info("seed: extra inspection order not placed: %s", exc.detail)
    quiet(people["client"], started)
