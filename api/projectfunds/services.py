"""PRJ Project funds: the public interface other modules may call.

    create_fund_project(actor, data) -> Project              FR-PRJ-001 (registered as BLD project type "funds")
    add_supplier, update_supplier, remove_supplier            FR-PRJ-001, US-PRJ-001 AC2
    start_checks(project, by)                                 FR-PRJ-002: the runner and every supplier
    record_runner_check(check, by, outcome, ...)              FR-PRJ-002
    link_supplier_payee(supplier, by, payee=None, details=None)  RUL-21, RUL-22
    prepare_aml / decide_aml                                  FR-PRJ-004
    agreement_text(project), accept_agreement(project, client)   FR-PRJ-005
    submit_invoice / decide_invoice / close_stage             FR-PRJ-003, RUL-21
    funding_blockers(project) -> [reason]                     before money is accepted at the bank

Events published: supplier.checked, invoice.accepted. Consumed: case.status_changed, milestone.status_changed,
payee.verified, release.confirmed (through BLD's payment engine).
"""
import hashlib
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from administration import flags
from construction import payments, projects
from construction.common import alert_staff, audit, evidence_objects, fmt, link_all, notify, now
from construction.models import Milestone, Payment, Project
from core import state
from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from .models import NO_ADVICE_STATEMENT, Agreement, AmlReview, BackgroundCheck, Invoice, Supplier

FLAG = "projects.funds"
REQUIRED_SUPPLIER_FIELDS = {"contact_phone": "a phone number", "bank_name": "the bank",
                            "account_number": "the account number"}


def _r(rule, code, message):
    return {"rule": rule, "code": code, "message": message}


def _on(country):
    flags.require(FLAG, country)
    flags.read_only_guard()


def _client_or_staff(p: Project, by):
    if by.pk == p.client_id:
        return "client"
    if has_role(by, "CM", "RV", country=p.country):
        return "staff"
    raise NotFound()


# ----------------------------------------------------------------- creating (FR-PRJ-001, FR-PRJ-005)

@transaction.atomic
def create_fund_project(actor, data: dict) -> Project:
    country = data.get("country") or getattr(actor, "home_country", None)
    if country is None:
        raise Invalid("Choose the country of the project.", code="validation-error")
    _on(country)
    client = data.get("client") or actor
    if client.pk != actor.pk and not has_role(actor, "CM", "RV", country=country):
        raise Forbidden("A client sets up their own project; otherwise a case manager does.")
    if not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client sets up a project fund.")
    budget = q(data.get("budget") or 0)
    if budget <= 0:
        raise Invalid("Enter the budget.", code="validation-error")
    stages = list(data.get("stages") or [])
    if not stages:
        raise Invalid("List the stages of the project.", code="validation-error")
    total = sum((q(s["amount"]) for s in stages), Decimal("0"))
    if total != budget:  # US-PRJ-001 AC1
        raise Invalid(f"The stages total {fmt(total, country.currency)}, not the budget of "
                      f"{fmt(budget, country.currency)}.", code="stages-not-budget",
                      extra={"stages_total": f"{total:.2f}", "budget": f"{budget:.2f}"})
    if not (data.get("title") or "").strip():
        raise Invalid("Give the project a name.", code="validation-error")
    runner = data.get("runner") or {}
    runner_person = None
    if runner.get("person_id"):
        from accounts.models import Person

        runner_person = Person.objects.filter(pk=runner["person_id"]).first()
        if runner_person is None:
            raise Invalid("That person was not found.", code="validation-error")
    if not runner_person and not (runner.get("name") or "").strip():
        raise Invalid("Name the person running the project.", code="validation-error")
    route = projects._route_for(country, "funds", data.get("payment_route"), actor)
    p = Project.objects.create(
        country=country, type="funds", title=data["title"].strip(), description=data.get("description") or "",
        client=client, runner_person=runner_person,
        runner_name=(runner_person.full_name if runner_person else runner.get("name", "")).strip(),
        runner_phone=runner.get("phone", "") or (runner_person.phone if runner_person else ""),
        budget_amount=budget, budget_currency=country.currency, payment_route=route, created_by=actor,
        case_manager=actor if has_role(actor, "CM", country=country) else None)
    rows, running = [], Decimal("0")
    for i, s in enumerate(stages):
        amount = q(s["amount"])
        share = projects.round_share(amount, budget) if i < len(stages) - 1 else Decimal("100") - running
        running += share
        rows.append({"key": s.get("key") or f"stage_{i + 1}", "name": s["name"], "share_pct": share,
                     "amount": amount, "visit_required": s.get("visit_required", True)})
    projects.build_milestones(p, rows, funds=True)
    # The client set the stages and their amounts themselves: that is the budget they approve.
    p.budget_approved_at, p.budget_approved_by = now(), client
    p.save(update_fields=["budget_approved_at", "budget_approved_by"])
    for sd in data.get("suppliers") or []:
        add_supplier(p, actor, sd)
    _new_agreement(p, actor)
    _aml_if_needed(p)
    audit(actor, "project.created", p, {"type": "funds", "route": route})
    publish("project.created", p.pk, projects.project_payload(p))
    alert_staff(country, ("CM",), "project_created", f"{client.full_name} set up a project fund: {p.title}. Start "
                                                     "the checks on the person running it and the suppliers.",
                obj=p, link=f"/back-office/projects/{p.pk}")
    return p


def no_advice_statement(country) -> str:
    """FR-PRJ-005: the country's published locked text `no_advice_statement` (lawyer signed), else the
    working text NO_ADVICE_STATEMENT [TO VERIFY]."""
    from administration.selectors import current_locked_text

    lt = current_locked_text("no_advice_statement", country)
    return lt.text if lt is not None and (lt.text or "").strip() else NO_ADVICE_STATEMENT


def agreement_text(p: Project) -> str:
    from administration.selectors import current_locked_text

    terms = current_locked_text("terms", p.country)
    stages = "\n".join(f"- {m.name}: {fmt(m.amount, m.currency)}" for m in p.milestones.order_by("seq"))
    return (f"Project agreement: {p.title}\n\nClient: {p.client.full_name}\nPerson running the project: "
            f"{p.runner_name}\nBudget: {fmt(p.budget_amount, p.budget_currency)}\n\nStages:\n{stages}\n\n"
            f"{no_advice_statement(p.country)}\n\nMoney is paid only to named, checked suppliers against invoices, never as "
            "cash to the person running the project (RUL-21). "
            + (terms.text if terms else "") + "\n[Working text, TO VERIFY by the lawyer.]")


def _new_agreement(p: Project, by) -> Agreement:
    from administration.selectors import current_locked_text

    text = agreement_text(p)
    if no_advice_statement(p.country) not in text:  # FR-PRJ-005; the database checks it again
        raise StateConflict("Every project agreement carries the no-advice statement.", code="statement-missing")
    v = Agreement.objects.filter(project=p).count() + 1
    return Agreement.objects.create(country=p.country, project=p, version=v, text=text,
                                    text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                                    terms_version=current_locked_text("terms", p.country))


def current_agreement(p: Project) -> Agreement | None:
    return Agreement.objects.filter(project=p).order_by("-version").first()


@transaction.atomic
def accept_agreement(p: Project, client) -> Agreement:
    """US-PRJ-005: the statement is shown from the agreement and the acceptance recorded."""
    _on(p.country)
    if p.client_id != client.pk:
        raise NotFound()
    a = current_agreement(p)
    if a is None:
        a = _new_agreement(p, client)
    if a.accepted_at:
        return a
    a.accepted_by, a.accepted_at = client, now()
    a.save(update_fields=["accepted_by", "accepted_at"])
    audit(client, "prj_agreement.accepted", a, {"version": a.version, "sha256": a.text_sha256})
    projects._try_start(p, None)
    return a


def _threshold(country):
    from countries.selectors import config

    t = config(country, "aml_threshold") or {}
    if not t:
        from administration.selectors import setting

        t = setting("prj_enhanced_check_amount", country) or {}
    return q(t.get("amount", "0")), (t.get("currency") or country.currency).upper()


def _in_currency(country, amount, currency):
    """The budget in the threshold's currency at the guide rate."""
    from administration.selectors import guide_rate

    if currency == country.currency:
        return q(amount)
    fx = guide_rate(country, currency, country.currency)
    if fx is None:
        return None
    return q(Decimal(amount) / fx.rate)


def _aml_if_needed(p: Project):
    """FR-PRJ-004, TC-PRJ-004-01: above the threshold the enhanced review is required."""
    amount, currency = _threshold(p.country)
    converted = _in_currency(p.country, p.budget_amount, currency)
    needed = converted is None or converted > amount
    existing = AmlReview.objects.filter(project=p).first()
    if needed and existing is None:
        return AmlReview.objects.create(country=p.country, project=p, threshold_amount=amount,
                                        threshold_currency=currency,
                                        budget_in_threshold_currency=converted if converted is not None else 0)
    return existing


def aml_required(p: Project) -> bool:
    return AmlReview.objects.filter(project=p).exists()


# ----------------------------------------------------------------- suppliers (FR-PRJ-001)

def _missing(s: Supplier):
    return [label for f, label in REQUIRED_SUPPLIER_FIELDS.items() if not (getattr(s, f) or "").strip()]


def _refresh_completeness(s: Supplier, by):
    s.missing = _missing(s)
    s.save(update_fields=["missing"])
    if s.missing and s.status == "pending_check":
        state.transition(s, "prj_supplier", "incomplete", actor=by, payload={"supplier_id": s.pk})
    elif not s.missing and s.status == "incomplete":
        state.transition(s, "prj_supplier", "pending_check", actor=by, payload={"supplier_id": s.pk})


FIELDS = ("name", "what_they_supply", "contact_name", "contact_phone", "contact_email", "registration_number",
          "bank_name", "account_number", "account_name")


@transaction.atomic
def add_supplier(p: Project, by, data: dict) -> Supplier:
    _on(p.country)
    _client_or_staff(p, by)
    if p.type != "funds":
        raise StateConflict("Suppliers belong to project funds.")
    if p.status in ("completed", "cancelled"):
        raise StateConflict(f"The project is {p.status}.")
    if p.payment_route == "escrow" and p.escrow_id:
        raise StateConflict("The escrow is open. A new supplier is added through a payee change at the bank.")
    if not (data.get("name") or "").strip():
        raise Invalid("Give the supplier's name.", code="validation-error")
    s = Supplier(country=p.country, project=p, added_by=by,
                 **{f: (data.get(f) or "").strip() for f in FIELDS})
    s.missing = _missing(s)
    s.save()
    if not s.missing:
        state.transition(s, "prj_supplier", "pending_check", actor=by, payload={"supplier_id": s.pk})
    _runner_supplier_reasons(s, raise_=True)
    audit(by, "prj_supplier.added", s, {"incomplete": s.missing})
    return s


@transaction.atomic
def update_supplier(s: Supplier, by, data: dict) -> Supplier:
    _on(s.country)
    _client_or_staff(s.project, by)
    if s.status not in ("incomplete", "pending_check", "failed"):
        raise StateConflict("A supplier being checked or checked cannot be changed. Add a new supplier instead.")
    for f in FIELDS:
        if f in data and data[f] is not None:
            setattr(s, f, str(data[f]).strip())
    s.save()
    if s.status == "failed":
        state.transition(s, "prj_supplier", "pending_check", actor=by, payload={"supplier_id": s.pk})
    _refresh_completeness(s, by)
    _runner_supplier_reasons(s, raise_=True)
    return s


@transaction.atomic
def remove_supplier(s: Supplier, by, *, reason="") -> Supplier:
    _client_or_staff(s.project, by)
    if Invoice.objects.filter(supplier=s, status__in=["submitted", "accepted"]).exists():
        raise StateConflict("This supplier has invoices waiting.")
    s.status_reason = reason or "Removed"
    state.transition(s, "prj_supplier", "removed", actor=by, reason=s.status_reason, extra_fields=["status_reason"],
                     payload={"supplier_id": s.pk})
    return s


def _runner_supplier_reasons(s: Supplier, raise_=False) -> list[dict]:
    """RUL-21, TC-RUL-21-02: the person running the project is never a supplier, by name, account or phone."""
    from accounts.models import BankAccount
    from accounts.normalise import normalise_name
    from administration.services import account_bidx

    p = s.project
    out = []
    runner = p.runner_person
    names = {normalise_name(p.runner_name)} if p.runner_name else set()
    if runner is not None:
        names.add(normalise_name(runner.full_name))
    if s.name and normalise_name(s.name) in names:
        out.append(_r("RUL-21", "runner-not-payee", "The person running the project cannot be a supplier."))
    if p.runner_phone and s.contact_phone and "".join(filter(str.isdigit, p.runner_phone))[-9:] == \
            "".join(filter(str.isdigit, s.contact_phone))[-9:]:
        out.append(_r("RUL-21", "runner-not-payee", "The supplier's phone is the phone of the person running the "
                                                    "project."))
    acct = s.account_number or (s.payee.account_number if s.payee_id else "")
    if runner is not None and acct:
        bidx = account_bidx(acct)
        if BankAccount.objects.filter(holder=runner, account_number_bidx=bidx).exists():
            out.append(_r("RUL-21", "runner-not-payee", "The supplier's account belongs to the person running the "
                                                        "project."))
    if s.payee_id and runner is not None and s.payee.person_id == runner.pk:
        out.append(_r("RUL-21", "runner-not-payee", "The payee is the person running the project."))
    if out and raise_:
        alert_staff(p.country, ("RV",), "runner_as_supplier", f"Someone tried to name the person running {p.title} "
                                                              "as a supplier. It was refused.", obj=p)
        raise RuleBlocked("Money never goes as cash to the person running the project. Name the real supplier.",
                          code="payee-not-verified", blocking_reasons=out)
    return out


# ----------------------------------------------------------------- checks (FR-PRJ-002, FR-PRJ-004)

@transaction.atomic
def start_checks(p: Project, by, *, runner_id_number="") -> list[BackgroundCheck]:
    from cases.services import open_case

    _on(p.country)
    if not has_role(by, "CM", country=p.country):
        raise Forbidden("A case manager starts the checks.")
    level = "enhanced" if aml_required(p) else "standard"
    out = []
    runner_check = BackgroundCheck.objects.filter(project=p, subject_kind="runner").exclude(status="failed").first()
    if runner_check is None:
        runner_check = BackgroundCheck.objects.create(country=p.country, project=p, subject_kind="runner",
                                                      person=p.runner_person, subject_name=p.runner_name,
                                                      requested_by=by, level=level)
    elif runner_check.level != level:
        runner_check.level = level
        runner_check.save(update_fields=["level"])
    if runner_check.national_id_check_id is None and runner_id_number:
        _runner_nid(runner_check, by, runner_id_number)
    out.append(runner_check)
    incomplete = list(Supplier.objects.filter(project=p, status="incomplete"))
    for s in Supplier.objects.filter(project=p, status="pending_check"):
        case = open_case("supplier_check", p.country, "prj_supplier", s.pk, client=p.client, actor=by,
                         case_manager=by, title=f"Supplier check: {s.name} ({p.title})")
        s.check_case_id = case.pk
        state.transition(s, "prj_supplier", "checking", actor=by, extra_fields=["check_case_id"],
                         payload={"supplier_id": s.pk})
        out.append(BackgroundCheck.objects.create(country=p.country, project=p, subject_kind="supplier", supplier=s,
                                                  subject_name=s.name, case_id=case.pk, requested_by=by, level=level))
    p.case_manager = p.case_manager or by
    p.save(update_fields=["case_manager"])
    if incomplete:
        notify(p.client, "approval_needed", "Some suppliers are missing contact or bank details: "
                                            + ", ".join(s.name for s in incomplete) + ". Please add them.",
               needs_action=True, obj=p, link=f"/projects/{p.pk}", category="request")
    audit(by, "prj.checks_started", p, {"checks": len(out), "level": level})
    return out


def _runner_nid(chk: BackgroundCheck, by, id_number):
    from accounts.services import request_national_id_check

    nid = request_national_id_check(by=by, country=chk.country, subject_role="signatory",
                                    subject_name=chk.subject_name, id_number=id_number, person=chk.person,
                                    context_type="prj_background_check", context_id=chk.pk)
    chk.national_id_check = nid
    chk.save(update_fields=["national_id_check"])
    return nid


@transaction.atomic
def record_runner_check(chk: BackgroundCheck, by, *, outcome, note="", evidence=None, id_number="") -> BackgroundCheck:
    """The identity check on the national system (RUL-31) and the background check on the person running the
    project. An enhanced check is decided by a reviewer."""
    _on(chk.country)
    if chk.subject_kind != "runner":
        raise StateConflict("Supplier checks are decided on their check case.")
    roles = ("RV",) if chk.level == "enhanced" else ("CM", "RV")
    if not has_role(by, *roles, country=chk.country):
        raise Forbidden("A reviewer decides an enhanced check." if chk.level == "enhanced" else
                        "A case manager records the check.")
    if chk.status != "pending":
        raise StateConflict("This check is already decided.")
    if outcome not in ("passed", "failed"):
        raise Invalid("Outcome must be passed or failed.", code="validation-error")
    if id_number and chk.national_id_check_id is None:
        _runner_nid(chk, by, id_number)
    if outcome == "passed":
        from accounts.services import require_national_id

        require_national_id({f"Person running the project {chk.subject_name}": chk.national_id_check},
                            "Passing this check")
        if evidence is None:
            raise Invalid("Attach the background check record.", code="validation-error")
    if outcome == "failed" and not (note or "").strip():
        raise Invalid("Say why the check failed.", code="validation-error")
    if evidence is not None:
        link_all([evidence], "prj_background_check", chk.pk, "background_check", by)
    chk.note, chk.evidence, chk.decided_by, chk.decided_at = note or "", evidence, by, now()
    state.transition(chk, "prj_background_check", outcome, actor=by, reason=note,
                     extra_fields=["note", "evidence", "decided_by", "decided_at"],
                     payload={"project_id": chk.project_id, "subject_kind": "runner"})
    if outcome == "failed":
        notify(chk.project.client, "case_status_changed", f"The check on the person running {chk.project.title} did "
                                                          "not pass. Your case manager will explain.",
               obj=chk.project, link=f"/projects/{chk.project_id}")
    projects._try_start(chk.project, None)
    return chk


def on_supplier_case(payload: dict):
    """case.status_changed for a supplier check: passed or failed (TC-PRJ-002-02: the client replaces it)."""
    if payload.get("subject_type") != "prj_supplier" or payload.get("status") != "completed":
        return
    s = Supplier.objects.filter(pk=payload.get("subject_id")).first()
    if s is None or s.status != "checking":
        return
    passed = payload.get("outcome") == "verified"
    to = "passed" if passed else "failed"
    s.status_reason = "" if passed else "The supplier check failed."
    state.transition(s, "prj_supplier", to, extra_fields=["status_reason"], payload={"supplier_id": s.pk})
    for chk in BackgroundCheck.objects.filter(supplier=s, status="pending"):
        chk.decided_at = now()
        state.transition(chk, "prj_background_check", to, extra_fields=["decided_at"],
                         payload={"project_id": s.project_id, "subject_kind": "supplier"})
    publish("supplier.checked", s.pk, {"supplier_id": s.pk, "project_id": s.project_id, "outcome": to,
                                       "client_id": s.project.client_id, "country": s.country.code})
    if not passed:
        notify(s.project.client, "approval_needed", f"{s.name} did not pass our supplier check. Please name another "
                                                    "supplier.", needs_action=True, obj=s.project,
               link=f"/projects/{s.project_id}", category="request")
    projects._try_start(s.project, None)


@transaction.atomic
def link_supplier_payee(s: Supplier, by, *, payee=None, details=None) -> Supplier:
    """The supplier's verified payee (ADR-17): an account in the supplier's own name, never the runner's."""
    from escrow import services as esc

    _on(s.country)
    if not has_role(by, "CM", "RV", country=s.country):
        raise Forbidden("A case manager records the supplier's payee.")
    if payee is None:
        d = dict(details or {})
        d.setdefault("legal_name", s.name)
        d.setdefault("bank_name", s.bank_name)
        d.setdefault("account_number", s.account_number)
        payee = esc.create_payee(by, country=s.country, kind="supplier", subject_type="supplier", subject_id=s.pk,
                                 **d)
        if payee.name_match == "matched":
            esc.prepare_verification(payee, by)
    elif payee.country_id != s.country_id or payee.kind not in ("supplier", "contractor", "vendor", "professional"):
        raise Invalid("That payee cannot be paid for a project in this country.", code="validation-error")
    s.payee = payee
    s.save(update_fields=["payee"])
    _runner_supplier_reasons(s, raise_=True)
    audit(by, "prj_supplier.payee_linked", s, {"payee_id": str(payee.pk)})
    return s


@transaction.atomic
def prepare_aml(p: Project, by, *, source_of_funds, purpose, evidence_ids) -> AmlReview:
    _on(p.country)
    if not has_role(by, "CM", country=p.country):
        raise Forbidden("A case manager prepares the enhanced check.")
    r = AmlReview.objects.filter(project=p).first()
    if r is None:
        raise StateConflict("This project is below the threshold. No enhanced check is needed.")
    if r.status not in ("required", "rejected"):
        raise StateConflict(f"The enhanced check is {r.status}.")
    if not (source_of_funds or "").strip() or not (purpose or "").strip():
        raise Invalid("Record the source of funds and the purpose.", code="validation-error")
    evidence = evidence_objects(evidence_ids, by, p.country, what="source of funds evidence")
    link_all(evidence, "prj_aml_review", r.pk, "aml_evidence", by)
    r.source_of_funds, r.purpose, r.evidence_ids = source_of_funds.strip(), purpose.strip(), [str(e.pk) for e in
                                                                                              evidence]
    r.prepared_by, r.decided_by, r.decided_at = by, None, None
    state.transition(r, "prj_aml_review", "submitted", actor=by, extra_fields=[
        "source_of_funds", "purpose", "evidence_ids", "prepared_by", "decided_by", "decided_at"],
        payload={"project_id": p.pk})
    alert_staff(p.country, ("RV",), "aml_review", f"The enhanced check on {p.title} waits for a reviewer.", obj=r)
    return r


@transaction.atomic
def decide_aml(r: AmlReview, by, *, decision, note="") -> AmlReview:
    _on(r.country)
    if by.pk == r.prepared_by_id:
        from core.errors import SameApprover

        raise SameApprover("The person who prepared the check cannot decide it.")
    if not has_role(by, "RV", country=r.country):
        raise Forbidden("A reviewer decides the enhanced check.")
    if r.status != "submitted":
        raise StateConflict(f"The enhanced check is {r.status}.")
    if decision not in ("approve", "reject"):
        raise Invalid("Decision must be approve or reject.", code="validation-error")
    if decision == "reject" and not (note or "").strip():
        raise Invalid("Say why.", code="validation-error")
    r.decided_by, r.decided_at, r.note = by, now(), note or ""
    state.transition(r, "prj_aml_review", "approved" if decision == "approve" else "rejected", actor=by,
                     reason=note, extra_fields=["decided_by", "decided_at", "note"],
                     payload={"project_id": r.project_id})
    projects._try_start(r.project, None)
    return r


def funding_blockers(p: Project) -> list[dict]:
    """US-PRJ-002, US-PRJ-004, US-PRJ-005: before money is accepted at the bank or the project starts."""
    out = []
    active = Supplier.objects.filter(project=p).exclude(status="removed")
    if not active.exists():
        out.append(_r("FR-PRJ-001", "suppliers-missing", "Name at least one supplier."))
    for s in active:
        if s.status != "passed":
            what = {"incomplete": "is missing details", "failed": "failed its check"}.get(s.status, "is not checked")
            out.append(_r("FR-PRJ-002", "supplier-unchecked", f"Supplier {s.name} {what}."))
        elif s.payee is None or s.payee.verification_status != "verified":
            out.append(_r("RUL-22", "payee-not-verified", f"Supplier {s.name} has no verified account yet."))
        out.extend(_runner_supplier_reasons(s))
    rc = BackgroundCheck.objects.filter(project=p, subject_kind="runner").order_by("-created_at").first()
    if rc is None or rc.status != "passed":
        out.append(_r("FR-PRJ-002", "runner-unchecked", "The person running the project is not checked."))
    r = AmlReview.objects.filter(project=p).first()
    if r is not None and r.status != "approved":
        out.append(_r("FR-PRJ-004", "aml-review-open", "The enhanced anti-money-laundering check is not approved."))
    a = current_agreement(p)
    if a is None or a.accepted_at is None:
        out.append(_r("FR-PRJ-005", "agreement-not-accepted", "The client has not accepted the project agreement."))
    return out


# ----------------------------------------------------------------- invoices (FR-PRJ-003, RUL-21)

def stage_committed(m: Milestone, exclude=None) -> Decimal:
    qs = Invoice.objects.filter(milestone=m, status__in=["accepted", "paid"])
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")


@transaction.atomic
def submit_invoice(p: Project, by, *, supplier_id, milestone_id, number, amount, evidence_ids, description=""):
    _on(p.country)
    who = "runner" if p.runner_person_id and by.pk == p.runner_person_id else None
    if who is None:
        _client_or_staff(p, by)
    s = Supplier.objects.filter(pk=supplier_id, project=p).first()
    if s is None:
        raise RuleBlocked("Invoices are paid only to the project's named suppliers.", code="payee-not-verified",
                          blocking_reasons=[_r("RUL-21", "supplier-unknown", "Not a named supplier.")])
    m = Milestone.objects.filter(pk=milestone_id, project=p).first()
    if m is None:
        raise Invalid("Choose the stage this invoice is for.", code="validation-error")
    if not (number or "").strip():
        raise Invalid("Give the invoice number.", code="validation-error")
    if Invoice.objects.filter(supplier=s, number=number.strip()).exclude(status__in=["rejected", "cancelled"]).exists():
        raise StateConflict("This invoice was already submitted. An invoice is paid once.", code="invoice-duplicate",
                            blocking_reasons=[_r("RUL-21", "invoice-duplicate", "Duplicate invoice number.")])
    amount = q(amount)
    if amount <= 0:
        raise Invalid("Enter the invoice amount.", code="validation-error")
    evidence = evidence_objects(evidence_ids, by, p.country, what="invoice")
    inv = Invoice.objects.create(country=p.country, project=p, milestone=m, supplier=s, number=number.strip(),
                                 amount=amount, currency=p.budget_currency, description=description or "",
                                 evidence=evidence[0], submitted_by=by)
    link_all(evidence, "prj_invoice", inv.pk, "invoice", by)
    audit(by, "prj_invoice.submitted", inv, {"amount": f"{amount:.2f}"})
    alert_staff(p.country, ("CM",), "invoice_submitted", f"An invoice from {s.name} for {m.name} on {p.title} "
                                                         "needs checking.", obj=inv)
    return inv


@transaction.atomic
def decide_invoice(inv: Invoice, by, *, decision, reason="") -> Invoice:
    _on(inv.country)
    if not has_role(by, "CM", "RV", country=inv.country):
        raise Forbidden("A case manager checks invoices.")
    if inv.status != "submitted":
        raise StateConflict(f"This invoice is {inv.status}.")
    if decision == "reject":
        if not (reason or "").strip():
            raise Invalid("Say why.", code="validation-error")
        inv.reject_reason = reason
        state.transition(inv, "prj_invoice", "rejected", actor=by, reason=reason, extra_fields=["reject_reason"],
                         payload={"invoice_id": inv.pk, "project_id": inv.project_id})
        return inv
    if decision != "accept":
        raise Invalid("Decision must be accept or reject.", code="validation-error")
    reasons = _supplier_reasons(inv)
    remaining = inv.milestone.amount - stage_committed(inv.milestone)
    if inv.amount > remaining:
        reasons.append(_r("FR-PRJ-003", "stage-budget", f"Only {fmt(remaining, inv.currency)} is left for "
                                                        f"{inv.milestone.name}."))
    if reasons:
        raise RuleBlocked("This invoice cannot be accepted.", code="release-blocked", blocking_reasons=reasons)
    inv.accepted_by, inv.accepted_at = by, now()
    state.transition(inv, "prj_invoice", "accepted", actor=by, event="invoice.accepted",
                     extra_fields=["accepted_by", "accepted_at"],
                     payload={"invoice_id": inv.pk, "project_id": inv.project_id, "supplier_id": inv.supplier_id,
                              "milestone_id": inv.milestone_id, "amount": inv.amount, "currency": inv.currency,
                              "client_id": inv.project.client_id})
    if inv.milestone.status in ("inspected",) and inv.project.status == "active":
        prepare_invoice_payment(inv, by)
    return inv


def _supplier_reasons(inv: Invoice) -> list[dict]:
    s = inv.supplier
    s.refresh_from_db()
    out = []
    if s.status != "passed":
        out.append(_r("RUL-21", "supplier-unchecked", f"{s.name} is not a checked supplier."))
    if s.payee is None or s.payee.verification_status != "verified":
        out.append(_r("RUL-22", "payee-not-verified", f"{s.name} has no verified account."))
    out.extend(_runner_supplier_reasons(s))
    return out


@transaction.atomic
def prepare_invoice_payment(inv: Invoice, by=None) -> Payment:
    from construction.milestones import _preparer

    by = _preparer(inv.milestone, by)
    return payments.prepare(inv.project, part="invoice", subject_type="project_invoice", subject_id=inv.pk,
                            payee=inv.supplier.payee, amount=inv.amount, by=by, milestone=inv.milestone,
                            label=f"Invoice {inv.number} from {inv.supplier.name}, {inv.milestone.name}",
                            evidence_ids=[inv.evidence_id])


def invoice_blockers(pay: Payment, stage) -> list[dict]:
    inv = Invoice.objects.filter(pk=pay.subject_id).select_related("supplier", "milestone", "project").first()
    if inv is None:
        return [_r("RUL-21", "invoice-missing", "There is no invoice for this payment.")]
    out = []
    if inv.status != "accepted":
        out.append(_r("RUL-21", "invoice-not-accepted", f"The invoice is {inv.status}."))
    out.extend(_supplier_reasons(inv))
    if inv.supplier.payee_id != pay.payee_id:
        out.append(_r("RUL-21", "payee-not-verified", "The payment must go to the invoice's own supplier."))
    if q(inv.amount) != q(pay.amount):
        out.append(_r("RUL-21", "amount-mismatch", f"The invoice is for {fmt(inv.amount, inv.currency)}."))
    m = inv.milestone
    if m.status == "frozen":
        out.append(_r("RUL-15", "milestone-frozen", f"{m.name} is frozen."))
    elif m.status != "inspected":
        why = "a visit" if m.visit_required else "the receipts"
        out.append(_r("FR-PRJ-003", "stage-unconfirmed", f"{m.name} is not confirmed by {why} yet."))
    r = AmlReview.objects.filter(project=inv.project).first()
    if r is not None and r.status != "approved":
        out.append(_r("FR-PRJ-004", "aml-review-open", "The enhanced check is not approved."))
    if Payment.objects.filter(subject_type="project_invoice", subject_id=inv.pk, status="paid").exists():
        out.append(_r("RUL-21", "invoice-duplicate", "This invoice is already paid."))
    return out


def on_invoice_status(pay: Payment, to):
    inv = Invoice.objects.select_for_update().filter(pk=pay.subject_id).first()
    if inv is None:
        return
    if to == "paid" and inv.status == "accepted":
        inv.paid_at = now()
        state.transition(inv, "prj_invoice", "paid", extra_fields=["paid_at"],
                         payload={"invoice_id": inv.pk, "project_id": inv.project_id})
        notify(inv.project.client, "money_update", f"{inv.supplier.name} was paid {fmt(pay.amount, pay.currency)} "
                                                   f"for invoice {inv.number}.", obj=inv.project,
               link=f"/projects/{inv.project_id}")
        _maybe_close_stage(inv.milestone)
    elif to in ("withdrawn", "rejected") and inv.status == "accepted":
        state.transition(inv, "prj_invoice", "submitted", reason=pay.closed_reason or to,
                         payload={"invoice_id": inv.pk, "project_id": inv.project_id})


payments.register_subject("invoice", blockers=invoice_blockers, on_status=on_invoice_status)


def _maybe_close_stage(m: Milestone):
    paid = Invoice.objects.filter(milestone=m, status="paid").aggregate(s=Sum("amount"))["s"] or 0
    if paid >= m.amount and m.status == "inspected":
        close_stage(m, None)


@transaction.atomic
def close_stage(m: Milestone, by, *, note="") -> Milestone:
    """A stage is done when its invoices are paid: the whole stage amount, or the case manager closes it."""
    from construction.milestones import move
    from construction.projects import on_milestone_paid

    if by is not None and not has_role(by, "CM", "RV", country=m.country):
        raise Forbidden("A case manager closes a stage.")
    if m.project.type != "funds" or m.status != "inspected":
        raise StateConflict("Only a confirmed project fund stage is closed.")
    if Invoice.objects.filter(milestone=m, status__in=["submitted", "accepted"]).exists():
        raise StateConflict("Invoices on this stage are still open.")
    if not Invoice.objects.filter(milestone=m, status="paid").exists():
        raise StateConflict("No invoice on this stage is paid yet.")
    m.paid_at = now()
    move(m, "paid", actor=by, reason=note or "Every invoice on the stage is paid", extra_fields=["paid_at"])
    on_milestone_paid(m)
    return m


def on_stage_confirmed(payload: dict):
    """milestone.status_changed to inspected on a funds project: prepare its accepted invoices."""
    if payload.get("to") != "inspected":
        return
    m = Milestone.objects.filter(pk=payload.get("id") or payload.get("milestone_id"), project__type="funds").first()
    if m is None:
        return
    for inv in Invoice.objects.filter(milestone=m, status="accepted"):
        if Payment.objects.filter(subject_type="project_invoice", subject_id=inv.pk, status__in=Payment.LIVE).exists():
            continue
        try:
            prepare_invoice_payment(inv, None)
        except Exception as exc:  # noqa: BLE001 - one blocked invoice never stops the others
            alert_staff(m.country, ("CM",), "payment_not_prepared", f"Invoice {inv.number} could not be prepared: "
                                                                    f"{getattr(exc, 'detail', exc)}", obj=inv)


def dashboard_extra(p: Project, person=None) -> dict:
    r = AmlReview.objects.filter(project=p).first()
    a = current_agreement(p)
    return {"funds": {
        "runner": p.runner_name,
        "disclaimer": no_advice_statement(p.country),
        "agreement": {"version": a.version, "accepted_at": a.accepted_at} if a else None,
        "suppliers": [{"id": str(s.pk), "name": s.name, "status": s.status, "missing": s.missing,
                       "payee_verified": bool(s.payee_id and s.payee.verification_status == "verified")}
                      for s in Supplier.objects.filter(project=p).exclude(status="removed")],
        "checks": [{"id": str(c.pk), "subject": c.subject_kind, "name": c.subject_name, "level": c.level,
                    "status": c.status} for c in BackgroundCheck.objects.filter(project=p)],
        "aml_review": {"status": r.status, "threshold": {"amount": f"{r.threshold_amount:.2f}",
                                                         "currency": r.threshold_currency}} if r else None,
        "invoices": [{"id": str(i.pk), "supplier": i.supplier.name, "number": i.number, "stage": i.milestone.name,
                      "status": i.status, "amount": {"amount": f"{i.amount:.2f}", "currency": i.currency}}
                     for i in Invoice.objects.filter(project=p).select_related("supplier", "milestone")],
        "funding_blockers": funding_blockers(p) if p.status == "setup" else [],
    }}


def get_project(pk) -> Project:
    p = Project.objects.filter(pk=pk, type="funds").first()
    if p is None:
        raise NotFound("Project not found.")
    return p
