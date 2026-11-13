"""GEO event subscribers. Every handler is idempotent.

- asset.boundary_saved (own): overlap check then overlay checks (geo.check_overlaps,
  geo.run_overlays in 02 7.12).
- listing.live (LST): mark the plot listed and start monitoring (05 sequence 5.5).
- listing.sold, listing.withdrawn (LST): stop the listing's monitoring.
- project.started (BLD/PRJ): start monitoring the project's plot.
- project.completed, project.closed (BLD/PRJ): stop it.
- report.released (RPT): when the payload names the asset, mark it verified (FR-GEO-005).
"""
import logging
import uuid

from django.utils import timezone

from core.events import subscribe

log = logging.getLogger(__name__)


def _uuid(value):
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _asset(payload):
    from .models import Asset

    aid = _uuid(payload.get("asset_id"))
    return Asset.objects.filter(pk=aid).first() if aid else None


@subscribe("asset.boundary_saved")
def on_boundary_saved(ev):
    from . import services
    from .models import BoundaryVersion, OverlayRun

    bv = BoundaryVersion.objects.filter(pk=_uuid(ev.payload.get("boundary_id"))).select_related("asset").first()
    if bv is None:
        return
    services.check_overlaps(bv)
    run = OverlayRun.objects.filter(pk=_uuid(ev.payload.get("run_id"))).first()
    if run is not None:
        services.run_overlays(run)


@subscribe("listing.live")
def on_listing_live(ev):
    from . import services

    asset = _asset(ev.payload)
    if asset is None:
        log.warning("listing.live without a known asset_id: %s", ev.payload)
        return
    if asset.listed_at is None:
        asset.listed_at = timezone.now()
        asset.save(update_fields=["listed_at"])
    services.enrol(asset, reason="listing", source_id=_uuid(ev.payload.get("listing_id") or ev.aggregate_id))


@subscribe("listing.sold", "listing.withdrawn", "listing.removed")
def on_listing_ended(ev):
    from . import services

    sid = _uuid(ev.payload.get("listing_id") or ev.aggregate_id)
    if sid:
        services.end_for_source(sid, reason=ev.topic)
    asset = _asset(ev.payload)
    if asset is not None and asset.listed_at is not None and ev.topic != "listing.sold":
        asset.listed_at = None
        asset.save(update_fields=["listed_at"])


@subscribe("project.started")
def on_project_started(ev):
    from . import services

    asset = _asset(ev.payload)
    if asset is None:
        log.warning("project.started without a known asset_id: %s", ev.payload)
        return
    services.enrol(asset, reason="project", source_id=_uuid(ev.payload.get("project_id") or ev.aggregate_id))


@subscribe("project.completed", "project.closed")
def on_project_ended(ev):
    from . import services

    sid = _uuid(ev.payload.get("project_id") or ev.aggregate_id)
    if sid:
        services.end_for_source(sid, reason=ev.topic)


@subscribe("report.released")
def on_report_released(ev):
    from . import services

    aid = _uuid(ev.payload.get("asset_id"))
    if aid:
        services.mark_verified(aid)
