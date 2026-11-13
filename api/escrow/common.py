"""Small helpers shared by the ESC services. Not for other modules."""
import logging
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from audit.services import record
from core.permissions import has_role

log = logging.getLogger("escrow")

STAFF = ("CM", "RV", "AD")


def now():
    return timezone.now()


def local_today(country) -> date:
    """Today in the country's own time zone (working days follow its calendar)."""
    import zoneinfo

    tz = getattr(country, "timezone", "") or "UTC"
    try:
        return timezone.now().astimezone(zoneinfo.ZoneInfo(tz)).date()
    except Exception:  # noqa: BLE001
        return timezone.localdate()


def local_date(country, when: datetime) -> date:
    import zoneinfo

    tz = getattr(country, "timezone", "") or "UTC"
    try:
        return when.astimezone(zoneinfo.ZoneInfo(tz)).date()
    except Exception:  # noqa: BLE001
        return when.date()


def setting(key, country, default=None):
    from administration.selectors import setting as adm_setting

    v = adm_setting(key, country, default)
    return default if v in (None, "") else v


def cfg(country, key, default=None):
    from countries.selectors import config

    return config(country, key, default)


def working_day_on_or_after(country, d: date) -> date:
    from countries.selectors import add_working_days, is_working_day

    return d if is_working_day(country, d) else add_working_days(country, d, 1)


def add_working_days(country, d: date, n: int) -> date:
    from countries.selectors import add_working_days as add

    return add(country, d, n)


def fmt(amount, currency) -> str:
    return f"{currency} {Decimal(amount):,.2f}"


def is_staff(p, country=None) -> bool:
    return has_role(p, *STAFF, country=country)


def has_rr(p, country=None) -> bool:
    """Release rights (RR) held by a staff member (02 10.4)."""
    return has_role(p, "RR", country=country) and is_staff(p, country)


def staff_in(country, *roles):
    from accounts.models import Person

    return Person.objects.filter(
        Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
        role_grants__role__in=roles, role_grants__revoked_at__isnull=True, is_active=True).distinct()


def notify(person, template, body, *, subject="", needs_action=False, obj=None, link="", channels=("in_app",),
           category=None, context=None, country=None):
    """Never let a notification failure stop a money step; log it instead."""
    from notifications.services import notify as ntf

    if person is None:
        return []
    try:
        return ntf(person, template, body=body, subject=subject, needs_action=needs_action, subject_obj=obj,
                   link=link, channels=channels, category=category, context=context, country=country)
    except Exception:  # noqa: BLE001
        log.exception("notification %s to %s failed", template, getattr(person, "pk", None))
        return []


def alert_staff(country, roles, template, body, *, obj=None, link=""):
    for p in staff_in(country, *roles):
        notify(p, template, body, obj=obj, link=link, needs_action=True, category="task")


def audit(actor, action, obj, data=None, country=None):
    record(actor=actor, action=action, entity=obj.__class__.__name__.lower(), entity_id=obj.pk, data=data or {},
           country=country if country is not None else getattr(obj, "country", None))
