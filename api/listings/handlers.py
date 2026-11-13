"""LST event subscribers and registrations. Every handler is idempotent and never raises a domain error back
into the producer's transaction.

Consumes: seller_invoice.paid, report.released, monitoring.alert_raised, monitoring.alert_resolved,
fresh_search.completed, release.confirmed, escrow.cancelled, dispute.opened, dispute.resolved, dispute.withdrawn.
Registers: client home items, evidence access for listing, listing_private and seller_screening, data
protection open matters and exporter.
"""
import logging

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)


def _safe(fn, *a, **kw):
    try:
        with transaction.atomic():
            return fn(*a, **kw)
    except DomainError as exc:
        log.warning("listings: %s failed: %s", getattr(fn, "__name__", fn), exc.detail)
        return None


@subscribe("seller_invoice.paid")
def on_invoice_paid(ev):
    from payments.models import Invoice

    from . import services

    inv = Invoice.objects.filter(pk=ev.payload.get("invoice_id")).first()
    if inv is not None and inv.kind == "listing_fee" and inv.subject_type == "listing" and inv.subject_id:
        _safe(services.on_fee_paid, inv.subject_id)


@subscribe("report.released")
def on_report_released(ev):
    from . import services

    _safe(services.on_report_released, ev.payload or {})


@subscribe("monitoring.alert_raised")
def on_alert_raised(ev):
    from . import services

    _safe(services.on_alert_raised, ev.payload or {})


@subscribe("monitoring.alert_resolved")
def on_alert_resolved(ev):
    from . import services

    _safe(services.on_alert_resolved, ev.payload or {})


@subscribe("fresh_search.completed")
def on_fresh_search(ev):
    from . import services

    _safe(services.on_fresh_search_completed, ev.payload or {})


@subscribe("release.confirmed")
def on_release_confirmed(ev):
    from . import services

    _safe(services.on_release_confirmed, ev.payload or {})


@subscribe("escrow.cancelled")
def on_escrow_cancelled(ev):
    from . import services

    _safe(services.on_escrow_cancelled, ev.payload or {})


@subscribe("dispute.opened")
def on_dispute_opened(ev):
    from . import services

    _safe(services.on_dispute, ev.payload or {}, True)


@subscribe("dispute.resolved", "dispute.withdrawn")
def on_dispute_closed(ev):
    from . import services

    _safe(services.on_dispute, ev.payload or {}, False)


# --------------------------------------------------------------------------- registries

def _home(person):
    from accounts.home import item

    from .models import Enquiry, Listing, Reservation

    out = []
    for r in Reservation.objects.filter(buyer=person, status="active").select_related("listing", "escrow"):
        text = {"pending": "A fresh search is running on the plot.",
                "passed": "The fresh search passed. Your purchase continues through the escrow.",
                "failed": "The fresh search found a problem."}[r.fresh_search_status]
        needs = r.escrow is not None and r.escrow.status == "proposed"
        out.append(item(kind="listing_reservation", id=r.pk, title=f"Reserved: {r.listing.title}", status=r.status,
                        status_text=text + (" Accept the escrow terms." if needs else ""), next_date=r.expires_at,
                        needs_action=needs, link=f"/reservations/{r.pk}", line="listings"))
    for e in Enquiry.objects.filter(buyer=person, status="answered"):
        out.append(item(kind="listing_enquiry", id=e.pk, title=f"Answer to enquiry {e.reference}", status=e.status,
                        status_text="Tenmina answered your question.", link=f"/enquiries/{e.pk}", line="listings"))
    for x in Listing.objects.filter(submitted_by=person, status="draft", submitted_at__isnull=False):
        out.append(item(kind="listing", id=x.pk, title=f"Listing {x.reference}", status="draft",
                        status_text="Pay the listing fee to start the checks.", needs_action=True,
                        link=f"/listings/{x.pk}", line="listings"))
    for x in Listing.objects.filter(submitted_by=person, status__in=["in_verification", "live", "suspended",
                                                                      "expired", "reserved"]):
        out.append(item(kind="listing", id=x.pk, title=x.title, status=x.status,
                        status_text={"in_verification": "Being verified.", "live": "Live with the badge.",
                                     "suspended": "Suspended. The badge is hidden.",
                                     "expired": "Badge expired. Order re-verification.",
                                     "reserved": "Reserved by a buyer."}[x.status],
                        needs_action=x.status == "expired", next_date=x.badge_expires_at,
                        link=f"/listings/{x.pk}", line="listings"))
    return out


def _listing(sid):
    from .models import Listing

    return Listing.objects.filter(pk=sid).first()


def _view_public(user, sid):
    """RUL-14: any signed-in buyer opens the photos and the full report of a live listing."""
    from . import services

    x = _listing(sid)
    if x is None:
        return False
    if services.is_seller(user, x) or x.reservations.filter(buyer=user).exists():
        return True
    return services.badge_valid(x)


def _view_private(user, sid):
    from . import services

    x = _listing(sid)
    return x is not None and services.is_seller(user, x)


def _attach(user, sid):
    from . import services

    x = _listing(sid)
    return x is not None and services.is_seller(user, x) and x.status not in ("sold", "withdrawn", "removed")


def _country(sid):
    x = _listing(sid)
    return x.country if x else None


def _register():
    from accounts import home
    from dataprotection import registry as dpr
    from evidence import access

    home.register(_home)
    access.register("listing", can_view=_view_public, can_attach=_attach, country=_country,
                    owner=lambda sid: ("listing", sid))
    access.register("listing_private", can_view=_view_private, can_attach=_attach, country=_country,
                    owner=lambda sid: ("listing", sid))
    access.register("seller_screening", can_view=lambda u, sid: False, can_attach=lambda u, sid: False)

    @dpr.open_matters
    def open_reservations(person):
        from .models import Reservation

        return [{"kind": "listing_reservation", "id": str(r.pk), "title": f"Reservation {r.reference}",
                 "reason": "A reservation with a purchase escrow is open."}
                for r in Reservation.objects.filter(buyer=person, status="active")]

    @dpr.exporter("listings")
    def export_listings(person):
        from .models import Enquiry, Listing, Reservation

        return {
            "listings": [{"reference": x.reference, "title": x.title, "status": x.status,
                          "price": f"{x.price_currency} {x.price_amount}", "created_at": x.created_at.isoformat()}
                         for x in Listing.objects.filter(submitted_by=person)],
            "enquiries": [{"reference": e.reference, "message": e.message, "answer": e.answer,
                           "created_at": e.created_at.isoformat()} for e in Enquiry.objects.filter(buyer=person)],
            "reservations": [{"reference": r.reference, "status": r.status, "listing": r.listing.reference,
                              "created_at": r.created_at.isoformat()}
                             for r in Reservation.objects.filter(buyer=person)],
        }


_register()
