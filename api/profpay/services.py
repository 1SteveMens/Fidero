"""PRO Professional payments: the public interface other modules may call
(document 02: 5.11, 6.14; ADR-23; FR-PRO-001 to FR-PRO-010; RUL-26, RUL-27).

Tenmina pays the professionals it contracts from its own operating account,
never from client money. Nothing here reads or writes an escrow, held-funds,
release-instruction, bank-event or statement table. A professional's pay
never depends on the verdict or outcome of their work (RUL-26).

Interface
---------
    create_agreement(by, *, country, professional, role, agreement_evidence, ...) -> Agreement
    activate_agreement / suspend_agreement / reinstate_agreement / end_agreement
    assignment_blockers(person, role_code, country) -> [reasons]    for CASE, BLD, CARE, TSK before assigning work
    draft_rate_card(by, *, country, role, unit, rate, valid_from, ...) -> RateCard   (pro_rate_card_change)
    decide_rate_card(card, approver, *, decision, mfa_at)
    record_work_accepted(payload, *, event_id) -> Payable | None    `work.accepted` from RPT, BLD, PMG, TSK, CARE
    close_runner_month(agreement, month, by) -> RunnerMonth          publishes `runner_month.closed`
    hold_payable / release_hold / cancel_payable                     fraud or misconduct review only (RUL-26)
    submit_claim / decide_claim / decide_exception / cancel_claim    expenses (FR-PRO-004)
    prepare_run / submit_run / decide_run / remove_line / withdraw_run / download_file / mark_uploaded
    import_confirmation / resolve_line / check_bank_letter           reconciliation (FR-PRO-009)
    generate_statements(country, tax_year) -> [Document]             FR-PRO-007
    check_overdue(today=None) -> int                                 FR-PRO-008, daily
    cost_per_case(country=None) -> list[dict]                        FR-PRO-010

Events published: payable.created, payable.overdue, payment_run.approved, payment_run.file_issued,
payment_line.confirmed, payment_line.failed, runner_month.closed (plus <entity>.status_changed).
Events consumed: work.accepted, runner_month.closed, payee.verified, payee.suspended,
bank_account.verified, bank_account.status_changed, approval.approved, approval.rejected.
"""
import calendar
import logging
import uuid
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max, Q, Sum
from django.utils import timezone

from administration import flags
from audit.services import record
from core import approvals, state
from core.errors import (DomainError, Forbidden, Invalid, NotFound, PayeeNotVerified, RuleBlocked, SameApprover,
                         StateConflict)
from core.events import publish
from core.money import q
from core.permissions import has_role

from . import adapters
from .models import (CODE_FOR_ROLE, EXPENSE_KINDS, RESULT_WORDS, REVIEW_HOLDS, ROLE_FROM_CODE, ROLES,
                     UNIT_FOR_WORK, UNITS, WORK_KINDS, Agreement, Document, ExpenseClaim, Payable, PaymentLine,
                     PaymentRun, RateCard, RunnerMonth, Scope)

log = logging.getLogger(__name__)
ZERO = Decimal("0.00")
STAFF = ("CM", "RV")
ADMIN = ("AD",)
PAUSE_FLAG = "pro.payment_runs_paused"
# Keys a work.accepted payload must never carry (RUL-26, TC-RUL-26-05). They are ignored if present.
RESULT_KEYS = {"verdict", "overall_verdict", "outcome", "result", "passed", "failed", "pass", "fail", "risk",
               "risk_flag", "findings", "defects", "inspection_result", "status"}
WORK_ALIASES = {"property_inspection": "inspection", "boq": "bill_of_quantities", "bill_of_quantity":
                "bill_of_quantities", "errand_document": "errand", "visit": "care_visit", "month": "runner_month"}
RUN_OPEN = ("draft", "pending_approval", "approved", "file_issued")


# =========================================================================== helpers

def _now():
    return timezone.now()


def _cfg(country, key, default=None):
    from countries.selectors import config

    try:
        value = config(country, key, None)
    except Exception:  # noqa: BLE001
        value = None
    return default if value is None else value


def _audit(actor, action, obj, data=None, country=None):
    record(actor=actor, action=action, entity=obj.__class__.__name__.lower(), entity_id=obj.pk, data=data or {},
           country=country if country is not None else getattr(obj, "country", None))


def _notify(person, template, body, *, subject="", obj=None, link="", needs_action=False, category="money"):
    from notifications.services import notify

    if person is None:
        return
    try:
        notify(person, template, body=body, subject=subject, subject_obj=obj, link=link, needs_action=needs_action,
               category=category)
    except Exception:  # noqa: BLE001 - a notification never stops a pay step
        log.exception("notification %s failed", template)


def staff_in(country, *roles):
    from accounts.models import Person

    return Person.objects.filter(
        Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
        role_grants__role__in=roles, role_grants__revoked_at__isnull=True, is_active=True).distinct()


def _alert(country, roles, template, body, *, obj=None, link=""):
    for p in staff_in(country, *roles):
        _notify(p, template, body, obj=obj, link=link, needs_action=True, category="task")


def is_staff(user, country, *roles) -> bool:
    return has_role(user, *(roles or STAFF), country=country)


def _require_staff(by, country, *roles, msg="Only Tenmina staff do this."):
    if not is_staff(by, country, *(roles or STAFF)):
        raise Forbidden(msg)


def is_admin(user, country=None) -> bool:
    return has_role(user, *ADMIN, country=country)


def has_payment_rights(user, country) -> bool:
    """PY in the run's country; nobody who holds a contracted professional role (01 C2)."""
    from core.permissions import PROFESSIONAL_ROLES

    return has_role(user, "PY", country=country) and not has_role(user, *PROFESSIONAL_ROLES)


def _mentions_result(text: str) -> bool:
    t = (text or "").lower()
    return any(w in t for w in RESULT_WORDS)


def _guard():
    flags.read_only_guard()


def _not_paused(country):
    if flags.enabled(PAUSE_FLAG, country):
        raise DomainError("Payment runs are paused. Nothing can be prepared, approved or issued until the founder "
                          "switches them back on.", code="payment-runs-paused", status=409,
                          blocking_reasons=[{"rule": "06-2.6", "message": f"{PAUSE_FLAG} is on"}])


def _current_config(country):
    from countries.selectors import current_config

    cfg = current_config(country)
    if cfg is None:
        raise StateConflict("The country has no published configuration.", code="config-missing")
    return cfg


def _dec(value, default="0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except Exception:  # noqa: BLE001
        return Decimal(default)


def _utc_date(dt) -> date:
    return dt.astimezone(dt_tz.utc).date()


def _local_date(country, dt=None) -> date:
    import zoneinfo

    dt = dt or _now()
    try:
        return dt.astimezone(zoneinfo.ZoneInfo(country.timezone or "UTC")).date()
    except Exception:  # noqa: BLE001
        return dt.date()


def _reference(prefix, country, model):
    year = _now().year
    base = f"{prefix}-{country.code}-{year}-"
    n = model.objects.filter(reference__startswith=base).count() + 1
    while model.objects.filter(reference=f"{base}{n:04d}").exists():
        n += 1
    return f"{base}{n:04d}"


def _store(country, by, data: bytes, *, name, content_type, owner_type="", owner_id=None):
    from evidence.services import store

    return store(data=data, country=country, uploaded_by=by, content_type=content_type, original_name=name,
                 source="generated", data_class="payables", owner_type=owner_type, owner_id=owner_id,
                 description=name)


def _link(ev, subject_type, subject_id, role, by=None):
    from evidence.services import link

    link(ev, subject_type, subject_id, role=role, by=by)


def _atomic_after_checks(fn):
    """Like transaction.atomic, but a refusal raised before any write keeps its audit entry: the refusal is
    recorded, then the error is raised outside the savepoint (TC-RUL-26-04: the attempt is audited)."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        refused = []
        try:
            with transaction.atomic():
                return fn(*args, _refused=refused, **kwargs)
        except DomainError:
            for actor, action, obj, data in refused:
                _audit(actor, action, obj, data)
            raise
    return wrapper


def _refuse(refused, actor, action, obj, data=None):
    refused.append((actor, action, obj, data or {}))


# =========================================================================== configuration (FR-PRO-004, 007, 008)

def withholding_rate(country, agreement) -> Decimal:
    """FR-PRO-007, Q-25: from the published configuration. `pro.withholding_rates` by tax status if set,
    else the country's `withholding_tax_rate`; an exempt professional pays none unless configured."""
    rates = _cfg(country, "pro.withholding_rates", None)
    if isinstance(rates, dict) and agreement.tax_status in rates:
        return _dec(rates[agreement.tax_status])
    if agreement.tax_status == "exempt":
        return ZERO
    return _dec(_cfg(country, "withholding_tax_rate", "0"))


def other_deductions(country) -> list[dict]:
    """`pro.other_deductions`: [{"code", "name", "rate"}] applied to fees, never to reimbursed expenses."""
    out = []
    for d in _cfg(country, "pro.other_deductions", []) or []:
        if isinstance(d, dict) and d.get("rate") not in (None, ""):
            out.append({"code": d.get("code", ""), "name": d.get("name", d.get("code", "")),
                        "rate": _dec(d["rate"])})
    return out


def other_deductions_rate(country) -> Decimal:
    return sum((d["rate"] for d in other_deductions(country)), ZERO)


def payment_period_days(country) -> int:
    return int(_cfg(country, "pro.payment_period_working_days", 10) or 10)


def expense_limit(country, role, kind) -> Decimal:
    """`pro.expense_limits.<role>.<kind>`, else `pro.expense_limits.default.<kind>`. With no limit set,
    every claim needs a second approval."""
    limits = _cfg(country, "pro.expense_limits", {}) or {}
    for key in (role, "default"):
        v = (limits.get(key) or {}).get(kind) if isinstance(limits.get(key), dict) else None
        if v not in (None, ""):
            return q(v)
    return ZERO


def due_date(country, accepted_at) -> date:
    from countries.selectors import add_working_days

    return add_working_days(country, _local_date(country, accepted_at), payment_period_days(country))


def tax_year_of(country, d: date) -> int:
    start = int(_cfg(country, "pro.tax_year_start_month", 1) or 1)
    return d.year if d.month >= start else d.year - 1


# =========================================================================== agreements (FR-PRO-001, FR-PRO-006)

def destination(agreement):
    """The verified account the agreement pays: an esc_payee or an acc_bank_account."""
    return agreement.payee or agreement.bank_account


def destination_reasons(agreement) -> list[dict]:
    """Why the agreement's destination cannot be paid (FR-PRO-006, RUL-22). Empty when it can."""
    out = []
    p, b = agreement.payee, agreement.bank_account
    if p is None and b is None:
        return [{"rule": "FR-PRO-006", "code": "no-payee", "message": "No verified payee account is on file."}]
    if p is not None:
        p.refresh_from_db()
        if p.kind != "contracted_professional":
            out.append({"rule": "RUL-27", "code": "payee-kind",
                        "message": "The payee is not registered as a contracted professional's account. A run pays "
                                   "only professionals Tenmina contracts, and such an account is never paid from "
                                   "client money."})
        if p.verification_status != "verified":
            out.append({"rule": "FR-PRO-006", "code": "payee-not-verified",
                        "message": f"The payee account ending {p.last4} is {p.verification_status}, not verified."})
        if p.name_match != "matched":
            out.append({"rule": "FR-ESC-015", "code": "name-mismatch",
                        "message": "The bank's account name does not match the payee's name."})
        own = (agreement.contracting_party == "person" and (p.person_id == agreement.professional_id or (
            p.subject_type == "person" and str(p.subject_id) == str(agreement.professional_id)))) or (
            agreement.contracting_party == "organisation" and (p.organisation_id == agreement.organisation_id or (
                p.subject_type == "organisation" and str(p.subject_id) == str(agreement.organisation_id))))
        if not own:
            out.append({"rule": "FR-PRO-006", "code": "not-own-account",
                        "message": "The account is not in the professional's own name or their firm's."})
    if b is not None:
        b.refresh_from_db()
        if b.verification_status != "verified":
            out.append({"rule": "FR-PRO-006", "code": "payee-not-verified",
                        "message": f"The account ending {b.last4} is {b.verification_status}, not verified."})
        if b.name_match != "matched":
            out.append({"rule": "FR-ESC-015", "code": "name-mismatch",
                        "message": "The account name does not match the professional's name."})
        if b.holder_id != agreement.professional_id or agreement.contracting_party != "person":
            out.append({"rule": "FR-PRO-006", "code": "not-own-account",
                        "message": "The account is not in the professional's own name."})
    return out


def _check_professional(professional, role):
    code = CODE_FOR_ROLE[role]
    if not professional.has_tenmina_role(code):
        raise Invalid(f"This person does not hold the {role.replace('_', ' ')} role.", code="validation-error")
    from core.permissions import STAFF_ROLES

    if professional.has_tenmina_role(*STAFF_ROLES, "PY", "RR"):
        raise Invalid("Tenmina staff are not contracted professionals.", code="validation-error")


@transaction.atomic
def create_agreement(by, *, country, professional, role, agreement_evidence, contracting_party="person",
                     organisation=None, tax_status="not_registered", tax_id="", payee=None, bank_account=None,
                     valid_from=None, valid_to=None) -> Agreement:
    """FR-PRO-001: a signed agreement. It starts as a draft and pays nothing until activated."""
    _guard()
    if not (is_admin(by, country) or is_staff(by, country, "CM")):
        raise Forbidden("Only an administrator or case manager records agreements.")
    if role not in ROLES:
        raise Invalid(f"Role must be one of {', '.join(ROLES)}.", code="validation-error")
    _check_professional(professional, role)
    if agreement_evidence is None:
        raise Invalid("Attach the signed agreement.", code="validation-error")
    if contracting_party == "organisation" and organisation is None:
        raise Invalid("Name the firm that signs the agreement.", code="validation-error")
    if payee is not None and bank_account is not None:
        raise Invalid("Choose one payee account.", code="validation-error")
    a = Agreement.objects.create(
        country=country, reference=_reference("PRO", country, Agreement), professional=professional, role=role,
        contracting_party=contracting_party, organisation=organisation if contracting_party == "organisation"
        else None, agreement_evidence=agreement_evidence, tax_status=tax_status, tax_id=tax_id or "", payee=payee,
        bank_account=bank_account, valid_from=valid_from or timezone.localdate(), valid_to=valid_to,
        monthly_fee_currency=country.currency, created_by=by)
    _link(agreement_evidence, "pro_agreement", a.pk, "signed_agreement", by)
    _audit(by, "pro_agreement.created", a, {"role": role, "professional_id": str(professional.pk)})
    return a


@transaction.atomic
def update_agreement(a: Agreement, by, data: dict) -> Agreement:
    _guard()
    if not (is_admin(by, a.country) or is_staff(by, a.country, "CM")):
        raise Forbidden("Only an administrator or case manager changes agreements.")
    if a.status == "ended":
        raise StateConflict("This agreement has ended.")
    changed = []
    for f in ("tax_status", "tax_id", "valid_to", "payee", "bank_account"):
        if f in data:
            setattr(a, f, data[f])
            changed.append(f)
    if a.status == "draft":
        for f in ("valid_from", "contracting_party", "organisation"):
            if f in data:
                setattr(a, f, data[f])
                changed.append(f)
    if "payee" in data and data["payee"] is not None:
        a.bank_account = None
        changed.append("bank_account")
    elif "bank_account" in data and data["bank_account"] is not None:
        a.payee = None
        changed.append("payee")
    if a.status == "active" and ({"payee", "bank_account"} & set(changed)):
        reasons = destination_reasons(a)
        if reasons:
            raise PayeeNotVerified("The new account is not a verified account in the professional's own name.",
                                   blocking_reasons=reasons)
    a.save(update_fields=list(set(changed)) or None)
    _audit(by, "pro_agreement.updated", a, {"fields": sorted(set(changed))})
    if {"payee", "bank_account"} & set(changed):
        _release_holds(a, "payee_not_verified", by)
    return a


@transaction.atomic
def activate_agreement(a: Agreement, by) -> Agreement:
    _guard()
    if not (is_admin(by, a.country) or is_staff(by, a.country, "CM")):
        raise Forbidden("Only an administrator or case manager activates agreements.")
    reasons = destination_reasons(a)
    if reasons:
        raise PayeeNotVerified("The agreement needs a verified account in the professional's own name first.",
                               blocking_reasons=reasons)
    if Agreement.objects.filter(country=a.country, professional=a.professional, role=a.role,
                                status="active").exclude(pk=a.pk).exists():
        raise StateConflict("This professional already has an active agreement for this role.")
    return state.transition(a, "pro_agreement", "active", actor=by)


@_atomic_after_checks
def suspend_agreement(a: Agreement, by, reason: str, _refused=None) -> Agreement:
    if not (is_admin(by, a.country) or is_staff(by, a.country, "RV")):
        raise Forbidden("Only an administrator or reviewer suspends an agreement.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if _mentions_result(reason):
        _refuse(_refused, by, "pro_agreement.suspend_refused", a, {"reason": reason})
        raise RuleBlocked("An agreement is never suspended because of a verdict or outcome.",
                          code="pay-independent-of-result",
                          blocking_reasons=[{"rule": "RUL-26", "message": "The reason names a result of the work."}])
    a.status_reason = reason.strip()
    state.transition(a, "pro_agreement", "suspended", actor=by, reason=reason, extra_fields=["status_reason"])
    for p in a.payables.filter(status="approved"):
        _hold(p, "agreement_suspended", None, f"Agreement suspended: {reason}")
    return a


@transaction.atomic
def reinstate_agreement(a: Agreement, by) -> Agreement:
    if not (is_admin(by, a.country) or is_staff(by, a.country, "RV")):
        raise Forbidden("Only an administrator or reviewer reinstates an agreement.")
    reasons = destination_reasons(a)
    if reasons:
        raise PayeeNotVerified("The agreement needs a verified account first.", blocking_reasons=reasons)
    a.status_reason = ""
    state.transition(a, "pro_agreement", "active", actor=by, extra_fields=["status_reason"])
    _release_holds(a, "agreement_suspended", by)
    return a


@transaction.atomic
def end_agreement(a: Agreement, by, *, reason: str, valid_to=None) -> Agreement:
    if not is_admin(by, a.country):
        raise Forbidden("Only an administrator ends an agreement.")
    a.valid_to = valid_to or timezone.localdate()
    if a.valid_to < a.valid_from:
        a.valid_to = a.valid_from
    a.status_reason = reason or ""
    return state.transition(a, "pro_agreement", "ended", actor=by, reason=reason,
                            extra_fields=["valid_to", "status_reason"])


def active_agreement(person, role, country):
    return Agreement.objects.filter(professional=person, role=role, country=country, status="active").first()


def agreement_for_code(person, role_code, country, statuses=("active",)):
    roles = [r for r, c in CODE_FOR_ROLE.items() if c == role_code] or [ROLE_FROM_CODE.get(role_code, "")]
    return Agreement.objects.filter(professional=person, role__in=roles, country=country,
                                    status__in=statuses).order_by("-created_at").first()


def assignment_blockers(person, role_code, country) -> list[dict]:
    """US-PRO-001 AC1: work is assigned only to a professional with a signed, active agreement and a
    verified payee account. CASE, BLD, CARE and TSK call this before assigning."""
    if role_code not in CODE_FOR_ROLE.values():
        return []
    a = agreement_for_code(person, role_code, country, statuses=("active", "suspended"))
    if a is None:
        return [{"rule": "FR-PRO-001", "code": "no-agreement",
                 "message": f"{person.full_name} has no signed agreement with Tenmina for this role."}]
    if a.status == "suspended":
        return [{"rule": "FR-PRO-001", "code": "agreement-suspended",
                 "message": f"{person.full_name}'s agreement is suspended: {a.status_reason}"}]
    return destination_reasons(a)


# =========================================================================== rate cards (FR-PRO-001, FR-PRO-003)

def _scope(key) -> Scope:
    s = Scope.objects.filter(key=key or "standard").first()
    if s is None:
        raise Invalid("Choose a scope from the fixed list. A rate may vary only by what is known when the work "
                      "is assigned (RUL-26).", code="validation-error")
    return s


def _card_key(country, role, agreement, unit, scope_key):
    return RateCard.objects.filter(country=country, role=role, agreement=agreement, unit=unit, scope_key=scope_key)


@transaction.atomic
def draft_rate_card(by, *, country, role, unit, rate, valid_from, scope_key="standard", agreement=None,
                    currency=None) -> RateCard:
    """FR-PRO-001, FR-PRO-003: one flat rate per unit and scope. The drafter can never approve it."""
    _guard()
    if not is_admin(by, country):
        raise Forbidden("Only an administrator drafts rate cards.")
    if role not in ROLES:
        raise Invalid(f"Role must be one of {', '.join(ROLES)}.", code="validation-error")
    if unit not in UNITS:
        raise Invalid(f"Unit must be one of {', '.join(UNITS)}.", code="validation-error")
    scope = _scope(scope_key)
    rate = q(rate)
    if rate <= 0:
        raise Invalid("The rate must be more than zero.", code="validation-error")
    currency = (currency or country.currency).upper()
    if currency != country.currency:
        raise Invalid(f"Professionals in {country.name} are paid in {country.currency}.", code="validation-error")
    if valid_from < timezone.localdate():
        raise Invalid("A new rate starts today or later. Work already assigned keeps its rate.",
                      code="validation-error")
    if agreement is not None and (agreement.role != role or agreement.country_id != country.pk):
        raise Invalid("The agreement is for another role or country.", code="validation-error")
    key = _card_key(country, role, agreement, unit, scope)
    last = key.filter(state="approved").order_by("-valid_from").first()
    if last and valid_from <= last.valid_from:
        raise Invalid("A new version must start after the current one.", code="validation-error")
    if key.filter(state="draft").exists():
        raise StateConflict("A draft version of this rate is already waiting for approval.")
    version = (key.aggregate(m=Max("version"))["m"] or 0) + 1
    card = RateCard.objects.create(country=country, role=role, agreement=agreement, unit=unit, scope_key=scope,
                                   rate=rate, currency=currency, version=version, valid_from=valid_from,
                                   created_by=by)
    card.approval_request = approvals.request_approval(
        "pro_rate_card_change", card.pk, by, required=1, country=country,
        summary=f"{country.code} {role} rate per {unit} ({scope.key}) v{version}: {currency} {rate} from {valid_from}")
    card.save(update_fields=["approval_request"])
    _audit(by, "pro_rate_card.drafted", card, {"role": role, "unit": unit, "scope": scope.key, "rate": rate,
                                               "version": version, "valid_from": valid_from})
    _alert(country, ADMIN, "pro_rate_card_review",
           f"A {role.replace('_', ' ')} rate per {unit.replace('_', ' ')} needs a second administrator.", obj=card,
           link=f"/admin/pro/rate-cards/{card.pk}")
    return card


@_atomic_after_checks
def update_rate_card(card: RateCard, by, *, rate=None, valid_from=None, _refused=None) -> RateCard:
    """Only a draft changes. An approved card never does: a change is a new version (US-PRO-001 AC3)."""
    if card.state != "draft":
        _refuse(_refused, by, "pro_rate_card.edit_refused", card, {"state": card.state})
        raise StateConflict("An approved rate card never changes. Draft a new version instead.",
                            code="rate-card-immutable")
    if not is_admin(by, card.country):
        raise Forbidden("Only an administrator changes rate cards.")
    if rate is not None:
        rate = q(rate)
        if rate <= 0:
            raise Invalid("The rate must be more than zero.", code="validation-error")
        card.rate = rate
    if valid_from is not None:
        if valid_from < timezone.localdate():
            raise Invalid("A new rate starts today or later.", code="validation-error")
        card.valid_from = valid_from
    card.save(update_fields=["rate", "valid_from"])
    if card.approval_request_id and card.approval_request.status == "open":
        # The text the approver sees changed: the second administrator approves the new figures.
        approvals.withdraw(card.approval_request, by)
        card.approval_request = approvals.request_approval(
            "pro_rate_card_change", card.pk, by, required=1, country=card.country,
            summary=f"{card.role} per {card.unit}: {card.currency} {card.rate} from {card.valid_from} (changed)")
        card.save(update_fields=["approval_request"])
    _audit(by, "pro_rate_card.updated", card, {"rate": card.rate, "valid_from": card.valid_from})
    return card


def rate_card_allowed(card):
    return lambda a: is_admin(a, card.country) and a.pk != card.created_by_id


def decide_rate_card(card: RateCard, approver, *, decision="approve", mfa_at=None, note=""):
    if card.state != "draft" or card.approval_request is None or card.approval_request.status != "open":
        raise StateConflict("This rate card is not waiting for approval.")
    if approver.pk == card.created_by_id:
        raise SameApprover("The administrator who drafted the rate card cannot approve it.")
    return approvals.decide(card.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=rate_card_allowed(card))


@transaction.atomic
def apply_rate_card(card: RateCard, approved: bool):
    card = RateCard.objects.select_for_update().get(pk=card.pk)
    if card.state != "draft":
        return card
    req = card.approval_request
    if not approved:
        state.transition(card, "pro_rate_card", "retired", reason="Second administrator rejected the version")
        return card
    approval = req.approvals.filter(decision="approve").order_by("-approved_at").first()
    prev = _card_key(card.country, card.role, card.agreement, card.unit, card.scope_key).filter(
        state="approved", valid_from__lt=card.valid_from).filter(
        Q(valid_to__isnull=True) | Q(valid_to__gte=card.valid_from)).first()
    if prev is not None:
        prev.valid_to = card.valid_from - timedelta(days=1)
        prev.save(update_fields=["valid_to"])
    card.approved_by_id = approval.approver_id if approval else None
    card.approved_at = _now()
    state.transition(card, "pro_rate_card", "approved", actor=approval.approver if approval else None,
                     event="pro_rate_card.approved",
                     payload={"rate_card_id": card.pk, "country": card.country.code, "role": card.role,
                              "unit": card.unit, "version": card.version, "valid_from": card.valid_from},
                     extra_fields=["approved_by", "approved_at"])
    return card


@transaction.atomic
def retire_rate_card(card: RateCard, by) -> RateCard:
    if not is_admin(by, card.country):
        raise Forbidden("Only an administrator retires rate cards.")
    if card.state == "draft" and card.approval_request and card.approval_request.status == "open":
        approvals.withdraw(card.approval_request, by)
    if card.state == "approved" and card.valid_to is None:
        card.valid_to = max(timezone.localdate(), card.valid_from)
        card.save(update_fields=["valid_to"])
    return state.transition(card, "pro_rate_card", "retired", actor=by, extra_fields=[])


def card_in_force(agreement, unit, scope_key, at) -> RateCard | None:
    """The approved card for the agreement (or, if it has none, the country's standard card) for the role,
    unit and scope valid on the day the work was assigned (RUL-26: before any result existed)."""
    d = _utc_date(at)
    base = RateCard.objects.filter(state__in=["approved", "retired"], approved_at__isnull=False,
                                   country=agreement.country, role=agreement.role, unit=unit,
                                   valid_from__lte=d).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=d))
    for scope in dict.fromkeys([scope_key or "standard", "standard"]):
        own = base.filter(agreement=agreement, scope_key_id=scope).order_by("-version").first()
        if own:
            return own
        std = base.filter(agreement__isnull=True, scope_key_id=scope).order_by("-version").first()
        if std:
            return std
    return None


def current_cards(agreement) -> list[RateCard]:
    today = timezone.localdate()
    cards = RateCard.objects.filter(country=agreement.country, role=agreement.role, state="approved",
                                    valid_from__lte=today).filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
    own = list(cards.filter(agreement=agreement))
    keys = {(c.unit, c.scope_key_id) for c in own}
    return own + [c for c in cards.filter(agreement__isnull=True) if (c.unit, c.scope_key_id) not in keys]


# =========================================================================== payables (FR-PRO-002, 003, 007, 010)

def _uuid(v):
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


def _dt(v, default=None):
    if isinstance(v, datetime):
        return v
    if not v:
        return default
    try:
        d = datetime.fromisoformat(str(v))
    except ValueError:
        return default
    if timezone.is_naive(d):
        d = timezone.make_aware(d, dt_tz.utc)
    return d


def _scope_for(payload, case):
    key = payload.get("scope_key")
    if key and Scope.objects.filter(key=key).exists():
        return key
    order = getattr(case, "order", None) if case is not None else None
    if order is not None and getattr(order, "tier", ""):
        key = f"tier_{order.tier}"
        if Scope.objects.filter(key=key).exists():
            return key
    return "standard"


ITEM_TYPE = {"lawyer": "lawyer", "surveyor": "surveyor", "runner": "runner", "inspector": "inspector",
             "quantity_surveyor": "other", "carer": "other", "errand_agent": "other"}


def _case_cost(case, *, item_type, amount, currency, source, source_id, description, on):
    if case is None:
        return
    from cases.services import add_cost

    try:
        add_cost(case, item_type=item_type, amount=amount, currency=currency, incurred_on=on,
                 description=description, source=source, source_id=source_id)
    except DomainError as exc:
        log.warning("case cost for %s not recorded: %s", source_id, exc.detail)


def _create_payable(agreement, *, work_kind, work_ref, work_period=None, event_id, case=None, subject_type="",
                    subject_id=None, assigned_at, accepted_at, quantity=Decimal("1"), scope_key="standard",
                    actor=None) -> Payable | None:
    existing = Payable.objects.filter(work_kind=work_kind, work_ref=work_ref, work_period=work_period).first()
    if existing:
        return existing
    country = agreement.country
    unit = UNIT_FOR_WORK[work_kind]
    card = card_in_force(agreement, unit, scope_key, assigned_at)
    if card is None:
        _alert(country, ("CM", "AD"), "pro_no_rate_card",
               f"Accepted {work_kind.replace('_', ' ')} for {agreement.professional.full_name} has no approved rate "
               f"in force on {_utc_date(assigned_at)}. Approve a rate card, then record the payable.",
               obj=agreement)
        record(actor=actor, action="pro_payable.no_rate_card", entity="pro_agreement", entity_id=agreement.pk,
               data={"work_kind": work_kind, "work_ref": str(work_ref), "assigned_at": assigned_at.isoformat()},
               country=country)
        return None
    cfg = _current_config(country)
    accepted_at = max(accepted_at, assigned_at)
    status, hold = "approved", None
    if agreement.status == "suspended":
        status, hold = "held", "agreement_suspended"
    elif destination_reasons(agreement):
        status, hold = "held", "payee_not_verified"
    try:
        with transaction.atomic():
            p = Payable.objects.create(
                country=country, agreement=agreement, work_kind=work_kind, work_ref=work_ref, work_period=work_period,
                source_event_id=event_id, case=case, subject_type=subject_type or "", subject_id=subject_id,
                assigned_at=assigned_at, accepted_at=accepted_at, rate_card=card, unit_rate=card.rate,
                quantity=q(quantity) if work_kind != "runner_month" else Decimal(quantity).quantize(Decimal("0.0001")),
                currency=card.currency, country_config=cfg, withholding_rate=withholding_rate(country, agreement),
                other_deductions_rate=other_deductions_rate(country), due_by=due_date(country, accepted_at),
                status=status, hold_reason=hold)
    except IntegrityError:
        return Payable.objects.filter(work_kind=work_kind, work_ref=work_ref, work_period=work_period).first()
    p.refresh_from_db()
    _audit(actor, "pro_payable.created", p, {"work_kind": work_kind, "work_ref": str(work_ref), "gross": p.gross,
                                             "rate_card_id": str(card.pk), "config_version": cfg.version})
    publish("payable.created", p.pk, {"payable_id": p.pk, "agreement_id": agreement.pk,
                                      "professional_id": agreement.professional_id, "work_kind": work_kind,
                                      "work_ref": work_ref, "case_id": p.case_id, "gross": p.gross,
                                      "currency": p.currency, "due_by": p.due_by, "country": country.code})
    _case_cost(case, item_type=ITEM_TYPE.get(agreement.role, "other"), amount=p.gross, currency=p.currency,
               source="pro_payable", source_id=p.pk, on=_local_date(country, accepted_at),
               description=f"{agreement.role.replace('_', ' ').capitalize()}: {work_kind.replace('_', ' ')}")
    _notify(agreement.professional, "pro_payable_created",
            f"Accepted work is now payable: {p.currency} {p.gross:,.2f} before tax, due by {p.due_by:%d %B %Y}.",
            subject="New payable in My pay", obj=p, link=f"/me/pay/payables/{p.pk}")
    return p


def _role_of(payload) -> str | None:
    role = payload.get("role") or ""
    if role in ROLES:
        return role
    return ROLE_FROM_CODE.get(role)


@transaction.atomic
def record_work_accepted(payload: dict, *, event_id) -> Payable | None:
    """FR-PRO-002: a payable only for accepted work. The payload carries the work item, the professional,
    the unit and the dates; a verdict or outcome field is ignored and recorded as a contract breach
    (RUL-26, TC-RUL-26-05)."""
    from accounts.models import Person
    from cases.models import Case
    from countries.models import Country

    leaked = sorted(k for k in payload if k in RESULT_KEYS)
    if leaked:
        record(action="work_accepted.result_field_ignored", entity="event", entity_id=event_id,
               data={"keys": leaked, "work_ref": str(payload.get("work_ref"))})
    kind = payload.get("work_kind") or payload.get("work_type") or ""
    kind = WORK_ALIASES.get(kind, kind)
    if kind not in WORK_KINDS or kind == "runner_month":
        return None
    person = Person.objects.filter(pk=_uuid(payload.get("person_id"))).first()
    work_ref = _uuid(payload.get("work_ref")) or _uuid(payload.get("subject_id"))
    if person is None or work_ref is None:
        return None
    case = Case.objects.filter(pk=_uuid(payload.get("case_id"))).select_related("country", "order").first()
    country = case.country if case else Country.objects.filter(code=str(payload.get("country") or "").upper()).first()
    if country is None:
        return None
    role = _role_of(payload)
    if role is None:
        return None
    if role == "errand_agent" and kind == "care_visit":
        role = "carer"
    agreement = Agreement.objects.filter(professional=person, country=country, role=role,
                                         status__in=["active", "suspended"]).order_by("-created_at").first()
    if agreement is None:
        if role == "errand_agent":
            agreement = Agreement.objects.filter(professional=person, country=country, role="carer",
                                                 status__in=["active", "suspended"]).first()
    if agreement is None:
        _alert(country, ("CM",), "pro_work_without_agreement",
               f"{person.full_name} finished accepted work ({kind.replace('_', ' ')}) but has no agreement. "
               "Record the agreement so the work can be paid.")
        record(action="pro_payable.no_agreement", entity="person", entity_id=person.pk, country=country,
               data={"work_kind": kind, "work_ref": str(work_ref)})
        return None
    if kind == "report_section" and case is not None and Payable.objects.filter(
            agreement=agreement, case=case, work_kind="report_section").exists():
        # TC-RUL-26-06: a corrected report version is the same work; it creates no second payable.
        return Payable.objects.filter(agreement=agreement, case=case, work_kind="report_section").first()
    accepted_at = _dt(payload.get("accepted_at"), _now())
    assigned_at = _dt(payload.get("assigned_at"), accepted_at)
    p = _create_payable(agreement, work_kind=kind, work_ref=work_ref, event_id=event_id, case=case,
                        subject_type=payload.get("subject_type", "") if not case else "",
                        subject_id=_uuid(payload.get("subject_id")) if not case else None,
                        assigned_at=assigned_at, accepted_at=accepted_at,
                        quantity=_dec(payload.get("quantity"), "1") or Decimal("1"),
                        scope_key=_scope_for(payload, case))
    if kind == "report_section" and case is not None:
        _site_visit_payables(case, event_id=event_id, accepted_at=accepted_at)
    return p


def _site_visit_payables(case, *, event_id, accepted_at):
    """02 6.14: where an agreement pays per site visit, one payable for each completed visit task of the case
    when the report's work is accepted."""
    from cases.models import Task

    for t in Task.objects.filter(case=case, site_visit=True, status="done").exclude(assignee__isnull=True):
        a = agreement_for_code(t.assignee, t.owner_role, case.country, statuses=("active", "suspended"))
        if a is None or card_in_force(a, "site_visit", "standard", t.assigned_at or t.created_at) is None:
            continue
        _create_payable(a, work_kind="site_visit", work_ref=t.pk, event_id=event_id, case=case,
                        assigned_at=t.assigned_at or t.created_at, accepted_at=max(accepted_at,
                                                                                  t.assigned_at or t.created_at))


def _month_start(d: date) -> date:
    return d.replace(day=1)


@transaction.atomic
def close_runner_month(agreement: Agreement, month: date, by) -> RunnerMonth:
    """FR-PRO-002 AC4: a case manager closes a runner's month on or after its last working day. A part month
    is paid by calendar days at the monthly fee (assumption, I-34). A second close is refused."""
    from countries.selectors import add_working_days, is_working_day

    _guard()
    _require_staff(by, agreement.country, "CM", msg="Only a case manager closes a runner's month.")
    if agreement.role != "runner":
        raise Invalid("Only a runner's agreement has a monthly fee.", code="validation-error")
    if agreement.status not in ("active", "suspended", "ended"):
        raise StateConflict("This agreement is not in force.")
    month = _month_start(month)
    days_in = calendar.monthrange(month.year, month.month)[1]
    last = month.replace(day=days_in)
    last_working = last if is_working_day(agreement.country, last) else add_working_days(agreement.country, last, -1)
    if timezone.localdate() < last_working:
        raise StateConflict(f"This month closes on its last working day, {last_working:%d %B %Y}.",
                            code="month-not-ended")
    if RunnerMonth.objects.filter(agreement=agreement, month=month).exists():
        raise StateConflict("This month is already closed. It is paid once.", code="month-already-closed")
    start = max(month, agreement.valid_from)
    end = min(last, agreement.valid_to or last)
    if end < start:
        raise Invalid("The agreement was not in force in this month.", code="validation-error")
    days = (end - start).days + 1
    rm = RunnerMonth.objects.create(country=agreement.country, agreement=agreement, month=month, days_worked=days,
                                    days_in_month=days_in, closed_by=by)
    _audit(by, "pro_runner_month.closed", rm, {"month": month, "days": days})
    publish("runner_month.closed", rm.pk, {
        "runner_month_id": rm.pk, "agreement_id": agreement.pk, "person_id": agreement.professional_id,
        "role": "runner", "month": month, "period_start": start, "period_end": end, "days_worked": days,
        "days_in_month": days_in, "closed_at": rm.closed_at, "country": agreement.country.code})
    return rm


@transaction.atomic
def record_runner_month(payload: dict, *, event_id) -> Payable | None:
    """runner_month.closed -> one payable for the month at the monthly card in force at its start."""
    rm = RunnerMonth.objects.filter(pk=_uuid(payload.get("runner_month_id"))).select_related("agreement").first()
    if rm is None:
        return None
    a = rm.agreement
    start = date.fromisoformat(str(payload.get("period_start"))) if payload.get("period_start") else rm.month
    assigned_at = datetime.combine(start, time(0, 0), tzinfo=dt_tz.utc)
    quantity = (Decimal(rm.days_worked) / Decimal(rm.days_in_month)).quantize(Decimal("0.0001"))
    return _create_payable(a, work_kind="runner_month", work_ref=a.pk, work_period=rm.month, event_id=event_id,
                           assigned_at=assigned_at, accepted_at=max(rm.closed_at, assigned_at), quantity=quantity)


def _hold(p: Payable, reason, by, note=""):
    p.hold_reason, p.held_by, p.hold_note = reason, by, note or ""
    state.transition(p, "pro_payable", "held", actor=by, reason=note or reason,
                     extra_fields=["hold_reason", "held_by", "hold_note"])


def _release_holds(agreement, reason, by):
    for p in agreement.payables.filter(status="held", hold_reason=reason):
        if reason == "payee_not_verified" and destination_reasons(agreement):
            continue
        p.hold_reason, p.held_by, p.hold_note = None, None, ""
        state.transition(p, "pro_payable", "approved", actor=by, reason=f"Hold lifted: {reason}",
                         extra_fields=["hold_reason", "held_by", "hold_note"])


@_atomic_after_checks
def hold_payable(p: Payable, by, *, reason: str, note: str, _refused=None) -> Payable:
    """US-PRO-003 AC3, TC-RUL-26-04: a reviewer holds pay only for a fraud or misconduct review, with the
    reason shown to the professional. Any other reason is refused and the attempt audited."""
    _require_staff(by, p.country, "RV", msg="Only a reviewer holds a payable.")
    if reason not in REVIEW_HOLDS or _mentions_result(note):
        _refuse(_refused, by, "pro_payable.hold_refused", p, {"reason": reason, "note": note})
        raise RuleBlocked("Pay is never held because of a verdict or outcome. Only a fraud or misconduct review "
                          "holds a payable.", code="pay-independent-of-result",
                          blocking_reasons=[{"rule": "RUL-26", "message": f"'{reason}' is not a review hold."}])
    if not (note or "").strip():
        raise Invalid("Say what the review is about. The professional sees this reason.", code="validation-error")
    if p.status != "approved":
        raise StateConflict(f"This payable is {p.status}; only an unpaid payable not in a run can be held.")
    _hold(p, reason, by, note.strip())
    _notify(p.agreement.professional, "pro_payable_held",
            f"A payable of {p.currency} {p.gross:,.2f} is on hold while a review is done: {note.strip()}",
            obj=p, link=f"/me/pay/payables/{p.pk}")
    return p


@transaction.atomic
def release_hold(p: Payable, by, *, note="") -> Payable:
    _require_staff(by, p.country, "RV", msg="Only a reviewer releases a hold.")
    if p.status != "held" or p.hold_reason not in REVIEW_HOLDS:
        raise StateConflict("This payable has no review hold.")
    p.hold_reason, p.held_by, p.hold_note = None, None, ""
    state.transition(p, "pro_payable", "approved", actor=by, reason=note or "Review closed",
                     extra_fields=["hold_reason", "held_by", "hold_note"])
    if destination_reasons(p.agreement):
        _hold(p, "payee_not_verified", None, "Payee account not verified")
    _notify(p.agreement.professional, "pro_payable_released", "The hold on your payable is lifted. It joins the "
            "next payment run.", obj=p, link=f"/me/pay/payables/{p.pk}")
    return p


@_atomic_after_checks
def cancel_payable(p: Payable, by, *, reason: str, _refused=None) -> Payable:
    """Cancelling needs a reviewer and a reason that is not a result of the work (RUL-26)."""
    _require_staff(by, p.country, "RV", msg="Only a reviewer cancels a payable.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    if _mentions_result(reason):
        _refuse(_refused, by, "pro_payable.cancel_refused", p, {"reason": reason})
        raise RuleBlocked("Pay is never cancelled because of a verdict or outcome.",
                          code="pay-independent-of-result",
                          blocking_reasons=[{"rule": "RUL-26", "message": "The reason names a result of the work."}])
    if p.status not in ("approved", "held"):
        raise StateConflict(f"A payable that is {p.status} cannot be cancelled here.")
    p.cancel_reason = reason.strip()
    if p.status == "held":
        p.hold_reason, p.held_by = None, None
    state.transition(p, "pro_payable", "cancelled", actor=by, reason=reason,
                     extra_fields=["cancel_reason", "hold_reason", "held_by"])
    _notify(p.agreement.professional, "pro_payable_cancelled", f"A payable was cancelled: {reason}", obj=p)
    return p


def is_overdue(p: Payable, today=None) -> bool:
    return p.status in ("approved", "held", "in_run") and p.due_by < (today or timezone.localdate())


def check_overdue(today=None) -> int:
    """FR-PRO-008 (daily): alert operations once for each payable past its due date and unpaid."""
    today = today or timezone.localdate()
    n = 0
    for p in Payable.objects.filter(status__in=["approved", "held", "in_run"], due_by__lt=today,
                                    overdue_alerted_at__isnull=True).select_related("agreement__professional",
                                                                                   "country"):
        with transaction.atomic():
            p.overdue_alerted_at = _now()
            p.save(update_fields=["overdue_alerted_at"])
            publish("payable.overdue", p.pk, {"payable_id": p.pk, "due_by": p.due_by, "status": p.status,
                                              "professional_id": p.agreement.professional_id,
                                              "country": p.country.code})
            _alert(p.country, ("CM", "RV"), "pro_payable_overdue",
                   f"Pay for {p.agreement.professional.full_name} ({p.currency} {p.gross:,.2f}) was due on "
                   f"{p.due_by:%d %B %Y} and is not paid.", obj=p, link=f"/pro/payables/{p.pk}")
        n += 1
    return n


# =========================================================================== expenses (FR-PRO-004)

def _assigned_to_case(person, case) -> bool:
    from cases.models import Task

    return Task.objects.filter(case=case).filter(Q(assignee=person) | Q(second_assignee=person)).exists()


@transaction.atomic
def submit_claim(person, *, kind, description, amount, incurred_on, receipt_evidence=None, case=None,
                 project_id=None, errand_id=None, agreement=None, currency=None) -> ExpenseClaim:
    """US-PRO-004: a claim with a receipt photo, against assigned work."""
    _guard()
    if kind not in EXPENSE_KINDS:
        raise Invalid(f"Kind must be one of {', '.join(EXPENSE_KINDS)}.", code="validation-error")
    if agreement is None:
        agreement = Agreement.objects.filter(professional=person, status="active").order_by("-created_at").first()
    if agreement is None or agreement.professional_id != person.pk:
        raise Forbidden("Only a professional with an active agreement claims expenses.")
    if agreement.status != "active":
        raise StateConflict("Your agreement is not active.")
    country = agreement.country
    amount = q(amount)
    if amount <= 0:
        raise Invalid("The amount must be more than zero.", code="validation-error")
    currency = (currency or country.currency).upper()
    if currency != country.currency:
        raise Invalid(f"Claim in {country.currency}, the currency you are paid in.", code="validation-error")
    if len([x for x in (case, project_id, errand_id) if x]) > 1:
        raise Invalid("Name one case, project or errand.", code="validation-error")
    if kind != "approved_cost" and not (case or project_id or errand_id):
        raise Invalid("Name the case, project or errand the expense was for.", code="validation-error")
    if case is not None and not _assigned_to_case(person, case):
        raise Forbidden("You can claim only for work you were assigned.")
    if incurred_on > timezone.localdate():
        raise Invalid("The date cannot be in the future.", code="validation-error")
    sha = None
    if receipt_evidence is not None:
        sha = receipt_evidence.sha256
        if ExpenseClaim.objects.filter(receipt_sha256=sha).exists():
            raise StateConflict("This receipt is already on another claim. One receipt pays once.",
                                code="receipt-reused", blocking_reasons=[
                                    {"rule": "FR-PRO-004", "message": "Receipt already used."}])
    cfg = _current_config(country)
    try:
        with transaction.atomic():
            c = ExpenseClaim.objects.create(
                country=country, agreement=agreement, claimant=person, case=case, project_id=project_id,
                errand_id=errand_id, kind=kind, description=description.strip(), amount=amount, currency=currency,
                incurred_on=incurred_on, receipt_evidence=receipt_evidence, receipt_sha256=sha,
                limit_amount=expense_limit(country, agreement.role, kind), country_config=cfg)
    except IntegrityError as exc:
        raise StateConflict("This receipt is already on another claim.", code="receipt-reused") from exc
    c.refresh_from_db()
    if receipt_evidence is not None:
        _link(receipt_evidence, "pro_expense_claim", c.pk, "receipt", person)
    _audit(person, "pro_expense.submitted", c, {"kind": kind, "amount": amount,
                                               "needs_second_approval": c.needs_second_approval})
    _alert(country, ("CM",), "pro_expense_submitted",
           f"{person.full_name} claimed {currency} {amount:,.2f} for {kind.replace('_', ' ')}.", obj=c,
           link=f"/pro/expense-claims/{c.pk}")
    return c


def _claim_approved(c: ExpenseClaim, actor):
    c.approved_at = c.approved_at or _now()
    state.transition(c, "pro_expense_claim", "approved", actor=actor, extra_fields=["approved_at"])
    _case_cost(c.case, item_type="fees" if c.kind == "official_search_fee" else "travel" if c.kind == "travel"
               else "other", amount=c.amount, currency=c.currency, source="pro_expense", source_id=c.pk,
               on=c.incurred_on, description=f"Expense: {c.description}"[:200])
    _notify(c.claimant, "pro_expense_approved", f"Your claim for {c.currency} {c.amount:,.2f} is approved. It joins "
            "the next payment run.", obj=c, link=f"/me/pay/expense-claims/{c.pk}")


@_atomic_after_checks
def decide_claim(c: ExpenseClaim, by, *, decision: str, note="", _refused=None) -> ExpenseClaim:
    """US-PRO-004 AC1, AC2, AC4: a staff member who is not the claimant approves or rejects. Over the limit
    or without a receipt, a second, different staff member must also approve (pro_expense_exception)."""
    _guard()
    c = ExpenseClaim.objects.select_for_update().get(pk=c.pk)
    if by.pk == c.claimant_id:
        _refuse(_refused, by, "pro_expense.self_approval_refused", c)
        raise SameApprover("You cannot decide your own claim.")
    _require_staff(by, c.country, msg="Only a case manager or reviewer decides a claim.")
    if c.status != "submitted" or c.approved_by_id:
        raise StateConflict("This claim is not waiting for a first decision.")
    c.decision_note = note or ""
    if decision == "reject":
        if not (note or "").strip():
            raise Invalid("Say why the claim is rejected.", code="validation-error")
        state.transition(c, "pro_expense_claim", "rejected", actor=by, reason=note, extra_fields=["decision_note"])
        _notify(c.claimant, "pro_expense_rejected", f"Your claim was not approved: {note}", obj=c)
        return c
    if decision != "approve":
        raise Invalid("Decision must be approve or reject.", code="validation-error")
    c.approved_by, c.approved_at = by, _now()
    if c.needs_second_approval:
        why = "it has no receipt" if c.receipt_evidence_id is None else \
            f"it is above the limit of {c.currency} {c.limit_amount:,.2f}"
        c.approval_request = approvals.request_approval(
            "pro_expense_exception", c.pk, by, required=1, country=c.country,
            summary=f"Expense {c.currency} {c.amount:,.2f} by {c.claimant.full_name}: second approval, {why}")
        c.save(update_fields=["approved_by", "approved_at", "approval_request", "decision_note"])
        _audit(by, "pro_expense.first_approval", c, {"needs_second_approval": True})
        _alert(c.country, STAFF, "pro_expense_exception",
               f"A claim needs a second approval because {why}.", obj=c, link=f"/pro/expense-claims/{c.pk}")
        return c
    c.save(update_fields=["approved_by", "approved_at", "decision_note"])
    _claim_approved(c, by)
    return c


def exception_allowed(c):
    return lambda a: (is_staff(a, c.country) and a.pk not in (c.claimant_id, c.approved_by_id))


def decide_exception(c: ExpenseClaim, by, *, decision="approve", mfa_at=None, note=""):
    if c.approval_request is None or c.approval_request.status != "open":
        raise StateConflict("This claim has no open second approval.")
    if by.pk in (c.claimant_id, c.approved_by_id):
        raise SameApprover("A different staff member gives the second approval, never the claimant.")
    return approvals.decide(c.approval_request, by, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=exception_allowed(c))


@transaction.atomic
def apply_exception(c: ExpenseClaim, approved: bool):
    c = ExpenseClaim.objects.select_for_update().get(pk=c.pk)
    if c.status != "submitted":
        return c
    if approved:
        approver = c.approval_request.approvals.filter(decision="approve").first()
        _claim_approved(c, approver.approver if approver else None)
    else:
        state.transition(c, "pro_expense_claim", "rejected", reason="Second approval refused")
        _notify(c.claimant, "pro_expense_rejected", "Your claim was not approved at the second check.", obj=c)
    return c


@transaction.atomic
def cancel_claim(c: ExpenseClaim, by) -> ExpenseClaim:
    if by.pk != c.claimant_id and not is_staff(by, c.country):
        raise NotFound()
    if c.status != "submitted":
        raise StateConflict("Only a claim not yet decided can be withdrawn.")
    if c.approval_request_id and c.approval_request.status == "open":
        approvals.withdraw(c.approval_request, by)
    return state.transition(c, "pro_expense_claim", "cancelled", actor=by)


# =========================================================================== payment runs (FR-PRO-005, 006, 009)

def operating_account(country, pk=None):
    """RUL-27: a run debits only an operating account of its country, never an escrow or held-funds account."""
    from administration.models import Partner

    qs = Partner.objects.filter(country=country, kind__in=["operating_bank", "operating_mobile_money"],
                                status="active")
    acct = qs.filter(pk=pk).first() if pk else qs.order_by("kind", "created_at").first()
    if acct is None:
        if pk and Partner.objects.filter(pk=pk).exists():
            raise RuleBlocked("A payment run debits only Tenmina's operating account.", code="not-operating-account",
                              blocking_reasons=[{"rule": "RUL-27", "message": "Not an operating account of this "
                                                                             "country."}])
        raise StateConflict("No operating account is registered for this country.", code="no-operating-account")
    return acct


def _line_amounts(country, payables, claims):
    gross = sum((p.gross for p in payables), ZERO)
    wh = sum((p.withholding for p in payables), ZERO)
    other = sum((p.other_deductions for p in payables), ZERO)
    exp = sum((c.amount for c in claims), ZERO)
    if _cfg(country, "pro.withholding_on_expenses", False):
        rate = withholding_rate(country, payables[0].agreement if payables else claims[0].agreement)
        wh += q(exp * rate)
    return gross, wh, other, exp


def _recount(run: PaymentRun):
    agg = run.lines.aggregate(g=Sum("gross"), n=Sum("net"))
    run.total_gross = agg["g"] or ZERO
    run.total_net = agg["n"] or ZERO
    run.line_count = run.lines.count()
    run.save(update_fields=["total_gross", "total_net", "line_count"])


def _excluded(kind, obj, reason, rule="FR-PRO-005"):
    a = obj.agreement
    amount = obj.gross if kind == "payable" else obj.amount
    return {"kind": kind, "id": str(obj.pk), "professional": a.professional.full_name, "agreement_id": str(a.pk),
            "amount": f"{amount:.2f}", "currency": obj.currency, "reason": reason, "rule": rule}


def _build_lines(run: PaymentRun):
    country = run.country
    payables = Payable.objects.filter(country=country, currency=run.currency, accepted_at__lte=run.cut_off_at,
                                      status="approved", payment_line__isnull=True).select_related(
        "agreement__professional", "agreement__payee", "agreement__bank_account")
    claims = ExpenseClaim.objects.filter(country=country, currency=run.currency, status="approved",
                                         approved_at__lte=run.cut_off_at, payment_line__isnull=True).select_related(
        "agreement__professional", "agreement__payee", "agreement__bank_account")
    excluded = []
    for p in Payable.objects.filter(country=country, status="held", accepted_at__lte=run.cut_off_at):
        excluded.append(_excluded("payable", p, f"Held: {p.hold_reason.replace('_', ' ')}"
                                  + (f" ({p.hold_note})" if p.hold_note else ""), "RUL-26"))
    for c in ExpenseClaim.objects.filter(country=country, status="submitted", approved_by__isnull=False,
                                         approved_at__lte=run.cut_off_at):
        excluded.append(_excluded("expense", c, "Waiting for a second staff approval (over the limit or no "
                                                "receipt)", "FR-PRO-004"))
    groups: dict = {}
    for p in payables:
        groups.setdefault(p.agreement_id, ([], []))[0].append(p)
    for c in claims:
        groups.setdefault(c.agreement_id, ([], []))[1].append(c)
    pos = run.lines.aggregate(m=Max("position"))["m"] or 0
    for _aid, (ps, cs) in groups.items():
        a = (ps or cs)[0].agreement
        reasons = destination_reasons(a)
        if a.status != "active":
            reasons = [{"rule": "FR-PRO-001", "message": f"Agreement is {a.status}"}] + reasons
        if reasons:
            msg = "; ".join(r["message"] for r in reasons)
            excluded += [_excluded("payable", p, msg, "FR-PRO-006") for p in ps]
            excluded += [_excluded("expense", c, msg, "FR-PRO-006") for c in cs]
            continue
        gross, wh, other, exp = _line_amounts(country, ps, cs)
        dest = destination(a)
        pos += 1
        line = PaymentLine.objects.create(
            run=run, position=pos, reference=f"{run.reference}-{pos:03d}", agreement=a, payee=a.payee,
            bank_account=a.bank_account, account_name=dest.account_name, account_last4=dest.last4, gross=gross,
            withholding=wh, other_deductions=other, reimbursed_expenses=exp, currency=run.currency)
        for p in ps:
            p.payment_line = line
            state.transition(p, "pro_payable", "in_run", extra_fields=["payment_line"],
                             payload={"run_id": str(run.pk)})
        for c in cs:
            c.payment_line = line
            state.transition(c, "pro_expense_claim", "in_run", extra_fields=["payment_line"],
                             payload={"run_id": str(run.pk)})
    run.excluded = excluded
    run.save(update_fields=["excluded"])
    _recount(run)


@transaction.atomic
def prepare_run(by, *, country, operating_account_id=None, cut_off_at=None) -> PaymentRun:
    """US-PRO-005 AC1: approved payables and expenses up to the cut-off, grouped per professional with gross,
    tax, expenses and net, and the items left out with reasons."""
    _guard()
    _require_staff(by, country, msg="Only a case manager or reviewer prepares a payment run.")
    _not_paused(country)
    acct = operating_account(country, operating_account_id)
    run = PaymentRun.objects.create(
        country=country, reference=_reference("PAYRUN", country, PaymentRun), operating_account=acct,
        file_format=str(_cfg(country, "pro.bulk_file_format", adapters.GenericCsvBulkFile.name)),
        cut_off_at=cut_off_at or _now(), currency=country.currency, prepared_by=by)
    _build_lines(run)
    _audit(by, "pro_payment_run.prepared", run, {"lines": run.line_count, "total_net": run.total_net,
                                                 "excluded": len(run.excluded)})
    return run


@transaction.atomic
def refresh_run(run: PaymentRun, by) -> PaymentRun:
    """Add items approved since the run was prepared (draft only)."""
    run = PaymentRun.objects.select_for_update().get(pk=run.pk)
    _require_staff(by, run.country)
    _not_paused(run.country)
    if run.status != "draft":
        raise StateConflict("Only a draft run is refreshed.")
    _build_lines(run)
    return run


@transaction.atomic
def submit_run(run: PaymentRun, by) -> PaymentRun:
    _guard()
    run = PaymentRun.objects.select_for_update().get(pk=run.pk)
    _require_staff(by, run.country)
    _not_paused(run.country)
    if run.status != "draft":
        raise StateConflict("Only a draft run is sent for approval.")
    if run.line_count == 0:
        raise StateConflict("This run has no lines to pay.", code="run-empty")
    run.prepared_by = by
    run.approval_request = approvals.request_approval(
        "pro_payment_run", run.pk, by, required=1, country=run.country,
        summary=f"Payment run {run.reference}: {run.line_count} lines, {run.currency} {run.total_net:,.2f} net")
    state.transition(run, "pro_payment_run", "pending_approval", actor=by,
                     extra_fields=["prepared_by", "approval_request"])
    for p in staff_in(run.country, "PY"):
        if p.pk != by.pk:
            _notify(p, "pro_payment_run_approval", f"Payment run {run.reference} needs your approval.", obj=run,
                    link=f"/pro/payment-runs/{run.pk}", needs_action=True, category="approval")
    return run


def run_allowed(run):
    return lambda a: has_payment_rights(a, run.country) and a.pk != run.prepared_by_id


def decide_run(run: PaymentRun, approver, *, decision="approve", mfa_at=None, note=""):
    """US-PRO-005 AC2, AC4: a different person with payment rights approves with the second factor."""
    _not_paused(run.country)
    if run.status != "pending_approval" or run.approval_request is None or run.approval_request.status != "open":
        raise StateConflict("This run is not waiting for approval.")
    if approver.pk == run.prepared_by_id:
        _audit(approver, "pro_payment_run.self_approval_refused", run)
        raise SameApprover("The person who prepared the run cannot approve it.")
    if not has_payment_rights(approver, run.country):
        raise Forbidden("Only a person with payment rights approves a payment run.")
    return approvals.decide(run.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=run_allowed(run))


def _back_to_draft(run: PaymentRun, by, reason):
    if run.approval_request_id and run.approval_request.status == "open":
        approvals.withdraw(run.approval_request, by)
    run.approved_by = run.approved_at = None
    run.approval_request = None
    run.file_evidence, run.file_sha256, run.uploaded_by, run.uploaded_at = None, "", None, None
    run.status_reason = reason
    state.transition(run, "pro_payment_run", "draft", actor=by, reason=reason,
                     extra_fields=["approved_by", "approved_at", "approval_request", "file_evidence", "file_sha256",
                                   "uploaded_by", "uploaded_at", "status_reason"])


def _drop_line(line: PaymentLine, by, reason):
    for p in line.payables.all():
        p.payment_line = None
        state.transition(p, "pro_payable", "approved", actor=by, reason=reason, extra_fields=["payment_line"])
    for c in line.expenses.all():
        c.payment_line = None
        state.transition(c, "pro_expense_claim", "approved", actor=by, reason=reason, extra_fields=["payment_line"])
    run = line.run
    run.excluded = list(run.excluded or []) + [{"kind": "line", "id": str(line.pk),
                                                "professional": line.agreement.professional.full_name,
                                                "agreement_id": str(line.agreement_id), "amount": f"{line.net:.2f}",
                                                "currency": line.currency, "reason": reason, "rule": "FR-PRO-006"}]
    run.save(update_fields=["excluded"])
    line.delete()


@transaction.atomic
def remove_line(line: PaymentLine, by, *, reason: str, system=False) -> PaymentRun:
    """US-PRO-005 AC3: any change to a line after approval withdraws the approval and returns the run to draft;
    the file can no longer be downloaded."""
    run = PaymentRun.objects.select_for_update().get(pk=line.run_id)
    if not system:
        _require_staff(by, run.country)
    if run.status not in RUN_OPEN:
        raise StateConflict("Lines change only before the bank's confirmation is imported.")
    if not (reason or "").strip():
        raise Invalid("Give the reason.", code="validation-error")
    _drop_line(line, by, reason)
    _recount(run)
    _audit(by, "pro_payment_line.removed", run, {"line": str(line.pk), "reason": reason})
    if run.status in ("pending_approval", "approved", "file_issued"):
        _back_to_draft(run, by, f"A line changed: {reason}")
    return run


@transaction.atomic
def withdraw_run(run: PaymentRun, by, *, reason="") -> PaymentRun:
    run = PaymentRun.objects.select_for_update().get(pk=run.pk)
    _require_staff(by, run.country)
    if run.status not in ("draft", "pending_approval"):
        raise StateConflict("Only a draft or pending run is withdrawn.")
    for line in list(run.lines.all()):
        _drop_line(line, by, reason or "Run withdrawn")
    if run.approval_request_id and run.approval_request.status == "open":
        approvals.withdraw(run.approval_request, by)
    run.status_reason = reason or ""
    state.transition(run, "pro_payment_run", "withdrawn", actor=by, reason=reason, extra_fields=["status_reason"])
    _recount(run)
    return run


def _line_dest(line: PaymentLine) -> dict:
    d = line.payee or line.bank_account
    return {"bank": d.bank_name, "account": d.account_number, "account_name": d.account_name}


def _file_payload(run: PaymentRun) -> dict:
    acct = run.operating_account
    lines = []
    for line in run.lines.order_by("position"):
        d = _line_dest(line)
        lines.append({"reference": line.reference, "bank": d["bank"], "account": d["account"],
                      "account_name": d["account_name"], "net": line.net,
                      "narrative": f"Tenmina professional fees {run.reference}"})
    return {"reference": run.reference, "currency": run.currency, "total_net": run.total_net,
            "debit": {"bank": acct.bank_name, "account": acct.account_number, "name": acct.account_name},
            "lines": lines}


def _check_lines_payable(run, by) -> list:
    bad = []
    for line in list(run.lines.select_related("agreement")):
        reasons = destination_reasons(line.agreement)
        if (line.payee_id != line.agreement.payee_id or line.bank_account_id != line.agreement.bank_account_id):
            reasons.append({"rule": "FR-PRO-006", "message": "The professional's payee account changed."})
        if reasons:
            bad.append((line, "; ".join(r["message"] for r in reasons)))
    return bad


@transaction.atomic
def apply_run_decision(run: PaymentRun, approved: bool):
    """approval.approved: re-check every payee (FR-PRO-006), then build, hash and store the bulk file."""
    run = PaymentRun.objects.select_for_update().get(pk=run.pk)
    if run.status != "pending_approval":
        return run
    req = run.approval_request
    approval = req.approvals.filter(decision="approve").order_by("-approved_at").first() if approved else None
    if not approved:
        _back_to_draft(run, None, "The approver rejected the run")
        return run
    if flags.enabled(PAUSE_FLAG, run.country):
        _back_to_draft(run, None, "Payment runs are paused")
        return run
    bad = _check_lines_payable(run, None)
    if bad:
        for line, why in bad:
            _drop_line(line, None, why)
        _recount(run)
        _back_to_draft(run, None, "A payee is no longer verified: " + "; ".join(w for _, w in bad))
        _alert(run.country, STAFF, "pro_run_payee_changed",
               f"Payment run {run.reference} went back to draft: a payee is no longer verified.", obj=run)
        return run
    run.approved_by_id, run.approved_at = approval.approver_id, _now()
    state.transition(run, "pro_payment_run", "approved", actor=approval.approver, event="payment_run.approved",
                     extra_fields=["approved_by", "approved_at"],
                     payload={"run_id": run.pk, "reference": run.reference, "country": run.country.code,
                              "total_net": run.total_net, "line_count": run.line_count})
    _issue_file(run, approval.approver)
    return run


def _issue_file(run: PaymentRun, by):
    """ADR-23 point 4: the bulk file in the operating account's format, hashed and stored write-once."""
    bad = _check_lines_payable(run, by)
    if bad:
        raise PayeeNotVerified("A payee is no longer verified; the file is not built.",
                               blocking_reasons=[{"rule": "FR-PRO-006", "message": w} for _, w in bad])
    fmt = adapters.bulk_file(run.file_format)
    data = fmt.build(_file_payload(run))
    ev = _store(run.country, by, data, name=f"{run.reference}.{fmt.extension}", content_type=fmt.content_type,
                owner_type="pro_payment_run", owner_id=run.pk)
    _link(ev, "pro_payment_run", run.pk, "bulk_file", by)
    run.file_evidence, run.file_sha256 = ev, ev.sha256
    state.transition(run, "pro_payment_run", "file_issued", actor=by, event="payment_run.file_issued",
                     extra_fields=["file_evidence", "file_sha256"],
                     payload={"run_id": run.pk, "reference": run.reference, "file_sha256": ev.sha256,
                              "country": run.country.code})
    return run


def can_download(user, run) -> bool:
    return user.pk == run.prepared_by_id or has_payment_rights(user, run.country)


def download_file(run: PaymentRun, by) -> tuple[bytes, str, str]:
    """US-PRO-005 AC2, TC-PRO-005-04: only after approval, only by a person with payment rights or the
    preparer; every download logged; an altered file fails its hash check and is never served."""
    from core.adapters import get_adapter

    if not can_download(by, run):
        raise Forbidden("Only the preparer or a person with payment rights downloads the bulk file.")
    if run.status not in ("file_issued", "partly_confirmed", "confirmed", "closed") or run.file_evidence is None:
        raise StateConflict("The file exists only for an approved run.", code="file-not-issued")
    if flags.enabled(PAUSE_FLAG, run.country):
        _not_paused(run.country)
    ev = run.file_evidence
    try:
        data = get_adapter("evidence_store").get(ev.storage_key)
    except (FileNotFoundError, KeyError):
        data = b""
    import hashlib

    digest = hashlib.sha256(data).hexdigest()
    if digest != run.file_sha256 or digest != ev.sha256:
        record(actor=by, action="pro_payment_run.file_integrity_failed", entity="pro_payment_run", entity_id=run.pk,
               country=run.country, data={"expected": run.file_sha256, "found": digest})
        _alert(run.country, ("RV",), "pro_run_file_integrity",
               f"The bulk file of {run.reference} does not match its hash. Do not upload it.", obj=run)
        raise DomainError("The stored file does not match the approved run's hash. It cannot be downloaded.",
                          code="file-integrity", status=409)
    record(actor=by, action="pro_payment_run.file_downloaded", entity="pro_payment_run", entity_id=run.pk,
           country=run.country, data={"sha256": digest})
    fmt = adapters.bulk_file(run.file_format)
    return data, fmt.content_type, ev.original_name or f"{run.reference}.{fmt.extension}"


@transaction.atomic
def mark_uploaded(run: PaymentRun, by) -> PaymentRun:
    if not can_download(by, run):
        raise Forbidden("Only the preparer or a person with payment rights records the upload.")
    if run.status != "file_issued":
        raise StateConflict("Only an issued file is uploaded to the bank.")
    run.uploaded_by, run.uploaded_at = by, _now()
    run.save(update_fields=["uploaded_by", "uploaded_at"])
    _audit(by, "pro_payment_run.uploaded", run, {"sha256": run.file_sha256})
    return run


def _confirm_line(line: PaymentLine, by, *, bank_reference=""):
    now = _now()
    line.outcome, line.confirmed_at = "confirmed", now
    if bank_reference:
        line.bank_reference = bank_reference
    line.save(update_fields=["outcome", "confirmed_at", "bank_reference", "resolution", "resolved_by",
                             "resolved_at", "resolution_note"])
    for p in line.payables.all():
        p.paid_at = now
        state.transition(p, "pro_payable", "paid", actor=by, extra_fields=["paid_at"])
    for c in line.expenses.all():
        state.transition(c, "pro_expense_claim", "paid", actor=by)
    publish("payment_line.confirmed", line.pk, {
        "line_id": line.pk, "run_id": line.run_id, "agreement_id": line.agreement_id,
        "professional_id": line.agreement.professional_id, "net": line.net, "currency": line.currency,
        "country": line.run.country.code})
    _issue_advice(line, by)


def _fail_line(line: PaymentLine, reason):
    line.outcome, line.failure_reason = "failed", reason or "Failed at the bank"
    line.save(update_fields=["outcome", "failure_reason"])
    publish("payment_line.failed", line.pk, {"line_id": line.pk, "run_id": line.run_id,
                                             "agreement_id": line.agreement_id, "reason": line.failure_reason,
                                             "country": line.run.country.code})
    _alert(line.run.country, STAFF, "pro_payment_line_failed",
           f"A payment to {line.agreement.professional.full_name} failed: {line.failure_reason}.", obj=line.run,
           link=f"/pro/payment-runs/{line.run_id}")
    _notify(line.agreement.professional, "pro_payment_failed",
            "Your payment did not go through at the bank. We will pay it in the next run once the account is "
            "fixed.", obj=line.run)


def _refresh_status(run: PaymentRun, by):
    lines = list(run.lines.all())
    if not lines:
        return run
    done = all(ln.outcome == "confirmed" or ln.resolution for ln in lines)
    all_confirmed = all(ln.outcome == "confirmed" for ln in lines)
    if run.status == "file_issued":
        state.transition(run, "pro_payment_run", "confirmed" if all_confirmed else "partly_confirmed", actor=by)
    elif run.status == "partly_confirmed" and all_confirmed:
        state.transition(run, "pro_payment_run", "confirmed", actor=by)
    if run.status == "partly_confirmed" and done:
        # Every failed or unconfirmed line is resolved (next run, cancelled or a checked bank letter).
        state.transition(run, "pro_payment_run", "closed", actor=by)
    return run


@transaction.atomic
def import_confirmation(run: PaymentRun, by, *, data: bytes, content_type="text/csv",
                        name="confirmation.csv") -> PaymentRun:
    """US-PRO-009 AC1: each line confirmed, failed or unconfirmed from the bank's or provider's file."""
    _guard()
    run = PaymentRun.objects.select_for_update().get(pk=run.pk)
    _require_staff(by, run.country, msg="Only a case manager or reviewer imports the bank's confirmation.")
    if run.status not in ("file_issued", "partly_confirmed"):
        raise StateConflict("Only an issued run takes a confirmation.")
    ev = _store(run.country, by, data, name=name, content_type=content_type, owner_type="pro_payment_run",
                owner_id=run.pk)
    _link(ev, "pro_payment_run", run.pk, "bank_confirmation", by)
    rows = {r["reference"]: r for r in adapters.bulk_file(run.file_format).parse_confirmation(data)}
    run.confirmation_evidence = ev
    run.save(update_fields=["confirmation_evidence"])
    counts = {"confirmed": 0, "failed": 0, "unconfirmed": 0}
    for line in run.lines.select_related("agreement__professional").order_by("position"):
        if line.outcome == "confirmed" or line.resolution:
            continue
        r = rows.get(line.reference)
        if r is None:
            if line.outcome == "pending":
                line.outcome = "unconfirmed"
                line.save(update_fields=["outcome"])
            counts["unconfirmed"] += 1
        elif r["status"] in ("paid", "confirmed", "success", "successful", "completed"):
            if r["amount"] is not None and q(r["amount"]) != line.net:
                line.outcome = "unconfirmed"
                line.resolution_note = f"The bank reported {r['amount']}, the line is {line.net}."
                line.save(update_fields=["outcome", "resolution_note"])
                counts["unconfirmed"] += 1
            else:
                _confirm_line(line, by, bank_reference=r["bank_reference"])
                counts["confirmed"] += 1
        elif r["status"] in ("failed", "rejected", "returned", "error"):
            _fail_line(line, r["reason"])
            counts["failed"] += 1
        else:
            line.outcome = "unconfirmed"
            line.save(update_fields=["outcome"])
            counts["unconfirmed"] += 1
    _audit(by, "pro_payment_run.confirmation_imported", run, {"sha256": ev.sha256, **counts})
    _refresh_status(run, by)
    return run


@transaction.atomic
def resolve_line(line: PaymentLine, by, *, resolution: str, note="", letter_evidence=None) -> PaymentLine:
    """US-PRO-009 AC2, AC3: a failed line goes to the next run (paid once only) or is cancelled; an
    unconfirmed line is confirmed by a bank letter that a second staff member checks."""
    _guard()
    line = PaymentLine.objects.select_for_update().select_related("run", "agreement").get(pk=line.pk)
    run = line.run
    _require_staff(by, run.country)
    if line.resolution:
        raise StateConflict("This line is already resolved.")
    if resolution == "next_run":
        if line.outcome != "failed":
            raise StateConflict("Only a failed line goes to the next run. An unconfirmed line may have been paid; "
                                "confirm it with the bank first.")
        for p in line.payables.all():
            p.payment_line = None
            state.transition(p, "pro_payable", "approved", actor=by, reason="Failed line moved to the next run",
                             extra_fields=["payment_line"])
        for c in line.expenses.all():
            c.payment_line = None
            state.transition(c, "pro_expense_claim", "approved", actor=by, reason="Failed line moved",
                             extra_fields=["payment_line"])
    elif resolution == "cancelled":
        if not has_role(by, "RV", country=run.country):
            raise Forbidden("Only a reviewer cancels a payment line.")
        if not (note or "").strip() or _mentions_result(note):
            raise RuleBlocked("Give a reason that is not a result of the work.", code="pay-independent-of-result",
                              blocking_reasons=[{"rule": "RUL-26", "message": "A reason is needed."}])
        if line.outcome not in ("failed", "unconfirmed"):
            raise StateConflict("Only a failed or unconfirmed line is cancelled.")
        for p in line.payables.all():
            p.cancel_reason = note
            state.transition(p, "pro_payable", "cancelled", actor=by, reason=note, extra_fields=["cancel_reason"])
        for c in line.expenses.all():
            state.transition(c, "pro_expense_claim", "cancelled", actor=by, reason=note)
    elif resolution == "confirmed_by_bank_letter":
        if line.outcome != "unconfirmed":
            raise StateConflict("Only an unconfirmed line is confirmed by a bank letter.")
        if letter_evidence is None:
            raise Invalid("Attach the bank's letter.", code="validation-error")
        line.letter_evidence, line.letter_recorded_by = letter_evidence, by
        line.resolution_note = note or ""
        line.save(update_fields=["letter_evidence", "letter_recorded_by", "resolution_note"])
        _link(letter_evidence, "pro_payment_run", run.pk, "bank_letter", by)
        _audit(by, "pro_payment_line.letter_recorded", line, {"line": line.reference}, country=run.country)
        _alert(run.country, STAFF, "pro_bank_letter_check",
               f"A bank letter for line {line.reference} needs a second staff member to check it.", obj=run)
        return line
    else:
        raise Invalid("Resolution is next_run, cancelled or confirmed_by_bank_letter.", code="validation-error")
    line.resolution, line.resolved_by, line.resolved_at = resolution, by, _now()
    line.resolution_note = note or line.resolution_note
    line.save(update_fields=["resolution", "resolved_by", "resolved_at", "resolution_note"])
    _audit(by, "pro_payment_line.resolved", line, {"resolution": resolution, "line": line.reference},
           country=run.country)
    _refresh_status(run, by)
    return line


@transaction.atomic
def check_bank_letter(line: PaymentLine, by, *, accept=True, note="") -> PaymentLine:
    """TC-PRO-009-03: not confirmed until staff B checks the letter staff A recorded."""
    line = PaymentLine.objects.select_for_update().select_related("run").get(pk=line.pk)
    _require_staff(by, line.run.country)
    if line.letter_evidence_id is None or line.resolution:
        raise StateConflict("No bank letter is waiting for a check on this line.")
    if by.pk == line.letter_recorded_by_id:
        raise SameApprover("A different staff member checks the bank letter.")
    if not accept:
        line.letter_evidence, line.letter_recorded_by = None, None
        line.resolution_note = note or "Bank letter not accepted"
        line.save(update_fields=["letter_evidence", "letter_recorded_by", "resolution_note"])
        return line
    line.resolution, line.resolved_by, line.resolved_at = "confirmed_by_bank_letter", by, _now()
    _confirm_line(line, by)
    _audit(by, "pro_payment_line.letter_checked", line, {"line": line.reference}, country=line.run.country)
    _refresh_status(line.run, by)
    return line


# =========================================================================== documents (FR-PRO-007)

def _money(currency, amount) -> str:
    return f"{currency} {Decimal(amount):,.2f}"


def _deduction_rows(line) -> list[tuple[str, str]]:
    rows = []
    cfgs = {p.country_config_id: p.country_config for p in line.payables.select_related("country_config")}
    names = []
    for cfg in cfgs.values():
        for d in (cfg.data.get("pro", {}) or {}).get("other_deductions", []) or []:
            if isinstance(d, dict) and d.get("name") and d["name"] not in names:
                names.append(d["name"])
    rows.append(("Withholding tax", f"- {_money(line.currency, line.withholding)}"))
    if line.other_deductions:
        rows.append((f"Other deductions ({', '.join(names) or 'as configured'})",
                     f"- {_money(line.currency, line.other_deductions)}"))
    return rows


def _issue_advice(line: PaymentLine, by):
    if Document.objects.filter(payment_line=line, kind="remittance_advice").exists():
        return
    a, run = line.agreement, line.run
    items = [(f"{p.work_kind.replace('_', ' ').capitalize()} accepted {p.accepted_at:%d %b %Y}",
              _money(p.currency, p.gross)) for p in line.payables.order_by("accepted_at")]
    items += [(f"Expense: {c.description[:60]}", _money(c.currency, c.amount)) for c in line.expenses.all()]
    vers = sorted({p.country_config.version for p in line.payables.select_related("country_config")})
    doc = {"title": "Remittance advice", "issued_at": line.confirmed_at or _now(),
           "header": [f"Tenmina pays {a.professional.full_name} ({a.role.replace('_', ' ')})",
                      f"Agreement {a.reference}. Payment run {run.reference}, line {line.reference}.",
                      f"Paid to account ending {line.account_last4} ({line.account_name}).",
                      f"Paid from Tenmina's operating account. Bank reference {line.bank_reference or '-'}."],
           "rows": items + [("Gross fees", _money(line.currency, line.gross))] + _deduction_rows(line)
           + [("Reimbursed expenses", f"+ {_money(line.currency, line.reimbursed_expenses)}"),
              ("Net paid", _money(line.currency, line.net))],
           "notes": [f"Tax rules from the {run.country.name} configuration, version(s) "
                     f"{', '.join(str(v) for v in vers) or '-'}. Expenses carry no withholding unless the "
                     "country's rules say so.",
                     "Your pay does not depend on the verdict or outcome of your work."]}
    from .pdf import render

    ev = _store(run.country, by, render(doc), name=f"remittance-{line.reference}.pdf",
                content_type="application/pdf", owner_type="pro_agreement", owner_id=a.pk)
    _link(ev, "pro_agreement", a.pk, "remittance_advice", by)
    Document.objects.create(country=run.country, agreement=a, kind="remittance_advice", payment_line=line,
                            evidence=ev, gross=line.gross, withholding=line.withholding,
                            other_deductions=line.other_deductions, reimbursed_expenses=line.reimbursed_expenses,
                            net=line.net, currency=line.currency)
    _notify(a.professional, "pro_remittance_advice",
            f"You were paid {_money(line.currency, line.net)} (gross {_money(line.currency, line.gross)}, tax "
            f"{_money(line.currency, line.withholding)}). Your remittance advice is in My pay.",
            subject="Payment made", obj=line.run, link="/me/pay/statements")


@transaction.atomic
def generate_statements(country, tax_year: int, *, by=None) -> list[Document]:
    """US-PRO-007 AC3: one yearly statement per professional that adds up to their remittance advices."""
    if by is not None and not (is_staff(by, country) or is_admin(by, country)):
        raise Forbidden("Only staff generate yearly statements.")
    out = []
    advices = Document.objects.filter(country=country, kind="remittance_advice").select_related(
        "agreement__professional", "payment_line")
    by_agreement: dict = {}
    for d in advices:
        when = d.payment_line.confirmed_at or d.issued_at
        if tax_year_of(country, _local_date(country, when)) == tax_year:
            by_agreement.setdefault(d.agreement_id, []).append(d)
    for aid, docs in by_agreement.items():
        if Document.objects.filter(agreement_id=aid, kind="yearly_statement", tax_year=tax_year).exists():
            continue
        a = docs[0].agreement
        tot = {k: sum((getattr(d, k) for d in docs), ZERO) for k in ("gross", "withholding", "other_deductions",
                                                                       "reimbursed_expenses", "net")}
        cur = docs[0].currency
        from .pdf import render

        doc = {"title": f"Yearly statement {tax_year}", "issued_at": _now(),
               "header": [f"{a.professional.full_name}, {a.role.replace('_', ' ')}, agreement {a.reference}",
                          f"Tax status: {a.tax_status.replace('_', ' ')}. {len(docs)} payments in the tax year."],
               "rows": [(f"{d.payment_line.reference} ({(d.payment_line.confirmed_at or d.issued_at):%d %b %Y})",
                         _money(cur, d.net)) for d in sorted(docs, key=lambda x: x.issued_at)]
               + [("Gross fees", _money(cur, tot["gross"])), ("Withholding tax", _money(cur, tot["withholding"])),
                  ("Other deductions", _money(cur, tot["other_deductions"])),
                  ("Reimbursed expenses", _money(cur, tot["reimbursed_expenses"])),
                  ("Net paid", _money(cur, tot["net"]))],
               "notes": ["These totals add up to your remittance advices for the year."]}
        ev = _store(country, by, render(doc), name=f"statement-{a.reference}-{tax_year}.pdf",
                    content_type="application/pdf", owner_type="pro_agreement", owner_id=a.pk)
        _link(ev, "pro_agreement", a.pk, "yearly_statement", by)
        d = Document.objects.create(country=country, agreement=a, kind="yearly_statement", tax_year=tax_year,
                                    evidence=ev, currency=cur, **tot)
        _notify(a.professional, "pro_yearly_statement", f"Your yearly statement for {tax_year} is in My pay.",
                obj=d, link="/me/pay/statements")
        out.append(d)
    return out


def document_bytes(doc: Document) -> bytes:
    from core.adapters import get_adapter

    return get_adapter("evidence_store").get(doc.evidence.storage_key)


# =========================================================================== payee events and RUL-27

@transaction.atomic
def on_destination_changed(*, payee_id=None, bank_account_id=None, verified: bool):
    """payee.suspended / bank account suspended: pay waits (held, payee_not_verified) and lines not yet paid
    leave their run, which returns to draft. payee.verified: the holds lift."""
    qs = Agreement.objects.filter(Q(payee_id=payee_id) if payee_id else Q(bank_account_id=bank_account_id))
    for a in qs:
        if verified:
            _release_holds(a, "payee_not_verified", None)
            continue
        for p in a.payables.filter(status="approved"):
            _hold(p, "payee_not_verified", None, "Payee account not verified")
        for line in PaymentLine.objects.filter(agreement=a, run__status__in=RUN_OPEN, outcome="pending"):
            remove_line(line, None, reason="The professional's payee account is no longer verified", system=True)


def escrow_release_check(instruction) -> list[dict]:
    """RUL-27 (registered with ESC for every release subject): client money never pays a professional
    Tenmina contracts. A payee linked to an agreement is refused."""
    pid = getattr(instruction, "payee_id", None)
    if pid and Agreement.objects.filter(payee_id=pid).exclude(status="ended").exists():
        return [{"rule": "RUL-27", "code": "payee-not-verified",
                 "message": "This payee is a professional Tenmina contracts. Tenmina pays them from its own "
                            "account, never from client money."}]
    return []


# =========================================================================== cost per case (FR-PRO-010)

def cost_per_case(country=None, *, case_ids=None) -> list[dict]:
    pay = Payable.objects.exclude(status="cancelled").filter(case__isnull=False)
    exp = ExpenseClaim.objects.filter(status__in=["approved", "in_run", "paid"], case__isnull=False)
    if country is not None:
        pay, exp = pay.filter(country=country), exp.filter(country=country)
    if case_ids is not None:
        pay, exp = pay.filter(case_id__in=case_ids), exp.filter(case_id__in=case_ids)
    rows: dict = {}
    for r in pay.values("case_id", "case__reference", "case__product_line", "currency").annotate(t=Sum("gross")):
        rows.setdefault((r["case_id"], r["currency"]), {
            "case_id": str(r["case_id"]), "reference": r["case__reference"], "line": r["case__product_line"],
            "currency": r["currency"], "payables": ZERO, "expenses": ZERO})["payables"] += r["t"] or ZERO
    for r in exp.values("case_id", "case__reference", "case__product_line", "currency").annotate(t=Sum("amount")):
        rows.setdefault((r["case_id"], r["currency"]), {
            "case_id": str(r["case_id"]), "reference": r["case__reference"], "line": r["case__product_line"],
            "currency": r["currency"], "payables": ZERO, "expenses": ZERO})["expenses"] += r["t"] or ZERO
    out = []
    for row in rows.values():
        row["total"] = row["payables"] + row["expenses"]
        out.append({k: (f"{v:.2f}" if isinstance(v, Decimal) else v) for k, v in row.items()})
    return sorted(out, key=lambda r: r["reference"] or "")
