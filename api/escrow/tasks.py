"""ESC background jobs (02 section 7.12), scheduled in tenmina/celery_schedule.py:
escrow.release_clock_watch and escrow.retry_unsent every 15 minutes,
escrow.fx_collect_rates each working day at the bank's cut-off [TO VERIFY],
escrow.payee_expiry and escrow.reconcile_positions daily, and
escrow.cooling_off_end every 15 minutes. No job approves anything.

There is no job that dispatches later than the last approval: dispatch runs
on release.approved at once (RUL-33, ADR-26)."""
from celery import shared_task

from . import services


@shared_task(name="escrow.release_clock_watch")
def release_clock_watch():
    return services.release_clock_watch()


@shared_task(name="escrow.retry_unsent")
def retry_unsent():
    return services.retry_unsent()


@shared_task(name="escrow.fx_collect_rates")
def fx_collect_rates():
    from administration import flags
    from countries.selectors import active_countries

    out = {}
    for c in active_countries():
        if flags.enabled("escrow.enabled", c):
            out[c.code] = [str(r.pk) for r in services.collect_rates(c)]
    return out


@shared_task(name="escrow.payee_expiry")
def payee_expiry():
    return services.expire_payees()


@shared_task(name="escrow.cooling_off_end")
def cooling_off_end():
    return services.end_cooling_off()


@shared_task(name="escrow.reconcile_positions")
def reconcile_positions():
    return services.reconcile_positions()
