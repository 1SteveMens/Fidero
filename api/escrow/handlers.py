"""ESC event subscribers and registry hooks. Idempotent: each acts only on
objects still waiting, and core.events delivers each event once per consumer."""
from django.db import transaction

from accounts import home
from core.events import subscribe
from dataprotection import registry as dpr
from evidence import access

APPROVAL_TYPES = {"escrow_release", "escrow_cancel", "payee_verification", "payee_change", "programme_account",
                  "programme_rate"}


def _subject(st, sid):
    from .models import Escrow, Payee, PayeeChange, ProgrammeAccount, ProgrammeRate, ReleaseInstruction

    if st in ("escrow_release", "escrow_cancel"):
        ins = ReleaseInstruction.objects.filter(pk=sid).first()
        if ins is not None:
            return ins
        return Escrow.objects.filter(pk=sid).first()
    return {"payee_verification": Payee, "payee_change": PayeeChange, "programme_account": ProgrammeAccount,
            "programme_rate": ProgrammeRate}[st].objects.filter(pk=sid).first()


@subscribe("approval.approved", "approval.rejected")
def on_approval(ev):
    from . import bank, fx, payees, services
    from .models import Escrow, Payee, PayeeChange, ProgrammeAccount, ProgrammeRate, ReleaseInstruction

    st = ev.payload.get("subject_type")
    if st not in APPROVAL_TYPES:
        return
    obj = _subject(st, ev.payload.get("subject_id"))
    if obj is None:
        return
    ok = ev.topic == "approval.approved"
    with transaction.atomic():
        if isinstance(obj, ReleaseInstruction):
            if ok:
                services.on_instruction_approved(obj)
            else:
                services.on_instruction_rejected(obj)
        elif isinstance(obj, Escrow):
            services.on_cancel_approved(obj, ok)
        elif isinstance(obj, Payee):
            payees.apply_verification(obj, ok)
        elif isinstance(obj, PayeeChange):
            payees.on_change_approval(obj, ok)
        elif isinstance(obj, ProgrammeAccount):
            bank.on_programme_account_decided(obj, ok)
        elif isinstance(obj, ProgrammeRate):
            fx.on_programme_rate_decided(obj, ok)


@subscribe("release.approved")
def dispatch_instruction(ev):
    """escrow.dispatch_instruction: at once, no waiting period (RUL-33, ADR-26)."""
    from . import services
    from .models import ReleaseInstruction

    ins = ReleaseInstruction.objects.filter(pk=ev.payload.get("instruction_id") or ev.aggregate_id).first()
    if ins is not None:
        services.dispatch(ins)


@subscribe("report.released")
def on_report_released(ev):
    from . import services

    services.on_report_released(ev.payload or {})


@subscribe("fresh_search.completed")
def on_fresh_search(ev):
    from . import services

    services.on_fresh_search(ev.payload or {})


@subscribe("dispute.opened")
def on_dispute_opened(ev):
    from . import services

    services.on_dispute(ev.payload or {}, opened=True)


@subscribe("dispute.resolved", "dispute.withdrawn")
def on_dispute_resolved(ev):
    from . import services

    services.on_dispute(ev.payload or {}, opened=False)


@subscribe("incident.opened")
def on_incident_opened(ev):
    from . import services

    services.on_incident(ev.payload or {}, opened=True)


@subscribe("incident.closed")
def on_incident_closed(ev):
    from . import services

    services.on_incident(ev.payload or {}, opened=False)


@subscribe("national_id_check.completed")
def on_national_id(ev):
    """A fresh identity check finished: move a waiting payee change on."""
    from . import payees
    from .models import PayeeChange

    p = ev.payload or {}
    if p.get("context_type") != "payee_change" or not p.get("context_id"):
        return
    ch = PayeeChange.objects.filter(pk=p["context_id"], status="requested").first()
    if ch is not None and ch.national_id_check_id == p.get("check_id"):
        payees.advance_change(ch)


# ----------------------------------------------------------------- client home (FR-ACC-012)

@home.register
def escrow_home_items(person):
    from .models import OPEN_STATUSES, Escrow, PayeeChange, ReleaseInstruction
    from .selectors import held_at_bank

    out = []
    for e in Escrow.objects.filter(client=person, status__in=OPEN_STATUSES).order_by("-created_at")[:50]:
        held = held_at_bank(e)
        text = {"proposed": "Read and accept the escrow terms.", "agreed": "Pay the bank using its instructions.",
                "funded": "The money is held at the bank.", "ready_to_release": "Ready for your approval.",
                "client_approved": "Two Tenmina staff are approving.", "release_approved": "Sent to the bank.",
                "partly_released": "Part paid; the rest is held at the bank.",
                "frozen": "Payments are on hold while a check is made."}.get(e.status, "")
        out.append(home.item(kind="held_funds" if e.kind == "held_funds" else "escrow", id=e.pk,
                             title=e.title or e.reference, status=e.status, status_text=text,
                             needs_action=e.status == "proposed" and not e.acceptances.filter(
                                 party__person=person, terms_version=e.terms_version).exists(),
                             link=f"/escrows/{e.pk}", line="escrow",
                             amount={"amount": f"{held:.2f}", "currency": e.currency}))
    for ins in ReleaseInstruction.objects.filter(escrow__client=person, status="awaiting_client") \
            .select_related("escrow", "payee"):
        out.append(home.item(kind="release_approval", id=ins.pk, title=ins.subject_label or
                             f"Payment from {ins.escrow.reference}", status="awaiting_client",
                             status_text="Waiting for your approval. Nothing is paid until you approve.",
                             needs_action=True, link=f"/release-instructions/{ins.pk}", line="escrow",
                             family_member_id=ins.family_member_id,
                             amount={"amount": f"{ins.amount:.2f}", "currency": ins.currency}))
    for ch in PayeeChange.objects.filter(escrow__client=person, status="checks_passed"):
        out.append(home.item(kind="payee_change", id=ch.pk, title="Approve a change of account",
                             status=ch.status, status_text="An account change waits for your answer.",
                             needs_action=True, link=f"/payee-changes/{ch.pk}", line="escrow"))
    return out


# ----------------------------------------------------------------- evidence access

def _escrow_of(subject_type, sid):
    from .models import BankEvent, Condition, Escrow, ReleaseInstruction

    if subject_type == "escrow":
        return Escrow.objects.filter(pk=sid).first()
    model = {"escrow_condition": Condition, "escrow_instruction": ReleaseInstruction,
             "escrow_bank_event": BankEvent}[subject_type]
    obj = model.objects.filter(pk=sid).select_related("escrow").first()
    return obj.escrow if obj else None


def _party_can_view(user, e):
    if e is None:
        return False
    if e.client_id == user.pk:
        return True
    from accounts.selectors import is_representative

    return e.parties.filter(person=user).exists() or is_representative(user, "escrow", e.pk)


for _st in ("escrow", "escrow_condition", "escrow_instruction", "escrow_bank_event"):
    access.register(_st,
                    can_view=lambda user, sid, st=_st: _party_can_view(user, _escrow_of(st, sid)),
                    can_attach=lambda user, sid, st=_st: False,
                    country=lambda sid, st=_st: getattr(_escrow_of(st, sid), "country", None),
                    owner=lambda sid, st=_st: ("escrow", getattr(_escrow_of(st, sid), "pk", None)))


# ----------------------------------------------------------------- data protection (FR-APP-004, FR-DPR-003)

@dpr.open_matters
def escrow_open_matters(person):
    from .models import OPEN_STATUSES, Escrow
    from .selectors import currencies, held_at_bank

    out = []
    for e in Escrow.objects.filter(client=person):
        held = sum((held_at_bank(e, c) for c, _ in currencies(e)), start=0)
        if e.status in OPEN_STATUSES or held:
            out.append({"kind": "escrow", "id": str(e.pk), "title": e.title or e.reference,
                        "reason": "Money is held at the bank" if held else f"The escrow is {e.status}."})
    return out


@dpr.exporter("escrow")
def export_escrows(person):
    from .models import Escrow
    from .selectors import confirmed_funds

    return [{"reference": e.reference, "kind": e.kind, "status": e.status, "currency": e.currency,
             "agreed_amount": f"{e.agreed_amount:.2f}", "created_at": e.created_at.isoformat(),
             "funds": [{k: (str(v) if v is not None else None) for k, v in f.items() if k != "latest_bank_figure"}
                       for f in confirmed_funds(e)],
             "instructions": [{"kind": i.kind, "amount": f"{i.amount:.2f}", "currency": i.currency,
                               "status": i.status, "payee": i.payee.legal_name if i.payee_id else None}
                              for i in e.instructions.select_related("payee")]}
            for e in Escrow.objects.filter(client=person)]
