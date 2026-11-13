"""Celery beat schedule: every periodic job the modules provide (02 section 7.12).

All times are UTC, which is GMT, Ghana's time. Every schedule is a working
assumption; change it here, never in a module. Event-driven jobs (for example
`cases.create_from_order` or `geo.run_overlays`) are not listed: they run when
their event fires. `python manage.py run_jobs <name>` runs any job below once,
by hand.

No job here approves or releases anything: silence is never approval.
"""
from datetime import timedelta

from celery.schedules import crontab

EVERY_MINUTE = timedelta(minutes=1)
EVERY_5_MIN = timedelta(minutes=5)
EVERY_15_MIN = timedelta(minutes=15)


def daily(hour, minute=0):
    return crontab(hour=hour, minute=minute)


def hourly(minute):
    return crontab(minute=minute)


def first_working_day(hour, minute=0):
    """The first Monday-to-Friday of the month (Celery matches day of month AND day of week). Holidays are not
    known here; each monthly job skips a month it has already done."""
    return crontab(hour=hour, minute=minute, day_of_month="1-4", day_of_week="mon-fri")


def weekdays(hour, minute=0):
    return crontab(hour=hour, minute=minute, day_of_week="mon-fri")


# name -> (schedule, what it does). The task name is the key.
JOBS = {
    # Shared kernel and audit
    "core.relay_outbox": (timedelta(seconds=2), "Publish outbox events not yet dispatched (ADR-08)"),
    "core.purge_idempotency": (daily(3, 10), "Remove Idempotency-Key records past 24 hours (7.1)"),
    "audit.anchor_head": (hourly(5), "Write the audit chain head to write-once storage (FR-AUD-004)"),
    "audit.verify_chain": (daily(3, 30), "Recompute the audit chain and alert on a break (FR-AUD-004)"),
    # Accounts
    "accounts.licence_expiry": (daily(0, 20), "Flag expiring and expired licences (FR-ACC-005)"),
    "accounts.national_id_retry": (EVERY_15_MIN, "Retry pending national identity checks (FR-ACC-013)"),
    "accounts.vetting_expiry": (daily(0, 25), "Lapse expired carer and agent vettings"),
    "accounts.invitation_expiry": (daily(0, 30), "Expire unused staff and family invitations"),
    # Administration and notifications
    "administration.refresh_fx": (weekdays(10, 30), "Guide exchange rates after the day's rate collection"),
    "notifications.due_reminders": (daily(7, 0), "Reminders 2 working days before due; overdue alerts (FR-NTF-003)"),
    "notifications.send_deferred": (EVERY_5_MIN, "Send messages held for quiet hours"),
    # Evidence and data protection
    "evidence.integrity_sample": (daily(1, 0), "Re-hash a random sample of evidence (BR-06)"),
    "evidence.retention_sweep": (daily(2, 30), "Delete evidence past retention, respecting holds (6.10)"),
    "dataprotection.retention_sweep": (daily(2, 15), "Delete or anonymise data past retention (FR-DPR-004)"),
    "dataprotection.process_waiting_deletions": (daily(4, 0), "Close accounts whose open matters have ended"),
    "dataprotection.bulk_export_expiry": (hourly(40), "Expire bulk export download links (FR-DPR-005)"),
    "dataprotection.overdue_requests": (daily(7, 20), "Alert on data subject requests near their deadline"),
    # Payments
    "payments.reconcile_pending": (EVERY_15_MIN, "Verify open payment attempts, time out the rest (IF-02)"),
    "payments.reconcile": (daily(2, 0), "Reconcile yesterday's settlement against orders (FR-PAY-006)"),
    # Verification
    "geo.monitor_changes": (crontab(hour=3, minute=0, day_of_week="mon"), "Satellite change detection (FR-GEO-007)"),
    "cases.task_overdue": (daily(6, 0), "Mark overdue case tasks and alert the case manager"),
    "cases.search_result_watch": (daily(6, 10), "Alert on registry searches with no result (FR-CASE-016)"),
    "reports.draw_recheck_sample": (first_working_day(5, 0), "Draw last month's random re-check sample (FR-RPT-012)"),
    "reports.recheck_due": (daily(6, 20), "Alert a reviewer to re-checks due or unassigned (FR-RPT-012)"),
    # Escrow
    "escrow.release_clock_watch": (EVERY_15_MIN, "Releases not sent or not paid on time (FR-ESC-018, NFR-PERF-06)"),
    "escrow.retry_unsent": (EVERY_15_MIN, "Resend approved instructions that failed to send"),
    "escrow.fx_collect_rates": (weekdays(10, 0), "Collect reference and provider rates [TO VERIFY] (FR-ESC-024)"),
    # Family payments, care, errands, insurance
    "fees.schedule_due": (daily(6, 30), "Draft invoices from recurring schedules (FR-FEE-005)"),
    "fees.receipt_overdue": (daily(6, 40), "Chase receipts past the target days (FR-FEE-004)"),
    "fees.institution_reverify": (crontab(hour=4, minute=30, day_of_month="1"), "Re-verify institutions (RUL-22)"),
    "care.visit_reminders": (daily(6, 0), "Create visits, remind carers, tell families (FR-CARE-002, -003)"),
    "care.missed_and_unconfirmed": (EVERY_15_MIN, "Missed and unconfirmed visits (FR-CARE-004, -005)"),
    "care.weekly_payment_batch": (crontab(hour=8, minute=0, day_of_week="mon"), "Instructions for confirmed visits"),
    "errands.target_watch": (daily(6, 45), "Warn when an errand nears or passes its target (FR-TSK-001)"),
    "insurance.premium_due": (daily(6, 50), "Create due premiums (FR-INS-002)"),
    "insurance.renewal_reminders": (daily(7, 10), "Renewal reminders; mark lapsed policies (FR-INS-003)"),
    # Property
    "construction.remind_clients": (daily(8, 10), "Remind clients to approve inspected milestones (RUL-11)"),
    "listings.expire_badges": (hourly(15), "Expire badges, suspend on alerts (FR-LST-006)"),
    "listings.lapse_reservations": (hourly(20), "Release lapsed reservations (FR-LST-005)"),
    "propertymgmt.match_rent": (daily(7, 0), "Match rent to statements; late rent alerts (FR-PMG-003)"),
    "propertymgmt.schedule_inspections": (first_working_day(5, 30), "Periodic property inspections (FR-PMG-006)"),
    # Disputes, ratings, partners, professional payments
    "disputes.deadline_tick": (hourly(25), "Advance disputes on their deadlines (FR-DSP-003)"),
    "ratings.recompute": (daily(1, 30), "Recompute track records (FR-RAT-001)"),
    "partners.deliver_webhooks": (EVERY_MINUTE, "Deliver partner webhooks with retries (IF-08)"),
    "pro.check_overdue": (daily(7, 30), "Alert on payables past due (FR-PRO-008)"),
    "pro.yearly_statements": (first_working_day(6, 0), "Yearly statements once a tax year has ended (FR-PRO-007)"),
    # Field app
    "mobile.missing_checkouts": (daily(23, 30), "Report visits with a check-in and no check-out"),
}

CELERY_BEAT_SCHEDULE = {name: {"task": name, "schedule": schedule} for name, (schedule, _what) in JOBS.items()}
