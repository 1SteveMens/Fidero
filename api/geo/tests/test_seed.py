"""The demo seed covers every overlay outcome and monitoring state."""
from geo import services
from geo.models import MonitoringAlert, OverlapFlag


def test_seed_shows_every_outcome(seeded):
    a = seeded["geo"]["assets"]
    assert services.section7(a["clear"])["proposed_verdict"] == "green"
    assert services.section7(a["acquired"])["proposed_verdict"] == "red"
    assert services.section7(a["near_road"])["proposed_verdict"] == "amber"
    assert services.section7(a["overlapping"])["proposed_verdict"] == "amber"
    assert services.section7(a["disputed"])["proposed_verdict"] == "red"
    a["disputed"].refresh_from_db()
    assert a["disputed"].disputed_flag
    assert OverlapFlag.objects.filter(asset=a["overlapping"], other_asset=a["verified"], other_kind="verified").exists()
    assert MonitoringAlert.objects.filter(status="open").exists()
    assert MonitoringAlert.objects.filter(status="resolved").exists()


def test_seed_is_idempotent_and_quiet(seeded):
    """Seeds use get_or_create and, like the other seeds, write no audit entries."""
    from audit.models import AuditEvent
    from geo import seed
    from geo.models import Asset, BoundaryVersion, OverlayLayerVersion

    def counts():
        return (Asset.objects.count(), BoundaryVersion.objects.count(), OverlayLayerVersion.objects.count(),
                MonitoringAlert.objects.count())

    before = counts()
    audit_before = AuditEvent.objects.filter(entity__in=["asset", "overlay_layer", "monitoring_alert"]).count()
    seed.run(seeded)
    assert counts() == before
    # Other modules' seeds may audit assets they create; the geo seed itself writes none.
    assert AuditEvent.objects.filter(entity__in=["asset", "overlay_layer", "monitoring_alert"]).count() == audit_before
