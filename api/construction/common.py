"""Small helpers shared by the BLD and PRJ services. Not an interface for other modules."""
import logging
from datetime import date
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from administration import flags
from audit.services import record
from core.errors import Forbidden
from core.permissions import has_role

log = logging.getLogger("construction")

STAFF = ("CM", "RV", "AD")
BUILD_FLAG = "building.construction"
FUNDS_FLAG = "projects.funds"

# Working assumptions per country, read from the country configuration with these defaults [TO VERIFY].
DEFAULTS = {
    "payment_route": "client_direct",  # decision 2026-11-12: verify and confirm until a licensed partner pays
    "defects_period_days": 180,
    "reprice_max_age_days": 3,
    "inspection_lead_days": 3,
    "reprice_tolerance_pct": "0",  # any change at all is shown to the client (RUL-18)
}


def now():
    return timezone.now()


def today(country=None) -> date:
    import zoneinfo

    tz = getattr(country, "timezone", "") or "UTC"
    try:
        return timezone.now().astimezone(zoneinfo.ZoneInfo(tz)).date()
    except Exception:  # noqa: BLE001
        return timezone.localdate()


def flag_for(project_type: str) -> str:
    return FUNDS_FLAG if project_type == "funds" else BUILD_FLAG


def area_for(project_type: str) -> str:
    return "projects" if project_type == "funds" else "construction"


def require_on(project_type, country):
    flags.require(flag_for(project_type), country)
    flags.read_only_guard()


def cfg(country, project_type, key, default=None):
    from countries.selectors import config

    d = DEFAULTS.get(key) if default is None else default
    return config(country, f"{area_for(project_type)}.{key}", d)


def fmt(amount, currency) -> str:
    return f"{currency} {Decimal(amount):,.2f}"


def is_staff(person, country=None) -> bool:
    return has_role(person, *STAFF, country=country)


def require_staff(person, country, *roles, message="Only Tenmina staff can do this."):
    if not has_role(person, *(roles or STAFF), country=country):
        raise Forbidden(message)


def staff_in(country, *roles):
    from accounts.models import Person

    return Person.objects.filter(
        Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
        role_grants__role__in=roles, role_grants__revoked_at__isnull=True, is_active=True).distinct()


def audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=obj.__class__.__name__.lower(), entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None))


def notify(person, template, body, *, subject="", needs_action=False, obj=None, link="", channels=("in_app",),
           category=None):
    """Never let a notification failure stop a step; log it instead."""
    from notifications.services import notify as ntf

    if person is None:
        return []
    try:
        return ntf(person, template, body=body, subject=subject, needs_action=needs_action, subject_obj=obj,
                   link=link, channels=channels, category=category)
    except Exception:  # noqa: BLE001
        log.exception("notification %s to %s failed", template, getattr(person, "pk", None))
        return []


def alert_staff(country, roles, template, body, *, obj=None, link=""):
    for p in staff_in(country, *roles):
        notify(p, template, body, obj=obj, link=link, needs_action=True, category="task")


def resolve(obj):
    try:
        from notifications.services import resolve_action

        resolve_action(obj)
    except Exception:  # noqa: BLE001
        log.exception("could not resolve notifications for %s", obj)


def evidence_objects(ids, by, country, *, required=True, what="evidence"):
    """Evidence the caller uploaded (or staff may use) in this country."""
    from core.errors import Invalid
    from evidence.models import Evidence

    ids = [i for i in (ids or []) if i]
    if not ids:
        if required:
            raise Invalid(f"Attach the {what}.", code="validation-error")
        return []
    out = []
    for eid in ids:
        ev = Evidence.objects.filter(pk=eid, country=country).first()
        if ev is None or (ev.uploaded_by_id != by.pk and not is_staff(by, country)):
            raise Invalid("That file was not found. Upload it again.", code="evidence-rejected")
        if getattr(ev, "scan_status", "clean") == "rejected" or getattr(ev, "deleted_at", None):
            raise Invalid("That file cannot be used.", code="evidence-rejected")
        out.append(ev)
    return out


def link_all(evidence, subject_type, subject_id, role, by):
    from evidence.services import link

    for ev in evidence:
        link(ev, subject_type, subject_id, role=role, by=by)
