"""PRO background jobs (02 section 7.12, 06 section 6.7). The beat schedule in
settings should add: pro.check_overdue daily at 07:00 local time and
pro.yearly_statements on the first working day after each country's tax year
ends [TO VERIFY with the accountant, Q-25]."""
from celery import shared_task

from . import services


@shared_task(name="pro.check_overdue")
def check_overdue():
    return services.check_overdue()


@shared_task(name="pro.yearly_statements")
def yearly_statements(tax_year=None):
    from django.utils import timezone

    from countries.selectors import active_countries

    out = {}
    for c in active_countries():
        year = tax_year or services.tax_year_of(c, timezone.localdate()) - 1
        out[c.code] = len(services.generate_statements(c, year))
    return out
