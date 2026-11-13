"""PRJ demo data through the real services. Every amount is a synthetic working figure [TO VERIFY].

- Kofi's borehole for his mother's village (launch route): a checked supplier with a verified account, the
  runner checked, the agreement accepted; stage 1 confirmed from receipts and the driller's invoice waiting
  for Kofi's approval.
- Ama's shop fit-out in Kumasi: just set up. One supplier is missing bank details, the checks have started and
  the funding blockers are listed on the dashboard.
"""
import logging

from django.db import transaction
from django.utils import timezone

from core.errors import DomainError

log = logging.getLogger("projectfunds.seed")


def _ev(gh, by, name, kind="application/pdf"):
    from evidence.services import store

    data = (b"\xff\xd8\xff\xe0" + f"demo {name}".encode()) if kind == "image/jpeg" else f"%PDF-1.4 {name}".encode()
    return store(data=data, country=gh, uploaded_by=by, content_type=kind, original_name=name, description=name)


def complete_case(case_id, gh, people, outcome="verified", note=""):
    """Seed and tests: do every check task and record the reviewer's decision."""
    from cases import services as cs
    from cases.models import Case
    from cases.seed import attach

    cm, rv = people["cm"], people["reviewer2"]
    case = Case.objects.get(pk=case_id)
    for t in case.tasks.filter(review_step=False).exclude(status="done").order_by("position"):
        t.refresh_from_db()
        if t.site_visit:
            cs.record_risk_screen(case, cm, task=t, outcome="proceed", people_required=1)
        for k in t.required_evidence:
            attach(t, cm, gh, k)
        cs.complete_task(t, cm)
    cs.decide_verification(Case.objects.get(pk=case_id), rv, outcome=outcome, note=note or "Checked [demo]")


def _supplier_payee(s, gh, people, number_id):
    from accounts.services import request_national_id_check
    from core import approvals

    from . import services

    cm = people["cm"]
    nid = request_national_id_check(by=cm, country=gh, subject_role="signatory", subject_name=s.contact_name or s.name,
                                    id_number=number_id)
    services.link_supplier_payee(s, cm, details={
        "legal_name_evidence": _ev(gh, cm, f"registration-{s.name}"), "account_name": "",
        "account_name_source": "bank_name_check", "national_id_check": nid, "contact_phone": s.contact_phone})
    s.refresh_from_db()
    req = s.payee.approval_request
    for who in ("reviewer", "reviewer2"):
        req.refresh_from_db()
        if req.status == "open":
            approvals.decide(req, people[who], mfa_at=timezone.now(), note="Seed approval")


def _client(gh, people):
    """A diaspora client of her own, so the demo does not tie up the other seeded clients."""
    from construction.seed import _person

    return _person(gh, "kojo", "akosua.darko@example.com", "Akosua Darko", "CL", people["admin"])


def _borehole(gh, people):
    from construction import milestones, payments
    from construction.models import Payment, Project

    from . import services
    from .models import BackgroundCheck, Invoice

    client, cm = _client(gh, people), people["cm"]
    p = Project.objects.filter(client=client, type="funds", title__startswith="Borehole").first()
    if p is None:
        p = services.create_fund_project(cm, {
            "country": gh, "client": client, "title": "Borehole for Nana's village, Abetifi",
            "description": "A borehole and a water tank for the family compound.", "budget": "42000.00",
            "payment_route": "client_direct",
            "runner": {"name": "Kwame Boateng", "phone": "+233244555101"},
            "stages": [{"name": "Drilling and casing", "amount": "30000.00", "visit_required": False},
                       {"name": "Pump, tank and stand", "amount": "12000.00"}],
            "suppliers": [{"name": "Afram Drilling Ltd (demo)", "contact_name": "Afua Afram",
                           "contact_phone": "+233244555202", "bank_name": "Demo Commercial Bank [TO VERIFY]",
                           "account_number": "1100661100221", "what_they_supply": "Drilling"}]})
    if p.status != "setup":
        return p
    services.accept_agreement(p, client)
    checks = services.start_checks(p, cm, runner_id_number="GHA-700000041-3")
    for chk in checks:
        chk.refresh_from_db()
        if chk.subject_kind == "supplier" and chk.status == "pending":
            complete_case(chk.case_id, gh, people)
    runner = BackgroundCheck.objects.get(project=p, subject_kind="runner")
    if runner.status == "pending":
        services.record_runner_check(runner, cm, outcome="passed", note="No adverse records [demo]",
                                     evidence=_ev(gh, cm, "runner-background-check"))
    for s in p.suppliers.filter(status="passed", payee__isnull=True):
        _supplier_payee(s, gh, people, "GHA-700000042-4")
    p.refresh_from_db()
    if p.status != "active":
        log.warning("seed: borehole not started: %s", services.funding_blockers(p))
        return p
    stage = p.milestones.get(seq=0)
    milestones.submit_stage_evidence(stage, cm, evidence_ids=[_ev(gh, cm, "drilling-receipt-and-log").pk])
    milestones.review_evidence(stage, cm, decision="accept")
    milestones.confirm_stage(stage, cm, note="Drilling log and receipts match [demo]")
    sup = p.suppliers.get(status="passed")
    inv = Invoice.objects.filter(supplier=sup).first() or services.submit_invoice(
        p, cm, supplier_id=sup.pk, milestone_id=stage.pk, number="AFD-2026-0114", amount="30000.00",
        evidence_ids=[_ev(gh, cm, "afram-invoice-0114").pk], description="Drilling 60 m and casing")
    if inv.status == "submitted":
        services.decide_invoice(inv, cm, decision="accept")
    pay = Payment.objects.filter(subject_id=inv.pk, status="awaiting_client").first()
    if pay is None:
        log.warning("seed: borehole invoice payment not prepared")
    _ = payments
    return p


def _shop(gh, people):
    from construction.models import Project

    from . import services

    client, cm = people["client"], people["cm"]
    p = Project.objects.filter(client=client, type="funds").first()
    if p is not None:
        return p
    p = services.create_fund_project(client, {
        "country": gh, "title": "Shop fit-out for Efua, Kumasi", "budget": "18000.00",
        "runner": {"name": "Efua Mensah", "phone": "+233244555303"},
        "stages": [{"name": "Shelving and counter", "amount": "8000.00"},
                   {"name": "First stock", "amount": "10000.00", "visit_required": True}],
        "suppliers": [{"name": "Kejetia Carpentry Works (demo)", "contact_phone": "+233244555404",
                       "bank_name": "Demo Savings Bank [TO VERIFY]", "account_number": "2200123123123"},
                      {"name": "Adum Wholesale (demo)", "contact_phone": "+233244555505"}]})
    services.start_checks(p, cm)
    return p


def run(ctx):
    from administration import flags

    from construction.seed import quiet

    gh, people = ctx["gh"], ctx["people"]
    if not flags.enabled("projects.funds", gh):
        return
    refs = ctx.setdefault("projectfunds", {})
    started = timezone.now()
    for key, fn in (("borehole", _borehole), ("shop", _shop)):
        try:
            with transaction.atomic():
                refs[key] = fn(gh, people)
        except DomainError as exc:
            log.warning("seed: project fund %s not seeded: %s %s", key, exc.detail,
                        getattr(exc, "blocking_reasons", ""))
    quiet(people["client"], started)
