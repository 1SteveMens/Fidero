"""PTR event subscribers and registrations. Idempotent; never raises into the producer.

Consumes: report.released (status webhooks, partner orders completed), consent.changed (consent.withdrawn
webhooks), order.paid (link a partner order to its order). Registers: client home items for partner orders
waiting for the client, the data protection exporter.
"""
import logging

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)


@subscribe("report.released")
def on_report_released(ev):
    from . import services

    try:
        with transaction.atomic():
            services.on_report_released(dict(ev.payload or {}))
    except DomainError as exc:
        log.warning("partner webhooks for %s not queued: %s", ev.id, exc.detail)


@subscribe("consent.changed")
def on_consent_changed(ev):
    from . import services

    try:
        with transaction.atomic():
            services.on_consent_changed(dict(ev.payload or {}))
    except DomainError as exc:
        log.warning("consent webhook for %s not queued: %s", ev.id, exc.detail)


def _register():
    from accounts import home
    from dataprotection import registry

    from .models import PartnerOrder

    @home.register
    def partner_orders(person):
        out = []
        for o in PartnerOrder.objects.filter(person=person, status="awaiting_client").select_related("client"):
            out.append(home.item(kind="partner_order", id=o.pk, title=f"Check requested by {o.client.name}",
                                 status=o.status, needs_action=True, link=f"/partner-orders/{o.pk}",
                                 status_text=f"{o.client.name} asked us to check a plot at {o.locality}. Confirm "
                                             "or decline.", line="property"))
        return out

    @registry.exporter("partner_orders")
    def export_orders(person):
        return [{"reference": o.reference, "partner": o.client.name, "locality": o.locality, "status": o.status,
                 "created_at": o.created_at.isoformat()} for o in PartnerOrder.objects.filter(person=person)]


_register()
