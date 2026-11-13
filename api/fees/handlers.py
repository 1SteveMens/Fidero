"""FEE event subscribers and registry hooks. Idempotent: each acts only on
objects still waiting, and core.events delivers each event once per consumer."""
from accounts import home
from core.events import subscribe
from dataprotection import registry as dpr
from escrow import registry as esc_registry
from evidence import access
from mobile import inbox


@subscribe("case.status_changed")
def on_case(ev):
    from . import services

    services.on_case_status_changed(ev.payload or {})


@subscribe("payee.verified", "payee.suspended", "payee.status_changed")
def on_payee(ev):
    from . import services

    p = ev.payload or {}
    payee_id = p.get("payee_id") or (p.get("id") if p.get("entity") == "payee" else None)
    to = p.get("to") or {"payee.verified": "verified", "payee.suspended": "suspended"}.get(ev.topic)
    if payee_id and to:
        services.on_payee_status(payee_id, to, p.get("reason", ""))


@subscribe("payee_change.applied")
def on_payee_change(ev):
    from . import services

    p = ev.payload or {}
    if p.get("kind") == "new_account" and p.get("payee_id"):
        services.on_payee_account_changed(p["payee_id"])


@subscribe("release.confirmed")
def on_release_confirmed(ev):
    from . import services

    services.on_release_confirmed(ev.payload or {})


@subscribe("release.withdrawn", "release.rejected", "release.rejected_by_bank")
def on_release_closed(ev):
    from . import services

    why = {"release.withdrawn": "the instruction was withdrawn", "release.rejected": "the payment was not approved",
           "release.rejected_by_bank": "the bank refused the payment"}[ev.topic]
    services.on_release_closed(ev.payload or {}, (ev.payload or {}).get("reason") or why)


@subscribe("held_funds.deposit_confirmed")
def on_deposit(ev):
    from . import services

    services.on_deposit_confirmed(ev.payload or {})


@subscribe("submission.received")
def on_submission(ev):
    from . import services

    services.on_submission(ev.payload or {})


# ----------------------------------------------------------------- escrow hooks (RUL-22, FR-FEE-003)

def _fee_invoice_check(instruction):
    from . import services

    return services.release_check(instruction)


def _fee_invoice_label(subject_id):
    from . import services

    return services.label(subject_id)


esc_registry.register_subject_check("fee_invoice", _fee_invoice_check)
esc_registry.subject_label("fee_invoice", _fee_invoice_label)


# ----------------------------------------------------------------- client home (FR-ACC-012)

@home.register
def fee_home_items(person):
    from .models import ClientInstitution, Invoice, Payment, Schedule

    out = []
    if not person.has_tenmina_role("CL"):
        return out
    for link in ClientInstitution.objects.filter(client=person).select_related("institution"):
        inst = link.institution
        if inst.status == "verified":
            continue
        text = {"pending": "Tenmina is checking it: registration, bank account in its own name, a named contact.",
                "not_verified": inst.status_reason or "We could not verify it. Tenmina cannot pay it.",
                "not_eligible": inst.status_reason or "Tenmina cannot pay it.",
                "suspended": inst.status_reason or "Payments to it are paused."}.get(inst.status, "")
        out.append(home.item(kind="institution", id=inst.pk, title=inst.legal_name, status=inst.status,
                             status_text=text, link=f"/institutions/{inst.pk}", line="fee"))
    texts = {"draft": "Waiting for the institution's bill.", "submitted": "Tenmina is checking the bill.",
             "checked": "Checked. Approve it to pay.", "client_approved": "Approved. Waiting for the payment.",
             "instructed": "Two Tenmina staff are approving the bank's payment.",
             "paid": "Paid. Waiting for the receipt.", "receipted": "Paid. Receipt returned."}
    for inv in Invoice.objects.filter(client=person).exclude(status__in=["rejected", "cancelled"]) \
            .select_related("institution", "family_member").order_by("-created_at")[:50]:
        if inv.status == "receipted":
            continue
        out.append(home.item(kind="fee_invoice", id=inv.pk,
                             title=f"{inv.description or 'Bill'}: {inv.institution.legal_name}",
                             status=inv.status, status_text=texts.get(inv.status, ""), next_date=inv.due_on,
                             needs_action=inv.status == "checked", link=f"/invoices/{inv.pk}",
                             family_member_id=inv.family_member_id, line="fee",
                             amount={"amount": f"{inv.amount:.2f}", "currency": inv.currency}))
    for pay in Payment.objects.filter(invoice__client=person, status__in=["awaiting_client_payment",
                                                                          "client_reported", "receipt_overdue"]) \
            .select_related("invoice", "invoice__institution"):
        text = {"awaiting_client_payment": "Pay the institution's verified account, then tell us.",
                "client_reported": "The institution is confirming it received your payment.",
                "receipt_overdue": "The institution's receipt is late. We are chasing it."}[pay.status]
        out.append(home.item(kind="fee_payment", id=pay.pk, title=f"Payment to {pay.invoice.institution.legal_name}",
                             status=pay.status, status_text=text, needs_action=pay.status == "awaiting_client_payment",
                             link=f"/fee-payments/{pay.pk}", family_member_id=pay.invoice.family_member_id, line="fee",
                             amount={"amount": f"{pay.amount:.2f}", "currency": pay.currency}))
    for s in Schedule.objects.filter(client=person, status="active").select_related("institution"):
        out.append(home.item(kind="fee_schedule", id=s.pk, title=s.label, status=s.status,
                             status_text="Recurring. We remind you and ask for your approval each time.",
                             next_date=s.next_due_on, link=f"/fee-schedules/{s.pk}",
                             family_member_id=s.family_member_id, line="fee"))
    return out


# ----------------------------------------------------------------- field inbox (FR-FEE-006)

@inbox.register
def runner_tasks(person):
    from .models import RunnerTask

    if not person.has_tenmina_role("RN"):
        return
    for t in RunnerTask.objects.filter(runner=person, status="open").select_related("institution",
                                                                                   "deliver_to_family_member"):
        inst = t.institution
        if t.kind == "collect_invoice":
            title = f"Collect a bill from {inst.legal_name}"
            req = [{"key": "invoice_photo", "label": "Photo of the bill", "media": "photo", "required": True},
                   {"key": "reference", "label": "Reference on the bill", "media": "text", "required": False},
                   {"key": "amount", "label": "Amount on the bill", "media": "text", "required": False}]
        else:
            fm = t.deliver_to_family_member
            title = f"Deliver a receipt to {fm.full_name.split()[0] if fm else 'the family'}"
            req = [{"key": "handover", "label": "Photo or signature of the handover", "media": "photo",
                    "required": True}]
        yield inbox.InboxItem(subject_type="fee_runner_task", subject_id=str(t.pk), title=title,
                              kind="fee_runner_task", country=t.country, address=inst.address,
                              required_evidence=req, due_at=t.due_at,
                              details={"institution": inst.legal_name, "kind": t.kind,
                                       "instructions": t.instructions,
                                       "note": "You carry paper only, never money."},
                              updated_at=t.updated_at)


# ----------------------------------------------------------------- evidence access

def _invoice_view(user, sid):
    from .selectors import invoices_visible

    return invoices_visible(user).filter(pk=sid).exists()


def _invoice_attach(user, sid):
    from .models import Invoice
    from .services import contact_for

    inv = Invoice.objects.filter(pk=sid).select_related("institution").first()
    if inv is None:
        return False
    return inv.client_id == user.pk or contact_for(user, inv.institution) is not None


def _invoice_country(sid):
    from .models import Invoice

    inv = Invoice.objects.filter(pk=sid).select_related("country").first()
    return inv.country if inv else None


def _payment_view(user, sid):
    from .selectors import payments_visible

    return payments_visible(user).filter(pk=sid).exists()


def _payment_attach(user, sid):
    from .models import Payment
    from .services import contact_for

    p = Payment.objects.filter(pk=sid).select_related("invoice", "invoice__institution").first()
    if p is None:
        return False
    return p.invoice.client_id == user.pk or contact_for(user, p.invoice.institution) is not None


def _payment_country(sid):
    from .models import Payment

    p = Payment.objects.filter(pk=sid).select_related("country").first()
    return p.country if p else None


def _institution_view(user, sid):
    from .models import ClientInstitution
    from .selectors import contact_institution_ids

    return ClientInstitution.objects.filter(client=user, institution_id=sid).exists() or \
        str(sid) in {str(i) for i in contact_institution_ids(user)}


def _institution_country(sid):
    from .models import Institution

    i = Institution.objects.filter(pk=sid).select_related("country").first()
    return i.country if i else None


def _task_view(user, sid):
    from .models import RunnerTask

    return RunnerTask.objects.filter(pk=sid, runner=user).exists()


def _task_country(sid):
    from .models import RunnerTask

    t = RunnerTask.objects.filter(pk=sid).select_related("country").first()
    return t.country if t else None


def _statement_view(user, sid):
    from accounts.models import FamilyMember

    return FamilyMember.objects.filter(pk=sid, client=user).exists()


def _statement_country(sid):
    from accounts.models import FamilyMember

    fm = FamilyMember.objects.filter(pk=sid).select_related("country").first()
    return fm.country if fm else None


access.register("fee_invoice", can_view=_invoice_view, can_attach=_invoice_attach, country=_invoice_country,
                owner=lambda sid: ("fee_invoice", sid))
access.register("fee_payment", can_view=_payment_view, can_attach=_payment_attach, country=_payment_country,
                owner=lambda sid: ("fee_payment", sid))
access.register("institution", can_view=_institution_view, can_attach=lambda user, sid: False,
                country=_institution_country, owner=lambda sid: ("institution", sid))
access.register("fee_runner_task", can_view=_task_view, can_attach=_task_view, country=_task_country,
                owner=lambda sid: ("fee_runner_task", sid))
access.register("fee_statement", can_view=_statement_view, can_attach=lambda user, sid: False,
                country=_statement_country, owner=lambda sid: ("fee_statement", sid))


# ----------------------------------------------------------------- data protection

@dpr.open_matters
def fee_open_matters(person):
    from .models import Payment

    out = []
    for p in Payment.objects.filter(invoice__client=person, status__in=["client_reported", "instructed"]) \
            .select_related("invoice__institution"):
        out.append({"kind": "fee_payment", "id": str(p.pk),
                    "title": f"Payment to {p.invoice.institution.legal_name}",
                    "reason": "A payment to an institution is under way."})
    return out


@dpr.exporter("fees")
def export_fees(person):
    from .models import Invoice, Payment, Schedule

    return {
        "invoices": [{"id": str(i.pk), "institution": i.institution.legal_name, "reference": i.institution_reference,
                      "family_member_id": str(i.family_member_id), "amount": f"{i.amount:.2f}",
                      "currency": i.currency, "status": i.status, "created_at": i.created_at.isoformat()}
                     for i in Invoice.objects.filter(client=person).select_related("institution")],
        "payments": [{"id": str(p.pk), "invoice_id": str(p.invoice_id), "route": p.route,
                      "amount": f"{p.amount:.2f}", "currency": p.currency, "status": p.status,
                      "paid_at": p.paid_at.isoformat() if p.paid_at else None}
                     for p in Payment.objects.filter(invoice__client=person)],
        "schedules": [{"id": str(s.pk), "label": s.label, "period": s.period, "status": s.status}
                      for s in Schedule.objects.filter(client=person)],
    }
