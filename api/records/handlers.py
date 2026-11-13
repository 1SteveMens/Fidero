"""REC event subscribers and registrations. Idempotent; never raises into the producer.

Consumes: asset.boundary_saved and case.status_changed (match the case's plot against the records).
Registers: evidence access for rec_allocation and rec_authority (staff, and the authority's own representative).
"""
import logging
import uuid

from django.db import transaction

from core.errors import DomainError
from core.events import subscribe

log = logging.getLogger(__name__)


def _uuid(v):
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


def _match(cases):
    from . import services

    for c in cases:
        try:
            with transaction.atomic():
                services.match_case(c)
        except DomainError as exc:
            log.warning("records match for case %s failed: %s", c.pk, exc.detail)


@subscribe("asset.boundary_saved")
def on_boundary_saved(ev):
    from cases.models import OPEN_STATUSES, Case

    if (ev.payload or {}).get("source") == "records_programme":
        return
    _match(Case.objects.filter(asset_id=_uuid(ev.payload.get("asset_id")), status__in=OPEN_STATUSES))


@subscribe("case.status_changed", "case.created")
def on_case(ev):
    from cases.models import Case

    p = ev.payload or {}
    if p.get("to") not in (None, "in_progress", "paid") and p.get("status") not in ("in_progress", "paid"):
        return
    c = Case.objects.filter(pk=_uuid(p.get("case_id") or p.get("id"))).select_related("asset", "country").first()
    if c is not None and c.asset_id:
        _match([c])


def _register():
    from evidence import access

    from . import services
    from .models import Allocation, Authority

    def _alloc(sid):
        return Allocation.objects.filter(pk=sid).select_related("authority", "country").first()

    access.register(
        "rec_allocation",
        can_view=lambda u, sid: (lambda a: a is not None and services.can_view_authority(u, a.authority))(
            _alloc(sid)),
        can_attach=lambda u, sid: (lambda a: a is not None and services.can_view_authority(u, a.authority))(
            _alloc(sid)),
        country=lambda sid: _alloc(sid).country, owner=lambda sid: ("rec_authority", _alloc(sid).authority_id))
    access.register(
        "rec_authority",
        can_view=lambda u, sid: (lambda a: a is not None and services.can_view_authority(u, a))(
            Authority.objects.filter(pk=sid).first()),
        can_attach=lambda u, sid: False,
        country=lambda sid: Authority.objects.get(pk=sid).country, owner=lambda sid: ("rec_authority", sid))


_register()
