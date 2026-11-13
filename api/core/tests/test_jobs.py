"""Background jobs (02 section 7.12): the beat schedule, the run_jobs command and the app version middleware."""
import io
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.utils import timezone

# Every periodic job the modules provide must be on the schedule.
REQUIRED = [
    "core.relay_outbox", "core.purge_idempotency", "audit.anchor_head", "audit.verify_chain",
    "accounts.licence_expiry", "accounts.national_id_retry", "accounts.vetting_expiry", "accounts.invitation_expiry",
    "administration.refresh_fx", "notifications.due_reminders", "notifications.send_deferred",
    "evidence.integrity_sample", "evidence.retention_sweep", "dataprotection.retention_sweep",
    "dataprotection.process_waiting_deletions", "dataprotection.bulk_export_expiry", "dataprotection.overdue_requests",
    "payments.reconcile_pending", "payments.reconcile", "geo.monitor_changes", "cases.task_overdue",
    "cases.search_result_watch", "reports.draw_recheck_sample", "reports.recheck_due", "escrow.release_clock_watch",
    "escrow.retry_unsent", "escrow.fx_collect_rates", "fees.schedule_due", "fees.receipt_overdue",
    "fees.institution_reverify", "care.visit_reminders", "care.missed_and_unconfirmed", "care.weekly_payment_batch",
    "errands.target_watch", "insurance.premium_due", "insurance.renewal_reminders", "construction.remind_clients",
    "listings.expire_badges", "listings.lapse_reservations", "propertymgmt.match_rent",
    "propertymgmt.schedule_inspections", "disputes.deadline_tick", "ratings.recompute", "partners.deliver_webhooks",
    "pro.check_overdue", "pro.yearly_statements", "mobile.missing_checkouts",
]
# Tasks that run on an event or on demand, never on a timer.
EVENT_DRIVEN = {"cases.create_from_order", "countries.copy_config", "geo.run_overlays"}


def _registered():
    from tenmina.celery import app

    app.loader.import_default_modules()
    return {n for n in app.tasks if not n.startswith("celery.")}


def test_every_scheduled_job_is_a_registered_task():
    """02 7.12: each schedule entry names a real Celery task."""
    registered = _registered()
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        assert entry["task"] in registered, name


def test_every_periodic_task_is_scheduled():
    """02 7.12: no module's periodic job is left off the schedule, and nothing event-driven is put on it."""
    scheduled = set(settings.CELERY_BEAT_SCHEDULE)
    assert set(REQUIRED) <= scheduled
    assert not (EVENT_DRIVEN & scheduled)
    assert _registered() - scheduled - EVENT_DRIVEN == set()


def test_run_jobs_lists_and_runs_a_job(db):
    """Staff run any scheduled job once by hand in development."""
    from core.models import IdempotencyKey

    old = IdempotencyKey.objects.create(principal="p", key="k-old", request_hash="h")
    IdempotencyKey.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=25))
    IdempotencyKey.objects.create(principal="p", key="k-new", request_hash="h")
    out = io.StringIO()
    call_command("run_jobs", "core.purge_idempotency", stdout=out)
    assert "core.purge_idempotency: 1" in out.getvalue()
    assert list(IdempotencyKey.objects.values_list("key", flat=True)) == ["k-new"]
    listing = io.StringIO()
    call_command("run_jobs", "--list", stdout=listing)
    assert "escrow.release_clock_watch" in listing.getvalue()


def test_run_jobs_runs_module_jobs_on_seeded_data(seeded):
    """The wrappers added for payments, construction and the outbox run on real data."""
    out = io.StringIO()
    call_command("run_jobs", "core.relay_outbox", "payments.reconcile_pending", "construction.remind_clients",
                 "disputes.deadline_tick", stdout=out)
    assert out.getvalue().count(":") >= 4


def test_run_jobs_refuses_an_unknown_name(db):
    with pytest.raises(CommandError, match="Did you mean fees.schedule_due"):
        call_command("run_jobs", "fees.schedule_dew")


def test_app_version_middleware_is_registered(seeded, api, people):
    """FR-APP-006: an app below the minimum version gets 426 on any /v1 call; the web portal sends no header."""
    from administration.models import FeatureFlag

    assert "mobile.appversion.AppVersionMiddleware" in settings.MIDDLEWARE
    FeatureFlag.objects.filter(name="app.min_version.client.android").update(value="5.0.0")
    c = api(people["client"])
    r = c.get("/v1/home", HTTP_TENMINA_APP="client/android/4.9.0")
    assert r.status_code == 426 and r.json()["code"] == "app-version-unsupported"
    assert c.get("/v1/home", HTTP_TENMINA_APP="client/android/5.0.0").status_code == 200
    assert c.get("/v1/home").status_code == 200
