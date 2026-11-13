"""GEO background jobs (02 section 7.12). Beat schedule: geo.monitor_changes weekly."""
from celery import shared_task


@shared_task(name="geo.run_overlays")
def run_overlays(run_id):
    from . import services
    from .models import OverlayRun

    run = OverlayRun.objects.filter(pk=run_id).first()
    return None if run is None else str(services.run_overlays(run).status)


@shared_task(name="geo.monitor_changes")
def monitor_changes(country_code=None):
    from countries.models import Country

    from . import services

    country = Country.objects.get(code=country_code) if country_code else None
    out = services.run_monitoring(country=country)
    return {k: v for k, v in out.items() if k != "alert_ids"}
