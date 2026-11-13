"""EVT event subscribers and registrations. Handlers are idempotent and never raise a domain error back into
the producer's transaction.

Consumes: case.status_changed (vendor verification), payee.verified, payee.suspended, escrow.funded,
release.confirmed, release.withdrawn, release.rejected, release.rejected_by_bank,
family_confirmation.confirmed, family_confirmation.disputed (ADR-20).
Registers: the escrow subject check and label for `event_vendor_payment`, client home items, evidence access
for evt_event, evt_vendor and event_vendor_payment, data protection open matters and exporter.
"""
import logging

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)


def _safe(fn, *args, **kw):
    try:
        with transaction.atomic():
            return fn(*args, **kw)
    except DomainError as exc:
        log.info("events handler %s: %s", getattr(fn, "__name__", fn), exc.detail)
        return None


@subscribe("case.status_changed")
def on_case_status(ev):
    p = ev.payload
    if p.get("entity") != "case" or p.get("product_line") != "vendor_verification" or p.get("to") != "completed":
        return
    from . import services

    _safe(services.on_vendor_case, p.get("case_id") or p.get("id"), p.get("outcome") or "", p.get("reason", ""))


@subscribe("payee.verified")
def on_payee_verified(ev):
    if ev.payload.get("kind") != "vendor":
        return
    from . import services

    _safe(services.on_payee_status, ev.payload.get("payee_id"), True)


@subscribe("payee.suspended")
def on_payee_suspended(ev):
    from . import services

    _safe(services.on_payee_status, ev.payload.get("payee_id"), False)


@subscribe("escrow.funded")
def on_funded(ev):
    if ev.payload.get("kind") != "event":
        return
    from . import services

    _safe(services.on_escrow_funded, ev.payload.get("escrow_id"))


@subscribe("release.confirmed")
def on_release_confirmed(ev):
    if ev.payload.get("subject_type") != "event_vendor_payment":
        return
    from . import services

    _safe(services.on_release_confirmed, ev.payload)


@subscribe("release.withdrawn", "release.rejected", "release.rejected_by_bank")
def on_release_closed(ev):
    if ev.payload.get("subject_type") != "event_vendor_payment":
        return
    from . import services

    _safe(services.on_release_closed, ev.payload)


@subscribe("family_confirmation.confirmed", "family_confirmation.disputed")
def on_family_confirmation(ev):
    if ev.payload.get("subject_type") != "event_vendor_payment":
        return
    from . import services

    _safe(services.on_family_confirmation, ev.payload, ev.topic.endswith("confirmed"))


def _register():
    from accounts import home
    from dataprotection import registry as dpr
    from escrow import registry as esc_registry
    from evidence import access

    from . import services
    from .models import Event, Vendor, VendorPayment

    esc_registry.register_subject_check("event_vendor_payment", services.payment_release_check)
    esc_registry.subject_label("event_vendor_payment", services.payment_label)

    @home.register
    def evt_home(person):
        out = []
        for e in Event.objects.filter(client=person).exclude(status__in=["closed", "cancelled"]):
            waiting = e.payments.filter(status="evidenced").count()
            if waiting:
                text, needs = f"{waiting} vendor payment(s) wait for your approval.", True
            elif e.escrow_id is None:
                text = "Add vendors. Once one is verified, the budget goes to the bank."
                needs = e.vendors.filter(status="verified").exists()
            elif e.escrow.status in ("proposed", "agreed"):
                text, needs = "Pay the budget to the bank, using the bank's details.", e.escrow.status == "agreed"
            else:
                text, needs = "Vendors are paid against quotes, invoices and delivery evidence.", False
            out.append(home.item(kind="event", id=e.pk, title=e.name, status=e.status, status_text=text,
                                 next_date=e.event_date, needs_action=needs, link=services.event_link(e), line="evt",
                                 amount={"amount": f"{e.budget_amount:.2f}", "currency": e.budget_currency}))
        return out

    def _ev(sid):
        return Event.objects.filter(pk=sid).first()

    access.register("evt_event",
                    can_view=lambda u, sid: (lambda e: bool(e) and services.can_view(u, e))(_ev(sid)),
                    can_attach=lambda u, sid: (lambda e: bool(e) and services.can_view(u, e))(_ev(sid)),
                    country=lambda sid: getattr(_ev(sid), "country", None), owner=lambda sid: ("evt_event", sid))

    def _vd(sid):
        return Vendor.objects.filter(pk=sid).select_related("event").first()

    access.register("evt_vendor",
                    can_view=lambda u, sid: (lambda v: bool(v) and services.can_view(u, v.event))(_vd(sid)),
                    can_attach=lambda u, sid: (lambda v: bool(v) and services.can_view(u, v.event))(_vd(sid)),
                    country=lambda sid: getattr(_vd(sid), "country", None),
                    owner=lambda sid: ("evt_event", getattr(_vd(sid), "event_id", None)))

    def _pay(sid):
        return VendorPayment.objects.filter(pk=sid).select_related("event").first()

    access.register("event_vendor_payment",
                    can_view=lambda u, sid: (lambda p: bool(p) and services.can_view(u, p.event))(_pay(sid)),
                    can_attach=lambda u, sid: (lambda p: bool(p) and services.is_staff(u, p.country))(_pay(sid)),
                    country=lambda sid: getattr(_pay(sid), "country", None),
                    owner=lambda sid: ("evt_event", getattr(_pay(sid), "event_id", None)))

    @dpr.open_matters
    def evt_open_matters(person):
        return [{"kind": "event", "id": str(e.pk), "title": e.name,
                 "reason": "Event money is held at the bank or vendor payments are open."}
                for e in Event.objects.filter(client=person, status__in=["funded", "in_progress"])]

    @dpr.exporter("events")
    def evt_export(person):
        return [{"id": str(e.pk), "name": e.name, "kind": e.kind, "date": e.event_date.isoformat(),
                 "budget": f"{e.budget_amount:.2f}", "currency": e.budget_currency, "status": e.status,
                 "payments": [{"vendor": p.vendor.name, "amount": f"{p.amount:.2f}", "status": p.status}
                              for p in e.payments.select_related("vendor")]}
                for e in Event.objects.filter(client=person)]


_register()
