"""PMG Property management: the public interface other modules may call.

FR-PMG-001 register a property; onboarding case and a condition inspection with photos
FR-PMG-002 tenant, agreement, rent and the owner's own verified account as rent destination (RUL-24)
FR-PMG-003 rent due and received from the statement lines of that account only, under the owner's
           written mandate; late rent alerts to the owner, the tenant and Tenmina
FR-PMG-004 repairs reported by the tenant, owner or inspector; two quotes from vetted contractors with
           verified payees; the owner approves one (RUL-11)
FR-PMG-005 repair money held at the bank (repair escrow); released to the contractor only after an
           inspection pass with photos, through the two-person approval (RUL-22, RUL-05)
FR-PMG-006 periodic inspections and the owner's timeline

Tenmina never receives rent and never appears as a rent destination (RUL-24).

Events published: managed_property.registered, property.onboarded, statement_mandate.activated, tenancy.recorded,
rent.received, rent.late, rent.unmatched_line, repair.reported, repair.quote_added, repair.quote_approved,
repair.funded, repair.work_done, repair.inspected, repair.paid, pmg_inspection.submitted, work.accepted.
"""
import logging
import secrets
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from administration import flags
from audit.services import record
from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, PayeeNotVerified, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from . import adapters
from .models import (OUTCOMES, RENT_PERIODS, Inspection, ManagedProperty, RentPeriod, Repair, RepairQuote,
                     StatementImport, StatementMandate, Tenancy)

log = logging.getLogger(__name__)
STAFF = ("CM", "RV", "AD")
OPEN_RENT = ("due", "late", "partial")
OPEN_REPAIR = ("reported", "quoting", "quotes_ready", "approved", "funded", "in_progress", "inspected", "instructed")
ONBOARDING_ROOMS_MIN = 1


# --------------------------------------------------------------------------- helpers

def _now():
    return timezone.now()


def _today():
    return timezone.localdate()


def _on(country):
    flags.require("lines.pmg", country)
    flags.read_only_guard()


def _cfg(country, key, default=None):
    from countries.selectors import config

    try:
        value = config(country, f"pmg.{key}", default)
    except Exception:  # noqa: BLE001
        value = default
    return default if value is None else value


def _setting(key, country, default):
    from administration.selectors import setting

    try:
        value = setting(key, country, default)
    except Exception:  # noqa: BLE001
        value = default
    return default if value is None else value


def is_staff(person, country=None) -> bool:
    return has_role(person, *STAFF, country=country)


def _require_staff(by, country, roles=STAFF, msg="Only Tenmina staff can do this."):
    if not has_role(by, *roles, country=country):
        raise Forbidden(msg)


def _audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=type(obj).__name__.lower(), entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None))


def _notify(person, template, body, *, subject="", obj=None, link="", needs_action=False, category=None,
            channels=("in_app",)):
    """Never let a notification failure stop the work; log it instead."""
    from notifications.services import notify

    if person is None:
        return
    try:
        with transaction.atomic():
            notify(person, template, body=body, subject=subject, subject_obj=obj, link=link,
                   needs_action=needs_action, category=category, channels=channels)
    except Exception:  # noqa: BLE001
        log.exception("notification %s failed", template)


def staff_in(country, *roles):
    from accounts.models import Person

    return Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                 role_grants__role__in=roles, role_grants__revoked_at__isnull=True,
                                 is_active=True).distinct()


def _alert_staff(country, template, body, *, obj=None, link="", roles=("CM",), needs_action=True, prop=None):
    people = [prop.case_manager] if prop is not None and prop.case_manager_id else list(staff_in(country, *roles))
    for p in people:
        _notify(p, template, body, obj=obj, link=link, needs_action=needs_action, category="task")


def _fmt(amount, currency):
    return f"{currency} {Decimal(amount):,.2f}"


def _money(value, country, field="amount"):
    if isinstance(value, dict):
        amount, currency = value.get("amount"), value.get("currency") or country.currency
    else:
        amount, currency = value, country.currency
    try:
        amount = q(amount)
    except Exception as exc:  # noqa: BLE001
        raise Invalid(f"Enter the {field}.", code="validation-error") from exc
    if amount <= 0:
        raise Invalid(f"The {field} must be more than zero.", code="validation-error")
    return amount, str(currency).upper()


def _evidence(ids, *, required=0, what="evidence"):
    from evidence.models import Evidence

    ids = [i for i in (ids or []) if i]
    out = []
    for i in ids:
        ev = Evidence.objects.filter(pk=i).first() if _is_uuid(i) else None
        if ev is None:
            raise Invalid(f"The {what} {i} was not found.", code="validation-error")
        out.append(ev)
    if len(out) < required:
        raise Invalid(f"Attach at least {required} {what}.", code="validation-error")
    return out


def _is_uuid(v) -> bool:
    import uuid

    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False


def _link(ev, subject_type, subject_id, role, by):
    from evidence.services import link

    return link(ev, subject_type, subject_id, role=role, by=by)


def _add_months(d: date, n: int, day: int | None = None) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(day or d.day, monthrange(year, month)[1]))


def property_link(p):
    return f"/properties/{p.pk}"


# --------------------------------------------------------------------------- visibility

def is_owner(person, prop) -> bool:
    return bool(person and person.is_authenticated and prop.owner_id == person.pk)


def active_tenancy(prop):
    return prop.tenancies.filter(status="active").first()


def is_tenant_of(person, prop) -> bool:
    return bool(person and person.is_authenticated and
                prop.tenancies.filter(tenant=person, status="active").exists())


def can_view_property(person, prop) -> bool:
    return is_owner(person, prop) or is_staff(person, prop.country)


def can_view_tenancy(person, t) -> bool:
    return person.pk in (t.tenant_id, t.property.owner_id) or is_staff(person, t.country)


def can_view_repair(person, r) -> bool:
    if is_owner(person, r.property) or is_staff(person, r.country) or r.reported_by_id == person.pk:
        return True
    if r.approved_quote_id and r.approved_quote.contractor_id == person.pk:
        return True
    return r.inspections.filter(inspector=person).exists()


def can_view_inspection(person, insp) -> bool:
    return insp.inspector_id == person.pk or is_owner(person, insp.property) or is_staff(person, insp.country)


def properties_for(person):
    qs = ManagedProperty.objects.select_related("asset", "country", "owner")
    if is_staff(person):
        from accounts.selectors import scope_to_staff_countries

        return scope_to_staff_countries(qs, person)
    return qs.filter(owner=person)


def repairs_for(person):
    qs = Repair.objects.select_related("property", "property__asset", "approved_quote")
    if is_staff(person):
        from accounts.selectors import scope_to_staff_countries

        return scope_to_staff_countries(qs, person)
    return qs.filter(Q(property__owner=person) | Q(reported_by=person) | Q(approved_quote__contractor=person)
                     | Q(inspections__inspector=person)).distinct()


# --------------------------------------------------------------------------- properties (FR-PMG-001)

@transaction.atomic
def register_property(by, *, country, title, locality, owner=None, address="", region="", district="",
                      ghana_post_gps="", location=None, asset_id=None, ownership_evidence_ids=(),
                      inspection_interval_months=None) -> ManagedProperty:
    """US-PMG-001 AC1: a property with its address and ownership documents is registered; the onboarding
    case opens and a condition inspection is created for a field inspector."""
    from cases.services import open_case
    from geo.models import Asset
    from geo.services import create_asset

    _on(country)
    owner = owner or by
    if by.pk != owner.pk:
        _require_staff(by, country, ("CM",), "A case manager registers a property for an owner.")
    if not owner.has_tenmina_role("CL"):
        raise Invalid("The owner must be a Tenmina client.", code="validation-error")
    docs = _evidence(ownership_evidence_ids, required=1, what="ownership document")
    if asset_id:
        asset = Asset.objects.filter(pk=asset_id, owner=owner).first()
        if asset is None:
            raise NotFound("Property not found.")
        if asset.type not in ("building", "managed_property"):
            raise Invalid("Only a house or building can be managed.", code="validation-error")
        if ManagedProperty.objects.filter(asset=asset).exists():
            raise StateConflict("This property is already registered for management.", code="property-exists")
    else:
        asset = create_asset(actor=by, country=country, type="building", locality=locality, owner=owner,
                             name=title, region=region, district=district, address=address,
                             ghana_post_gps=ghana_post_gps, location=location)
    interval = int(inspection_interval_months or _cfg(country, "inspection_interval_months", 6))
    if not 1 <= interval <= 24:
        raise Invalid("Inspections are every 1 to 24 months.", code="validation-error")
    prop = ManagedProperty.objects.create(country=country, owner=owner, asset=asset, title=title.strip(),
                                          inspection_interval_months=interval, created_by=by,
                                          case_manager=by if is_staff(by, country) else None)
    for ev in docs:
        _link(ev, "managed_property", prop.pk, "ownership_document", by)
    case = open_case("property_onboarding", country, subject_type="managed_property", subject_id=prop.pk,
                     client=owner, asset=asset, actor=by, title=f"Property onboarding: {prop.title}")
    prop.onboarding_case = case
    prop.save(update_fields=["onboarding_case"])
    task = case.tasks.filter(step_key="ownership_check").first()
    if task is not None:
        for ev in docs:
            try:
                _link(ev, "task", task.pk, "title_document", by)
            except DomainError:
                log.info("ownership document %s not linked to the case task", ev.pk)
    Inspection.objects.create(country=country, property=prop, kind="onboarding",
                              scheduled_for=_today() + timedelta(days=int(_cfg(country, "onboarding_visit_days", 5))))
    _draft_fee_order(prop, by)
    _audit(by, "managed_property.registered", prop, {"asset_id": str(asset.pk), "case_id": str(case.pk)})
    publish("managed_property.registered", prop.pk, {"property_id": prop.pk, "owner_id": owner.pk,
                                                     "asset_id": asset.pk, "case_id": case.pk,
                                                     "country": country.code})
    _alert_staff(country, "pmg_property_registered",
                 f"{owner.full_name} registered {prop.title} for management. Assign an inspector for the condition "
                 "inspection and check the ownership documents.", obj=prop, link=f"/back-office{property_link(prop)}")
    _notify(owner, "pmg_property_registered",
            f"We received {prop.title}. An inspector will visit and record its condition with photos before "
            "management starts. Next: add your own verified bank account for the rent.", obj=prop,
            link=property_link(prop))
    return prop


def _draft_fee_order(prop, by):
    """Tenmina's fee for the line (ORD property_onboarding). Best effort: the order is a draft the owner pays."""
    from orders.services import create_line_order

    try:
        with transaction.atomic():
            order = create_line_order(client=prop.owner, kind="property_onboarding", country=prop.country,
                                      subject_type="managed_property", subject_id=prop.pk,
                                      details={"asset_id": str(prop.asset_id), "title": prop.title},
                                      placed_by=by if by.pk != prop.owner_id else None)
        prop.fee_order_id = order.pk
        prop.save(update_fields=["fee_order_id"])
    except DomainError as exc:
        log.info("fee order for property %s not drafted: %s", prop.pk, exc.detail)


def onboarding_inspection(prop):
    return prop.inspections.filter(kind="onboarding").exclude(status="cancelled").order_by("-created_at").first()


def activation_blockers(prop) -> list[dict]:
    out = []
    insp = onboarding_inspection(prop)
    if insp is None or insp.status != "submitted":
        out.append({"rule": "FR-PMG-001", "code": "inspection-required",
                    "message": "The condition inspection with photos is not recorded yet."})
    if prop.ownership_outcome != "verified":
        out.append({"rule": "FR-PMG-001", "code": "ownership-not-checked",
                    "message": "The ownership documents are not checked yet."})
    if prop.rent_account_id is None:
        out.append({"rule": "RUL-24", "code": "rent-account-missing",
                    "message": "Add your own verified bank account for the rent."})
    return out


@transaction.atomic
def try_activate(prop) -> ManagedProperty:
    prop = ManagedProperty.objects.select_for_update().get(pk=prop.pk)
    if prop.status != "onboarding" or activation_blockers(prop):
        return prop
    prop.managed_at = _now()
    prop.next_inspection_due_on = _add_months(_today(), prop.inspection_interval_months)
    state.transition(prop, "managed_property", "managed", event="property.onboarded",
                     extra_fields=["managed_at", "next_inspection_due_on"],
                     payload={"property_id": prop.pk, "owner_id": prop.owner_id, "asset_id": prop.asset_id,
                              "country": prop.country.code})
    _notify(prop.owner, "pmg_property_managed",
            f"{prop.title} is now under management. Its condition report with photos is on your timeline.",
            obj=prop, link=f"{property_link(prop)}/timeline")
    return prop


@transaction.atomic
def on_onboarding_case(case_id, outcome, note=""):
    """case.status_changed for a property_onboarding case: the ownership check is done."""
    prop = ManagedProperty.objects.filter(onboarding_case_id=case_id).first()
    if prop is None or prop.ownership_outcome:
        return prop
    prop.ownership_outcome = outcome or "not_verified"
    prop.ownership_verified_at = _now() if outcome == "verified" else None
    prop.save(update_fields=["ownership_outcome", "ownership_verified_at"])
    _audit(None, "managed_property.ownership_checked", prop, {"outcome": prop.ownership_outcome})
    if outcome == "verified":
        return try_activate(prop)
    prop.end_reason = f"The ownership could not be verified. {note}".strip()
    prop.ended_at = _now()
    if prop.status == "onboarding":
        state.transition(prop, "managed_property", "ended", extra_fields=["end_reason", "ended_at"],
                         payload={"property_id": prop.pk})
    _notify(prop.owner, "pmg_ownership_not_verified",
            f"We could not verify the ownership of {prop.title}. Your case manager will explain what is needed.",
            obj=prop, link=property_link(prop), needs_action=True)
    return prop


@transaction.atomic
def pause_property(prop, by, reason) -> ManagedProperty:
    _require_staff(by, prop.country, ("CM", "RV"))
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    state.transition(prop, "managed_property", "paused", actor=by, reason=reason)
    return prop


@transaction.atomic
def resume_property(prop, by) -> ManagedProperty:
    _require_staff(by, prop.country, ("CM", "RV"))
    state.transition(prop, "managed_property", "managed", actor=by)
    return prop


@transaction.atomic
def end_management(prop, by, reason) -> ManagedProperty:
    _on(prop.country)
    if not (is_owner(by, prop) or is_staff(by, prop.country)):
        raise NotFound()
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if active_tenancy(prop) is not None:
        raise StateConflict("End the tenancy first.", code="tenancy-active")
    if prop.repairs.filter(status__in=["approved", "funded", "in_progress", "inspected", "instructed"]).exists():
        raise StateConflict("A repair with money held at the bank is still open.", code="repair-open")
    prop.end_reason, prop.ended_at = reason.strip(), _now()
    state.transition(prop, "managed_property", "ended", actor=by, reason=reason,
                     extra_fields=["end_reason", "ended_at"], payload={"property_id": prop.pk})
    return prop


# --------------------------------------------------------------------------- rent destination (RUL-24)

def _tenmina_account(number: str) -> bool:
    """TC-RUL-24-02: a Tenmina fee or operating account, the bank's escrow programme account, or a payee's
    account is never a rent destination."""
    from administration.models import Partner
    from administration.services import account_bidx
    from escrow.models import Payee, ProgrammeAccount

    norm = adapters.normalise_account(number)
    if not norm:
        return False
    if Partner.objects.filter(account_number_bidx=account_bidx(norm)).exists():
        return True
    for model in (ProgrammeAccount, Payee):
        for n in model.objects.values_list("account_number", flat=True):
            if adapters.normalise_account(n) == norm:
                return True
    return False


def _refuse_rent_destination(prop, by, message, reason):
    from audit.services import security_event

    security_event("rent_destination.refused", actor=by, entity="managed_property", entity_id=prop.pk,
                   country=prop.country, data={"reason": reason},
                   summary=f"A rent destination was refused on {prop.title}: {reason}", defer=True)
    raise DomainError(message, code="rent-destination-invalid", status=422,
                      blocking_reasons=[{"rule": "RUL-24", "message": message}])


def check_rent_account(prop, bank_account_id, by=None):
    """The owner's own verified account, never Tenmina's or anyone else's (RUL-24)."""
    from accounts.models import BankAccount

    acct = BankAccount.objects.filter(pk=bank_account_id).first() if _is_uuid(bank_account_id) else None
    if acct is None:
        _refuse_rent_destination(prop, by, "Choose your own bank account.", "unknown account")
    if acct.holder_id != prop.owner_id:
        _refuse_rent_destination(prop, by, "Rent is paid only into the owner's own account.",
                                 "account not held by the owner")
    if acct.verification_status != "verified" or acct.name_match != "matched":
        _refuse_rent_destination(prop, by, "The account must be verified in the owner's own name first.",
                                 f"account {acct.verification_status}")
    if _tenmina_account(acct.account_number):
        _refuse_rent_destination(prop, by, "A Tenmina, escrow or payee account can never receive rent.",
                                 "deny-listed account")
    return acct


@transaction.atomic
def set_rent_account(prop, by, bank_account_id) -> ManagedProperty:
    """FR-PMG-002, RUL-24: PUT /v1/managed-properties/{id}/rent-account."""
    _on(prop.country)
    if not (is_owner(by, prop) or has_role(by, "CM", "RV", country=prop.country)):
        raise NotFound()
    if prop.status == "ended":
        raise StateConflict("Management of this property has ended.")
    acct = check_rent_account(prop, bank_account_id, by)
    old = prop.rent_account_id
    prop.rent_account = acct
    prop.save(update_fields=["rent_account"])
    if old and old != acct.pk and prop.statement_mandate_id:
        m = prop.statement_mandate
        if m.status in ("signed", "active") and m.bank_account_id != acct.pk:
            revoke_mandate(m, by, "The rent account changed.", _system=True)
    _audit(by, "managed_property.rent_account_set", prop, {"last4": acct.last4})
    for t in prop.tenancies.filter(status="active"):
        _notify(t.tenant, "pmg_rent_account_changed",
                f"Rent for {prop.title} is now paid to {prop.owner.full_name}'s account ending {acct.last4} at "
                f"{acct.bank_name}. Never pay rent to Tenmina or to anyone else.", obj=t,
                link=f"/tenancies/{t.pk}")
    try_activate(prop)
    prop.refresh_from_db()
    return prop


# --------------------------------------------------------------------------- statement mandate (FR-PMG-003, 9.3)

def _statement_ref(country):
    return f"RENT-{country.code}-{secrets.token_hex(4).upper()}"


@transaction.atomic
def record_mandate(prop, by, *, mandate_evidence_id, valid_from=None, valid_to=None,
                   bank_acknowledgement_evidence_id=None, statement_ref="") -> StatementMandate:
    """The owner's written mandate letting the bank share the rent account's statement lines."""
    _on(prop.country)
    if not (is_owner(by, prop) or has_role(by, "CM", "RV", country=prop.country)):
        raise NotFound()
    if prop.rent_account_id is None:
        raise StateConflict("Set the rent account first. The mandate covers that account only.",
                            code="rent-account-missing")
    check_rent_account(prop, prop.rent_account_id, by)
    if prop.mandates.filter(status__in=["signed", "active"]).exists():
        raise StateConflict("A mandate for this property is already on file. Revoke it first.",
                            code="mandate-exists")
    (ev,) = _evidence([mandate_evidence_id], required=1, what="signed mandate")
    valid_from = valid_from or _today()
    if valid_to and valid_to <= valid_from:
        raise Invalid("The mandate must end after it starts.", code="validation-error")
    m = StatementMandate.objects.create(country=prop.country, property=prop, owner=prop.owner,
                                        bank_account=prop.rent_account, mandate_evidence=ev,
                                        statement_ref=(statement_ref or "").strip() or _statement_ref(prop.country),
                                        valid_from=valid_from, valid_to=valid_to, recorded_by=by)
    _link(ev, "managed_property", prop.pk, "statement_mandate", by)
    prop.statement_mandate = m
    prop.save(update_fields=["statement_mandate"])
    _audit(by, "statement_mandate.recorded", m, {"property_id": str(prop.pk)})
    if bank_acknowledgement_evidence_id and has_role(by, "CM", "RV", country=prop.country):
        acknowledge_mandate(m, by, evidence_id=bank_acknowledgement_evidence_id)
    else:
        _alert_staff(prop.country, "pmg_mandate_signed",
                     f"{prop.owner.full_name} signed the statement mandate for {prop.title}. Send it to the bank and "
                     "record the bank's acknowledgement.", obj=m, prop=prop)
    m.refresh_from_db()
    return m


@transaction.atomic
def acknowledge_mandate(m: StatementMandate, by, *, evidence_id, statement_ref="") -> StatementMandate:
    _on(m.country)
    _require_staff(by, m.country, ("CM", "RV"), "A case manager records the bank's acknowledgement.")
    (ev,) = _evidence([evidence_id], required=1, what="bank acknowledgement")
    if m.status != "signed":
        raise StateConflict(f"This mandate is {m.status}.")
    m.bank_acknowledgement_evidence, m.acknowledged_by, m.acknowledged_at = ev, by, _now()
    if statement_ref:
        m.statement_ref = statement_ref.strip()
    state.transition(m, "statement_mandate", "active", actor=by, event="statement_mandate.activated",
                     extra_fields=["bank_acknowledgement_evidence", "acknowledged_by", "acknowledged_at",
                                   "statement_ref"],
                     payload={"mandate_id": m.pk, "property_id": m.property_id})
    _link(ev, "managed_property", m.property_id, "bank_acknowledgement", by)
    _notify(m.owner, "pmg_mandate_active",
            f"Your bank confirmed it will share the statement lines of your account ending "
            f"{m.bank_account.last4} with Tenmina. We will show you when rent arrives.", obj=m,
            link=property_link(m.property))
    return m


@transaction.atomic
def revoke_mandate(m: StatementMandate, by, reason, _system=False) -> StatementMandate:
    if not _system and not (by and (by.pk == m.owner_id or has_role(by, "CM", "RV", country=m.country))):
        raise NotFound()
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if m.status not in ("signed", "active"):
        raise StateConflict(f"This mandate is {m.status}.")
    m.revoked_at, m.revoke_reason = _now(), reason.strip()
    state.transition(m, "statement_mandate", "revoked", actor=by, reason=reason,
                     extra_fields=["revoked_at", "revoke_reason"], payload={"mandate_id": m.pk})
    return m


def live_mandate(prop, on=None):
    """The active mandate covering the rent account on a day, or None (FR-PMG-003)."""
    on = on or _today()
    m = prop.mandates.filter(status="active", bank_account_id=prop.rent_account_id).order_by("-valid_from").first()
    if m is None or m.valid_from > on or (m.valid_to and m.valid_to < on):
        return None
    return m


# --------------------------------------------------------------------------- tenancies (FR-PMG-002)

def _tenant_person(*, email, full_name, phone, country, by, owner):
    from accounts.models import Person
    from accounts.services import grant_role

    email = (email or "").strip().lower()
    if not email or not (full_name or "").strip():
        raise Invalid("Enter the tenant's name and email.", code="validation-error")
    p = Person.objects.filter(email=email).first()
    created = False
    if p is None:
        p = Person.objects.create_user(email=email, password=None, full_name=full_name.strip(),
                                       phone=(phone or "").strip(), home_country=country)
        created = True
    if p.pk == owner.pk:
        raise Invalid("The owner cannot be the tenant of their own managed property.", code="validation-error")
    if p.has_tenmina_role(*STAFF, "RN"):
        raise Invalid("Tenmina staff cannot be recorded as a tenant here.", code="validation-error")
    if not p.has_tenmina_role("TN"):
        grant_role(p, "TN", country=country, granted_by=by)
    return p, created


@transaction.atomic
def record_tenancy(prop, by, *, tenant_email, tenant_name, agreement_evidence_id, rent, period, due_day, starts_on,
                   tenant_phone="", tenant_id_number="", ends_on=None, tenant_reference="") -> Tenancy:
    """US-PMG-002: tenant with an identity check, agreement stored as evidence, rent and due day; the
    tenant gets a tenant account. Rent goes to the owner's own account only."""
    from accounts.services import request_national_id_check

    _on(prop.country)
    _require_staff(by, prop.country, ("CM", "RV"), "A case manager records the tenancy.")
    if prop.status not in ("onboarding", "managed"):
        raise StateConflict(f"This property is {prop.status}.")
    insp = onboarding_inspection(prop)
    if insp is None or insp.status != "submitted":
        raise RuleBlocked("Management cannot start before the condition inspection is recorded.",
                          code="inspection-required",
                          blocking_reasons=[{"rule": "FR-PMG-001",
                                             "message": "No condition inspection with photos yet."}])
    if prop.rent_account_id is None:
        raise DomainError("Set the owner's own verified account as the rent destination first.",
                          code="rent-destination-invalid", status=422,
                          blocking_reasons=[{"rule": "RUL-24", "message": "No rent account"}])
    acct = check_rent_account(prop, prop.rent_account_id, by)
    if not agreement_evidence_id:
        raise Invalid("Attach the signed tenancy agreement.", code="validation-error",
                      extra={"errors": [{"pointer": "/agreement_evidence_id", "message": "Required."}]})
    (agreement,) = _evidence([agreement_evidence_id], required=1, what="tenancy agreement")
    if active_tenancy(prop) is not None:
        raise StateConflict("This property already has an active tenancy. End it first.", code="tenancy-active")
    if period not in RENT_PERIODS:
        raise Invalid(f"Period must be one of {', '.join(RENT_PERIODS)}.", code="validation-error")
    try:
        due_day = int(due_day)
    except (TypeError, ValueError):
        due_day = 0
    if not 1 <= due_day <= 28:
        raise Invalid("The due day is between 1 and 28.", code="validation-error")
    amount, currency = _money(rent, prop.country, "rent")
    if ends_on and ends_on <= starts_on:
        raise Invalid("The tenancy must end after it starts.", code="validation-error")
    tenant, created = _tenant_person(email=tenant_email, full_name=tenant_name, phone=tenant_phone,
                                     country=prop.country, by=by, owner=prop.owner)
    chk = None
    if tenant_id_number:
        chk = request_national_id_check(by=by, country=prop.country, subject_role="signatory",
                                        subject_name=tenant.full_name, id_number=tenant_id_number, person=tenant,
                                        context_type="tenancy", context_id=prop.pk)
        if chk.result in ("no_match", "not_found"):
            raise RuleBlocked("The tenant's identity did not match the national identity system.",
                              code="national-id-check-required",
                              blocking_reasons=[{"rule": "RUL-31", "message": f"Result: {chk.result}"}])
    ref = (tenant_reference or "").strip().upper() or f"RENT-{prop.asset.reference.split('-')[-1]}-" \
                                                      f"{secrets.token_hex(2).upper()}"
    t = Tenancy.objects.create(country=prop.country, property=prop, tenant=tenant, tenant_id_check=chk,
                               agreement_evidence=agreement, rent_amount=amount, rent_currency=currency,
                               period=period, due_day=due_day, starts_on=starts_on, ends_on=ends_on,
                               tenant_reference=ref, recorded_by=by)
    _link(agreement, "tenancy", t.pk, "agreement", by)
    ensure_periods(t)
    _audit(by, "tenancy.recorded", t, {"property_id": str(prop.pk), "rent": f"{amount:.2f}", "currency": currency})
    publish("tenancy.recorded", t.pk, {"tenancy_id": t.pk, "property_id": prop.pk, "owner_id": prop.owner_id,
                                       "tenant_id": tenant.pk, "country": prop.country.code})
    _notify(tenant, "pmg_tenant_welcome",
            (f"Welcome to Tenmina. " if created else "") +
            f"Your tenancy of {prop.title} is recorded. Pay {_fmt(amount, currency)} each {period.replace('_', ' ')} "
            f"period by day {due_day} to {prop.owner.full_name}'s own account ending {acct.last4} at "
            f"{acct.bank_name}, with the reference {ref}. Never pay rent to Tenmina. "
            + ("Sign in with this email and choose 'Forgot password' to set your password." if created else ""),
            obj=t, link=f"/tenancies/{t.pk}", channels=("in_app", "email"))
    _notify(prop.owner, "pmg_tenancy_recorded",
            f"{tenant.full_name} is recorded as the tenant of {prop.title}, paying {_fmt(amount, currency)} into "
            f"your account ending {acct.last4}.", obj=t, link=f"{property_link(prop)}/timeline")
    return t


@transaction.atomic
def end_tenancy(t: Tenancy, by, *, reason, terminated=False) -> Tenancy:
    _require_staff(by, t.country, ("CM", "RV"))
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    t.ended_at, t.end_reason = _now(), reason.strip()
    state.transition(t, "tenancy", "terminated" if terminated else "ended", actor=by, reason=reason,
                     extra_fields=["ended_at", "end_reason"], payload={"tenancy_id": t.pk})
    return t


def payment_details(t: Tenancy) -> dict:
    """TC-RUL-24-04: what the tenant sees: the owner's account at the partner bank and the reference.
    Never Tenmina's details."""
    acct = t.property.rent_account
    return {"pay_to": "owner", "account_holder": t.property.owner.full_name,
            "bank_name": acct.bank_name if acct else "", "account_name": acct.account_name if acct else "",
            "account_number": acct.account_number if acct else "", "reference": t.tenant_reference,
            "amount": {"amount": f"{t.rent_amount:.2f}", "currency": t.rent_currency},
            "note": "Pay the owner's own account only. Tenmina never receives rent."}


# --------------------------------------------------------------------------- rent periods (FR-PMG-003)

def _due_on(period_start: date, due_day: int) -> date:
    d = date(period_start.year, period_start.month, min(due_day, monthrange(period_start.year,
                                                                            period_start.month)[1]))
    return d if d >= period_start else _add_months(d, 1, due_day)


def ensure_periods(t: Tenancy, upto: date | None = None) -> int:
    """Create rent periods from the start of the tenancy to the next one due."""
    upto = upto or (_today() + timedelta(days=31))
    step = RENT_PERIODS[t.period]
    n = 0
    for k in range(0, 600):
        ps = _add_months(t.starts_on, k * step)
        if ps > upto or (t.ends_on and ps >= t.ends_on):
            break
        _, made = RentPeriod.objects.get_or_create(
            tenancy=t, period_start=ps,
            defaults={"due_on": _due_on(ps, t.due_day), "expected_amount": t.rent_amount,
                      "expected_currency": t.rent_currency})
        n += int(made)
    return n


def rent_status_text(p: RentPeriod, mandate_on_file: bool) -> str:
    if p.status == "received":
        return f"Received on {p.received_on:%d %B %Y}, from your bank's statement."
    if p.status == "partial":
        return f"{_fmt(p.received_amount, p.expected_currency)} of {_fmt(p.expected_amount, p.expected_currency)} " \
               f"received, from your bank's statement."
    if p.status == "written_off":
        return "Written off."
    if not mandate_on_file:
        return "Not yet confirmed by the bank. Sign the statement mandate so we can read your account."
    if p.status == "late":
        return f"Late. Due on {p.due_on:%d %B %Y} and not in your bank's statement."
    return f"Due on {p.due_on:%d %B %Y}."


def _norm(text):
    return "".join(ch for ch in (text or "").upper() if ch.isalnum())


def _apply_line(period: RentPeriod, line, method, by=None):
    period.line_ids = [*period.line_ids, line.pk]
    period.received_amount = q((period.received_amount or 0) + line.amount)
    period.received_on = line.booked_on
    period.statement_line = line
    period.match_method = method
    target = "received" if period.received_amount >= period.expected_amount else "partial"
    fields = ["line_ids", "received_amount", "received_on", "statement_line", "match_method", "pending_line",
              "pending_by", "checked_by"]
    t = period.tenancy
    prop = t.property
    payload = {"period_id": period.pk, "tenancy_id": t.pk, "property_id": prop.pk, "owner_id": prop.owner_id,
               "amount": period.received_amount, "currency": period.expected_currency,
               "received_on": period.received_on, "statement_line_id": line.pk, "method": method}
    if period.status == target:
        period.save(update_fields=fields)
    else:
        state.transition(period, "rent_period", target, actor=by,
                         event="rent.received" if target == "received" else "rent.partly_received",
                         extra_fields=fields, payload=payload)
    acct = prop.rent_account
    _notify(prop.owner, "pmg_rent_received",
            f"Rent of {_fmt(line.amount, line.currency)} for {prop.title} reached your account ending "
            f"{acct.last4 if acct else ''} on {line.booked_on:%d %B %Y}, according to your bank's statement.",
            obj=period, link=f"{property_link(prop)}/rent-periods", category="money")
    return period


def _line_taken(line, tenancy) -> bool:
    if RentPeriod.objects.filter(line_ids__contains=[line.pk]).exists():
        return True
    if line.bank_reference:
        from escrow.models import StatementLine

        ids = [i for p in tenancy.periods.exclude(line_ids=[]) for i in p.line_ids]
        if StatementLine.objects.filter(pk__in=ids, bank_reference=line.bank_reference).exists():
            return True
    return False


def tenancy_on(prop, day):
    return prop.tenancies.filter(starts_on__lte=day + timedelta(days=31)).filter(
        Q(status="active") | Q(ends_on__gte=day - timedelta(days=31))).order_by("-starts_on").first()


@transaction.atomic
def match_line(line, mandate: StatementMandate) -> RentPeriod | None:
    """pmg.match_rent: a credit on the owner's account matched to a rent period by the tenant's reference,
    then by amount and date within rent_grace_days. Unmatched lines go to the owner and a case manager."""
    prop = mandate.property
    if line.kind != "credit":
        return None
    t = tenancy_on(prop, line.booked_on)
    if t is None:
        _unmatched(prop, line, "No tenancy covers this date.")
        return None
    ensure_periods(t, max(line.booked_on, _today()) + timedelta(days=31))
    if _line_taken(line, t):
        return None
    grace = int(_setting("rent_grace_days", prop.country, 5))
    open_periods = list(t.periods.select_for_update().filter(status__in=OPEN_RENT).order_by("period_start"))
    text = _norm(f"{line.narrative} {line.bank_reference}")
    if line.currency == t.rent_currency and _norm(t.tenant_reference) and _norm(t.tenant_reference) in text:
        for p in open_periods:
            if (p.due_on - line.booked_on).days <= 31:
                return _apply_line(p, line, "reference")
    for p in open_periods:
        if line.currency == p.expected_currency and line.amount == p.expected_amount \
                and abs((line.booked_on - p.due_on).days) <= grace:
            return _apply_line(p, line, "amount_date")
    _unmatched(prop, line, "No rent period matches the reference, amount or date.")
    return None


def _unmatched(prop, line, why):
    publish("rent.unmatched_line", line.pk, {"property_id": prop.pk, "statement_line_id": line.pk,
                                            "amount": line.amount, "currency": line.currency,
                                            "booked_on": line.booked_on})
    text = (f"A credit of {_fmt(line.amount, line.currency)} on {line.booked_on:%d %B %Y} in the rent account for "
            f"{prop.title} did not match a rent period. {why}")
    _notify(prop.owner, "pmg_rent_unmatched", text + " Your case manager will check it with you.", obj=prop,
            link=f"{property_link(prop)}/rent-periods")
    _alert_staff(prop.country, "pmg_rent_unmatched", text + " Match it by hand; a second staff member checks it.",
                 obj=prop, prop=prop)


@transaction.atomic
def import_rent_statement(prop, by, *, data: bytes, original_name="statement.csv", source="manual",
                          owner_confirmed=False) -> StatementImport:
    """9.3: read the bank's statement lines for the rent account only, under an active mandate. Lines for
    any other account are refused at import and only counted (TC-PMG-003-03). The `manual` route is the
    owner's upload; the `file` route is the bank's file, imported by staff."""
    from escrow.services import import_statement

    _on(prop.country)
    if source not in StatementImport.SOURCES:
        raise Invalid("Source must be file, api or manual.", code="validation-error")
    staff = has_role(by, "CM", "RV", country=prop.country)
    if not (staff or is_owner(by, prop)):
        raise NotFound()
    if not staff and source != "manual":
        raise Forbidden("Owners upload their bank's statement by hand (manual).")
    m = live_mandate(prop)
    if m is None:
        _notify(prop.owner, "pmg_mandate_needed",
                f"We cannot read rent for {prop.title} until you sign the mandate that lets your bank share the "
                "statement lines of your rent account.", obj=prop, link=property_link(prop), needs_action=True)
        raise RuleBlocked("Nothing is read or matched without the owner's written mandate on file.",
                          code="mandate-missing",
                          blocking_reasons=[{"rule": "FR-PMG-003", "message": "No active statement mandate."}])
    try:
        rows = adapters.rent_statement().parse(data)
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        raise Invalid(f"The statement file could not be read: {exc}", code="validation-error") from exc
    account = adapters.normalise_account(prop.rent_account.account_number)
    accepted = [r for r in rows if r["account_number"] == account]
    refused = len(rows) - len(accepted)
    imp = StatementImport(country=prop.country, property=prop, mandate=m, source=source,
                          original_name=original_name or "", accepted_count=len(accepted), refused_count=refused,
                          uploaded_by=by)
    if accepted:
        sf = import_statement(by if staff else None, country=prop.country, data=adapters.to_escrow_csv(
            accepted, m.statement_ref), original_name=f"rent-{m.statement_ref}-{original_name}",
            account_kind="owner_rent")
        imp.statement_file = sf
        imp.matched_count = RentPeriod.objects.filter(tenancy__property=prop,
                                                      statement_line__file=sf).count()
    imp.save()
    _audit(by, "rent_statement.imported", imp, {"accepted": len(accepted), "refused": refused, "source": source,
                                                "owner_confirmed": bool(owner_confirmed)})
    if refused:
        from audit.services import security_event

        security_event("rent_statement.foreign_lines_refused", actor=by, entity="managed_property",
                       entity_id=prop.pk, country=prop.country, data={"refused": refused},
                       summary=f"{refused} statement line(s) for another account were refused at import")
    return imp


def unmatched_lines(prop):
    from escrow.models import StatementLine

    files = prop.statement_imports.exclude(statement_file__isnull=True).values_list("statement_file_id", flat=True)
    taken = {i for p in RentPeriod.objects.filter(tenancy__property=prop) for i in p.line_ids}
    pending = set(RentPeriod.objects.filter(tenancy__property=prop, pending_line__isnull=False)
                  .values_list("pending_line_id", flat=True))
    return [ln for ln in StatementLine.objects.filter(file_id__in=list(files), kind="credit").order_by("booked_on")
            if ln.pk not in taken and ln.pk not in pending]


@transaction.atomic
def propose_manual_match(period: RentPeriod, by, *, line_id) -> RentPeriod:
    """US-PMG-003 AC3: a manual match is checked by a second staff member before it counts."""
    from escrow.models import StatementLine

    prop = period.tenancy.property
    _on(prop.country)
    _require_staff(by, prop.country, ("CM", "RV"), "A case manager matches a line by hand.")
    if period.status not in OPEN_RENT:
        raise StateConflict(f"This rent period is {period.status}.")
    line = StatementLine.objects.filter(pk=line_id).first() if _is_uuid(line_id) else None
    if line is None or line.pk not in {ln.pk for ln in unmatched_lines(prop)}:
        raise Invalid("Choose an unmatched credit from this property's rent account statement.",
                      code="validation-error")
    period.pending_line, period.pending_by, period.checked_by = line, by, None
    period.save(update_fields=["pending_line", "pending_by", "checked_by"])
    _audit(by, "rent_period.manual_match_proposed", period, {"line_id": str(line.pk)})
    for p in staff_in(prop.country, "CM", "RV"):
        if p.pk != by.pk:
            _notify(p, "pmg_rent_match_check", f"A manual rent match on {prop.title} waits for your check.",
                    obj=period, needs_action=True, category="task")
    return period


@transaction.atomic
def check_manual_match(period: RentPeriod, by, *, agree=True, note="") -> RentPeriod:
    prop = period.tenancy.property
    _on(prop.country)
    _require_staff(by, prop.country, ("CM", "RV"))
    if period.pending_line_id is None:
        raise StateConflict("No manual match is waiting for a check.")
    if period.pending_by_id == by.pk:
        from core.errors import SameApprover

        raise SameApprover("A different staff member must check a manual match.")
    line = period.pending_line
    if not agree:
        period.pending_line, period.pending_by = None, None
        period.save(update_fields=["pending_line", "pending_by"])
        _audit(by, "rent_period.manual_match_refused", period, {"note": note})
        return period
    period.checked_by = by
    _apply_line(period, line, "manual", by=by)
    period.pending_line = None
    period.save(update_fields=["pending_line"])
    return period


@transaction.atomic
def write_off(period: RentPeriod, by, reason) -> RentPeriod:
    _require_staff(by, period.tenancy.country, ("RV",), "A reviewer writes off rent.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    period.written_off_reason = reason.strip()
    state.transition(period, "rent_period", "written_off", actor=by, reason=reason,
                     extra_fields=["written_off_reason"])
    return period


def rent_watch(today: date | None = None) -> dict:
    """Job propertymgmt.match_rent (daily 07:00 GMT): create the next periods and alert late rent after
    rent_grace_days, to the owner, the tenant and the case manager (US-PMG-003 AC2). Without a mandate,
    nothing is marked late: the owner is asked to sign it (TC-PMG-003-04)."""
    today = today or _today()
    out = {"late": 0, "mandate_reminders": 0, "periods": 0}
    for t in Tenancy.objects.filter(status="active").select_related("property", "property__owner", "tenant"):
        prop = t.property
        if not flags.enabled("lines.pmg", prop.country):
            continue
        out["periods"] += ensure_periods(t, today + timedelta(days=31))
        grace = int(_setting("rent_grace_days", prop.country, 5))
        mandate = live_mandate(prop, today)
        for p in t.periods.filter(status__in=["due", "partial"], due_on__lt=today - timedelta(days=grace)):
            if mandate is None:
                if p.late_alert_sent_at is None:
                    p.late_alert_sent_at = _now()
                    p.save(update_fields=["late_alert_sent_at"])
                    _notify(prop.owner, "pmg_mandate_needed",
                            f"Rent for {prop.title} due on {p.due_on:%d %B %Y} is not yet confirmed by the bank. "
                            "Sign the statement mandate so we can read your rent account.", obj=prop,
                            link=property_link(prop), needs_action=True)
                    out["mandate_reminders"] += 1
                continue
            with transaction.atomic():
                p.late_alert_sent_at = _now()
                state.transition(p, "rent_period", "late", event="rent.late", extra_fields=["late_alert_sent_at"],
                                 payload={"period_id": p.pk, "tenancy_id": t.pk, "property_id": prop.pk,
                                          "owner_id": prop.owner_id, "tenant_id": t.tenant_id, "due_on": p.due_on,
                                          "amount": p.expected_amount, "currency": p.expected_currency})
            text = f"Rent of {_fmt(p.expected_amount, p.expected_currency)} for {prop.title}, due on " \
                   f"{p.due_on:%d %B %Y}, is not in the bank's statement for the owner's account."
            _notify(prop.owner, "pmg_rent_late", text, obj=p, link=f"{property_link(prop)}/rent-periods",
                    category="money")
            _notify(t.tenant, "pmg_rent_late_tenant",
                    f"Your rent for {prop.title}, due on {p.due_on:%d %B %Y}, has not reached the owner's account. "
                    f"Pay the owner's own account with the reference {t.tenant_reference}.", obj=t,
                    link=f"/tenancies/{t.pk}")
            _alert_staff(prop.country, "pmg_rent_late", text, obj=p, prop=prop)
            out["late"] += 1
    return out


# --------------------------------------------------------------------------- inspections (FR-PMG-001, 005, 006)

def _check_inspector(person, prop, repair=None):
    from accounts.services import require_valid_licence

    if not person.has_tenmina_role("IN", country=prop.country):
        raise Invalid("Choose an inspector.", code="validation-error")
    require_valid_licence(person, "IN")
    conflicts = {prop.owner_id} | set(prop.tenancies.filter(status="active").values_list("tenant_id", flat=True))
    if repair is not None:
        conflicts |= set(repair.quotes.values_list("contractor_id", flat=True))
    if person.pk in conflicts:
        raise DomainError("The inspector has a conflict with this property.", code="inspector-conflict",
                          status=409, blocking_reasons=[{"rule": "FR-BLD-005",
                                                         "message": "Owner, tenant or quoting contractor"}])


@transaction.atomic
def schedule_inspection(prop, by, *, kind, scheduled_for=None, inspector=None, repair=None) -> Inspection:
    _on(prop.country)
    _require_staff(by, prop.country, ("CM", "RV"), "A case manager schedules inspections.")
    if kind not in ("periodic", "repair", "onboarding"):
        raise Invalid("Kind must be onboarding, periodic or repair.", code="validation-error")
    if (kind == "repair") != (repair is not None):
        raise Invalid("A repair inspection names its repair.", code="validation-error")
    if prop.status == "ended":
        raise StateConflict("Management of this property has ended.")
    open_q = prop.inspections.filter(kind=kind, status__in=["scheduled", "assigned"])
    if repair is not None:
        open_q = open_q.filter(repair=repair)
    insp = open_q.first()
    if insp is None:
        insp = Inspection.objects.create(country=prop.country, property=prop, kind=kind, repair=repair,
                                         scheduled_for=scheduled_for or _today() + timedelta(days=3))
    elif scheduled_for:
        insp.scheduled_for = scheduled_for
        insp.save(update_fields=["scheduled_for"])
    if inspector is not None:
        assign_inspector(insp, by, inspector)
    return insp


@transaction.atomic
def assign_inspector(insp: Inspection, by, inspector) -> Inspection:
    """RUL-20: only a licensed inspector with no conflict."""
    _on(insp.country)
    _require_staff(by, insp.country, ("CM", "RV"), "A case manager assigns inspectors.")
    if insp.status not in ("scheduled", "assigned"):
        raise StateConflict(f"This inspection is {insp.status}.")
    _check_inspector(inspector, insp.property, insp.repair)
    insp.inspector, insp.assigned_by, insp.assigned_at = inspector, by, _now()
    if insp.status == "scheduled":
        state.transition(insp, "pmg_inspection", "assigned", actor=by,
                         extra_fields=["inspector", "assigned_by", "assigned_at"],
                         payload={"inspection_id": insp.pk, "inspector_id": inspector.pk})
    else:
        insp.save(update_fields=["inspector", "assigned_by", "assigned_at"])
    _notify(inspector, "pmg_inspection_assigned",
            f"New inspection at {insp.property.title} ({insp.kind}) on or before {insp.scheduled_for:%d %B %Y}. "
            "It is in My jobs in Tenmina Field.", obj=insp, link=f"/field/jobs/property_inspection/{insp.pk}",
            channels=("in_app", "push"))
    return insp


@transaction.atomic
def cancel_inspection(insp: Inspection, by, reason) -> Inspection:
    _require_staff(by, insp.country, ("CM", "RV"))
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    insp.cancel_reason = reason.strip()
    state.transition(insp, "pmg_inspection", "cancelled", actor=by, reason=reason, extra_fields=["cancel_reason"])
    return insp


def _photos_for(insp, ids, by):
    """Each photo is evidence linked to this inspection; RUL-08 (app capture only) runs on link."""
    from evidence.models import EvidenceLink

    out = []
    for ev in _evidence(ids, what="photo"):
        if not ev.content_type.startswith("image/"):
            raise Invalid("Inspection photos must be photos.", code="validation-error")
        if not EvidenceLink.objects.filter(evidence=ev, subject_type="property_inspection",
                                           subject_id=insp.pk).exists():
            _link(ev, "property_inspection", insp.pk, "inspection_photo", by)
        out.append(ev)
    return out


@transaction.atomic
def record_inspection(insp: Inspection, by, *, outcome, condition_rating="", rooms=(), photo_ids=(), checklist=(),
                      defects=(), notes="", submission_id=None) -> Inspection:
    """The inspector records the visit with app photos: a condition rating and photos per room for an
    onboarding inspection (US-PMG-001 AC2), a pass or fail with photos for a repair (FR-PMG-005)."""
    from mobile.services import evidence_blockers

    insp = Inspection.objects.select_for_update().get(pk=insp.pk)
    _on(insp.country)
    if not (by.pk == insp.inspector_id or has_role(by, "CM", "RV", country=insp.country)):
        raise NotFound("This inspection is not assigned to you.")
    if insp.status != "assigned":
        raise StateConflict(f"This inspection is {insp.status}." if insp.status != "scheduled"
                            else "Assign an inspector first.")
    if outcome not in OUTCOMES:
        raise Invalid("Outcome must be pass, pass_with_defects or fail.", code="validation-error")
    if outcome == "fail" and not (notes or "").strip():
        raise Invalid("Say why it failed.", code="validation-error")
    rooms = list(rooms or [])
    all_ids = list(photo_ids or [])
    clean_rooms = []
    for i, r in enumerate(rooms, 1):
        name = (r.get("room") or "").strip()
        ids = [str(x) for x in (r.get("evidence_ids") or [])]
        if not name or not ids:
            raise Invalid(f"Room {i} needs a name and at least one photo.", code="validation-error")
        if r.get("condition") and r["condition"] not in ("good", "fair", "poor"):
            raise Invalid(f"Room {i}: condition must be good, fair or poor.", code="validation-error")
        clean_rooms.append({"room": name, "condition": r.get("condition") or "", "note": r.get("note") or "",
                            "evidence_ids": ids})
        all_ids.extend(ids)
    for d in defects or []:
        all_ids.extend(str(x) for x in (d.get("evidence_ids") or []))
    all_ids = list(dict.fromkeys(str(x) for x in all_ids))
    if insp.kind in ("onboarding", "periodic"):
        if condition_rating not in ("good", "fair", "poor"):
            raise Invalid("Give the condition: good, fair or poor.", code="validation-error")
        if insp.kind == "onboarding" and len(clean_rooms) < ONBOARDING_ROOMS_MIN:
            raise Invalid("Record each room with its photos.", code="validation-error")
    if not all_ids:
        raise Invalid("Attach the photos taken in Tenmina Field.", code="validation-error")
    photos = _photos_for(insp, all_ids, by)
    if insp.kind == "repair":
        reasons = evidence_blockers([p.pk for p in photos])
        if reasons:
            raise RuleBlocked("These photos cannot back a payment.", code="evidence-rejected",
                              blocking_reasons=reasons)
    insp.outcome, insp.condition_rating = outcome, condition_rating or ""
    insp.rooms, insp.checklist, insp.defects = clean_rooms, list(checklist or []), list(defects or [])
    insp.notes, insp.photo_ids = (notes or "").strip(), [p.pk for p in photos]
    insp.submitted_at, insp.submitted_by, insp.submission_id = _now(), by, submission_id
    state.transition(insp, "pmg_inspection", "submitted", actor=by, event="pmg_inspection.submitted",
                     extra_fields=["outcome", "condition_rating", "rooms", "checklist", "defects", "notes",
                                   "photo_ids", "submitted_at", "submitted_by", "submission_id"],
                     payload={"inspection_id": insp.pk, "property_id": insp.property_id, "kind": insp.kind,
                              "repair_id": insp.repair_id})
    _work_accepted(insp)
    prop = insp.property
    if insp.kind == "onboarding":
        _close_case_visit(prop, photos)
        _notify(prop.owner, "pmg_condition_recorded",
                f"The inspector recorded the condition of {prop.title}: {condition_rating}, with "
                f"{len(photos)} photo(s). It is on your timeline.", obj=insp, link=f"{property_link(prop)}/timeline")
        try_activate(prop)
    elif insp.kind == "periodic":
        prop.next_inspection_due_on = _add_months(_today(), prop.inspection_interval_months)
        prop.save(update_fields=["next_inspection_due_on"])
        _notify(prop.owner, "pmg_inspection_recorded",
                f"Inspection of {prop.title} on {_today():%d %B %Y}: {condition_rating}. Photos are on your "
                "timeline.", obj=insp, link=f"{property_link(prop)}/timeline")
        if condition_rating == "poor" or defects:
            _alert_staff(prop.country, "pmg_inspection_defects",
                         f"The inspection of {prop.title} found problems. Consider a repair.", obj=insp, prop=prop)
    else:
        _after_repair_inspection(insp, by)
    return insp


def _work_accepted(insp):
    """work.accepted for PRO: the inspector's work, with no outcome field (RUL-26)."""
    publish("work.accepted", insp.pk, {
        "work_kind": "property_inspection", "work_type": "property_inspection", "work_ref": insp.pk,
        "person_id": insp.inspector_id, "role": "IN", "case_id": insp.property.onboarding_case_id
        if insp.kind == "onboarding" else None, "property_id": insp.property_id,
        "assigned_at": insp.assigned_at or insp.created_at, "accepted_at": insp.submitted_at, "quantity": 1,
        "country": insp.country.code})


def _close_case_visit(prop, photos):
    """The onboarding case's site visit is done by this inspection: its photos go on the case task."""
    from cases.services import complete_task

    case = prop.onboarding_case
    if case is None:
        return
    task = case.tasks.filter(step_key="site_visit").exclude(status__in=["done", "cancelled"]).first()
    if task is None:
        return
    try:
        with transaction.atomic():
            for ev in photos:
                _link(ev, "task", task.pk, "site_photo", None)
            complete_task(task, None, note="Condition inspection recorded in property management", system=True)
    except DomainError as exc:
        log.info("onboarding case task %s not closed: %s", task.pk, exc.detail)


def scheduled_inspection_watch(today: date | None = None) -> int:
    """Job propertymgmt.schedule_inspections (monthly): one periodic inspection per property when its
    interval has passed (US-PMG-006 AC1)."""
    today = today or _today()
    n = 0
    for prop in ManagedProperty.objects.filter(status="managed", next_inspection_due_on__isnull=False):
        lead = int(_cfg(prop.country, "inspection_lead_days", 14))  # assumption [TO VERIFY]
        if prop.next_inspection_due_on > today + timedelta(days=lead) or not flags.enabled("lines.pmg",
                                                                                            prop.country):
            continue
        if prop.inspections.filter(kind="periodic", status__in=["scheduled", "assigned"]).exists():
            continue
        insp = Inspection.objects.create(country=prop.country, property=prop, kind="periodic",
                                         scheduled_for=max(prop.next_inspection_due_on, today))
        _audit(None, "pmg_inspection.scheduled", insp, {"kind": "periodic"})
        _alert_staff(prop.country, "pmg_inspection_due",
                     f"A periodic inspection of {prop.title} is due by {insp.scheduled_for:%d %B %Y}. Assign an "
                     "inspector.", obj=insp, prop=prop)
        n += 1
    return n


def on_field_submission(payload: dict):
    """submission.received from Tenmina Field for a property inspection: photos first (evidence set), then
    the inspection with its outcome and checklist."""
    from accounts.models import Person

    insp = Inspection.objects.filter(pk=payload.get("subject_id")).first()
    person = Person.objects.filter(pk=payload.get("person_id")).first()
    if insp is None or person is None or insp.status != "assigned" or insp.inspector_id != person.pk:
        return
    items = payload.get("items") or []
    if payload.get("kind") == "evidence_set":
        rooms = list(insp.rooms or [])
        rating = insp.condition_rating
        for it in items:
            key = it.get("requirement_key") or ""
            if it.get("evidence_id"):
                label = key.replace("room_", "").replace("_", " ").strip() or "photo"
                room = next((r for r in rooms if r["room"] == label), None)
                if room is None:
                    room = {"room": label, "condition": "", "note": "", "evidence_ids": []}
                    rooms.append(room)
                room["evidence_ids"] = list(dict.fromkeys([*room["evidence_ids"], str(it["evidence_id"])]))
            elif key == "condition_rating" and it.get("value") in ("good", "fair", "poor"):
                rating = it["value"]
        insp.rooms, insp.condition_rating = rooms, rating
        insp.save(update_fields=["rooms", "condition_rating"])
        return
    if payload.get("kind") != "inspection":
        return
    outcome = payload.get("outcome")
    rating = insp.condition_rating or {"pass": "good", "pass_with_defects": "fair", "fail": "poor"}.get(outcome, "")
    try:
        with transaction.atomic():
            record_inspection(insp, person, outcome=outcome, condition_rating=rating, rooms=insp.rooms or [],
                              photo_ids=[it["evidence_id"] for it in items if it.get("evidence_id")],
                              checklist=payload.get("checklist") or [], defects=payload.get("defects") or [],
                              notes=payload.get("reason") or payload.get("note") or "",
                              submission_id=payload.get("submission_id"))
    except DomainError as exc:
        log.info("field inspection %s not recorded: %s", insp.pk, exc.detail)
        _alert_staff(insp.country, "pmg_inspection_incomplete",
                     f"The inspection of {insp.property.title} sent from Tenmina Field could not be recorded: "
                     f"{exc.detail}", obj=insp, prop=insp.property)


# --------------------------------------------------------------------------- repairs (FR-PMG-004, FR-PMG-005)

def _reporter_role(by, prop):
    if is_tenant_of(by, prop):
        return "tenant"
    if is_owner(by, prop):
        return "owner"
    if prop.inspections.filter(inspector=by).exists() and by.has_tenmina_role("IN"):
        return "inspector"
    if has_role(by, "CM", "RV", country=prop.country):
        return "staff"
    return None


@transaction.atomic
def report_repair(by, prop, *, title, description, photo_ids=(), urgent=False) -> Repair:
    """US-PMG-004 AC1: a tenant or inspector (or the owner) reports a repair with photos; the owner and the
    case manager are notified and a repair record opens."""
    _on(prop.country)
    role = _reporter_role(by, prop)
    if role is None:
        raise NotFound("Property not found.")
    if prop.status not in ("managed", "paused"):
        raise StateConflict("Repairs are reported once the property is under management.")
    if not (title or "").strip() or not (description or "").strip():
        raise Invalid("Say what needs repairing.", code="validation-error")
    photos = _evidence(photo_ids, required=1, what="photo of the problem")
    r = Repair.objects.create(country=prop.country, property=prop, reported_by=by, reporter_role=role,
                              title=title.strip(), description=description.strip(), urgent=bool(urgent))
    for ev in photos:
        _link(ev, "repair", r.pk, "report_photo", by)
    _audit(by, "repair.reported", r, {"reporter_role": role})
    publish("repair.reported", r.pk, {"repair_id": r.pk, "property_id": prop.pk, "owner_id": prop.owner_id,
                                      "reporter_role": role, "country": prop.country.code})
    _notify(prop.owner, "pmg_repair_reported",
            f"A repair was reported at {prop.title}: {r.title}. We will get at least two quotes from vetted "
            "contractors for you to choose from.", obj=r, link=f"/repairs/{r.pk}")
    _alert_staff(prop.country, "pmg_repair_reported",
                 f"Repair reported at {prop.title} by the {role}: {r.title}. Collect two quotes from the panel.",
                 obj=r, prop=prop, link=f"/back-office/repairs/{r.pk}")
    return r


def _contractor_payee_ok(contractor, payee) -> bool:
    if payee.person_id == contractor.pk:
        return True
    if payee.organisation_id:
        from accounts.selectors import is_member

        return is_member(contractor, payee.organisation_id)
    return False


def quotes_needed(r: Repair) -> int:
    limit = _cfg(r.country, "repair_single_quote_max_amount", None)  # [TO VERIFY]
    live = list(r.quotes.filter(status="received"))
    if limit is not None and live and all(qq.quote_amount <= q(limit) for qq in live):
        return 1
    return 1 if r.single_quote_exception_by_id else 2


def _distinct_live_quotes(r):
    return r.quotes.filter(status="received").values("contractor_id").distinct().count()


def _refresh_quote_state(r: Repair, by):
    n, need = _distinct_live_quotes(r), quotes_needed(r)
    if r.status == "reported" and n >= 1:
        state.transition(r, "repair", "quoting", actor=by)
    if r.status == "quoting" and n >= need:
        state.transition(r, "repair", "quotes_ready", actor=by, event="repair.quotes_ready",
                         payload={"repair_id": r.pk, "quotes": n})
        _notify(r.property.owner, "pmg_quotes_ready",
                f"{n} quote(s) for '{r.title}' at {r.property.title} are ready. Choose one; the money is then held "
                "at the bank and paid to the contractor only after our inspector passes the work.", obj=r,
                link=f"/repairs/{r.pk}", needs_action=True)
    elif r.status == "quotes_ready" and n < need:
        state.transition(r, "repair", "quoting", actor=by, reason="Not enough quotes")


@transaction.atomic
def add_quote(r: Repair, by, *, contractor, payee, amount, evidence_id, valid_until=None,
              description="") -> RepairQuote:
    """FR-PMG-004: a quote from a vetted panel contractor with a verified payee in their own name."""
    from accounts.selectors import is_relative_or_representative, is_vetted

    r = Repair.objects.select_for_update().get(pk=r.pk)
    _on(r.country)
    _require_staff(by, r.country, ("CM", "RV"), "A case manager collects quotes.")
    if r.status not in ("reported", "quoting", "quotes_ready"):
        raise StateConflict(f"This repair is {r.status.replace('_', ' ')}; quotes are closed.")
    prop = r.property
    if not is_vetted(contractor, "contractor"):
        raise RuleBlocked("Quotes come only from vetted panel contractors.", code="contractor-not-vetted",
                          blocking_reasons=[{"rule": "FR-PMG-004", "message": f"{contractor.full_name} is not vetted."}])
    if contractor.pk in (prop.owner_id, r.reported_by_id) or is_tenant_of(contractor, prop):
        raise RuleBlocked("The owner, the tenant or the reporter cannot quote.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "message": "Conflict of interest"}])
    if payee.country_id != r.country_id or payee.kind not in ("contractor", "supplier"):
        raise PayeeNotVerified("The quote must name the contractor's payee.",
                               blocking_reasons=[{"rule": "RUL-22", "message": "Wrong payee kind or country"}])
    if payee.verification_status != "verified" or payee.name_match != "matched":
        raise PayeeNotVerified("The contractor's account must be verified in their own name first.",
                               blocking_reasons=[{"rule": "RUL-22", "message": f"{payee.legal_name} is "
                                                                               f"{payee.verification_status}"}])
    if not _contractor_payee_ok(contractor, payee):
        raise PayeeNotVerified("The payee is not the contractor's own account.",
                               blocking_reasons=[{"rule": "RUL-22", "message": "Payee is not the contractor"}])
    if is_relative_or_representative(prop.owner, person=payee.person if payee.person_id else None,
                                     name=payee.legal_name) or (payee.person_id and is_tenant_of(payee.person, prop)):
        raise PayeeNotVerified("Money never goes to a relative, a representative or the tenant.",
                               blocking_reasons=[{"rule": "RUL-22", "message": "Relative or tenant as payee"}])
    amount, currency = _money(amount, r.country, "quote amount")
    if currency != r.country.currency:
        raise Invalid(f"Repair quotes are in {r.country.currency}.", code="validation-error")
    (ev,) = _evidence([evidence_id], required=1, what="quote document")
    if valid_until and valid_until < _today():
        raise Invalid("This quote has already expired.", code="validation-error")
    if r.quotes.filter(contractor=contractor).exists():
        raise StateConflict("This contractor already quoted. Withdraw that quote first.", code="quote-exists")
    qt = RepairQuote.objects.create(country=r.country, repair=r, contractor=contractor, payee=payee,
                                    quote_amount=amount, quote_currency=currency, quote_evidence=ev,
                                    valid_until=valid_until, description=description or "", added_by=by)
    _link(ev, "repair", r.pk, "quote", by)
    _audit(by, "repair.quote_added", qt, {"amount": f"{amount:.2f}", "contractor_id": str(contractor.pk)})
    publish("repair.quote_added", qt.pk, {"repair_id": r.pk, "quote_id": qt.pk})
    _refresh_quote_state(r, by)
    return qt


@transaction.atomic
def withdraw_quote(qt: RepairQuote, by, reason) -> RepairQuote:
    _require_staff(by, qt.country, ("CM", "RV"))
    if qt.status != "received":
        raise StateConflict(f"This quote is {qt.status}.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    state.transition(qt, "repair_quote", "withdrawn", actor=by, reason=reason)
    r = Repair.objects.select_for_update().get(pk=qt.repair_id)
    _refresh_quote_state(r, by)
    return qt


@transaction.atomic
def single_quote_exception(r: Repair, by, reason) -> Repair:
    """US-PMG-004 AC2: a reviewer may record an exception with a reason to proceed with one quote."""
    r = Repair.objects.select_for_update().get(pk=r.pk)
    _require_staff(by, r.country, ("RV",), "Only a reviewer records a single-quote exception.")
    if not (reason or "").strip():
        raise Invalid("Give the reason for accepting one quote.", code="validation-error")
    if r.status not in ("quoting", "reported"):
        raise StateConflict(f"This repair is {r.status.replace('_', ' ')}.")
    if _distinct_live_quotes(r) < 1:
        raise StateConflict("Add the one quote first.")
    r.single_quote_exception_by, r.single_quote_exception_reason = by, reason.strip()
    r.save(update_fields=["single_quote_exception_by", "single_quote_exception_reason"])
    _audit(by, "repair.single_quote_exception", r, {"reason": reason.strip()})
    _refresh_quote_state(r, by)
    return r


def approval_blockers(r: Repair) -> list[dict]:
    out = []
    if _distinct_live_quotes(r) < quotes_needed(r):
        out.append({"rule": "FR-PMG-004", "code": "quotes-missing",
                    "message": "At least two quotes from different vetted contractors are needed, unless a reviewer "
                               "records an exception."})
    return out


@transaction.atomic
def approve_quote(r: Repair, owner, *, quote_id, confirm_amount, mfa_at=None) -> Repair:
    """7.11: the owner approves one quote with a fresh MFA step-up; a repair escrow is proposed for that
    amount (RUL-11, US-PMG-004 AC3)."""
    from escrow import services as esc

    r = Repair.objects.select_for_update().get(pk=r.pk)
    _on(r.country)
    prop = r.property
    if not is_owner(owner, prop):
        raise NotFound()
    if mfa_at is None:
        from core.errors import MfaRequired

        raise MfaRequired()
    reasons = approval_blockers(r)
    if r.status != "quotes_ready" or reasons:
        raise StateConflict("This repair is not ready for your approval: fewer than two quotes.",
                            code="state-conflict", blocking_reasons=reasons or [
                                {"rule": "FR-PMG-004", "message": f"The repair is {r.status.replace('_', ' ')}."}])
    qt = r.quotes.filter(pk=quote_id, status="received").first() if _is_uuid(quote_id) else None
    if qt is None:
        raise Invalid("Choose one of the quotes for this repair.", code="validation-error")
    if qt.valid_until and qt.valid_until < _today():
        raise StateConflict("This quote has expired. Ask for a fresh quote.", code="quote-expired")
    amount, currency = _money(confirm_amount, r.country, "amount")
    if amount != qt.quote_amount or currency != qt.quote_currency:
        raise Invalid("The amount you confirmed is not the quote's amount.", code="validation-error",
                      extra={"errors": [{"pointer": "/confirm_amount", "message": "Differs from the quote."}]})
    qt.payee.refresh_from_db()
    if qt.payee.verification_status != "verified":
        raise PayeeNotVerified("The contractor's account is no longer verified.",
                               blocking_reasons=[{"rule": "RUL-22", "message": qt.payee.legal_name}])
    state.transition(qt, "repair_quote", "approved", actor=owner)
    for other in r.quotes.filter(status="received").exclude(pk=qt.pk):
        state.transition(other, "repair_quote", "declined", actor=owner)
    e = esc.open_line_escrow(kind="repair", client=owner, country=r.country, agreed_amount=qt.quote_amount,
                             by=owner, title=f"Repair: {r.title} at {prop.title}", currency=qt.quote_currency,
                             asset_id=prop.asset_id, payees=[qt.payee])
    esc.accept_terms(e, owner)
    r.approved_quote, r.owner_approved_at, r.escrow = qt, _now(), e
    state.transition(r, "repair", "approved", actor=owner, event="repair.quote_approved",
                     extra_fields=["approved_quote", "owner_approved_at", "escrow"],
                     payload={"repair_id": r.pk, "quote_id": qt.pk, "escrow_id": e.pk, "amount": qt.quote_amount,
                              "currency": qt.quote_currency, "property_id": prop.pk})
    from notifications.services import resolve_action

    try:
        with transaction.atomic():
            resolve_action(r)
    except Exception:  # noqa: BLE001
        log.exception("could not resolve the quote action")
    _alert_staff(r.country, "pmg_repair_approved",
                 f"The owner approved {qt.payee.legal_name}'s quote of {_fmt(qt.quote_amount, qt.quote_currency)} for "
                 f"'{r.title}'. Record Tenmina's acceptance and the bank's virtual account for escrow {e.reference}.",
                 obj=r, prop=prop, link=f"/back-office/escrows/{e.pk}")
    _notify(qt.contractor, "pmg_quote_approved",
            f"Your quote for '{r.title}' at {prop.title} was approved. Start when we tell you the bank holds the "
            "money. You are paid after our inspector passes the work.", obj=r, link=f"/repairs/{r.pk}")
    return r


@transaction.atomic
def on_escrow_funded(escrow_id):
    r = Repair.objects.select_for_update().filter(escrow_id=escrow_id, status="approved").first()
    if r is None:
        return None
    state.transition(r, "repair", "funded", event="repair.funded",
                     payload={"repair_id": r.pk, "escrow_id": escrow_id})
    _notify(r.property.owner, "pmg_repair_funded",
            f"The bank holds the money for '{r.title}'. The contractor is paid only after our inspector passes "
            "the work.", obj=r, link=f"/repairs/{r.pk}")
    if r.approved_quote_id:
        _notify(r.approved_quote.contractor, "pmg_repair_start",
                f"The bank holds the money for '{r.title}' at {r.property.title}. You can start the work.", obj=r,
                link=f"/repairs/{r.pk}")
    return r


@transaction.atomic
def record_work_done(r: Repair, by, *, evidence_ids=(), note="") -> Repair:
    """The contractor (or the case manager) reports the work done with photos; a repair inspection is
    scheduled for an inspector."""
    r = Repair.objects.select_for_update().get(pk=r.pk)
    _on(r.country)
    contractor = r.approved_quote.contractor if r.approved_quote_id else None
    if not (contractor and by.pk == contractor.pk) and not has_role(by, "CM", "RV", country=r.country):
        raise NotFound()
    if r.status not in ("funded", "in_progress"):
        raise StateConflict("Work is reported done once the bank holds the money.", code="repair-not-funded")
    for ev in _evidence(evidence_ids, required=1, what="photo of the finished work"):
        _link(ev, "repair", r.pk, "work_photo", by)
    r.work_done_at, r.work_done_by = _now(), by
    if r.status == "funded":
        state.transition(r, "repair", "in_progress", actor=by, event="repair.work_done",
                         extra_fields=["work_done_at", "work_done_by"],
                         payload={"repair_id": r.pk, "note": note or ""})
    else:
        r.save(update_fields=["work_done_at", "work_done_by"])
        publish("repair.work_done", r.pk, {"repair_id": r.pk, "note": note or ""})
    insp = r.inspections.filter(status__in=["scheduled", "assigned"]).first()
    if insp is None:
        Inspection.objects.create(country=r.country, property=r.property, repair=r, kind="repair",
                                  scheduled_for=_today() + timedelta(days=2))
    _alert_staff(r.country, "pmg_repair_inspection_due",
                 f"'{r.title}' at {r.property.title} is reported done. Assign an inspector to check it with photos.",
                 obj=r, prop=r.property)
    return r


def _after_repair_inspection(insp: Inspection, by):
    r = Repair.objects.select_for_update().get(pk=insp.repair_id)
    publish("repair.inspected", r.pk, {"repair_id": r.pk, "inspection_id": insp.pk, "outcome": insp.outcome,
                                       "property_id": r.property_id})
    if insp.outcome == "pass" and r.status == "in_progress":
        r.inspection = insp
        state.transition(r, "repair", "inspected", actor=by, extra_fields=["inspection"],
                         payload={"repair_id": r.pk, "inspection_id": insp.pk})
        _alert_staff(r.country, "pmg_repair_passed",
                     f"'{r.title}' passed inspection. Prepare the payment to the contractor.", obj=r,
                     prop=r.property)
        _notify(r.property.owner, "pmg_repair_passed",
                f"Our inspector passed the work on '{r.title}'. You will be asked to approve the payment to the "
                "contractor.", obj=r, link=f"/repairs/{r.pk}")
        return
    text = f"The work on '{r.title}' did not pass inspection ({insp.outcome.replace('_', ' ')}). {insp.notes}".strip()
    if r.approved_quote_id:
        _notify(r.approved_quote.contractor, "pmg_repair_failed", text + " Fix it and report it done again.",
                obj=r, link=f"/repairs/{r.pk}")
    _notify(r.property.owner, "pmg_repair_failed", text + " Nothing is paid until it passes.", obj=r,
            link=f"/repairs/{r.pk}")
    _alert_staff(r.country, "pmg_repair_failed", text, obj=r, prop=r.property)


@transaction.atomic
def prepare_instruction(r: Repair, by):
    """FR-PMG-005: the instruction to pay the contractor's verified payee after an inspection pass. The owner
    approves it, then two staff with release rights (5.3)."""
    from escrow import services as esc

    r = Repair.objects.select_for_update().get(pk=r.pk)
    _on(r.country)
    _require_staff(by, r.country, ("CM", "RV"), "A case manager prepares the instruction.")
    if r.status != "inspected" or r.inspection_id is None:
        raise RuleBlocked("The contractor is paid only after an inspection pass with photos.",
                          blocking_reasons=[{"rule": "FR-PMG-005", "code": "inspection-missing",
                                             "message": "No inspection pass recorded."}])
    qt = r.approved_quote
    ins = esc.request_release(r.escrow, payee=qt.payee, amount=qt.quote_amount, subject_type="repair",
                              subject_id=r.pk, requested_by=by, evidence_ids=list(r.inspection.photo_ids),
                              reason=f"Repair '{r.title}' passed inspection", kind="partial_release",
                              subject_label=repair_label(r.pk))
    r.release_instruction = ins
    state.transition(r, "repair", "instructed", actor=by, extra_fields=["release_instruction"],
                     payload={"repair_id": r.pk, "instruction_id": ins.pk})
    return ins


def repair_label(repair_id) -> str:
    r = Repair.objects.filter(pk=repair_id).select_related("property").first()
    return f"Repair: {r.title} at {r.property.title}" if r else ""


def repair_release_check(ins) -> list[dict]:
    """escrow.registry subject check for `repair` (FR-PMG-005, RUL-22): an inspection pass with app photos,
    the approved quote's payee, never more than the approved quote."""
    from mobile.services import evidence_blockers

    r = Repair.objects.filter(pk=ins.subject_id).select_related("approved_quote", "inspection", "property").first()
    if r is None:
        return [{"rule": "FR-PMG-005", "code": "subject-missing", "message": "The repair was not found."}]
    out = []
    insp = r.inspection
    if r.status not in ("inspected", "instructed") or insp is None or insp.kind != "repair" \
            or insp.status != "submitted" or insp.outcome != "pass" or insp.repair_id != r.pk:
        out.append({"rule": "FR-PMG-005", "code": "inspection-missing",
                    "message": "The repair has no inspection pass. Nothing is paid before the inspector passes it."})
    elif not insp.photo_ids:
        out.append({"rule": "FR-PMG-005", "code": "inspection-photos-missing",
                    "message": "The inspection pass has no photos."})
    else:
        out.extend(evidence_blockers(list(insp.photo_ids)))
    qt = r.approved_quote
    if qt is None or ins.payee_id != qt.payee_id:
        out.append({"rule": "RUL-22", "code": "payee-not-verified",
                    "message": "A repair pays only the contractor whose quote the owner approved."})
    elif ins.amount > qt.quote_amount:
        out.append({"rule": "RUL-11", "code": "amount-above-quote",
                    "message": f"The payment is more than the approved quote ({_fmt(qt.quote_amount, qt.quote_currency)})."})
    if ins.payee_id and ins.payee.person_id and is_tenant_of(ins.payee.person, r.property):
        out.append({"rule": "RUL-22", "code": "payee-not-verified", "message": "The tenant is never a payee."})
    return out


@transaction.atomic
def on_release_confirmed(payload):
    r = Repair.objects.select_for_update().filter(pk=payload.get("subject_id")).first()
    if r is None or r.status != "instructed":
        return None
    r.paid_at = _now()
    state.transition(r, "repair", "paid", event="repair.paid", extra_fields=["paid_at"],
                     payload={"repair_id": r.pk, "amount": payload.get("amount"), "currency": payload.get("currency"),
                              "bank_reference": payload.get("bank_reference"), "property_id": r.property_id})
    _notify(r.property.owner, "pmg_repair_paid",
            f"The bank confirmed payment of {payload.get('currency')} {payload.get('amount')} to "
            f"{r.approved_quote.payee.legal_name} for '{r.title}'. The photos and receipt are on your timeline.",
            obj=r, link=f"{property_link(r.property)}/timeline", category="money")
    return r


@transaction.atomic
def on_release_closed(payload):
    """A withdrawn or refused instruction sends the repair back to be instructed again."""
    r = Repair.objects.select_for_update().filter(pk=payload.get("subject_id")).first()
    if r is None or r.status != "instructed" or str(r.release_instruction_id) != str(payload.get("instruction_id")):
        return None
    r.release_instruction = None
    state.transition(r, "repair", "inspected", extra_fields=["release_instruction"],
                     reason="The instruction was withdrawn or refused")
    return r


@transaction.atomic
def close_repair(r: Repair, by, *, reason, reject=False) -> Repair:
    r = Repair.objects.select_for_update().get(pk=r.pk)
    if not (is_owner(by, r.property) or has_role(by, "CM", "RV", country=r.country)):
        raise NotFound()
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if reject and not has_role(by, "CM", "RV", country=r.country):
        raise Forbidden("Only staff reject a repair report.")
    if r.status == "approved" and r.escrow_id and r.escrow.status != "proposed":
        raise StateConflict("Money for this repair is already at the bank. Ask your case manager to cancel the "
                            "escrow.", code="repair-funded")
    if r.status not in ("reported", "quoting", "quotes_ready", "approved"):
        raise StateConflict(f"This repair is {r.status.replace('_', ' ')}.")
    r.closed_reason = reason.strip()
    state.transition(r, "repair", "rejected" if reject else "cancelled", actor=by, reason=reason,
                     extra_fields=["closed_reason"])
    return r


# --------------------------------------------------------------------------- timeline (FR-PMG-006)

def _photo(ev_id):
    return {"evidence_id": str(ev_id), "preview": f"/v1/evidence/{ev_id}"}


def timeline(prop) -> list[dict]:
    """US-PMG-006 AC2: rent, repairs and inspections in date order with photo previews."""
    items = [{"date": prop.created_at.date(), "kind": "registered", "title": "Registered for management",
              "status": "done", "detail": prop.asset.reference, "photos": [], "id": str(prop.pk)}]
    if prop.managed_at:
        items.append({"date": prop.managed_at.date(), "kind": "managed", "title": "Management started",
                      "status": "done", "detail": "", "photos": [], "id": str(prop.pk)})
    for insp in prop.inspections.filter(status="submitted"):
        items.append({"date": insp.submitted_at.date(), "kind": f"inspection_{insp.kind}",
                      "title": {"onboarding": "Condition inspection", "periodic": "Periodic inspection",
                                "repair": "Repair inspection"}[insp.kind],
                      "status": insp.outcome, "detail": insp.condition_rating or insp.notes,
                      "photos": [_photo(i) for i in insp.photo_ids], "id": str(insp.pk)})
    for t in prop.tenancies.all():
        items.append({"date": t.starts_on, "kind": "tenancy_started", "title": f"Tenancy of {t.tenant.full_name}",
                      "status": t.status, "detail": f"{_fmt(t.rent_amount, t.rent_currency)} {t.period}",
                      "photos": [], "id": str(t.pk)})
        mandate = live_mandate(prop) is not None
        for p in t.periods.all():
            when = p.received_on or p.due_on
            if p.status == "due" and p.due_on > _today():
                continue
            items.append({"date": when, "kind": "rent", "title": f"Rent for {p.period_start:%B %Y}",
                          "status": p.status, "detail": rent_status_text(p, mandate), "photos": [],
                          "amount": {"amount": f"{(p.received_amount or p.expected_amount):.2f}",
                                     "currency": p.expected_currency}, "id": str(p.pk)})
    from evidence.models import EvidenceLink

    for r in prop.repairs.all():
        photos = EvidenceLink.objects.filter(subject_type="repair", subject_id=r.pk,
                                             role__in=["report_photo", "work_photo"]).values_list("evidence_id",
                                                                                                  flat=True)
        items.append({"date": r.created_at.date(), "kind": "repair_reported", "title": f"Repair reported: {r.title}",
                      "status": r.status, "detail": r.description, "photos": [_photo(i) for i in photos],
                      "id": str(r.pk)})
        if r.paid_at:
            qt = r.approved_quote
            items.append({"date": r.paid_at.date(), "kind": "repair_paid", "title": f"Repair paid: {r.title}",
                          "status": "paid", "detail": f"Paid to {qt.payee.legal_name} by the bank",
                          "amount": {"amount": f"{qt.quote_amount:.2f}", "currency": qt.quote_currency},
                          "photos": [], "id": str(r.pk)})
    items.sort(key=lambda i: (i["date"], i["kind"]))
    for i in items:
        i["date"] = i["date"].isoformat()
    return items
