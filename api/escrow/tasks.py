"""ESC background jobs (02 section 7.12). The beat schedule in settings should
add: escrow.release_clock_watch every 15 minutes, escrow.retry_unsent every
15 minutes, escrow.fx_collect_rates each working day at the bank's cut-off
[TO VERIFY] and again hourly while a source is stale.

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
