"""RPT background jobs (02 section 7.12). The beat schedule should add reports.draw_recheck_sample monthly
(first working day, 05:00 GMT) and reports.recheck_due daily."""
from datetime import date, timedelta

from celery import shared_task

from . import services


@shared_task(name="reports.draw_recheck_sample")
def draw_recheck_sample(today=None):
    """Draw last month's sample in every active country; a month already drawn is skipped."""
    from countries.selectors import active_countries
    from core.errors import DomainError

    today = today or date.today()
    last_month = (date(today.year, today.month, 1) - timedelta(days=1)).replace(day=1)
    out = []
    for c in active_countries():
        try:
            out.append(str(services.draw(c, last_month).pk))
        except DomainError:
            continue
    return out


@shared_task(name="reports.recheck_due")
def recheck_due():
    return services.recheck_due()
