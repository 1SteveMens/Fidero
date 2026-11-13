"""PRO event subscribers and registrations. Every handler is idempotent and never
raises a domain error back into the producer's transaction: a released report
stays released even if its payable cannot be created yet (operations is alerted).

Consumes: work.accepted (RPT, BLD, PMG, TSK, CARE), runner_month.closed, payee.verified, payee.suspended,
payee.status_changed, bank_account.verified, bank_account.status_changed, approval.approved,
approval.rejected, task.assigned.
Registers: evidence access for pro_agreement, pro_expense_claim and pro_payment_run; data protection
exporter and open matters; the RUL-27 check on every escrow release subject.
"""
import logging
import uuid

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)
APPROVAL_TYPES = {"pro_rate_card_change", "pro_payment_run", "pro_expense_exception"}


def _uuid(v):
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


@subscribe("work.accepted")
def on_work_accepted(ev):
    """FR-PRO-002: a payable for accepted work only (US-PRO-002 AC1 to AC3, AC5)."""
    from . import services

    try:
        with transaction.atomic():
            services.record_work_accepted(dict(ev.payload or {}), event_id=ev.id)
    except DomainError as exc:
        log.warning("work.accepted %s not recorded: %s", ev.id, exc.detail)


@subscribe("runner_month.closed")
def on_runner_month(ev):
    from . import services

    try:
        with transaction.atomic():
            services.record_runner_month(dict(ev.payload or {}), event_id=ev.id)
    except DomainError as exc:
        log.warning("runner_month.closed %s not recorded: %s", ev.id, exc.detail)


@subscribe("payee.verified", "payee.suspended", "payee.status_changed")
def on_payee(ev):
    from . import services

    p = ev.payload or {}
    pid = _uuid(p.get("payee_id") or p.get("id"))
    if pid is None:
        return
    to = p.get("to") or ("verified" if ev.topic == "payee.verified" else "suspended")
    services.on_destination_changed(payee_id=pid, verified=(to == "verified"))


@subscribe("bank_account.verified", "bank_account.status_changed")
def on_bank_account(ev):
    from . import services

    p = ev.payload or {}
    bid = _uuid(p.get("bank_account_id") or p.get("id"))
    if bid is None:
        return
    to = p.get("to") or "verified"
    if to == "pending" and p.get("from") != "verified":
        return
    services.on_destination_changed(bank_account_id=bid, verified=(to == "verified"))


@subscribe("approval.approved", "approval.rejected")
def on_approval(ev):
    from . import services
    from .models import ExpenseClaim, PaymentRun, RateCard

    st = (ev.payload or {}).get("subject_type")
    if st not in APPROVAL_TYPES:
        return
    sid = _uuid(ev.payload.get("subject_id"))
    ok = ev.topic == "approval.approved"
    if st == "pro_rate_card_change":
        card = RateCard.objects.filter(pk=sid).first()
        if card:
            services.apply_rate_card(card, ok)
    elif st == "pro_payment_run":
        run = PaymentRun.objects.filter(pk=sid).first()
        if run:
            services.apply_run_decision(run, ok)
    elif st == "pro_expense_exception":
        c = ExpenseClaim.objects.filter(pk=sid).first()
        if c:
            services.apply_exception(c, ok)


@subscribe("task.assigned")
def on_task_assigned(ev):
    """US-PRO-001 AC1 until CASE refuses the assignment itself: tell the case manager at once when work went
    to a professional with no signed agreement or no verified payee account."""
    from accounts.models import Person
    from countries.models import Country

    from . import services

    p = ev.payload or {}
    person = Person.objects.filter(pk=_uuid(p.get("assignee_id"))).first()
    country = Country.objects.filter(code=str(p.get("country") or "").upper()).first()
    if person is None or country is None:
        return
    reasons = services.assignment_blockers(person, p.get("role") or "", country)
    if reasons:
        services._alert(country, ("CM",), "pro_assignment_without_agreement",
                        f"{person.full_name} was assigned work but cannot be paid yet: "
                        + "; ".join(r["message"] for r in reasons))


# --------------------------------------------------------------------------- registries

def _register():
    from dataprotection import registry
    from escrow import registry as esc_registry
    from escrow.models import SUBJECT_TYPES as ESC_SUBJECTS
    from evidence import access

    from . import services
    from .models import Agreement, ExpenseClaim, PaymentRun

    def _agreement(sid):
        return Agreement.objects.filter(pk=sid).select_related("country").first()

    def _claim(sid):
        return ExpenseClaim.objects.filter(pk=sid).select_related("country").first()

    def _run(sid):
        return PaymentRun.objects.filter(pk=sid).select_related("country").first()

    access.register(
        "pro_agreement",
        can_view=lambda u, sid: (lambda a: a is not None and (a.professional_id == u.pk or services.is_staff(
            u, a.country, "CM", "RV", "AD")))(_agreement(sid)),
        can_attach=lambda u, sid: (lambda a: a is not None and services.is_staff(u, a.country, "CM", "AD"))(
            _agreement(sid)),
        country=lambda sid: _agreement(sid).country, owner=lambda sid: ("pro_agreement", sid))
    access.register(
        "pro_expense_claim",
        can_view=lambda u, sid: (lambda c: c is not None and (c.claimant_id == u.pk or services.is_staff(
            u, c.country)))(_claim(sid)),
        can_attach=lambda u, sid: (lambda c: c is not None and c.claimant_id == u.pk and c.status == "submitted")(
            _claim(sid)),
        country=lambda sid: _claim(sid).country, owner=lambda sid: ("pro_expense_claim", sid))
    access.register(
        "pro_payment_run",
        can_view=lambda u, sid: (lambda r: r is not None and services.is_staff(u, r.country, "CM", "RV", "AD"))(
            _run(sid)),
        can_attach=lambda u, sid: (lambda r: r is not None and services.is_staff(u, r.country))(_run(sid)),
        country=lambda sid: _run(sid).country, owner=lambda sid: ("pro_payment_run", sid))

    # RUL-27: no release from client money may name a payee linked to a professional's agreement.
    for st in ESC_SUBJECTS:
        esc_registry.register_subject_check(st, services.escrow_release_check)

    @registry.exporter("professional_pay")
    def export_pay(person):
        out = []
        for a in Agreement.objects.filter(professional=person):
            out.append({
                "agreement": a.reference, "role": a.role, "status": a.status, "valid_from": a.valid_from.isoformat(),
                "payables": [{"work_kind": p.work_kind, "accepted_at": p.accepted_at.isoformat(),
                              "gross": f"{p.gross:.2f}", "withholding": f"{p.withholding:.2f}",
                              "currency": p.currency, "status": p.status} for p in a.payables.all()],
                "expense_claims": [{"kind": c.kind, "amount": f"{c.amount:.2f}", "currency": c.currency,
                                    "status": c.status} for c in a.expense_claims.all()],
            })
        return out

    @registry.open_matters
    def unpaid_pay(person):
        from .models import Payable

        n = Payable.objects.filter(agreement__professional=person, status__in=["approved", "held", "in_run"]).count()
        if not n:
            return []
        return [{"kind": "professional_pay", "id": str(person.pk), "title": f"{n} payments due to you",
                 "reason": "Tenmina still owes you pay for accepted work."}]


_register()
