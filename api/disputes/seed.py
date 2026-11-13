"""DSP demo data (J-07), built through the real services on purchase escrows of its own so other modules'
demo escrows keep their states. Every amount is a synthetic figure [TO VERIFY].

- Awaiting response is skipped by the seller's reply: a dispute in Evidence (one withdrawn before it).
- A dispute in Decision with a decision waiting for its two approvals.
- A dispute closed: decided to continue, approved by two reviewers; the escrow is funded again.
- A dispute referred to mediation.
"""
import logging

from django.utils import timezone

from core.errors import DomainError

log = logging.getLogger(__name__)

ESCROWS = {
    "evidence": ("Plot at Ashaiman (dispute in evidence)", "95000.00", "VA-GH-000301"),
    "decision": ("Plot at Kasoa (dispute in decision)", "120000.00", "VA-GH-000302"),
    "closed": ("Plot at Nsawam (dispute decided)", "88000.00", "VA-GH-000303"),
    "referred": ("Plot at Ada (dispute with mediator)", "102000.00", "VA-GH-000304"),
}


def funded_escrow(gh, people, key, title, price, va):
    """A funded purchase escrow between Ama and Ato Estates, on a green report snapshot."""
    from accounts.models import Organisation
    from escrow import services as esc
    from escrow.models import Escrow, Payee, ReportSnapshot
    from escrow.seed import _agree, _deposit, demo_id

    e = Escrow.objects.filter(title=title).first()
    if e is not None:
        return e
    cm, rv = people["cm"], people["reviewer"]
    rid = demo_id(f"report:dsp:{key}")
    ReportSnapshot.objects.get_or_create(report_id=rid, defaults=dict(
        country=gh, client=people["client"], case_id=demo_id(f"case:dsp:{key}"),
        asset_id=demo_id(f"asset:dsp:{key}"), verdict="green", released_at=timezone.now(), conditions=[]))
    ato = Organisation.objects.filter(name="Ato Estates Ltd").first()
    payee = Payee.objects.filter(organisation=ato, kind="seller", verification_status="verified").first()
    e = esc.create_escrow(cm, kind="purchase", client=people["client"], country=gh, agreed_amount=price, title=title,
                          report_id=rid, parties=[{"role": "seller", "person": people["seller"], "organisation": ato,
                                                   "name": "Ato Estates Ltd", "payee": payee}])
    _agree(e, people, cm, va)
    _deposit(Escrow.objects.get(pk=e.pk), cm, rv, price, f"DEP-DSP-{key.upper()}")
    return Escrow.objects.get(pk=e.pk)


def run(ctx):
    from administration import flags

    gh, people = ctx["gh"], ctx["people"]
    if not flags.enabled("escrow.enabled", gh):
        return
    seeded = ctx.setdefault("disputes", {})
    for key, fn in (("evidence", _evidence), ("decision", _decision), ("closed", _closed), ("referred", _referred)):
        try:
            title, price, va = ESCROWS[key]
            e = funded_escrow(gh, people, key, title, price, va)
            seeded[f"{key}_escrow"] = e
            seeded[key] = fn(gh, people, e)
        except DomainError as exc:
            log.warning("seed disputes %s: %s %s", key, exc.detail, getattr(exc, "blocking_reasons", ""))


def _existing(e):
    from .models import Dispute

    return Dispute.objects.filter(subject_type="escrow", subject_id=e.pk).exclude(status="withdrawn").first()


def _evidence(gh, people, e):
    from . import services

    d = _existing(e)
    if d is not None:
        return d
    w = services.open_dispute(people["client"], subject_type="escrow", subject_id=e.pk, category="misrepresentation",
                              reason="The seller says the plot is smaller than the site plan. [demo]")
    services.withdraw(w, people["client"], "We measured it together and it matches. [demo]")
    d = services.open_dispute(people["client"], subject_type="escrow", subject_id=e.pk, category="title_or_documents",
                              reason="A neighbour claims part of the plot is family land. [demo]",
                              statement="On my visit a neighbour said the back 20 feet belong to his family.")
    services.add_statement(d, people["seller"], text="The plot was surveyed in 2024 and the pillars are in place. "
                                                     "The neighbour's land starts behind the wall. [demo]")
    d.refresh_from_db()
    return d


def _to_decision(people, d):
    from . import services

    if d.status == "awaiting_response":
        services.add_statement(d, people["seller"], text="We disagree and attach our survey. [demo]")
        d.refresh_from_db()
    if d.status == "evidence":
        services.confirm_evidence_complete(d, people["client"])
        services.confirm_evidence_complete(d, people["seller"])
        d.refresh_from_db()
    return d


def _decision(gh, people, e):
    from . import services

    d = _existing(e)
    if d is None:
        d = services.open_dispute(people["client"], subject_type="escrow", subject_id=e.pk, category="delay",
                                  reason="The seller has not handed over the signed indenture. [demo]")
    d = _to_decision(people, d)
    if d.status == "decision" and not d.decisions.exists():
        services.propose_decision(d, people["cm"], outcome="continue", in_favour_of="raised_by",
                                  reasons="The seller must hand over the signed indenture within 10 days; the "
                                          "release waits for it as a condition. [demo]")
    d.refresh_from_db()
    return d


def _closed(gh, people, e):
    from . import services

    d = _existing(e)
    if d is None:
        d = services.open_dispute(people["client"], subject_type="escrow", subject_id=e.pk, category="payment",
                                  reason="The agreed price in the escrow is higher than the seller's receipt. [demo]")
    d = _to_decision(people, d)
    if d.status == "decision":
        dec = d.decisions.filter(status="pending").first() or services.propose_decision(
            d, people["cm"], outcome="continue", in_favour_of="respondent",
            reasons="The receipt was for a deposit paid earlier, outside the escrow. The agreed price is right. "
                    "[demo]")
        now = timezone.now()
        services.approve_decision(d, people["reviewer"], mfa_at=now)
        services.approve_decision(d, people["reviewer2"], mfa_at=now)
    d.refresh_from_db()
    return d


def _referred(gh, people, e):
    from . import services

    d = _existing(e)
    if d is None:
        d = services.open_dispute(people["client"], subject_type="escrow", subject_id=e.pk, category="other",
                                  reason="The family heads disagree about who may sign the indenture. [demo]")
    if d.status not in ("referred", "closed"):
        services.refer(d, people["reviewer"], mediator="Ghana ADR Centre [demo, TO VERIFY]",
                       reason="A family matter that needs a mediator with customary standing. [demo]")
    d.refresh_from_db()
    return d
