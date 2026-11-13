"""EVT Events and ceremonies: the public interface other modules may call.

FR-EVT-001 an event with a budget, a date and vendors; each vendor's registration and bank account verified
           (a vendor verification case and a verified payee, two staff) before any payment
FR-EVT-002 vendor payments through the event escrow: deposits against a signed quote, balances against an
           invoice, delivery evidence and a family confirmation code (ADR-20); each to the vendor's verified
           payee, after the client's approval and two staff approvals (RUL-11, RUL-05, RUL-22)
FR-EVT-003 budget against actual, and a receipt for every payment

Events published: event.created, vendor.added, vendor.verified, vendor_payment.proposed,
vendor_payment.evidenced, vendor_payment.paid, evt_event.status_changed.
"""
import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from administration import flags
from audit.services import record
from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, PayeeNotVerified, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from .models import COMMITTED, EVENT_KINDS, PAYMENT_KINDS, VENDOR_KINDS, Event, Vendor, VendorPayment

log = logging.getLogger(__name__)
STAFF = ("CM", "RV", "AD")
SUBJECT = "event_vendor_payment"


# --------------------------------------------------------------------------- helpers

def _now():
    return timezone.now()


def _today():
    return timezone.localdate()


def _on(country):
    flags.require("lines.evt", country)
    flags.read_only_guard()


def _cfg(country, key, default=None):
    from countries.selectors import config

    try:
        value = config(country, f"evt.{key}", default)
    except Exception:  # noqa: BLE001
        value = default
    return default if value is None else value


def is_staff(person, country=None) -> bool:
    return has_role(person, *STAFF, country=country)


def _require_staff(by, country, roles=("CM", "RV"), msg="Only a case manager can do this."):
    if not has_role(by, *roles, country=country):
        raise Forbidden(msg)


def _audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=type(obj).__name__.lower(), entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None))


def _notify(person, template, body, *, obj=None, link="", needs_action=False, category=None, channels=("in_app",)):
    from notifications.services import notify

    if person is None:
        return
    try:
        with transaction.atomic():
            notify(person, template, body=body, subject_obj=obj, link=link, needs_action=needs_action,
                   category=category, channels=channels)
    except Exception:  # noqa: BLE001
        log.exception("notification %s failed", template)


def _staff_in(country, *roles):
    from accounts.models import Person

    return Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                 role_grants__role__in=roles, role_grants__revoked_at__isnull=True,
                                 is_active=True).distinct()


def _alert_staff(event, template, body, *, obj=None, link=""):
    people = [event.case_manager] if event.case_manager_id else list(_staff_in(event.country, "CM"))
    for p in people:
        _notify(p, template, body, obj=obj, link=link or f"/back-office/events/{event.pk}", needs_action=True,
                category="task")


def _fmt(amount, currency):
    return f"{currency} {Decimal(amount):,.2f}"


def _is_uuid(v) -> bool:
    import uuid

    try:
        uuid.UUID(str(v))
        return True
    except (ValueError, TypeError):
        return False


def _evidence(ids, *, required=0, what="evidence"):
    from evidence.models import Evidence

    out = []
    for i in [i for i in (ids or []) if i]:
        ev = Evidence.objects.filter(pk=i).first() if _is_uuid(i) else None
        if ev is None:
            raise Invalid(f"The {what} {i} was not found.", code="validation-error")
        out.append(ev)
    if len(out) < required:
        raise Invalid(f"Attach the {what}.", code="validation-error")
    return out


def _link(ev, subject_type, subject_id, role, by):
    from evidence.services import link

    return link(ev, subject_type, subject_id, role=role, by=by)


def _money(value, currency_default):
    amount = value.get("amount") if isinstance(value, dict) else value
    currency = (value.get("currency") if isinstance(value, dict) else None) or currency_default
    try:
        amount = q(amount)
    except Exception as exc:  # noqa: BLE001
        raise Invalid("Enter the amount.", code="validation-error") from exc
    if amount <= 0:
        raise Invalid("The amount must be more than zero.", code="validation-error")
    return amount, str(currency).upper()


def event_link(e):
    return f"/events/{e.pk}"


# --------------------------------------------------------------------------- visibility

def is_client(person, event) -> bool:
    return bool(person and person.is_authenticated and event.client_id == person.pk)


def can_view(person, event) -> bool:
    return is_client(person, event) or is_staff(person, event.country)


def events_for(person):
    qs = Event.objects.select_related("country", "client", "escrow")
    if is_staff(person):
        from accounts.selectors import scope_to_staff_countries

        return scope_to_staff_countries(qs, person)
    return qs.filter(client=person)


def _require_view(person, event):
    if not can_view(person, event):
        raise NotFound()


def _require_client_or_staff(by, event):
    if not (is_client(by, event) or has_role(by, "CM", "RV", country=event.country)):
        raise NotFound()


# --------------------------------------------------------------------------- events (FR-EVT-001)

@transaction.atomic
def create_event(by, *, country, kind, name, event_date, budget, client=None, locality="",
                 confirmer_family_member_id=None) -> Event:
    _on(country)
    client = client or by
    if by.pk != client.pk:
        _require_staff(by, country, ("CM",), "A case manager creates an event for a client.")
    if not client.has_tenmina_role("CL"):
        raise Invalid("The event belongs to a Tenmina client.", code="validation-error")
    if kind not in EVENT_KINDS:
        raise Invalid(f"Kind must be one of {', '.join(EVENT_KINDS)}.", code="validation-error")
    if not (name or "").strip():
        raise Invalid("Name the event.", code="validation-error")
    if event_date < _today():
        raise Invalid("The event date is in the past.", code="validation-error")
    amount, currency = _money(budget, country.currency)
    if currency != country.currency:
        raise Invalid(f"Event budgets in {country.name} are in {country.currency}.", code="validation-error")
    e = Event.objects.create(country=country, client=client, kind=kind, name=name.strip(), event_date=event_date,
                             locality=locality or "", budget_amount=amount, budget_currency=currency,
                             created_by=by, case_manager=by if is_staff(by, country) else None)
    if confirmer_family_member_id:
        set_confirmer(e, by, confirmer_family_member_id)
    _draft_fee_order(e, by)
    _audit(by, "event.created", e, {"budget": f"{amount:.2f}", "currency": currency})
    publish("event.created", e.pk, {"event_id": e.pk, "client_id": client.pk, "country": country.code,
                                    "kind": kind})
    _alert_staff(e, "evt_event_created",
                 f"{client.full_name} created '{e.name}' on {e.event_date:%d %B %Y}. Help them add and verify vendors.",
                 obj=e)
    return e


def _draft_fee_order(e, by):
    from orders.services import create_line_order

    try:
        with transaction.atomic():
            order = create_line_order(client=e.client, kind="event_service", country=e.country, subject_type="event",
                                      subject_id=e.pk, details={"name": e.name},
                                      placed_by=by if by.pk != e.client_id else None)
        e.fee_order_id = order.pk
        e.save(update_fields=["fee_order_id"])
    except DomainError as exc:
        log.info("fee order for event %s not drafted: %s", e.pk, exc.detail)


@transaction.atomic
def set_confirmer(e: Event, by, family_member_id) -> Event:
    """ADR-20: the family member who confirms deliveries by a one-time code."""
    from accounts.selectors import active_family_member

    _on(e.country)
    if not is_client(by, e) and not has_role(by, "CM", "RV", country=e.country):
        raise NotFound()
    fm = active_family_member(e.client, family_member_id)
    if not fm.phone and fm.person_id is None:
        raise Invalid("The family member needs a phone number or a Tenmina account to confirm deliveries.",
                      code="validation-error")
    e.confirmer_family_member = fm
    e.save(update_fields=["confirmer_family_member"])
    _audit(by, "event.confirmer_set", e, {"family_member_id": str(fm.pk)})
    return e


@transaction.atomic
def change_budget(e: Event, by, *, budget, reason) -> Event:
    """The client raises or lowers the budget; the change is recorded (evt.budget_not_exceeded)."""
    _on(e.country)
    if not is_client(by, e):
        raise NotFound()
    if e.status in ("closed", "cancelled"):
        raise StateConflict(f"This event is {e.status}.")
    if not (reason or "").strip():
        raise Invalid("Say why the budget changes.", code="validation-error")
    amount, currency = _money(budget, e.budget_currency)
    if currency != e.budget_currency:
        raise Invalid("Keep the budget in the event's currency.", code="validation-error")
    if amount < committed(e):
        raise RuleBlocked("The budget cannot be less than what is already committed to vendors.",
                          code="budget-exceeded", blocking_reasons=[{"rule": "FR-EVT-003",
                                                                     "message": f"Committed {_fmt(committed(e), currency)}"}])
    e.budget_history = [*e.budget_history, {"from": f"{e.budget_amount:.2f}", "to": f"{amount:.2f}",
                                            "at": _now().isoformat(), "by": str(by.pk), "reason": reason.strip()}]
    e.budget_amount = amount
    e.save(update_fields=["budget_amount", "budget_history"])
    _audit(by, "event.budget_changed", e, e.budget_history[-1])
    return e


def committed(e: Event, exclude=None) -> Decimal:
    qs = e.payments.filter(status__in=COMMITTED)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.aggregate(s=Sum("amount"))["s"] or Decimal("0.00")


def quotes_total(e: Event) -> Decimal:
    return e.vendors.exclude(status__in=["removed", "rejected"]).aggregate(s=Sum("quote_amount"))["s"] \
        or Decimal("0.00")


def budget_warnings(e: Event) -> list[dict]:
    """US-EVT-001 AC2: the client is warned when vendor quotes exceed the budget."""
    out = []
    qt = quotes_total(e)
    if qt > e.budget_amount:
        out.append({"code": "quotes-over-budget",
                    "message": f"Vendor quotes total {_fmt(qt, e.budget_currency)}, more than the budget of "
                               f"{_fmt(e.budget_amount, e.budget_currency)}."})
    return out


# --------------------------------------------------------------------------- vendors (FR-EVT-001)

@transaction.atomic
def add_vendor(e: Event, by, *, kind, name, is_organisation=True, registration_number="",
               registration_evidence_id=None, contact_name="", contact_phone="", quote=None, quote_evidence_id=None,
               payee_id=None) -> Vendor:
    """A vendor is Unverified until its registration and its account name are checked by two staff
    (US-EVT-001 AC1). A relative or representative of the client is never a vendor (RUL-22)."""
    from accounts.selectors import is_relative_or_representative
    from cases.services import open_case

    _on(e.country)
    _require_client_or_staff(by, e)
    if e.status in ("closed", "cancelled"):
        raise StateConflict(f"This event is {e.status}.")
    if kind not in VENDOR_KINDS:
        raise Invalid(f"Kind must be one of {', '.join(VENDOR_KINDS)}.", code="validation-error")
    if not (name or "").strip():
        raise Invalid("Name the vendor.", code="validation-error")
    if is_relative_or_representative(e.client, name=name, phone=contact_phone):
        raise PayeeNotVerified("A family member or representative of the client cannot be a vendor. Money never "
                               "goes to a relative.", blocking_reasons=[{"rule": "RUL-22",
                                                                         "message": "Relative as vendor"}])
    reg = _evidence([registration_evidence_id], what="registration document") if registration_evidence_id else []
    qev = _evidence([quote_evidence_id], what="signed quote") if quote_evidence_id else []
    amount = currency = None
    if quote:
        amount, currency = _money(quote, e.budget_currency)
        if currency != e.budget_currency:
            raise Invalid("Quotes are in the event's currency.", code="validation-error")
    v = Vendor.objects.create(country=e.country, event=e, kind=kind, name=name.strip(),
                              is_organisation=bool(is_organisation), registration_number=registration_number or "",
                              registration_evidence=reg[0] if reg else None, contact_name=contact_name or "",
                              contact_phone=contact_phone or "", quote_amount=amount, quote_currency=currency or "",
                              quote_evidence=qev[0] if qev else None, added_by=by)
    for ev, role in [(x, "registration_certificate") for x in reg] + [(x, "signed_quote") for x in qev]:
        _link(ev, "evt_vendor", v.pk, role, by)
    publish("vendor.added", v.pk, {"vendor_id": v.pk, "event_id": e.pk})
    if payee_id:
        _use_existing_payee(v, by, payee_id)
    else:
        case = open_case("vendor_verification", e.country, subject_type="evt_vendor", subject_id=v.pk,
                         client=e.client, actor=by, title=f"Vendor check: {v.name}")
        v.verification_case = case
        v.save(update_fields=["verification_case"])
        task = case.tasks.filter(step_key="registration_check").first()
        if task is not None:
            for ev in reg:
                try:
                    _link(ev, "task", task.pk, "registration_certificate", by)
                except DomainError:
                    pass
        state.transition(v, "evt_vendor", "verifying", actor=by, payload={"vendor_id": v.pk})
        _alert_staff(e, "evt_vendor_check",
                     f"Check vendor {v.name} for '{e.name}': registration and an account in its own name.", obj=v)
    _audit(by, "vendor.added", v, {"kind": kind})
    return v


def _use_existing_payee(v: Vendor, by, payee_id):
    """Staff may reuse a vendor payee already verified for another event."""
    from escrow.models import Payee

    _require_staff(by, v.country, ("CM", "RV"), "Only staff reuse a verified payee.")
    p = Payee.objects.filter(pk=payee_id).first() if _is_uuid(payee_id) else None
    if p is None or p.kind != "vendor" or p.country_id != v.country_id or p.verification_status != "verified":
        raise PayeeNotVerified("Choose a verified vendor payee in this country.",
                               blocking_reasons=[{"rule": "RUL-22", "message": "Payee not verified"}])
    v.payee, v.verified_at = p, _now()
    state.transition(v, "evt_vendor", "verified", actor=by, event="vendor.verified", extra_fields=["payee",
                                                                                                  "verified_at"],
                     payload={"vendor_id": v.pk, "event_id": v.event_id, "payee_id": p.pk})
    _after_vendor_verified(v, by)


@transaction.atomic
def register_vendor_payee(v: Vendor, by, *, legal_name, bank_name, account_number, account_name_source,
                          account_name="", account_name_evidence_id=None, legal_name_evidence_id=None,
                          signatory_name="", signatory_id_number="", contact_email="") -> object:
    """The vendor's account in its own name, checked by the bank's name check or a bank letter, then two
    staff (FR-ESC-015, RUL-31). Prepared here; approved through the payee verification flow."""
    from accounts.services import request_national_id_check
    from escrow import services as esc

    _on(v.country)
    _require_staff(by, v.country, ("CM", "RV"), "A case manager records the vendor's account.")
    if v.status not in ("verifying", "unverified", "rejected"):
        raise StateConflict(f"This vendor is {v.status}.")
    if v.payee_id:
        raise StateConflict("This vendor already has a payee. A change goes through a payee change.",
                            code="payee-exists")
    legal_ev = _evidence([legal_name_evidence_id or getattr(v.registration_evidence, "pk", None)], required=1,
                         what="registration or identity document")[0]
    name_ev = _evidence([account_name_evidence_id], what="bank letter")[0] if account_name_evidence_id else None
    nid = None
    if signatory_id_number:
        nid = request_national_id_check(by=by, country=v.country, subject_role="signatory" if v.is_organisation
                                        else "payee", subject_name=signatory_name or legal_name,
                                        id_number=signatory_id_number, context_type="evt_vendor", context_id=v.pk)
    p = esc.create_payee(by, country=v.country, kind="vendor",
                         subject_type="organisation" if v.is_organisation else "person", subject_id=v.pk,
                         legal_name=legal_name, legal_name_evidence=legal_ev, bank_name=bank_name,
                         account_number=account_number, account_name=account_name,
                         account_name_source=account_name_source, account_name_evidence=name_ev,
                         national_id_check=nid, contact_email=contact_email or "", contact_phone=v.contact_phone)
    if p.name_match == "matched" and (nid is None or nid.result == "match"):
        esc.prepare_verification(p, by)
    v.payee = p
    v.save(update_fields=["payee"])
    _audit(by, "vendor.payee_registered", v, {"payee_id": str(p.pk), "name_match": p.name_match})
    return p


def vendor_blockers(v: Vendor) -> list[dict]:
    out = []
    case = v.verification_case
    if case is not None and not (case.status == "completed" and case.outcome == "verified"):
        out.append({"rule": "FR-EVT-001", "code": "vendor-check-open",
                    "message": "The vendor's registration check is not finished."})
    if v.payee_id is None:
        out.append({"rule": "RUL-22", "code": "payee-missing", "message": "The vendor's account is not recorded."})
    elif v.payee.verification_status != "verified" or v.payee.name_match != "matched":
        out.append({"rule": "RUL-22", "code": "payee-not-verified",
                    "message": "The vendor's account is not verified by two staff."})
    return out


@transaction.atomic
def try_verify_vendor(v: Vendor, by=None) -> Vendor:
    v = Vendor.objects.select_for_update().get(pk=v.pk)
    if v.status not in ("verifying", "unverified") or vendor_blockers(v):
        return v
    v.verified_at = _now()
    state.transition(v, "evt_vendor", "verified", actor=by, event="vendor.verified", extra_fields=["verified_at"],
                     payload={"vendor_id": v.pk, "event_id": v.event_id, "payee_id": v.payee_id})
    _after_vendor_verified(v, by)
    return v


def _after_vendor_verified(v: Vendor, by):
    from escrow import services as esc

    e = v.event
    _notify(e.client, "evt_vendor_verified",
            f"{v.name} is verified for '{e.name}': its registration and its account in its own name were checked by "
            "two staff.", obj=v, link=event_link(e))
    if e.escrow_id and e.escrow.status == "proposed":
        actor = by if by is not None and is_staff(by, e.country) else (e.case_manager or v.payee.prepared_by)
        try:
            with transaction.atomic():
                esc.add_party(e.escrow, actor, role="vendor", payee=v.payee, must_accept=False)
        except DomainError as exc:
            log.info("vendor %s not added to escrow %s: %s", v.pk, e.escrow_id, exc.detail)


@transaction.atomic
def on_vendor_case(case_id, outcome, note=""):
    v = Vendor.objects.filter(verification_case_id=case_id).first()
    if v is None:
        return None
    if outcome == "verified":
        return try_verify_vendor(v)
    if v.status in ("verifying", "unverified"):
        state.transition(v, "evt_vendor", "rejected", reason=note or "Not verified",
                         payload={"vendor_id": v.pk, "event_id": v.event_id})
        _notify(v.event.client, "evt_vendor_rejected",
                f"We could not verify {v.name}. No payment can go to it. Your case manager will suggest another "
                "vendor.", obj=v, link=event_link(v.event), needs_action=True)
    return v


@transaction.atomic
def on_payee_status(payee_id, verified: bool):
    for v in Vendor.objects.filter(payee_id=payee_id):
        if verified:
            try_verify_vendor(v)
        elif v.status == "verified":
            state.transition(v, "evt_vendor", "unverified", reason="The vendor's payee was suspended")


@transaction.atomic
def remove_vendor(v: Vendor, by, reason) -> Vendor:
    _require_client_or_staff(by, v.event)
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if v.payments.filter(status__in=["client_approved", "instructed"]).exists():
        raise StateConflict("A payment to this vendor is on its way. Wait for it or withdraw it first.")
    v.removed_reason = reason.strip()
    state.transition(v, "evt_vendor", "removed", actor=by, reason=reason, extra_fields=["removed_reason"])
    return v


# --------------------------------------------------------------------------- the event escrow

@transaction.atomic
def open_escrow(e: Event, by):
    """The event escrow for the budget, naming the verified vendors' payees (open_line_escrow kind event)."""
    from escrow import services as esc

    e = Event.objects.select_for_update().get(pk=e.pk)
    _on(e.country)
    _require_client_or_staff(by, e)
    if e.escrow_id:
        raise StateConflict("This event already has its escrow.", code="escrow-exists")
    if e.status != "planning":
        raise StateConflict(f"This event is {e.status}.")
    vendors = list(e.vendors.filter(status="verified").select_related("payee"))
    if not vendors:
        raise RuleBlocked("Verify at least one vendor before the money goes to the bank.", code="vendor-not-verified",
                          blocking_reasons=[{"rule": "FR-EVT-001", "message": "No verified vendor yet."}])
    payees = list({v.payee_id: v.payee for v in vendors}.values())
    escrow = esc.open_line_escrow(kind="event", client=e.client, country=e.country, agreed_amount=e.budget_amount,
                                  by=by, title=f"Event: {e.name}", currency=e.budget_currency, payees=payees)
    if is_client(by, e):
        esc.accept_terms(escrow, by)
    e.escrow = escrow
    e.save(update_fields=["escrow"])
    _audit(by, "event.escrow_opened", e, {"escrow_id": str(escrow.pk)})
    _alert_staff(e, "evt_escrow_opened",
                 f"The escrow {escrow.reference} for '{e.name}' is proposed. Record Tenmina's acceptance and the bank's "
                 "virtual account.", obj=e, link=f"/back-office/escrows/{escrow.pk}")
    return escrow


@transaction.atomic
def on_escrow_funded(escrow_id):
    e = Event.objects.select_for_update().filter(escrow_id=escrow_id, status="planning").first()
    if e is None:
        return None
    state.transition(e, "evt_event", "funded", payload={"event_id": e.pk, "escrow_id": escrow_id})
    _notify(e.client, "evt_funded", f"The bank holds the money for '{e.name}'. Vendors are paid only against "
                                    "signed quotes, invoices and delivery evidence.", obj=e, link=event_link(e))
    return e


# --------------------------------------------------------------------------- vendor payments (FR-EVT-002)

@transaction.atomic
def propose_payment(e: Event, by, *, vendor_id, kind, amount, quote_evidence_id=None, invoice_evidence_id=None,
                    delivery_evidence_ids=(), description="") -> VendorPayment:
    """A deposit against a signed quote (up to the configured deposit share of the quote) or a balance or full
    payment against an invoice and delivery evidence. Never over the budget unless the client raises it."""
    e = Event.objects.select_for_update().get(pk=e.pk)
    _on(e.country)
    _require_staff(by, e.country, ("CM", "RV"), "A case manager prepares vendor payments.")
    if e.status in ("closed", "cancelled"):
        raise StateConflict(f"This event is {e.status}.")
    if kind not in PAYMENT_KINDS:
        raise Invalid(f"Kind must be one of {', '.join(PAYMENT_KINDS)}.", code="validation-error")
    v = e.vendors.filter(pk=vendor_id).select_related("payee").first() if _is_uuid(vendor_id) else None
    if v is None:
        raise Invalid("Choose a vendor of this event.", code="validation-error")
    if v.status != "verified":
        raise PayeeNotVerified(f"{v.name} is not verified. No payment can go to it.",
                               blocking_reasons=vendor_blockers(v) or [{"rule": "RUL-22",
                                                                        "message": f"Vendor is {v.status}"}])
    amount, currency = _money(amount, e.budget_currency)
    if currency != e.budget_currency:
        raise Invalid("Payments are in the event's currency.", code="validation-error")
    quote = _evidence([quote_evidence_id], what="signed quote") if quote_evidence_id else []
    invoice = _evidence([invoice_evidence_id], what="invoice") if invoice_evidence_id else []
    delivery = _evidence(delivery_evidence_ids, what="delivery evidence")
    if kind == "deposit":
        if not quote and v.quote_evidence_id is None:
            raise RuleBlocked("A deposit is paid only against a signed quote.", code="quote-missing",
                              blocking_reasons=[{"rule": "FR-EVT-002", "message": "No signed quote."}])
        if v.quote_amount is None:
            raise Invalid("Record the amount of the vendor's signed quote first.", code="validation-error")
        share = Decimal(str(_cfg(e.country, "deposit_share_pct", 50)))  # assumption [TO VERIFY]
        cap = q(v.quote_amount * share / 100)
        if amount > cap:
            raise RuleBlocked(f"A deposit is at most {share}% of the signed quote ({_fmt(cap, currency)}).",
                              code="deposit-too-large",
                              blocking_reasons=[{"rule": "FR-EVT-002", "message": f"Cap {_fmt(cap, currency)}"}])
        if v.payments.filter(kind="deposit").exclude(status="rejected").exists():
            raise StateConflict("This vendor already has a deposit.", code="deposit-exists")
    elif e.confirmer_family_member_id is None:
        raise StateConflict("Nominate the family member who confirms deliveries before paying for them.",
                            code="confirmer-missing")
    if committed(e) + amount > e.budget_amount:
        raise RuleBlocked("This payment would take the event over its budget. The client can raise the budget.",
                          code="budget-exceeded",
                          blocking_reasons=[{"rule": "FR-EVT-003", "message":
                                             f"Committed {_fmt(committed(e), currency)} of "
                                             f"{_fmt(e.budget_amount, currency)}"}])
    p = VendorPayment.objects.create(country=e.country, event=e, vendor=v, kind=kind, amount=amount,
                                     currency=currency, description=description or "",
                                     quote_evidence=quote[0] if quote else (v.quote_evidence if kind == "deposit"
                                                                            else None),
                                     invoice_evidence=invoice[0] if invoice else None,
                                     delivery_evidence_ids=[d.pk for d in delivery], prepared_by=by)
    for ev, role in ([(x, "signed_quote") for x in quote] + [(x, "invoice") for x in invoice]
                     + [(x, "delivery") for x in delivery]):
        _link(ev, SUBJECT, p.pk, role, by)
    _audit(by, "vendor_payment.proposed", p, {"kind": kind, "amount": f"{amount:.2f}"})
    publish("vendor_payment.proposed", p.pk, {"payment_id": p.pk, "event_id": e.pk, "vendor_id": v.pk})
    _advance(p, by)
    p.refresh_from_db()
    return p


@transaction.atomic
def add_payment_evidence(p: VendorPayment, by, *, invoice_evidence_id=None, delivery_evidence_ids=()):
    _on(p.country)
    _require_staff(by, p.country, ("CM", "RV"), "A case manager adds the evidence.")
    if p.status != "proposed":
        raise StateConflict(f"This payment is {p.status.replace('_', ' ')}.")
    if invoice_evidence_id:
        (inv,) = _evidence([invoice_evidence_id], required=1, what="invoice")
        p.invoice_evidence = inv
        _link(inv, SUBJECT, p.pk, "invoice", by)
    for d in _evidence(delivery_evidence_ids, what="delivery evidence"):
        _link(d, SUBJECT, p.pk, "delivery", by)
        if d.pk not in p.delivery_evidence_ids:
            p.delivery_evidence_ids = [*p.delivery_evidence_ids, d.pk]
    p.save(update_fields=["invoice_evidence", "delivery_evidence_ids"])
    _advance(p, by)
    p.refresh_from_db()
    return p


def evidence_missing(p: VendorPayment) -> list[dict]:
    out = []
    if p.kind == "deposit":
        if p.quote_evidence_id is None:
            out.append({"rule": "FR-EVT-002", "code": "quote-missing", "message": "No signed quote."})
        return out
    if p.invoice_evidence_id is None:
        out.append({"rule": "FR-EVT-002", "code": "invoice-missing", "message": "No invoice."})
    if not p.delivery_evidence_ids:
        out.append({"rule": "FR-EVT-002", "code": "delivery-evidence-missing",
                    "message": "No delivery evidence (photos or a delivery note)."})
    if p.family_confirmed_at is None:
        out.append({"rule": "FR-EVT-002", "code": "visit-not-confirmed",
                    "message": "The family has not confirmed the delivery."})
    return out


def _advance(p: VendorPayment, by=None):
    """Send the family confirmation once the invoice and delivery evidence are in; evidenced when complete."""
    if p.status != "proposed":
        return p
    if p.kind != "deposit" and p.invoice_evidence_id and p.delivery_evidence_ids and p.family_confirmed_at is None:
        from notifications.services import confirmation_status

        conf = confirmation_status(SUBJECT, p.pk)
        if conf is None or conf.status in ("expired", "locked", "cancelled"):
            send_confirmation(p, by)
    if evidence_missing(p):
        return p
    p.evidenced_at = _now()
    state.transition(p, "vendor_payment", "evidenced", actor=by, event="vendor_payment.evidenced",
                     extra_fields=["evidenced_at"],
                     payload={"payment_id": p.pk, "event_id": p.event_id, "vendor_id": p.vendor_id, "kind": p.kind,
                              "amount": p.amount, "currency": p.currency})
    _notify(p.event.client, "evt_payment_approval",
            f"Please approve {_fmt(p.amount, p.currency)} to {p.vendor.name} ({p.kind}) for '{p.event.name}'. "
            "Nothing is paid until you approve.", obj=p, link=f"/vendor-payments/{p.pk}", needs_action=True,
            category="approval")
    return p


def send_confirmation(p: VendorPayment, by=None):
    """ADR-20: a one-time code to the nominated family member, never to the vendor or the case manager."""
    from notifications.services import send_confirmation_code

    fm = p.event.confirmer_family_member
    if fm is None:
        raise StateConflict("Nominate the family member who confirms deliveries.", code="confirmer-missing")
    channel = "sms" if fm.phone else "in_app"
    conf = send_confirmation_code(subject_type=SUBJECT, subject_id=p.pk, country=p.country, purpose="event_delivery",
                                  to_address=fm.phone, channel=channel, recipient_name=fm.full_name,
                                  recipient_person=fm.person, created_by=by,
                                  summary=f"delivery by {p.vendor.name} for {p.event.name}")
    p.family_confirmation = conf
    p.save(update_fields=["family_confirmation"])
    return conf


@transaction.atomic
def resend_confirmation(p: VendorPayment, by):
    _require_staff(by, p.country, ("CM", "RV"))
    if p.status != "proposed" or p.kind == "deposit" or p.family_confirmed_at:
        raise StateConflict("This payment needs no family confirmation now.")
    return send_confirmation(p, by)


@transaction.atomic
def confirm_delivery(p: VendorPayment, by, *, code):
    """The nominated family member, signed in, confirms with the code they received."""
    from notifications.services import verify_code_or_raise

    fm = p.event.confirmer_family_member
    if fm is None or fm.person_id != by.pk:
        raise NotFound()
    verify_code_or_raise(subject_type=SUBJECT, subject_id=p.pk, code=code, via="code", actor=by)
    p.refresh_from_db()
    return p


@transaction.atomic
def on_family_confirmation(payload, confirmed: bool):
    p = VendorPayment.objects.select_for_update().filter(pk=payload.get("subject_id")).first()
    if p is None or p.status != "proposed":
        return None
    if confirmed:
        p.family_confirmed_at = _now()
        p.save(update_fields=["family_confirmed_at"])
        _audit(None, "vendor_payment.family_confirmed", p, {"via": payload.get("via")})
        return _advance(p)
    _alert_staff(p.event, "evt_delivery_disputed",
                 f"The family disputed the delivery by {p.vendor.name} for '{p.event.name}'. Nothing is paid; call them.",
                 obj=p)
    _notify(p.event.client, "evt_delivery_disputed",
            f"The family said the delivery by {p.vendor.name} was not right. Nothing is paid until it is resolved.",
            obj=p, link=f"/vendor-payments/{p.pk}")
    return p


def _instruct(p: VendorPayment, requested_by):
    from escrow import services as esc

    e = p.event
    if e.escrow_id is None:
        raise StateConflict("The event's money is not at the bank yet.", code="escrow-missing")
    evidence = [x for x in [p.quote_evidence_id, p.invoice_evidence_id, *p.delivery_evidence_ids] if x]
    ins = esc.request_release(e.escrow, payee=p.vendor.payee, amount=p.amount, subject_type=SUBJECT, subject_id=p.pk,
                              requested_by=requested_by, evidence_ids=evidence, kind="partial_release",
                              reason=f"{p.kind.capitalize()} to {p.vendor.name}", subject_label=payment_label(p.pk))
    p.release_instruction = ins
    state.transition(p, "vendor_payment", "instructed", actor=requested_by, extra_fields=["release_instruction"],
                     payload={"payment_id": p.pk, "instruction_id": ins.pk})
    return ins


@transaction.atomic
def client_approve(p: VendorPayment, client, *, mfa_at, confirm_amount=None,
                   acknowledge_budget_warning=False) -> VendorPayment:
    """POST /v1/vendor-payments/{id}/client-approval (RUL-11): the client approves with a fresh MFA step-up.
    The release instruction to the vendor's verified payee is prepared and carries this approval; two staff
    with release rights then approve (RUL-05)."""
    from escrow import services as esc

    p = VendorPayment.objects.select_for_update().get(pk=p.pk)
    e = p.event
    _on(e.country)
    if not is_client(client, e):
        raise NotFound()
    if mfa_at is None:
        from core.errors import MfaRequired

        raise MfaRequired()
    if p.status != "evidenced":
        reasons = evidence_missing(p) if p.status == "proposed" else []
        raise StateConflict(f"This payment is {p.status.replace('_', ' ')}, not waiting for your approval.",
                            blocking_reasons=reasons)
    if confirm_amount is not None:
        amount, currency = _money(confirm_amount, p.currency)
        if amount != p.amount or currency != p.currency:
            raise Invalid("The amount you confirmed is not the payment's amount.", code="validation-error")
    warnings = budget_warnings(e)
    if warnings and not acknowledge_budget_warning:
        raise DomainError("Your vendor quotes are over the budget. Confirm you have seen this before you approve.",
                          code="budget-warning", status=409, blocking_reasons=[
                              {"rule": "US-EVT-001", **w} for w in warnings])
    p.client_approved_at, p.budget_warning_acknowledged = _now(), bool(warnings)
    state.transition(p, "vendor_payment", "client_approved", actor=client,
                     extra_fields=["client_approved_at", "budget_warning_acknowledged"],
                     payload={"payment_id": p.pk, "event_id": e.pk})
    ins = _instruct(p, p.prepared_by)
    esc.client_approve(ins, client, mfa_at)
    from notifications.services import resolve_action

    try:
        with transaction.atomic():
            resolve_action(p)
    except Exception:  # noqa: BLE001
        log.exception("could not resolve the approval action")
    p.refresh_from_db()
    return p


@transaction.atomic
def prepare_instruction(p: VendorPayment, by):
    """POST /v1/vendor-payments/{id}/instructions: a fresh instruction after one was withdrawn or refused.
    The client approves it again in the release flow."""
    p = VendorPayment.objects.select_for_update().get(pk=p.pk)
    _on(p.country)
    _require_staff(by, p.country, ("CM", "RV"), "A case manager prepares the instruction.")
    if p.status != "client_approved":
        raise StateConflict("Only a payment the client approved, with no live instruction, is instructed.")
    return _instruct(p, by)


@transaction.atomic
def reject_payment(p: VendorPayment, by, reason) -> VendorPayment:
    _require_client_or_staff(by, p.event)
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if p.status not in ("proposed", "evidenced", "client_approved"):
        raise StateConflict(f"This payment is {p.status.replace('_', ' ')}.")
    p.reject_reason = reason.strip()
    state.transition(p, "vendor_payment", "rejected", actor=by, reason=reason, extra_fields=["reject_reason"])
    return p


def payment_label(pid) -> str:
    p = VendorPayment.objects.filter(pk=pid).select_related("vendor", "event").first()
    return f"{p.kind.capitalize()} to {p.vendor.name} for {p.event.name}" if p else ""


def payment_release_check(ins) -> list[dict]:
    """escrow.registry subject check for `event_vendor_payment` (FR-EVT-002, RUL-22)."""
    p = VendorPayment.objects.filter(pk=ins.subject_id).select_related("vendor", "event").first()
    if p is None:
        return [{"rule": "FR-EVT-002", "code": "subject-missing", "message": "The vendor payment was not found."}]
    out = []
    if p.event.status == "cancelled":
        out.append({"rule": "FR-EVT-002", "code": "event-cancelled", "message": "The event is cancelled."})
    if p.status not in ("client_approved", "instructed"):
        out.append({"rule": "RUL-11", "code": "client-approval-missing",
                    "message": "The client has not approved this vendor payment."})
    out.extend(evidence_missing(p))
    v = p.vendor
    if v.status != "verified" or v.payee_id is None or ins.payee_id != v.payee_id:
        out.append({"rule": "RUL-22", "code": "payee-not-verified",
                    "message": "An event payment goes only to the vendor's own verified payee."})
    if ins.amount > p.amount:
        out.append({"rule": "RUL-11", "code": "amount-above-approval",
                    "message": f"The instruction is more than the approved {_fmt(p.amount, p.currency)}."})
    return out


@transaction.atomic
def on_release_confirmed(payload):
    p = VendorPayment.objects.select_for_update().filter(pk=payload.get("subject_id")).first()
    if p is None or p.status != "instructed":
        return None
    p.paid_at, p.bank_reference = _now(), payload.get("bank_reference") or ""
    state.transition(p, "vendor_payment", "paid", event="vendor_payment.paid", extra_fields=["paid_at",
                                                                                            "bank_reference"],
                     payload={"payment_id": p.pk, "event_id": p.event_id, "vendor_id": p.vendor_id,
                              "amount": p.amount, "currency": p.currency})
    e = Event.objects.select_for_update().get(pk=p.event_id)
    if e.status == "funded":
        state.transition(e, "evt_event", "in_progress", payload={"event_id": e.pk})
    _notify(e.client, "evt_payment_receipt",
            f"The bank paid {_fmt(p.amount, p.currency)} to {p.vendor.name} for '{e.name}'. Your receipt is in the "
            "event's payments.", obj=p, link=f"{event_link(e)}/receipts", category="money")
    return p


@transaction.atomic
def on_release_closed(payload):
    p = VendorPayment.objects.select_for_update().filter(pk=payload.get("subject_id")).first()
    if p is None or p.status != "instructed" or str(p.release_instruction_id) != str(payload.get("instruction_id")):
        return None
    p.release_instruction = None
    state.transition(p, "vendor_payment", "client_approved", extra_fields=["release_instruction"],
                     reason="The instruction was withdrawn or refused")
    _alert_staff(p.event, "evt_instruction_closed",
                 f"The payment to {p.vendor.name} was withdrawn or refused. Prepare it again if it should go ahead.",
                 obj=p)
    return p


# --------------------------------------------------------------------------- close, cancel, budget against actual

@transaction.atomic
def close_event(e: Event, by) -> Event:
    e = Event.objects.select_for_update().get(pk=e.pk)
    _require_client_or_staff(by, e)
    if e.status not in ("funded", "in_progress"):
        raise StateConflict(f"This event is {e.status}.")
    if e.payments.filter(status__in=["proposed", "evidenced", "client_approved", "instructed"]).exists():
        raise StateConflict("Some vendor payments are still open. Pay or reject them first.", code="payments-open")
    e.closed_at = _now()
    state.transition(e, "evt_event", "closed", actor=by, extra_fields=["closed_at"], payload={"event_id": e.pk})
    _alert_staff(e, "evt_event_closed", f"'{e.name}' is closed. Refund any money left at the bank to the account it "
                                        "came from.", obj=e)
    return e


@transaction.atomic
def cancel_event(e: Event, by, reason) -> Event:
    from escrow import services as esc

    e = Event.objects.select_for_update().get(pk=e.pk)
    _require_client_or_staff(by, e)
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if e.payments.filter(status__in=["instructed", "paid"]).exists():
        raise StateConflict("Vendors were already paid. Close the event instead.")
    e.cancel_reason = reason.strip()
    state.transition(e, "evt_event", "cancelled", actor=by, reason=reason, extra_fields=["cancel_reason"])
    if e.escrow_id and e.escrow.status not in ("cancelled", "released"):
        try:
            with transaction.atomic():
                esc.request_cancellation(e.escrow, by, reason=f"Event cancelled: {reason.strip()}")
        except DomainError as exc:
            _alert_staff(e, "evt_escrow_cancel", f"Cancel escrow {e.escrow.reference}: {exc.detail}", obj=e)
    return e


def budget_vs_actual(e: Event) -> dict:
    """US-EVT-003: budget, committed and paid per vendor with each receipt."""
    rows = []
    for v in e.vendors.exclude(status="removed").order_by("created_at"):
        pays = list(v.payments.exclude(status="rejected").order_by("created_at"))
        rows.append({
            "vendor_id": str(v.pk), "name": v.name, "kind": v.kind, "status": v.status,
            "quote": None if v.quote_amount is None else {"amount": f"{v.quote_amount:.2f}",
                                                          "currency": v.quote_currency},
            "committed": {"amount": f"{sum((p.amount for p in pays if p.status != 'paid'), Decimal('0')):.2f}",
                          "currency": e.budget_currency},
            "paid": {"amount": f"{sum((p.amount for p in pays if p.status == 'paid'), Decimal('0')):.2f}",
                     "currency": e.budget_currency},
            "payments": [{"id": str(p.pk), "kind": p.kind, "status": p.status,
                          "amount": {"amount": f"{p.amount:.2f}", "currency": p.currency},
                          "receipt": receipt(p) if p.status == "paid" else None} for p in pays]})
    paid = e.payments.filter(status="paid").aggregate(s=Sum("amount"))["s"] or Decimal("0.00")
    comm = committed(e)
    return {"event_id": str(e.pk), "budget": {"amount": f"{e.budget_amount:.2f}", "currency": e.budget_currency},
            "quotes": {"amount": f"{quotes_total(e):.2f}", "currency": e.budget_currency},
            "committed": {"amount": f"{comm - paid:.2f}", "currency": e.budget_currency},
            "paid": {"amount": f"{paid:.2f}", "currency": e.budget_currency},
            "remaining": {"amount": f"{e.budget_amount - comm:.2f}", "currency": e.budget_currency},
            "warnings": budget_warnings(e), "vendors": rows}


def receipt(p: VendorPayment) -> dict:
    """FR-EVT-003: the bank's confirmation of one payment with its evidence."""
    payee = p.vendor.payee
    return {"payment_id": str(p.pk), "vendor": p.vendor.name, "paid_to": payee.legal_name if payee else "",
            "account_last4": payee.last4 if payee else "", "amount": {"amount": f"{p.amount:.2f}",
                                                                      "currency": p.currency},
            "kind": p.kind, "paid_at": p.paid_at.isoformat() if p.paid_at else None,
            "bank_reference": p.bank_reference, "instruction_id": str(p.release_instruction_id or ""),
            "evidence_ids": [str(x) for x in [p.quote_evidence_id, p.invoice_evidence_id,
                                              *p.delivery_evidence_ids] if x],
            "note": "Paid by the partner bank from the event escrow, never by Tenmina and never in cash."}


def receipts(e: Event) -> list[dict]:
    return [receipt(p) for p in e.payments.filter(status="paid").select_related("vendor", "vendor__payee")
            .order_by("paid_at")]
