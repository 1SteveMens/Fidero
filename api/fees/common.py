"""Small helpers shared by the FEE services, selectors and views."""
import logging
import secrets
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core.permissions import has_role

log = logging.getLogger("fees")
STAFF = ("CM", "RV", "AD")


def now():
    return timezone.now()


def today():
    return timezone.localdate()


def cfg(country, key, default=None):
    from countries.selectors import config

    try:
        value = config(country, key, None)
    except Exception:  # noqa: BLE001 - a country without configuration uses the default
        value = None
    return default if value is None else value


def setting(key, country, default=None):
    from administration.selectors import setting as adm_setting

    value = adm_setting(key, country, None)
    return default if value is None else value


def is_staff(user, country=None, roles=STAFF) -> bool:
    return has_role(user, *roles, country=country)


def staff_in(country, *roles):
    from accounts.models import Person

    return Person.objects.filter(
        Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
        role_grants__role__in=roles, role_grants__revoked_at__isnull=True, is_active=True).distinct()


def notify(person, template, body, *, subject="", needs_action=False, obj=None, link="", channels=("in_app", "email"),
           category=None, country=None):
    """A failed notification never stops a payment step; it is logged."""
    from notifications.services import notify as ntf

    if person is None:
        return []
    try:
        return ntf(person, template, body=body, subject=subject, needs_action=needs_action, subject_obj=obj,
                   subject_type=_subject_type(obj), link=link, channels=channels, category=category,
                   country=country)
    except Exception:  # noqa: BLE001
        log.exception("notification %s to %s failed", template, getattr(person, "pk", None))
        return []


def _subject_type(obj):
    if obj is None:
        return ""
    return {"Institution": "institution", "Invoice": "fee_invoice", "Payment": "fee_payment",
            "RunnerTask": "fee_runner_task", "Schedule": "fee_schedule"}.get(type(obj).__name__, "")


def resolve_action(obj, person=None):
    from notifications.services import resolve_action as resolve

    try:
        resolve(obj, subject_type=_subject_type(obj), person=person)
    except Exception:  # noqa: BLE001
        log.exception("resolve_action failed")


def alert_staff(country, roles, template, body, *, obj=None, link="", exclude=()):
    for p in staff_in(country, *roles):
        if p.pk in exclude:
            continue
        notify(p, template, body, obj=obj, link=link, needs_action=True, category="task", channels=("in_app",))


def audit(actor, action, obj, data=None, country=None):
    from audit.services import record

    record(actor=actor, action=action, entity=_subject_type(obj) or obj.__class__.__name__.lower(), entity_id=obj.pk,
           data=data or {}, country=country if country is not None else getattr(obj, "country", None))


def fmt(amount, currency) -> str:
    return f"{currency} {amount:,.2f}"


def new_reference(prefix, country) -> str:
    return f"{prefix}-{country.code}-{secrets.token_hex(3).upper()}"


def add_period(d, period, country=None):
    """Next due date of a recurring schedule. Term length is configuration (`fees.term_months`, 4 [TO VERIFY])."""
    months = {"month": 1, "quarter": 3, "term": int(cfg(country, "fees.term_months", 4) or 4)}[period]
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    import calendar

    day = min(d.day, calendar.monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


def days(n):
    return timedelta(days=int(n))
