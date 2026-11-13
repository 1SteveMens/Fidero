"""ESC Escrow and held funds: the public interface other modules may call.

Tenmina never holds client money (ADR-03). An escrow is a mirror of what the
licensed bank reports; held funds are derived from bank-confirmed events and
never edited (ADR-18, ADR-26). Everything here is behind the `escrow.enabled`
flag, and no instruction is sent while `escrow.instructions_paused` is on.

Line-facing interface (family and property lines: fees, care, errands,
insurance, events, repairs, construction milestones, project funds)
------------------------------------------------------------------------
    held_funds_for(client, country, currency) -> Escrow | None
    open_held_funds(client, country, currency, *, by) -> Escrow
    open_line_escrow(*, kind, client, country, agreed_amount, by, title="", currency=None, asset_id=None,
                     project_id=None, case_id=None, payees=(), conditions=()) -> Escrow
    available_to_instruct(escrow, currency=None) -> Decimal
    request_release(escrow, *, payee, amount, subject_type, subject_id, requested_by, evidence_ids=(), reason="",
                    subject_label="", family_member_id=None, holdback_amount=0, currency=None, kind=None,
                    release_part="main", standing_approval=None) -> ReleaseInstruction
    client_approve(instruction, client, mfa_at=None, *, code=None) -> ReleaseInstruction
    client_decline(instruction, client, reason="") -> ReleaseInstruction
    staff_approve(instruction, approver, *, mfa_at, decision="approve", confirm_amount=None, note="")
    withdraw_instruction(instruction, by, *, reason, system=False) -> ReleaseInstruction
    release_blockers(instruction, stage="send") -> list[dict]
    create_standing_approval(escrow, client, *, subject_kind, subject_id, monthly_max, mfa_at=None, code=None)
    lock_payee(escrow, payee, *, client_approved_at)        # held funds: first approved payment to a payee
    create_payee(by, *, country, kind, subject_type, subject_id, legal_name, ...) -> Payee
    registry.subject_check(subject_type)                    # the line's own evidence rule (RUL-09, RUL-23, ...)

Events lines subscribe to (payload keys):
    release.requested   instruction_id, escrow_id, client_id, subject_type, subject_id, amount, currency
    release.client_approved, release.approved, release.sent   same keys
    release.confirmed   instruction_id, escrow_id, client_id, subject_type, subject_id, payee_id, amount,
                        currency, bank_reference, kind
    release.withdrawn / release.rejected / release.rejected_by_bank   instruction_id, subject_type, subject_id
    held_funds.deposit_confirmed   escrow_id, client_id, amount, currency
    payee.verified / payee.suspended   payee_id, kind, subject_type, subject_id

Events consumed: report.released, fresh_search.completed, dispute.opened, dispute.resolved, incident.opened,
incident.closed, national_id_check.completed, approval.approved, approval.rejected.
"""
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from administration import flags
from core import approvals, state
from core.errors import DomainError, Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.ids import uuid7
from core.money import q
from core.permissions import has_role

from . import adapters, registry, selectors
from .blockers import fresh_search_reasons, open_condition_reasons, raise_if_blocked
from .blockers import release_blockers as _release_blockers
from .common import (add_working_days, alert_staff, audit, cfg, fmt, has_rr, is_staff, local_date, local_today, log,
                     notify, now, setting, working_day_on_or_after)
from .models import (ESCROW, OPEN_STATUSES, STAGED_KINDS, Acceptance, BankEvent, Condition, Escrow, EscrowPayee,
                     Freeze, Party, Payee, PayeeChange, ProgrammeAccount, ReleaseInstruction, ReportSnapshot,
                     StandingApproval)
from .payees import (_client_signed, apply_payee_change, apply_verification, change_identity_check,  # noqa: F401
                     check_change_account, client_approve_change, create_payee, decide_change, decide_verification,
                     lock_payee, on_change_approval, prepare_verification, reinstate_payee, request_change,
                     stop_change, suspend_payee, update_payee, withdraw_change)
from .selectors import available_to_instruct, held_funds_for  # noqa: F401

ZERO = Decimal("0.00")
RELEASABLE = ("funded", "ready_to_release", "client_approved", "release_approved", "partly_released")


def release_blockers(instruction, stage="send"):
    return _release_blockers(instruction, stage)


def _on(country):
    flags.require("escrow.enabled", country)
    flags.read_only_guard()


def _staff(by, country, *roles):
    if not has_role(by, *(roles or ("CM", "RV", "AD")), country=country):
        raise Forbidden("Only Tenmina staff can do this.")


def _client_payload(ins: ReleaseInstruction, **extra):
    e = ins.escrow
    return {"instruction_id": ins.pk, "escrow_id": e.pk, "client_id": e.client_id, "kind": ins.kind,
            "subject_type": ins.subject_type, "subject_id": ins.subject_id, "amount": ins.amount,
            "currency": ins.currency, "payee_id": ins.payee_id, "release_part": ins.release_part,
            "payee_name": ins.payee.account_name if ins.payee_id else "the account the money came from",
            "amount_label": fmt(ins.amount, ins.currency),
            "label": ins.subject_label or f"Payment from {e.reference}", **extra}


def _new_reference(country) -> str:
    import secrets

    return f"ESC-{country.code}-{timezone.now():%y%m}-{secrets.token_hex(3).upper()}"


def _route(e: Escrow, target: str, *, actor=None, event=None, payload=None, reason=""):
    """Move an escrow to `target` along the allowed transitions (01 C8)."""
    if e.status == target:
        return e
    if ESCROW.allowed(e.status, target):
        return state.transition(e, "escrow", target, actor=actor, event=event, payload=payload, reason=reason)
    for mid in ("ready_to_release", "client_approved", "funded"):
        if ESCROW.allowed(e.status, mid) and ESCROW.allowed(mid, target):
            state.transition(e, "escrow", mid, actor=actor, reason=reason)
            return state.transition(e, "escrow", target, actor=actor, event=event, payload=payload, reason=reason)
    return e


def _escrow_payload(e, **extra):
    return {"escrow_id": e.pk, "client_id": e.client_id, "kind": e.kind, "reference": e.reference,
            "country": e.country.code, "link": f"/escrows/{e.pk}", **extra}


def _parties_to_tell(e):
    out = {e.client}
    for p in Party.objects.filter(escrow=e, person__isnull=False).select_related("person"):
        if p.role != "tenmina":
            out.add(p.person)
    return out


# ----------------------------------------------------------------- creating an escrow (FR-ESC-001)

def _report_facts(report_id):
    """The released report's verdict and section 11 conditions, from RPT when
    it offers `reports.selectors.conditions_for`, else from the snapshot ESC
    kept when `report.released` was published."""
    snap = ReportSnapshot.objects.filter(report_id=report_id).first()
    try:
        from reports import selectors as rsel

        report = rsel.report(report_id)
        if report is not None:
            conds = [{"id": str(c["source_condition_id"]), "text": c["text"],
                      "release_part": c.get("release_part") or "main"} for c in rsel.conditions_for(report)]
            return report.overall_verdict, conds
    except ImportError:
        pass
    if snap is None:
        return None, []
    return snap.verdict, list(snap.conditions or [])


def _bank_for(country, bank_partner=None):
    from administration.models import Partner

    if bank_partner is not None:
        if bank_partner.kind != "escrow_bank" or bank_partner.status != "active":
            raise Invalid("The bank must be an active escrow bank partner.", code="validation-error")
        return bank_partner
    p = Partner.objects.filter(country=country, kind="escrow_bank", status="active").order_by("created_at").first()
    if p is None:
        raise StateConflict("No escrow bank is configured for this country.", code="escrow-bank-missing")
    return p


def _programme_account(country, currency):
    return ProgrammeAccount.objects.filter(country=country, currency=currency, kind="programme",
                                           status="active").first()


@transaction.atomic
def create_escrow(by, *, kind, client, country, agreed_amount, currency=None, title="", report_id=None,
                  asset_id=None, project_id=None, case_id=None, bank_partner=None, parties=(), conditions=(),
                  held_back_amount=0, held_back_condition="", terms_version=None) -> Escrow:
    """FR-ESC-001. `parties`: [{"role", "person", "organisation", "name", "payee", "national_id_check",
    "must_accept"}]. `conditions`: [{"text", "key"}] added by staff besides the report's section 11."""
    from accounts.services import require_client_identity
    from administration.selectors import current_locked_text

    _on(country)
    if by.pk != client.pk and not has_role(by, "CM", "RV", country=country):
        raise Forbidden("A client proposes their own escrow; otherwise a case manager does.")
    if not client.has_tenmina_role("CL"):
        raise Invalid("The escrow's client must be a client.", code="validation-error")
    require_client_identity(client)
    currency = (currency or country.currency).upper()
    allowed = {country.currency} | set(cfg(country, f"escrow.price_currencies.{kind}", []) or [])
    if currency not in allowed:
        raise RuleBlocked(f"Prices in {country.name} are in {country.currency}.", code="price-currency",
                          blocking_reasons=[{"rule": "RUL-35", "message": f"{currency} is not allowed (Q-32)."}])
    agreed_amount = q(agreed_amount or 0)
    if kind != "held_funds" and agreed_amount <= 0:
        raise Invalid("Enter the agreed price.", code="validation-error")
    held_back_amount = q(held_back_amount or 0)
    if held_back_amount > 0:
        if not cfg(country, "escrow.held_back_share_allowed", False):
            raise RuleBlocked("A held-back share needs the lawyer's answer on record for this country.",
                              code="held-back-not-allowed",
                              blocking_reasons=[{"rule": "RUL-33", "message": "No answer to Q-30 is recorded."}])
        if kind == "held_funds" or held_back_amount >= agreed_amount or not held_back_condition:
            raise Invalid("A held-back share is part of the price and needs its own condition.",
                          code="validation-error")
    terms = terms_version or current_locked_text("escrow_terms", country)
    if terms is None:
        raise StateConflict("No escrow terms are published for this country.", code="escrow-terms-missing")
    report_conditions = []
    if kind == "purchase":
        if not report_id:
            raise Invalid("A purchase escrow starts from a released report.", code="validation-error")
        verdict, report_conditions = _report_facts(report_id)
        if verdict is None:
            raise StateConflict("This report is not released.", code="report-not-released")
        if verdict == "red":
            raise RuleBlocked("An escrow cannot be created on a red report.", code="report-red",
                              blocking_reasons=[{"rule": "US-ESC-001", "message": "The report's verdict is red."}])
        snap = ReportSnapshot.objects.filter(report_id=report_id).first()
        if snap is not None:
            asset_id = asset_id or snap.asset_id
            case_id = case_id or snap.case_id
    bank = _bank_for(country, bank_partner)
    e = Escrow.objects.create(
        country=country, reference=_new_reference(country), kind=kind, title=title or kind.replace("_", " ").title(),
        client=client, asset_id=asset_id, report_id=report_id, project_id=project_id, case_id=case_id,
        bank_partner=bank, agreed_amount=agreed_amount, held_back_amount=held_back_amount,
        held_back_condition=held_back_condition or "", currency=currency, terms_version=terms, created_by=by)
    Party.objects.create(escrow=e, role="buyer", person=client, name=client.full_name)
    Party.objects.create(escrow=e, role="tenmina", name="Tenmina", must_accept=kind != "held_funds")
    for pd in parties:
        add_party(e, by, **pd, _creating=True)
    for c in report_conditions:
        Condition.objects.create(escrow=e, source_condition_id=c.get("id"), key=c.get("key", ""), text=c["text"],
                                 created_by=by)
    for c in conditions:
        Condition.objects.create(escrow=e, key=c.get("key", ""), text=c["text"], created_by=by)
    if held_back_amount > 0:
        Condition.objects.create(escrow=e, key="held_back", text=held_back_condition, release_part="held_back",
                                 created_by=by)
    pa = _programme_account(country, currency)
    if pa is not None:
        e.programme_account = pa
        ref = adapters.bank_instructions().open_virtual_account(escrow=e, programme_account=pa, currency=currency)
        if ref:
            e.virtual_account_ref = ref
        e.save(update_fields=["programme_account", "virtual_account_ref"])
    audit(by, "escrow.proposed", e, {"kind": kind, "amount": f"{agreed_amount:.2f}", "currency": currency})
    publish("escrow.proposed", e.pk, _escrow_payload(e))
    return e


def open_held_funds(client, country, currency=None, *, by) -> Escrow:
    """FR-ESC-014: one held amount per client, country and currency. The
    client accepts the escrow terms; the bank issues its virtual account."""
    currency = (currency or country.currency).upper()
    existing = held_funds_for(client, country, currency)
    if existing is not None:
        return existing
    e = create_escrow(by, kind="held_funds", client=client, country=country, agreed_amount=0, currency=currency,
                      title=f"Held at the bank for {client.full_name}")
    if by.pk == client.pk:
        accept_terms(e, client)
    return e


def open_line_escrow(*, kind, client, country, agreed_amount, by, title="", currency=None, asset_id=None,
                     project_id=None, case_id=None, payees=(), conditions=()) -> Escrow:
    """For construction, off-plan, project fund, repair and event escrows
    (FR-ESC-010). `payees`: verified payees named in the terms, locked when
    the escrow is agreed (RUL-28)."""
    role = {"construction": "contractor", "offplan": "developer", "project_fund": "supplier",
            "repair": "contractor", "event": "vendor"}.get(kind, "supplier")
    parties = [{"role": role, "person": p.person, "organisation": p.organisation, "name": p.legal_name, "payee": p,
                "national_id_check": p.national_id_check, "must_accept": False} for p in payees]
    return create_escrow(by, kind=kind, client=client, country=country, agreed_amount=agreed_amount,
                         currency=currency, title=title, asset_id=asset_id, project_id=project_id, case_id=case_id,
                         parties=parties, conditions=conditions)


def add_party(e: Escrow, by, *, role, name="", person=None, organisation=None, payee=None, national_id_check=None,
              must_accept=True, _creating=False) -> Party:
    if not _creating:
        _on(e.country)
        _staff(by, e.country, "CM", "RV")
        if e.status != "proposed":
            raise StateConflict("Parties are added only while the escrow is proposed. After that, use a payee change.")
    if role not in Party.ROLES or role in ("buyer", "tenmina"):
        raise Invalid(f"Role '{role}' cannot be added.", code="validation-error")
    if payee is not None and payee.country_id != e.country_id:
        raise Invalid("The payee is registered in another country.", code="validation-error")
    p = Party.objects.create(escrow=e, role=role, person=person, organisation=organisation,
                             name=name or (payee.legal_name if payee else getattr(person, "full_name", "")),
                             payee=payee, national_id_check=national_id_check, must_accept=must_accept)
    audit(by, "escrow.party_added", e, {"role": role, "party_id": str(p.pk)})
    return p


@transaction.atomic
def record_virtual_account(e: Escrow, by, *, virtual_account_ref, programme_account=None) -> Escrow:
    """RUL-34, FR-ESC-019: the bank's virtual account number or reference for
    this escrow. Unique among open escrows; never a Tenmina account."""
    from administration.models import Partner
    from administration.services import account_bidx

    _on(e.country)
    _staff(by, e.country, "CM", "RV")
    if e.status not in ("proposed", "agreed"):
        raise StateConflict("The virtual account is recorded before the escrow takes money.")
    if e.virtual_account_ref and e.status != "proposed":
        raise StateConflict("This escrow already has its virtual account.")
    pa = programme_account or e.programme_account or _programme_account(e.country, e.currency)
    if pa is None or pa.status != "active" or pa.country_id != e.country_id or pa.currency != e.currency:
        raise StateConflict("There is no active programme escrow account for this country and currency.",
                            code="programme-account-missing")
    if pa.kind == "single_escrow" and Escrow.objects.filter(programme_account=pa).exclude(pk=e.pk).exists():
        raise StateConflict("A single-escrow account serves one escrow only.")
    ref = (virtual_account_ref or "").strip()
    if not ref:
        raise Invalid("Enter the virtual account number or reference the bank issued.", code="validation-error")
    bidx = account_bidx(ref)
    if Partner.objects.filter(kind__in=("operating_bank", "operating_mobile_money"), account_number_bidx=bidx).exists():
        audit(by, "escrow.tenmina_account_refused", e)
        alert_staff(e.country, ("RV",), "tenmina_account_refused",
                    f"Someone tried to record a Tenmina account as escrow {e.reference}'s virtual account.", obj=e)
        raise RuleBlocked("A Tenmina account can never receive escrow money.", code="tenmina-account-refused",
                          blocking_reasons=[{"rule": "RUL-01", "message": "Operating account refused"}])
    from .models import FxAccount

    if Escrow.objects.filter(programme_account=pa, virtual_account_ref=ref).exclude(pk=e.pk).exists() or \
            FxAccount.objects.filter(virtual_account_ref=ref).exists():
        alert_staff(e.country, ("RV",), "virtual_account_duplicate",
                    f"The virtual account {ref} is already used by another escrow.", obj=e)
        raise StateConflict("This virtual account is already used by another escrow or held amount.",
                            code="virtual-account-duplicate")
    e.programme_account, e.virtual_account_ref = pa, ref
    e.save(update_fields=["programme_account", "virtual_account_ref"])
    audit(by, "escrow.virtual_account_recorded", e, {"ref_last4": ref[-4:]})
    try_agree(e)
    return e


@transaction.atomic
def set_terms_version(e: Escrow, by, terms_version) -> Escrow:
    """US-ESC-002 AC2: new terms need everyone's acceptance again; earlier
    acceptances stay on the old version."""
    _on(e.country)
    _staff(by, e.country, "CM", "RV")
    if e.status != "proposed":
        raise StateConflict("Terms change only while the escrow is proposed.")
    if terms_version.kind != "escrow_terms" or terms_version.status != "published" \
            or terms_version.country_id != e.country_id:
        raise Invalid("Use a published escrow terms version of this country.", code="validation-error")
    e.terms_version = terms_version
    e.save(update_fields=["terms_version"])
    audit(by, "escrow.terms_changed", e, {"terms_version": str(terms_version.pk)})
    for person in _parties_to_tell(e):
        notify(person, "escrow_terms_changed", f"The terms of escrow {e.reference} changed. Please read and accept "
                                               "the new version.", needs_action=True, obj=e, link=f"/escrows/{e.pk}")
    return e


def _party_for(e: Escrow, person):
    return Party.objects.filter(escrow=e, person=person, must_accept=True).first()


@transaction.atomic
def accept_terms(e: Escrow, by, *, party=None, evidence=None) -> Acceptance:
    """FR-ESC-002: a party accepts the current terms version. Staff record the
    Tenmina acceptance, or a signed paper acceptance with evidence."""
    _on(e.country)
    if e.status != "proposed":
        raise StateConflict("The terms are already agreed.")
    on_behalf = False
    if party is None:
        party = _party_for(e, by)
        if party is None:
            if is_staff(by, e.country):
                party = Party.objects.filter(escrow=e, role="tenmina").first()
            else:
                raise NotFound()
    elif party.person_id != by.pk:
        if not has_role(by, "CM", "RV", country=e.country):
            raise Forbidden("You can only accept for yourself.")
        if party.role != "tenmina":
            on_behalf = True
            if evidence is None:
                raise Invalid("Attach the party's signed acceptance.", code="validation-error")
    if party.role == "tenmina" and not is_staff(by, e.country):
        raise Forbidden()
    existing = Acceptance.objects.filter(party=party, terms_version=e.terms_version).first()
    if existing:
        return existing
    a = Acceptance.objects.create(escrow=e, party=party, terms_version=e.terms_version,
                                  terms_sha256=e.terms_version.text_sha256, accepted_by=by, on_behalf=on_behalf,
                                  evidence=evidence)
    audit(by, "escrow.terms_accepted", e, {"party": party.role, "terms_version": str(e.terms_version_id),
                                           "on_behalf": on_behalf})
    try_agree(e)
    return a


def agreement_blockers(e: Escrow) -> list[dict]:
    from accounts.services import national_id_blockers

    out = []
    for p in Party.objects.filter(escrow=e, must_accept=True):
        if not Acceptance.objects.filter(party=p, terms_version=e.terms_version).exists():
            out.append({"rule": "FR-ESC-002", "code": "acceptance-missing",
                        "message": f"{p.name or p.role.title()} has not accepted terms version "
                                   f"{e.terms_version.version}."})
    if not e.programme_account_id or not e.virtual_account_ref:
        out.append({"rule": "RUL-34", "code": "virtual-account-missing",
                    "message": "The bank has not issued this escrow's virtual account yet."})
    payee_parties = Party.objects.filter(escrow=e, payee__isnull=False).select_related("payee")
    if e.kind == "purchase" and not payee_parties.filter(role__in=("seller", "developer")).exists():
        out.append({"rule": "RUL-22", "code": "payee-missing", "message": "Name the seller's verified payee."})
    for p in payee_parties:
        if p.payee.verification_status != "verified" or p.payee.name_match != "matched":
            out.append({"rule": "RUL-22", "code": "payee-not-verified",
                        "message": f"The payee {p.payee.legal_name} is not verified."})
    for p in Party.objects.filter(escrow=e, role__in=("seller", "developer")):
        out.extend(national_id_blockers({f"{p.role.title()} {p.name}": p.national_id_check or (
            p.payee.national_id_check if p.payee_id else None)}))
    return out


def try_agree(e: Escrow) -> bool:
    e.refresh_from_db()
    if e.status != "proposed" or agreement_blockers(e):
        return False
    t = now()
    e.agreed_at = t
    e.save(update_fields=["agreed_at"])
    buyer = Party.objects.filter(escrow=e, role="buyer").first()
    acc = Acceptance.objects.filter(party=buyer, terms_version=e.terms_version).first() if buyer else None
    for p in Party.objects.filter(escrow=e, payee__isnull=False).select_related("payee"):
        lock_payee(e, p.payee, client_approved_at=acc.accepted_at if acc else t, source="terms_agreed")
    state.transition(e, "escrow", "agreed", event="escrow.agreed", payload=_escrow_payload(e))
    for person in _parties_to_tell(e):
        notify(person, "escrow_agreed", f"Escrow {e.reference} is agreed. Pay the bank only, using the bank's "
                                        "payment instructions in the app. Never pay Tenmina.", obj=e,
               link=f"/escrows/{e.pk}", category="money")
    return True


def payment_instructions(e: Escrow) -> dict:
    """FR-ESC-003, RUL-01: only the bank's details, never a Tenmina account."""
    if e.status == "proposed" or not e.virtual_account_ref:
        return {"available": False, "message": "The bank's payment details appear once the escrow is agreed."}
    pa, bank = e.programme_account, e.bank_partner
    out = {"available": True, "bank_name": pa.bank_partner.bank_name or bank.name, "account_name": pa.account_name,
           "account_number": pa.account_number, "virtual_account_ref": e.virtual_account_ref,
           "reference": e.reference, "currency": e.currency,
           "note": "Pay the bank, never Tenmina. Use this escrow's own reference so the bank credits it.",
           "foreign_currency_accounts": []}
    for fx in e.fx_accounts.select_related("programme_account").filter(closed_at__isnull=True):
        out["foreign_currency_accounts"].append({"currency": fx.currency, "account_name": fx.programme_account
                                                 .account_name, "account_number": fx.programme_account.account_number,
                                                 "virtual_account_ref": fx.virtual_account_ref})
    return out


# ----------------------------------------------------------------- fresh search and conditions

@transaction.atomic
def record_fresh_search(e: Escrow, by, *, case_id, registry_result_date, site_check_date) -> Escrow:
    """RUL-07: the fresh-search case, the date on the registry's result and the
    date of the site check (FR-CASE-014 publishes fresh_search.completed)."""
    _on(e.country)
    if by is not None:
        _staff(by, e.country, "CM", "RV")
    if e.status in ("released", "cancelled"):
        raise StateConflict("This escrow is closed.")
    if registry_result_date and registry_result_date > local_today(e.country):
        raise Invalid("The result date cannot be in the future.", code="validation-error")
    e.fresh_search_case_id, e.fresh_search_result_date, e.site_check_date = \
        case_id, registry_result_date, site_check_date
    e.save(update_fields=["fresh_search_case_id", "fresh_search_result_date", "site_check_date"])
    audit(by, "escrow.fresh_search_recorded", e, {"case_id": str(case_id), "result_date": str(registry_result_date),
                                                  "site_check_date": str(site_check_date)})
    sync_status(e)
    return e


@transaction.atomic
def add_condition(e: Escrow, by, *, text, key="") -> Condition:
    _on(e.country)
    _staff(by, e.country, "CM", "RV")
    if e.status in ("released", "cancelled"):
        raise StateConflict("This escrow is closed.")
    if not text:
        raise Invalid("Describe the condition.", code="validation-error")
    c = Condition.objects.create(escrow=e, text=text, key=key or "", created_by=by)
    audit(by, "escrow.condition_added", e, {"condition_id": str(c.pk)})
    _invalidate_client_approvals(e, "main", by, "A new condition was added")
    sync_status(e)
    return c


def _evidence_objects(ids, by, country):
    from evidence import access
    from evidence.models import Evidence

    out = []
    for i in ids or ():
        ev = Evidence.objects.filter(pk=i).first()
        if ev is None or not access.can_view(by, ev):
            raise Invalid(f"Evidence {i} was not found.", code="validation-error")
        out.append(ev)
    return out


@transaction.atomic
def close_condition(c: Condition, by, *, evidence_ids, note="") -> Condition:
    """FR-ESC-005: closed only with evidence that satisfies it, by staff."""
    from evidence.services import link

    e = c.escrow
    _on(e.country)
    if not has_role(by, "CM", "RV", country=e.country):
        raise Forbidden("Only a case manager or reviewer closes a condition.")
    if c.status != "open":
        raise StateConflict("This condition is already closed.")
    evs = _evidence_objects(evidence_ids, by, e.country)
    if not evs:
        raise Invalid("Attach the evidence that satisfies this condition.", code="evidence-required",
                      blocking_reasons=[{"rule": "FR-ESC-005", "message": "No evidence attached"}])
    for ev in evs:
        link(ev, "escrow_condition", c.pk, role="condition_evidence", by=by)
    c.closed_by, c.closed_at, c.closed_note = by, now(), note or ""
    state.transition(c, "esc_condition", "closed", actor=by, event="condition.closed",
                     extra_fields=["closed_by", "closed_at", "closed_note"],
                     payload={"condition_id": c.pk, "escrow_id": e.pk, "release_part": c.release_part,
                              "evidence_ids": [str(x.pk) for x in evs]})
    if not Condition.objects.filter(escrow=e, release_part=c.release_part, status="open").exists():
        publish("release.clock_started", e.pk, _escrow_payload(e, release_part=c.release_part,
                                                               started_at=c.closed_at))
    sync_status(e)
    return c


@transaction.atomic
def reopen_condition(c: Condition, by, *, reason) -> Condition:
    """A reviewer's hold in R1 (TC-ESC-006-03): reopening blocks the release
    and voids the client's approval of it (TC-ESC-006-06)."""
    e = c.escrow
    if not has_role(by, "RV", country=e.country):
        raise Forbidden("Only a reviewer reopens a condition.")
    if c.status != "closed":
        raise StateConflict("This condition is open.")
    if not reason:
        raise Invalid("Give the reason.", code="validation-error")
    c.reopened_by, c.reopened_at, c.reopen_reason = by, now(), reason
    c.closed_by = c.closed_at = None
    state.transition(c, "esc_condition", "open", actor=by, reason=reason,
                     extra_fields=["reopened_by", "reopened_at", "reopen_reason", "closed_by", "closed_at"])
    _invalidate_client_approvals(e, c.release_part, by, f"Condition reopened: {reason}")
    sync_status(e)
    return c


def _invalidate_client_approvals(e, release_part, by, reason):
    for ins in ReleaseInstruction.objects.filter(escrow=e, release_part=release_part,
                                                 kind__in=("release", "partial_release"),
                                                 status__in=("pending_approval", "approved")):
        if ins.status == "approved":
            withdraw_instruction(ins, by, reason=reason, system=True)
            continue
        if ins.approval_request.status == "open":
            approvals.withdraw(ins.approval_request, by)
        ins.approval_request = approvals.request_approval(
            "escrow_release", ins.pk, ins.prepared_by, required=2, country=e.country,
            summary=f"{ins.kind.replace('_', ' ')} {fmt(ins.amount, ins.currency)} from {e.reference}")
        ins.client_approved_at = ins.client_approved_by = ins.client_approved_amount = None
        ins.client_approval_method = ""
        ins.save(update_fields=["approval_request", "client_approved_at", "client_approved_by",
                                "client_approved_amount", "client_approval_method"])
        state.transition(ins, "release_instruction", "awaiting_client", actor=by, reason=reason)
        notify(e.client, "release_approval_again", f"{reason}. Please review and approve the payment again.",
               needs_action=True, obj=ins, link=f"/release-instructions/{ins.pk}", category="approval")


# ----------------------------------------------------------------- status of single-release escrows (01 C8)

def _main_release_amount(e: Escrow) -> Decimal:
    return e.agreed_amount - e.held_back_amount


def sync_status(e: Escrow):
    """Keep a purchase escrow's status in step with its release (01 C8).
    Staged kinds (held funds, construction, ...) live in funded or partly
    released; each instruction carries its own state."""
    e.refresh_from_db()
    if e.status in ("proposed", "agreed", "frozen", "released", "cancelled"):
        return e
    released_main = ReleaseInstruction.objects.filter(escrow=e, kind="release", release_part="main",
                                                      status="confirmed").exists()
    if e.is_staged:
        return e
    part = "held_back" if released_main else "main"
    live = ReleaseInstruction.objects.filter(escrow=e, kind="release", release_part=part,
                                             status__in=["awaiting_client", "pending_approval", "approved",
                                                         "sent"]).first()
    if live is not None:
        target = {"awaiting_client": "ready_to_release", "pending_approval": "client_approved",
                  "approved": "release_approved", "sent": "release_approved"}[live.status]
    else:
        amount = e.held_back_amount if released_main else _main_release_amount(e)
        ready = (not open_condition_reasons(e, part) and not fresh_search_reasons(e)
                 and selectors.available_to_instruct(e) >= amount > 0)
        if released_main:
            target = "ready_to_release" if ready else "partly_released"
        else:
            target = "ready_to_release" if ready else "funded"
    ev = "escrow.ready" if target == "ready_to_release" else None
    return _route(e, target, event=ev, payload=_escrow_payload(e) if ev else None)


# ----------------------------------------------------------------- releases (5.3, FR-ESC-006 to 010)

def release_allowed(ins):
    def ok(a):
        if not has_rr(a, ins.country):
            return False
        if a.pk == ins.escrow.client_id:
            return False
        if ins.payee_id and ins.payee.person_id == a.pk:
            return False
        return True

    return ok


def _default_payee(e):
    locks = EscrowPayee.objects.filter(escrow=e, ended_at__isnull=True,
                                       payee__kind__in=("seller", "developer")).select_related("payee")
    payees = {lk.payee for lk in locks}
    return payees.pop() if len(payees) == 1 else None


def _clock_start(e, release_part):
    last = Condition.objects.filter(escrow=e, release_part=release_part, status="closed").aggregate(
        m=Max("closed_at"))["m"]
    return last or now()


@transaction.atomic
def request_release(e: Escrow, *, payee=None, amount=None, subject_type=None, subject_id=None, requested_by,
                    evidence_ids=(), reason="", subject_label="", family_member_id=None, holdback_amount=0,
                    currency=None, kind=None, release_part="main", standing_approval=None) -> ReleaseInstruction:
    """Prepare a release (whole or staged) to one verified payee. Blocked with
    every reason when a rule is not met (FR-ESC-006, RUL-05 to RUL-36)."""
    from evidence.services import link

    _on(e.country)
    if not has_role(requested_by, "CM", "RV", country=e.country):
        raise Forbidden("A case manager prepares release instructions.")
    e.refresh_from_db()
    if kind is None:
        kind = "partial_release" if (subject_id or e.is_staged) else "release"
    if kind not in ("release", "partial_release"):
        raise Invalid("Use request_cancellation for refunds and the conversion flow for conversions.",
                      code="validation-error")
    if kind == "partial_release" and not subject_id:
        raise Invalid("A staged release names the milestone, invoice, visit or task it pays.",
                      code="validation-error")
    if release_part == "held_back" and e.held_back_amount <= 0:
        raise RuleBlocked("These escrow terms set no held-back share.", code="held-back-not-allowed",
                          blocking_reasons=[{"rule": "RUL-33", "message": "No held-back share in the terms."}])
    if not e.is_staged and kind == "release":
        expected = e.held_back_amount if release_part == "held_back" else _main_release_amount(e)
        if amount is not None and q(amount) != expected:
            raise RuleBlocked("A purchase release pays the agreed amount. Holding back part of it is allowed only "
                              "where the escrow terms set a held-back share.", code="release-amount",
                              blocking_reasons=[{"rule": "RUL-33",
                                                 "message": f"The release must be {fmt(expected, e.currency)}."}])
        amount = expected
        payee = payee or _default_payee(e)
    if amount is None or q(amount) <= 0:
        raise Invalid("Enter the amount.", code="validation-error")
    if payee is None:
        raise RuleBlocked("Every release names one verified payee.", code="payee-not-verified",
                          blocking_reasons=[{"rule": "RUL-22", "message": "No payee named."}])
    if subject_type and subject_type not in dict(ReleaseInstruction._meta.get_field("subject_type").choices):
        raise Invalid(f"Unknown subject type '{subject_type}'.", code="validation-error")
    iid = uuid7()
    ins = ReleaseInstruction(
        id=iid, country=e.country, escrow=e, kind=kind, subject_type=subject_type, subject_id=subject_id,
        subject_label=subject_label or registry.label_for(subject_type, subject_id) or reason or "",
        family_member_id=family_member_id, payee=payee, payee_account_version=payee.account_version,
        standing_approval=standing_approval, amount=q(amount), holdback_amount=q(holdback_amount or 0),
        currency=(currency or e.currency).upper(), prepared_by=requested_by, reason=reason or "",
        release_part=release_part, clock_started_at=_clock_start(e, release_part))
    raise_if_blocked(ins, "prepare")
    ins.approval_request = approvals.request_approval(
        "escrow_release", iid, requested_by, required=2, country=e.country,
        summary=f"{kind.replace('_', ' ')} {fmt(ins.amount, ins.currency)} to {payee.legal_name} from {e.reference}")
    from .blockers import standing_approval_covers

    covered = standing_approval is not None and standing_approval_covers(ins) is not None
    ins.status = "pending_approval" if covered else "awaiting_client"
    if covered:
        ins.client_approval_method = "standing"
        ins.staff_approval_due_on = add_working_days(e.country, local_today(e.country), int(
            cfg(e.country, "release.staff_approvals_within_working_days", 1)))
    try:
        with transaction.atomic():
            ins.save(force_insert=True)
    except IntegrityError as exc:
        raise StateConflict("There is already a live instruction for this payment.",
                            code="instruction-exists") from exc
    for ev in _evidence_objects(evidence_ids, requested_by, e.country):
        link(ev, "escrow_instruction", ins.pk, role="release_evidence", by=requested_by)
    audit(requested_by, "release.requested", ins, {"amount": f"{ins.amount:.2f}", "payee_id": str(payee.pk)})
    publish("release.requested", ins.pk, _client_payload(ins))
    if not Condition.objects.filter(escrow=e, release_part=release_part).exists():
        publish("release.clock_started", ins.pk, _client_payload(ins, started_at=ins.clock_started_at))
    if ins.status == "awaiting_client":
        promise = int(cfg(e.country, "release.client_promise_working_days", 3))
        notify(e.client, "approval_needed",
               f"Please approve {fmt(ins.amount, ins.currency)} to {payee.legal_name} (account ending {payee.last4}) "
               f"for {ins.subject_label or e.reference}. Nothing is paid until you approve. Once you approve, the "
               f"payee is paid within {promise} working days.", subject="Your approval is needed",
               needs_action=True, obj=ins, link=f"/release-instructions/{ins.pk}", category="approval",
               context={"subject_label": ins.subject_label or e.reference,
                        "link": f"/release-instructions/{ins.pk}"})
    else:
        _alert_approvers(ins)
    sync_status(e)
    return ins


def _alert_approvers(ins):
    for p in selectors_rr_staff(ins.country):
        if p.pk == ins.prepared_by_id:
            continue
        notify(p, "release_approval_needed",
               f"{fmt(ins.amount, ins.currency)} to {ins.payee.legal_name if ins.payee_id else 'source accounts'} "
               f"from {ins.escrow.reference} waits for two approvals.", needs_action=True, obj=ins,
               link=f"/back-office/release-instructions/{ins.pk}", category="approval")


def selectors_rr_staff(country):
    from .common import staff_in

    return [p for p in staff_in(country, "RR") if is_staff(p, country)]


@transaction.atomic
def client_approve(ins: ReleaseInstruction, client, mfa_at=None, *, code=None) -> ReleaseInstruction:
    """RUL-11: the client approves first, by press and hold with a fresh MFA
    step-up or an authenticator code. Silence is never approval."""
    e = ins.escrow
    _on(e.country)
    if e.client_id != client.pk:
        raise NotFound()
    ins.refresh_from_db()
    if ins.status != "awaiting_client":
        raise StateConflict("This payment is not waiting for your approval.")
    if ins.kind == "conversion":
        raise StateConflict("Approve a conversion by accepting its quote.")
    method = _client_signed(client, mfa_at, code)
    raise_if_blocked(ins, "client")
    t = now()
    if e.kind == "held_funds" and ins.payee_id and not EscrowPayee.objects.filter(escrow=e, payee=ins.payee).exists():
        lock_payee(e, ins.payee, client_approved_at=t, source="client_approved_payment")
    ins.client_approved_at, ins.client_approved_by, ins.client_approval_method = t, client, method
    ins.client_approved_amount = ins.amount
    ins.staff_approval_due_on = add_working_days(e.country, local_date(e.country, t), int(
        cfg(e.country, "release.staff_approvals_within_working_days", 1)))
    state.transition(ins, "release_instruction", "pending_approval", actor=client, event="release.client_approved",
                     extra_fields=["client_approved_at", "client_approved_by", "client_approval_method",
                                   "client_approved_amount", "staff_approval_due_on"],
                     payload=_client_payload(ins))
    from notifications.services import resolve_action

    resolve_action(ins)
    promise = int(cfg(e.country, "release.client_promise_working_days", 3))
    paid_by = add_working_days(e.country, local_date(e.country, t), promise)
    notify(client, "release_client_approved",
           f"Thank you. Two Tenmina staff now check and approve. The payee is paid within {promise} working days of "
           f"your approval, by {paid_by:%d %B %Y}.", obj=ins, link=f"/release-instructions/{ins.pk}",
           category="money")
    _alert_approvers(ins)
    sync_status(e)
    return ins


@transaction.atomic
def client_decline(ins: ReleaseInstruction, client, reason="") -> ReleaseInstruction:
    e = ins.escrow
    if e.client_id != client.pk:
        raise NotFound()
    if ins.status != "awaiting_client":
        raise StateConflict("This payment is not waiting for your approval.")
    ins.client_declined_at, ins.closed_reason = now(), reason or "Declined by the client"
    if ins.approval_request.status == "open":
        approvals.withdraw(ins.approval_request, client)
    state.transition(ins, "release_instruction", "rejected", actor=client, event="release.rejected",
                     extra_fields=["client_declined_at", "closed_reason"], payload=_client_payload(ins))
    alert_staff(e.country, ("CM",), "release_declined", f"The client declined the payment from {e.reference}: "
                                                        f"{ins.closed_reason}.", obj=ins)
    sync_status(e)
    return ins


def staff_approve(ins: ReleaseInstruction, approver, *, mfa_at, decision="approve", confirm_amount=None, note=""):
    """RUL-05: two different staff with release rights, each with a fresh
    MFA step-up, after the client. The payee, subject and funds checks run again."""
    e = ins.escrow
    _on(e.country)
    ins.refresh_from_db()
    if ins.status == "awaiting_client":
        raise RuleBlocked("The client has not approved this release. Silence is never approval.",
                          blocking_reasons=[{"rule": "RUL-11", "code": "client-approval-missing",
                                             "message": "The client approves first."}])
    if ins.status != "pending_approval":
        raise StateConflict(f"This instruction is {ins.status.replace('_', ' ')}.")
    if confirm_amount is not None:
        amt = confirm_amount.get("amount") if isinstance(confirm_amount, dict) else confirm_amount
        cur = confirm_amount.get("currency", ins.currency) if isinstance(confirm_amount, dict) else ins.currency
        if q(amt) != ins.amount or str(cur).upper() != ins.currency:
            raise Invalid("The amount you confirmed is not the instruction's amount.", code="amount-mismatch")
    if decision == "approve":
        raise_if_blocked(ins, "staff")
    return approvals.decide(ins.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=release_allowed(ins))


@transaction.atomic
def on_instruction_approved(ins: ReleaseInstruction):
    """Both staff approved: the instruction is approved and dispatched at once,
    with no waiting period (RUL-33)."""
    ins.refresh_from_db()
    if ins.status != "pending_approval":
        return ins
    t = now()
    ins.last_approval_at = t
    ins.send_due_on = working_day_on_or_after(ins.country, local_date(ins.country, t))
    approvers = [a.approver.full_name for a in ins.approval_request.approvals.filter(decision="approve")
                 .select_related("approver").order_by("approved_at")]
    state.transition(ins, "release_instruction", "approved", event="release.approved",
                     extra_fields=["last_approval_at", "send_due_on"],
                     payload=_client_payload(ins, approvers=approvers, send_due_on=ins.send_due_on))
    sync_status(ins.escrow)
    return ins


@transaction.atomic
def on_instruction_rejected(ins: ReleaseInstruction):
    ins.refresh_from_db()
    if ins.status not in ("pending_approval", "awaiting_client"):
        return ins
    state.transition(ins, "release_instruction", "rejected", event="release.rejected",
                     reason="A staff member rejected it", payload=_client_payload(ins))
    sync_status(ins.escrow)
    return ins


@transaction.atomic
def withdraw_instruction(ins: ReleaseInstruction, by, *, reason, system=False) -> ReleaseInstruction:
    ins.refresh_from_db()
    if not system and not has_role(by, "CM", "RV", country=ins.country):
        raise Forbidden("Only staff withdraw an instruction.")
    if ins.status not in ("draft", "awaiting_client", "pending_approval", "approved"):
        raise StateConflict("Only an instruction not yet sent can be withdrawn.")
    if ins.approval_request.status == "open":
        approvals.withdraw(ins.approval_request, by or ins.prepared_by)
    ins.closed_reason = reason
    ins.save(update_fields=["closed_reason"])
    state.transition(ins, "release_instruction", "withdrawn", actor=by, event="release.withdrawn", reason=reason,
                     payload=_client_payload(ins))
    sync_status(ins.escrow)
    return ins


# ----------------------------------------------------------------- dispatch (FR-ESC-008, IF-01, 9.1)

def _document(ins: ReleaseInstruction) -> dict:
    e = ins.escrow
    approvals_ = [{"slot": a.slot, "approver": a.approver.full_name, "at": a.approved_at.isoformat()}
                  for a in ins.approval_request.approvals.filter(decision="approve").select_related("approver")
                  .order_by("approved_at")]
    doc = {
        "format": "tenmina-instruction-v1 [TO VERIFY with the bank]", "instruction_id": str(ins.pk),
        "kind": ins.kind, "escrow_reference": e.reference, "bank_reference": e.bank_reference,
        "programme_account": {"name": e.programme_account.account_name,
                              "number_last4": e.programme_account.last4},
        "pay_from_virtual_account": e.virtual_account_ref if ins.currency == e.currency else
        next((fx.virtual_account_ref for fx in e.fx_accounts.all() if fx.currency == ins.currency), ""),
        "amount": f"{ins.amount:.2f}", "currency": ins.currency, "holdback": f"{ins.holdback_amount:.2f}",
        "value_date": "immediate (no later value date, RUL-33)",
        "conditions_closed": [{"text": c.text, "closed_at": c.closed_at.isoformat() if c.closed_at else None}
                              for c in e.conditions.filter(status="closed", release_part=ins.release_part)],
        "client_approved_at": ins.client_approved_at.isoformat() if ins.client_approved_at else None,
        "approvals": approvals_, "subject": {"type": ins.subject_type, "id": str(ins.subject_id or ""),
                                             "label": ins.subject_label},
    }
    if ins.payee_id:
        p = ins.payee
        doc["payee"] = {"name": p.account_name, "kind": p.kind, "bank": p.bank_name,
                        "account_number": p.account_number, "account_version": p.account_version}
    if ins.release_part == "main" and e.held_back_amount and ins.kind == "release":
        doc["held_back_share"] = {"amount": f"{e.held_back_amount:.2f}", "condition": e.held_back_condition}
    if ins.kind == "cancel_refund":
        dep = ins.refund_source_event
        if ins.refund_change_id:
            ch = ins.refund_change
            doc["refund_to"] = {"basis": "RUL-29 exception: account in the client's own name",
                                "name": ch.account_name, "bank": ch.bank_name, "account_number": ch.account_number}
        else:
            doc["refund_to"] = {"basis": "source of the deposit", "name": dep.source_account_name,
                                "bank": dep.source_bank_name, "account_number": dep.source_account_number}
        doc["refunds_deposit"] = {"bank_reference": dep.bank_reference, "date": dep.occurred_at.date().isoformat()}
    if ins.kind == "conversion":
        qt = ins.fx_quote
        doc["conversion"] = {"to_currency": ins.to_currency, "quote_id": str(qt.pk),
                             "offered_rate": str(qt.offered_rate), "margin_pct": str(qt.margin_pct),
                             "expected_to_amount": f"{qt.expected_to_amount:.2f}",
                             "programme_rate_id": str(qt.programme_rate_id or ""),
                             "report": "Report the rate and fees applied."}
    return doc


def _instruction_bytes(doc) -> bytes:
    import json

    return json.dumps(doc, sort_keys=True, indent=1).encode()


def dispatch(ins: ReleaseInstruction) -> ReleaseInstruction:
    """escrow.dispatch_instruction: runs on release.approved at once. Re-checks
    every blocker, signs the instruction and sends it by the agreed channel.
    A failure leaves the instruction approved and alerts the case manager."""
    from evidence.services import store, verify

    ins.refresh_from_db()
    if ins.status != "approved":
        return ins
    e = ins.escrow
    reasons = _release_blockers(ins, "send")
    if reasons:
        codes = {r["code"] for r in reasons}
        ins.last_send_error = "; ".join(r["message"] for r in reasons)[:2000]
        fields = ["last_send_error"]
        if "held-funds-insufficient" in codes and ins.shortfall_since is None:
            ins.shortfall_since = now()
            short = next(r for r in reasons if r["code"] == "held-funds-insufficient")["shortfall"]
            ins.shortfall_amount = Decimal(short["amount"])
            fields += ["shortfall_since", "shortfall_amount"]
            publish("escrow.fx_shortfall", e.pk, _client_payload(ins, shortfall=short))
            notify(e.client, "escrow_top_up",
                   f"Your escrow {e.reference} is short by {fmt(short['amount'], short['currency'])} for this "
                   "payment. Please top up at the bank; the payment waits until the bank confirms it.",
                   needs_action=True, obj=e, link=f"/escrows/{e.pk}", category="money")
        ins.save(update_fields=fields)
        audit(None, "release.dispatch_blocked", ins, {"reasons": reasons})
        alert_staff(e.country, ("CM", "RV"), "release_dispatch_blocked",
                    f"The instruction from {e.reference} was not sent: {ins.last_send_error}", obj=ins)
        return ins
    signer = adapters.signer()
    if ins.document_evidence_id:
        if not verify(ins.document_evidence) or ins.document_evidence.sha256 != ins.document_sha256 \
                or not signer.verify(ins.document_sha256, ins.kms_signature):
            ins.last_send_error = "The signed instruction no longer matches its hash. Sending is blocked."
            ins.save(update_fields=["last_send_error"])
            audit(None, "release.signature_check_failed", ins)
            alert_staff(e.country, ("RV", "CM"), "release_tampered",
                        f"The signed instruction for {e.reference} failed its integrity check. It was not sent.",
                        obj=ins)
            return ins
        from core.adapters import get_adapter

        data = get_adapter("evidence_store").get(ins.document_evidence.storage_key)
    else:
        data = _instruction_bytes(_document(ins))
        ev = store(data=data, country=e.country, content_type="application/json", source="generated",
                   original_name=f"instruction-{ins.pk}.json", data_class="escrow_payment", owner_type="escrow",
                   owner_id=e.pk, description=f"Signed {ins.kind.replace('_', ' ')} instruction")
        from evidence.services import link

        link(ev, "escrow_instruction", ins.pk, role="instruction_document")
        ins.document_evidence, ins.document_sha256 = ev, ev.sha256
        ins.kms_signature, ins.signature_key_id = signer.sign(ev.sha256), getattr(signer, "key_id", "")
        ins.save(update_fields=["document_evidence", "document_sha256", "kms_signature", "signature_key_id"])
    ins.send_attempts += 1
    try:
        res = adapters.bank_instructions().send(instruction=ins, document=data, signature=ins.kms_signature,
                                                recipient=e.bank_partner.contact_email)
    except Exception as exc:  # noqa: BLE001 - every channel failure is recorded, never raised to the approver
        ins.last_send_error = str(exc)[:2000]
        ins.save(update_fields=["send_attempts", "last_send_error"])
        audit(None, "release.send_failed", ins, {"error": ins.last_send_error})
        alert_staff(e.country, ("CM",), "release_send_failed",
                    f"The instruction from {e.reference} could not be sent: {exc}. It stays approved and is sent once "
                    "the channel returns.", obj=ins)
        return ins
    sent_at = res.get("sent_at") or now()
    ins.sent_at, ins.sent_channel = sent_at, res.get("channel", "")
    ins.sent_recipient, ins.sent_reference = res.get("recipient", ""), res.get("reference", "")
    ins.bank_pay_due_on = add_working_days(e.country, local_date(e.country, sent_at), int(
        setting("release_bank_pay_working_days", e.country, 2)))
    ins.last_send_error, ins.shortfall_since, ins.shortfall_amount = "", None, None
    state.transition(ins, "release_instruction", "sent", event="release.sent",
                     extra_fields=["sent_at", "sent_channel", "sent_recipient", "sent_reference", "bank_pay_due_on",
                                   "send_attempts", "last_send_error", "shortfall_since", "shortfall_amount"],
                     payload=_client_payload(ins, sent_at=sent_at, channel=ins.sent_channel))
    return ins


def retry_unsent(limit=200) -> int:
    """Approved instructions not yet sent are retried (TC-ESC-008-03). Never sent twice."""
    n = 0
    for ins in ReleaseInstruction.objects.filter(status="approved").order_by("last_approval_at")[:limit]:
        with transaction.atomic():
            if dispatch(ins).status == "sent":
                n += 1
    return n


# ----------------------------------------------------------------- bank events (FR-ESC-004, 009, 017, 019)

def _match_account(e: Escrow, virtual_account_ref):
    if e.virtual_account_ref and virtual_account_ref == e.virtual_account_ref:
        return e.programme_account, e.currency
    fx = e.fx_accounts.filter(virtual_account_ref=virtual_account_ref).first()
    if fx is not None:
        return fx.programme_account, fx.currency
    return None, None


@transaction.atomic
def record_bank_event(e: Escrow, *, kind, amount, bank_reference, occurred_at=None, virtual_account_ref=None,
                      source="manual", by=None, proof_evidence=None, currency=None, instruction=None,
                      source_bank_name="", source_account_number="", source_account_name="",
                      source_account_known=True, deposit_route="", transfer_partner=None, partner_reference="",
                      applied_rate=None, applied_fees=None, statement_line=None, misdirected=False,
                      note="") -> BankEvent:
    """What the bank reports. A manual entry needs the bank's confirmation
    attached and a second staff member's check before it counts."""
    from administration.services import account_bidx

    _on(e.country)
    if source == "manual":
        if by is None or not has_role(by, "CM", "RV", country=e.country):
            raise Forbidden("Only a case manager or reviewer records the bank's confirmation.")
        if proof_evidence is None:
            raise Invalid("Attach the bank's confirmation. A deposit is never recorded on a client's word.",
                          code="bank-confirmation-required",
                          blocking_reasons=[{"rule": "FR-ESC-004", "message": "No bank confirmation attached"}])
    if e.status == "proposed":
        raise StateConflict("The escrow is not agreed yet; the bank has no account for it.")
    if kind not in BankEvent.KINDS:
        raise Invalid(f"Unknown event kind '{kind}'.", code="validation-error")
    ref = virtual_account_ref or e.virtual_account_ref
    pa, cur = _match_account(e, ref)
    if pa is None:
        raise RuleBlocked("This line's virtual account is not this escrow's. It stays in the unmatched queue; it "
                          "counts only where the bank credited it.", code="virtual-account-mismatch",
                          blocking_reasons=[{"rule": "RUL-34", "message": f"Reference {ref} is not this escrow's."}])
    if currency and currency.upper() != cur:
        raise Invalid(f"This virtual account holds {cur}.", code="validation-error")
    if kind == "deposit":
        if source_account_known and not (source_account_number and source_account_name):
            raise Invalid("Record the source account exactly as the bank's confirmation gives it, or say the bank "
                          "gave none.", code="deposit-source-required",
                          blocking_reasons=[{"rule": "RUL-29", "message": "No source account recorded"}])
        if transfer_partner is not None and not source_account_number:
            source_account_known = False
    if kind in ("release_confirmed", "refund_confirmed", "conversion_debit"):
        if instruction is None or instruction.escrow_id != e.pk:
            raise Invalid("Name the instruction the bank confirms.", code="validation-error")
        if instruction.status != "sent":
            raise StateConflict("Only a sent instruction can be confirmed. Without a sent instruction, nothing is "
                                "marked released.", code="instruction-not-sent")
        expected = "refund_confirmed" if instruction.kind == "cancel_refund" else \
            "conversion_debit" if instruction.kind == "conversion" else "release_confirmed"
        if kind != expected:
            raise Invalid(f"A {instruction.kind.replace('_', ' ')} is confirmed as {expected}.",
                          code="validation-error")
        if q(amount) != instruction.amount or cur != instruction.currency:
            alert_staff(e.country, ("RV",), "bank_confirmation_mismatch",
                        f"The bank's confirmation for {e.reference} ({fmt(amount, cur)}) differs from the instruction "
                        f"({fmt(instruction.amount, instruction.currency)}). A reviewer must resolve it with the bank.",
                        obj=instruction)
            raise RuleBlocked("The bank's confirmation does not match the instruction. A reviewer resolves it with "
                              "the bank.", code="confirmation-mismatch",
                              blocking_reasons=[{"rule": "FR-ESC-009", "message": "Amount or currency differs"}])
    if BankEvent.objects.filter(escrow=e, kind=kind, bank_reference=bank_reference).exclude(status="rejected") \
            .exists():
        return BankEvent.objects.filter(escrow=e, kind=kind, bank_reference=bank_reference) \
            .exclude(status="rejected").first()  # a duplicate confirmation counts once
    ev = BankEvent.objects.create(
        country=e.country, escrow=e, kind=kind, amount=q(amount), currency=cur, occurred_at=occurred_at or now(),
        bank_reference=bank_reference, programme_account=pa, virtual_account_ref=ref, source=source,
        status="pending_check" if source == "manual" else "confirmed", proof_evidence=proof_evidence,
        entered_by=by, source_bank_name=source_bank_name or "", source_account_number=source_account_number or "",
        source_account_name=source_account_name or "",
        source_account_bidx=account_bidx(source_account_number) if source_account_number else "",
        source_account_known=bool(source_account_known), deposit_route=deposit_route or (
            "bank_transfer" if kind == "deposit" else ""), transfer_partner=transfer_partner,
        partner_reference=partner_reference or "", instruction=instruction, applied_rate=applied_rate,
        applied_fees=applied_fees, statement_line=statement_line, misdirected=misdirected, note=note or "")
    if proof_evidence is not None:
        from evidence.services import link

        link(proof_evidence, "escrow_bank_event", ev.pk, role="bank_confirmation", by=by)
    audit(by, f"bank_event.{kind}", ev, {"amount": f"{ev.amount:.2f}", "currency": cur, "source": source,
                                         "status": ev.status})
    if ev.status == "confirmed":
        _on_confirmed(ev)
    else:
        alert_staff(e.country, ("CM", "RV"), "bank_event_check",
                    f"A {kind.replace('_', ' ')} of {fmt(ev.amount, cur)} on {e.reference} waits for a second "
                    "person's check.", obj=ev)
    return ev


@transaction.atomic
def check_bank_event(ev: BankEvent, by, *, confirm=True, reason="") -> BankEvent:
    """FR-ESC-004: a second staff member checks a manual entry against the
    bank's confirmation. The person who entered it cannot check it."""
    if not has_role(by, "CM", "RV", country=ev.country):
        raise Forbidden("Only staff check bank confirmations.")
    ev.refresh_from_db()
    if ev.status != "pending_check":
        raise StateConflict("This entry is not waiting for a check.")
    if by.pk == ev.entered_by_id:
        raise Forbidden("A different person must check this entry.", code="same-approver")
    ev.checked_by, ev.checked_at = by, now()
    if not confirm:
        ev.status, ev.reject_reason = "rejected", reason or "Rejected at the second check"
        ev.save(update_fields=["checked_by", "checked_at", "status", "reject_reason"])
        audit(by, "bank_event.rejected", ev, {"reason": ev.reject_reason})
        return ev
    ev.status = "confirmed"
    ev.save(update_fields=["checked_by", "checked_at", "status"])
    audit(by, "bank_event.checked", ev)
    _on_confirmed(ev)
    return ev


def _on_confirmed(ev: BankEvent):
    e = ev.escrow
    e.refresh_from_db()
    if ev.kind == "deposit":
        _on_deposit(ev)
    elif ev.kind in ("release_confirmed", "refund_confirmed"):
        _on_payment_confirmed(ev)
    elif ev.kind in ("conversion_debit", "conversion_credit"):
        from . import fx

        fx.on_conversion_leg(ev)
    sync_status(e)


def _on_deposit(ev: BankEvent):
    e = ev.escrow
    payload = _escrow_payload(e, amount=ev.amount, currency=ev.currency, bank_event_id=ev.pk,
                              label=f"Deposit confirmed by the bank on {e.reference}")
    if ev.misdirected:
        alert_staff(e.country, ("RV",), "misdirected_deposit",
                    f"The bank credited {fmt(ev.amount, ev.currency)} to {e.reference} by mistake. It cannot be "
                    "released; ask the bank for its correcting entry.", obj=ev)
        return
    if e.status == "agreed":
        e.funded_at = now()
        e.save(update_fields=["funded_at"])
        state.transition(e, "escrow", "funded", event="escrow.funded", payload=payload,
                         extra_fields=["funded_at"])
        for person in _parties_to_tell(e):
            notify(person, "escrow_funded", f"The bank confirmed a deposit of {fmt(ev.amount, ev.currency)} for "
                                            f"{e.reference}. The money is held by the bank, not by Tenmina.",
                   obj=e, link=f"/escrows/{e.pk}", category="money")
        if e.kind != "held_funds" and ev.currency == e.currency and ev.amount != e.agreed_amount:
            alert_staff(e.country, ("RV",), "deposit_differs",
                        f"The first deposit on {e.reference} ({fmt(ev.amount, ev.currency)}) differs from the price "
                        f"({fmt(e.agreed_amount, e.currency)}). Check with the client and the bank.", obj=ev)
    else:
        notify(e.client, "escrow_deposit", f"The bank confirmed {fmt(ev.amount, ev.currency)} for {e.reference}.",
               obj=e, link=f"/escrows/{e.pk}", category="money")
    if e.kind == "held_funds":
        publish("held_funds.deposit_confirmed", e.pk, payload)
    from . import fx

    fx.on_deposit(ev)
    # A top-up may clear a shortfall on an approved instruction: send it now.
    for ins in ReleaseInstruction.objects.filter(escrow=e, status="approved", shortfall_since__isnull=False):
        dispatch(ins)


def _on_payment_confirmed(ev: BankEvent):
    ins = ev.instruction
    e = ins.escrow
    ins.bank_confirmation_event = ev
    state.transition(ins, "release_instruction", "confirmed", event="release.confirmed",
                     extra_fields=["bank_confirmation_event"],
                     payload=_client_payload(ins, bank_reference=ev.bank_reference, bank_event_id=ev.pk,
                                             confirmed_at=ev.occurred_at))
    if ins.kind == "cancel_refund":
        _after_refund(ins)
        return
    for person in _parties_to_tell(e) - {e.client}:
        notify(person, "release_confirmed", f"The bank confirmed payment of {fmt(ins.amount, ins.currency)} from "
                                            f"{e.reference}.", obj=ins, link=f"/escrows/{e.pk}", category="money")
    e.refresh_from_db()
    if e.is_staged:
        if e.status == "funded":
            _route(e, "partly_released")
        if e.kind != "held_funds" and selectors.released_total(e) >= e.agreed_amount:
            _close_if_empty(e, "released")
        return
    if ins.release_part == "main" and e.held_back_amount > 0:
        _route(e, "partly_released")
        return
    if selectors.held_at_bank(e) > 0 or any(selectors.held_at_bank(e, c) > 0 for c, _ in selectors.currencies(e)):
        _route(e, "partly_released")
        prepare_unused_refunds(e, ins.prepared_by)
        return
    _route(e, "released", event="escrow.released", payload=_escrow_payload(e))


def _close_if_empty(e, target):
    if all(selectors.held_at_bank(e, c) == 0 for c, _ in selectors.currencies(e)):
        if not ReleaseInstruction.objects.filter(escrow=e, status__in=["awaiting_client", "pending_approval",
                                                                       "approved", "sent"]).exists():
            e.closed_at = now()
            e.save(update_fields=["closed_at"])
            ev = "escrow.cancelled" if target == "cancelled" else "escrow.released"
            _route(e, target, event=ev, payload=_escrow_payload(e))
            return True
    return False


@transaction.atomic
def record_bank_rejection(ins: ReleaseInstruction, by, *, reason, proof_evidence=None,
                          source_cannot_receive=False) -> ReleaseInstruction:
    """The bank returned or refused the instruction. For a refund whose source
    account cannot receive it, the RUL-29 exception path is next."""
    if not has_role(by, "CM", "RV", country=ins.country):
        raise Forbidden()
    if ins.status != "sent":
        raise StateConflict("Only a sent instruction can be returned by the bank.")
    if proof_evidence is None:
        raise Invalid("Attach the bank's notice.", code="bank-confirmation-required")
    ins.closed_reason = reason
    ins.save(update_fields=["closed_reason"])
    state.transition(ins, "release_instruction", "rejected_by_bank", actor=by, event="release.rejected_by_bank",
                     reason=reason, payload=_client_payload(ins))
    if ins.kind == "cancel_refund" and source_cannot_receive:
        dep = ins.refund_source_event
        dep.source_cannot_receive = True
        dep.save(update_fields=["source_cannot_receive"])
        prepare_refund(ins.escrow, by, deposit=dep, amount=ins.amount, reason="Bank returned the refund")
    alert_staff(ins.country, ("CM", "RV"), "release_returned",
                f"The bank returned the instruction from {ins.escrow.reference}: {reason}.", obj=ins)
    sync_status(ins.escrow)
    return ins


# ----------------------------------------------------------------- cancellation and refunds (FR-ESC-013, 017)

def _refundable(dep: BankEvent) -> Decimal:
    used = sum((i.amount for i in ReleaseInstruction.objects.filter(
        refund_source_event=dep, status__in=["awaiting_client", "pending_approval", "approved", "sent",
                                             "confirmed"])), Decimal("0"))
    return dep.amount - used


@transaction.atomic
def prepare_refund(e: Escrow, by, *, deposit: BankEvent, amount=None, reason="", fx_quote=None,
                   approval_subject="escrow_cancel") -> ReleaseInstruction:
    """A refund instruction to the source of one deposit (RUL-29). There is
    no address field to edit: the bank instruction names the source account
    exactly as the bank's confirmation gave it."""
    _on(e.country)
    if deposit.escrow_id != e.pk or deposit.kind != "deposit" or deposit.status != "confirmed":
        raise Invalid("Name a bank-confirmed deposit of this escrow.", code="validation-error")
    amt = q(amount) if amount is not None else min(_refundable(deposit),
                                                   selectors.available_to_instruct(e, deposit.currency))
    if amt <= 0:
        raise StateConflict("Nothing is left to refund from this deposit.")
    iid = uuid7()
    ins = ReleaseInstruction(id=iid, country=e.country, escrow=e, kind="cancel_refund", amount=amt,
                             currency=deposit.currency, prepared_by=by, reason=reason or "Refund to source",
                             refund_source_event=deposit, fx_quote=fx_quote, status="pending_approval",
                             clock_started_at=now(), subject_label=f"Refund of deposit {deposit.bank_reference}")
    reasons = [r for r in _release_blockers(ins, "prepare")
               if r["code"] not in ("refund-exception-required", "payee-cooling-off", "escrow-cancelling")]
    if reasons:
        raise RuleBlocked("This refund is blocked: " + "; ".join(r["message"] for r in reasons[:3]),
                          code="held-funds-insufficient" if {r["code"] for r in reasons} == {
                              "held-funds-insufficient"} else "release-blocked", blocking_reasons=reasons)
    ins.approval_request = approvals.request_approval(
        approval_subject, iid, by, required=2, country=e.country,
        summary=f"Refund {fmt(amt, deposit.currency)} to the source of deposit {deposit.bank_reference}")
    try:
        with transaction.atomic():
            ins.save(force_insert=True)
    except IntegrityError as exc:
        raise StateConflict("A refund of this deposit is already in progress.", code="instruction-exists") from exc
    audit(by, "refund.requested", ins, {"deposit": str(deposit.pk), "amount": f"{amt:.2f}"})
    publish("release.requested", ins.pk, _client_payload(ins))
    _alert_approvers(ins)
    return ins


def _refund_plan(e: Escrow) -> list[tuple[BankEvent, Decimal]]:
    """Money still held, refunded to the source of each deposit, newest first."""
    plan = []
    for cur, _ in selectors.currencies(e):
        left = selectors.available_to_instruct(e, cur)
        for dep in BankEvent.objects.filter(escrow=e, kind="deposit", status="confirmed", currency=cur,
                                            misdirected=False).order_by("-occurred_at"):
            if left <= 0:
                break
            amt = min(_refundable(dep), left)
            if amt > 0:
                plan.append((dep, amt))
                left -= amt
    return plan


def prepare_unused_refunds(e: Escrow, by) -> list[ReleaseInstruction]:
    """escrow.unused_funds (RUL-36, RUL-29): after the last release, money left
    in either currency goes back to its source through two-person approval."""
    out = []
    for dep, amt in _refund_plan(e):
        out.append(prepare_refund(e, by, deposit=dep, amount=amt, reason="Money left after the last release"))
    if out:
        notify(e.client, "escrow_unused_refund", f"Money left in {e.reference} after the last payment goes back to "
                                                 "where it came from.", obj=e, category="money")
    return out


@transaction.atomic
def request_cancellation(e: Escrow, by, *, reason) -> Escrow:
    """FR-ESC-013: two staff approve a cancellation; any money held goes back
    to the source of each deposit (RUL-29)."""
    _on(e.country)
    _staff(by, e.country, "CM", "RV")
    if not reason:
        raise Invalid("Give the reason.", code="validation-error")
    if e.status in ("released", "cancelled"):
        raise StateConflict("This escrow is closed.")
    if e.cancel_requested_at:
        raise StateConflict("A cancellation is already in progress.")
    if e.status == "proposed":
        e.cancel_reason, e.closed_at = reason, now()
        e.save(update_fields=["cancel_reason", "closed_at"])
        return state.transition(e, "escrow", "cancelled", actor=by, event="escrow.cancelled", reason=reason,
                                payload=_escrow_payload(e))
    for ins in ReleaseInstruction.objects.filter(escrow=e, status__in=["awaiting_client", "pending_approval"]) \
            .exclude(kind="cancel_refund"):
        withdraw_instruction(ins, by, reason="The escrow is being cancelled")
    if ReleaseInstruction.objects.filter(escrow=e, status__in=["approved", "sent"]).exclude(kind="cancel_refund") \
            .exists():
        raise StateConflict("An approved or sent release must be confirmed or recalled with the bank first.")
    e.cancel_requested_at, e.cancel_requested_by, e.cancel_reason = now(), by, reason
    plan = _refund_plan(e)
    if not plan:
        e.cancel_approval = approvals.request_approval(
            "escrow_cancel", e.pk, by, required=2, country=e.country, summary=f"Cancel escrow {e.reference}")
    e.save(update_fields=["cancel_requested_at", "cancel_requested_by", "cancel_reason", "cancel_approval"])
    for dep, amt in plan:
        prepare_refund(e, by, deposit=dep, amount=amt, reason=f"Cancellation: {reason}")
    audit(by, "escrow.cancellation_requested", e, {"reason": reason, "refunds": len(plan)})
    for person in _parties_to_tell(e):
        notify(person, "escrow_cancelling", f"Escrow {e.reference} is being cancelled. Any money held goes back to "
                                            "where it came from.", obj=e, category="money")
    return e


def decide_cancellation(e: Escrow, approver, *, decision, mfa_at, note=""):
    if e.cancel_approval is None or e.cancel_approval.status != "open":
        raise StateConflict("This escrow has no cancellation waiting for approval.")
    return approvals.decide(e.cancel_approval, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=lambda a: has_rr(a, e.country) and a.pk != e.client_id)


def on_cancel_approved(e: Escrow, approved: bool):
    e.refresh_from_db()
    if not approved:
        e.cancel_requested_at, e.cancel_requested_by = None, None
        e.save(update_fields=["cancel_requested_at", "cancel_requested_by"])
        return e
    _close_if_empty(e, "cancelled")
    return e


def _after_refund(ins):
    e = ins.escrow
    e.refresh_from_db()
    notify(e.client, "refund_confirmed", f"The bank confirmed a refund of {fmt(ins.amount, ins.currency)} from "
                                         f"{e.reference} to the account it came from.", obj=ins, category="money")
    if e.cancel_requested_at:
        _close_if_empty(e, "cancelled")
    elif e.kind != "held_funds" and not e.is_staged:
        e.refresh_from_db()
        if e.status == "partly_released" and ReleaseInstruction.objects.filter(
                escrow=e, kind="release", status="confirmed", release_part="held_back" if e.held_back_amount
                else "main").exists():
            _close_if_empty(e, "released")


# ----------------------------------------------------------------- freezes (RUL-15, RUL-32)

@transaction.atomic
def freeze(e: Escrow, *, kind, source_id, reason="", by=None) -> Freeze:
    e.refresh_from_db()
    f = Freeze.objects.filter(escrow=e, kind=kind, source_id=source_id).first()
    if f is not None:
        return f
    prior = e.prior_status if e.status == "frozen" else e.status
    f = Freeze.objects.create(escrow=e, kind=kind, source_id=source_id, prior_status=prior, reason=reason or "",
                              frozen_by=by)
    if e.status in RELEASABLE:
        e.prior_status = e.status
        e.save(update_fields=["prior_status"])
        state.transition(e, "escrow", "frozen", actor=by, event="escrow.frozen", reason=reason,
                         payload=_escrow_payload(e, freeze_kind=kind))
    for ins in ReleaseInstruction.objects.filter(escrow=e, status="sent"):
        alert_staff(e.country, ("CM", "RV"), "release_recall",
                    f"{e.reference} is frozen ({kind}). A sent instruction of {fmt(ins.amount, ins.currency)} may need "
                    "recalling with the bank [TO VERIFY] (Q-12).", obj=ins)
    audit(by, "escrow.frozen", e, {"kind": kind, "source_id": str(source_id), "reason": reason})
    for person in _parties_to_tell(e):
        notify(person, "escrow_frozen", f"Payments from {e.reference} are on hold while a check is made.", obj=e,
               category="money")
    return f


@transaction.atomic
def lift_freeze(f: Freeze, *, by=None, note="") -> Escrow:
    if f.lifted_at:
        return f.escrow
    f.lifted_at, f.lifted_by, f.lift_note = now(), by, note or ""
    f.save(update_fields=["lifted_at", "lifted_by", "lift_note"])
    e = f.escrow
    e.refresh_from_db()
    audit(by, "escrow.freeze_lifted", e, {"kind": f.kind, "source_id": str(f.source_id)})
    if Freeze.objects.filter(escrow=e, lifted_at__isnull=True).exists():
        return e
    if e.status == "frozen":
        target = e.prior_status or "funded"
        state.transition(e, "escrow", target, actor=by, event="escrow.unfrozen", payload=_escrow_payload(e))
        sync_status(e)
    for ins in ReleaseInstruction.objects.filter(escrow=e, status="approved"):
        dispatch(ins)
    return e


def place_hold(e: Escrow, by, *, reason) -> Freeze:
    """US-ESC-006 AC4: a reviewer's hold blocks release."""
    if not has_role(by, "RV", country=e.country):
        raise Forbidden("Only a reviewer places a hold.")
    if not reason:
        raise Invalid("Give the reason.", code="validation-error")
    return freeze(e, kind="reviewer_hold", source_id=uuid7(), reason=reason, by=by)


def lift_hold(f: Freeze, by, *, note) -> Escrow:
    """A different reviewer lifts a hold (two people, RUL-05 spirit)."""
    if f.kind != "reviewer_hold":
        raise StateConflict("Only a reviewer's hold is lifted here; disputes and incidents lift when they close.")
    if not has_role(by, "RV", country=f.escrow.country):
        raise Forbidden("Only a reviewer lifts a hold.")
    if by.pk == f.frozen_by_id:
        raise Forbidden("A different reviewer must lift this hold.", code="same-approver")
    return lift_freeze(f, by=by, note=note)


# ----------------------------------------------------------------- standing approvals (RUL-11)

@transaction.atomic
def create_standing_approval(e: Escrow, client, *, subject_kind, subject_id, monthly_max, mfa_at=None,
                             code=None) -> StandingApproval:
    _on(e.country)
    if e.client_id != client.pk or e.kind != "held_funds":
        raise NotFound()
    _client_signed(client, mfa_at, code)
    if q(monthly_max) <= 0:
        raise Invalid("Set the monthly limit.", code="validation-error")
    StandingApproval.objects.filter(subject_kind=subject_kind, subject_id=subject_id, status="active").update(
        status="withdrawn", withdrawn_at=now())
    sa = StandingApproval.objects.create(country=e.country, client=client, escrow=e, subject_kind=subject_kind,
                                         subject_id=subject_id, monthly_max=q(monthly_max), currency=e.currency,
                                         approved_at=now())
    audit(client, "standing_approval.created", sa, {"monthly_max": f"{sa.monthly_max:.2f}"})
    return sa


@transaction.atomic
def withdraw_standing_approval(sa: StandingApproval, client) -> StandingApproval:
    if sa.client_id != client.pk:
        raise NotFound()
    if sa.status != "active":
        return sa
    sa.status, sa.withdrawn_at = "withdrawn", now()
    sa.save(update_fields=["status", "withdrawn_at"])
    audit(client, "standing_approval.withdrawn", sa)
    return sa


def standing_approval_for(subject_kind, subject_id):
    return StandingApproval.objects.filter(subject_kind=subject_kind, subject_id=subject_id, status="active").first()


# ----------------------------------------------------------------- the release clock (FR-ESC-018, NFR-PERF-06)

def release_clock_watch(at=None) -> dict:
    """escrow.release_clock_watch: alerts, never approvals (RUL-11, RUL-33)."""
    t = at or now()
    out = {"send_overdue": 0, "bank_overdue": 0, "approval_overdue": 0, "client_reminded": 0, "expired": 0}
    for ins in ReleaseInstruction.objects.filter(status="approved", send_overdue_alerted_at__isnull=True) \
            .select_related("escrow"):
        if ins.escrow.status == "frozen" or ins.send_due_on is None:
            continue
        if local_date(ins.country, t) > ins.send_due_on:
            ins.send_overdue_alerted_at = t
            ins.save(update_fields=["send_overdue_alerted_at"])
            publish("release.send_overdue", ins.pk, _client_payload(ins, send_due_on=ins.send_due_on))
            alert_staff(ins.country, ("CM", "RV"), "release_send_overdue",
                        f"The instruction from {ins.escrow.reference} was due to go to the bank on "
                        f"{ins.send_due_on:%d %B %Y} and has not been sent.", obj=ins)
            out["send_overdue"] += 1
    for ins in ReleaseInstruction.objects.filter(status="sent", bank_overdue_alerted_at__isnull=True) \
            .select_related("escrow"):
        if ins.bank_pay_due_on and local_date(ins.country, t) > ins.bank_pay_due_on:
            ins.bank_overdue_alerted_at = t
            ins.save(update_fields=["bank_overdue_alerted_at"])
            publish("release.bank_overdue", ins.pk, _client_payload(ins, bank_pay_due_on=ins.bank_pay_due_on))
            alert_staff(ins.country, ("CM",), "release_bank_overdue",
                        f"The bank has not confirmed the payment from {ins.escrow.reference}, due by "
                        f"{ins.bank_pay_due_on:%d %B %Y}. Chase the bank.", obj=ins)
            notify(ins.escrow.client, "release_bank_late", "The bank has not confirmed this payment yet. We are "
                                                            "following it up with the bank.", obj=ins,
                   category="money")
            out["bank_overdue"] += 1
    for ins in ReleaseInstruction.objects.filter(status="pending_approval", approval_overdue_alerted_at__isnull=True,
                                                 staff_approval_due_on__isnull=False):
        if local_date(ins.country, t) > ins.staff_approval_due_on:
            ins.approval_overdue_alerted_at = t
            ins.save(update_fields=["approval_overdue_alerted_at"])
            publish("release.approval_overdue", ins.pk, _client_payload(ins))
            alert_staff(ins.country, ("RV", "AD"), "release_approval_overdue",
                        f"Staff approvals for {ins.escrow.reference} are past their target.", obj=ins)
            out["approval_overdue"] += 1
    for ins in ReleaseInstruction.objects.filter(status="awaiting_client").select_related("escrow"):
        days = int(setting("client_approval_reminder_days", ins.country, 3))
        last = ins.client_reminded_at or ins.created_at
        if t - last >= timedelta(days=days):
            ins.client_reminded_at = t
            ins.save(update_fields=["client_reminded_at"])
            notify(ins.escrow.client, "approval_reminder",
                   f"A payment of {fmt(ins.amount, ins.currency)} from {ins.escrow.reference} still waits for your "
                   "approval. Nothing is paid until you approve.", needs_action=True, obj=ins,
                   link=f"/release-instructions/{ins.pk}", category="reminder")
            out["client_reminded"] += 1
    stand = 5  # RUL-36: approvals stand 5 working days after a shortfall is found [TO VERIFY]
    for ins in ReleaseInstruction.objects.filter(status="approved", shortfall_since__isnull=False):
        expiry = add_working_days(ins.country, local_date(ins.country, ins.shortfall_since), stand)
        if local_date(ins.country, t) > expiry:
            withdraw_instruction(ins, None, reason="The shortfall was not topped up in time; approve again (RUL-36)",
                                 system=True)
            out["expired"] += 1
    for ch in PayeeChange.objects.filter(status="checks_passed", escrow__isnull=False):
        days = int(setting("client_approval_reminder_days", ch.country, 3))
        last = ch.client_reminded_at or ch.requested_at
        if t - last >= timedelta(days=days):
            ch.client_reminded_at = t
            ch.save(update_fields=["client_reminded_at"])
            notify(ch.escrow.client, "approval_reminder", "An account change on your escrow waits for your answer. "
                                                          "Nothing changes until you approve.", needs_action=True,
                   obj=ch, category="reminder")
    return out


def clock(ins: ReleaseInstruction) -> dict:
    from countries.selectors import working_days_between

    c = ins.country
    today = local_today(c)
    started = local_date(c, ins.clock_started_at) if ins.clock_started_at else None
    frozen = ins.escrow.status == "frozen"
    state_ = "running"
    if ins.status == "confirmed":
        state_ = "paid"
    elif frozen:
        state_ = "frozen"
    elif ins.status == "approved" and ins.send_due_on and today > ins.send_due_on:
        state_ = "send_overdue"
    elif ins.status == "sent" and ins.bank_pay_due_on and today > ins.bank_pay_due_on:
        state_ = "bank_overdue"
    elif ins.shortfall_since:
        state_ = "paused_shortfall"
    end = local_date(c, ins.bank_confirmation_event.occurred_at) if ins.bank_confirmation_event_id else today
    return {"clock_started_at": ins.clock_started_at, "working_days_running":
            working_days_between(c, started, end) if started else None,
            "staff_approval_due_on": ins.staff_approval_due_on, "last_approval_at": ins.last_approval_at,
            "send_due_on": ins.send_due_on, "sent_at": ins.sent_at, "bank_pay_due_on": ins.bank_pay_due_on,
            "state": state_, "frozen_reason": "; ".join(f.reason or f.kind for f in ins.escrow.freezes.filter(
                lifted_at__isnull=True)) if frozen else ""}


# ----------------------------------------------------------------- events from other modules

@transaction.atomic
def on_report_released(payload: dict):
    from countries.models import Country

    rid = payload.get("report_id") or payload.get("id")
    if not rid:
        return None
    country = None
    if payload.get("country"):
        country = Country.objects.filter(code=str(payload["country"]).upper()).first()
    if country is None and payload.get("country_id"):
        country = Country.objects.filter(pk=payload["country_id"]).first()
    if country is None:
        return None
    snap, _ = ReportSnapshot.objects.update_or_create(report_id=rid, defaults=dict(
        country=country, client_id=payload.get("client_id"), case_id=payload.get("case_id"),
        asset_id=payload.get("asset_id"), verdict=str(payload.get("verdict") or "").lower(),
        conditions=[{"id": c.get("id"), "key": c.get("key", ""), "text": c.get("text", "")}
                    for c in (payload.get("conditions") or []) if isinstance(c, dict) and c.get("text")],
        released_at=now()))
    return snap


def on_fresh_search(payload: dict):
    from datetime import date

    def d(v):
        return date.fromisoformat(v[:10]) if isinstance(v, str) and v else v

    qs = Escrow.objects.filter(status__in=OPEN_STATUSES)
    if payload.get("escrow_id"):
        qs = qs.filter(pk=payload["escrow_id"])
    elif payload.get("asset_id"):
        qs = qs.filter(asset_id=payload["asset_id"], kind__in=("purchase", "offplan"))
    else:
        return
    for e in qs:
        record_fresh_search(e, None, case_id=payload.get("case_id"),
                            registry_result_date=d(payload.get("registry_result_date")),
                            site_check_date=d(payload.get("site_check_date")))


def _escrows_for_payload(payload) -> list[Escrow]:
    qs = Escrow.objects.exclude(status__in=("released", "cancelled"))
    if payload.get("escrow_id"):
        return list(qs.filter(pk=payload["escrow_id"]))
    out = []
    if payload.get("project_id"):
        out += list(qs.filter(project_id=payload["project_id"]))
    if payload.get("report_id"):
        out += list(qs.filter(report_id=payload["report_id"]))
    for rid in payload.get("superseded_report_ids") or []:
        out += list(qs.filter(report_id=rid))
    if payload.get("condition_id"):
        out += list(qs.filter(conditions__pk=payload["condition_id"]))
    return list({e.pk: e for e in out}.values())


def on_dispute(payload: dict, opened: bool):
    did = payload.get("dispute_id") or payload.get("id")
    if not did:
        return
    for e in _escrows_for_payload(payload):
        if opened:
            freeze(e, kind="dispute", source_id=did, reason=payload.get("reason", "Dispute opened"))
        else:
            f = Freeze.objects.filter(escrow=e, kind="dispute", source_id=did, lifted_at__isnull=True).first()
            if f is None:
                continue
            if payload.get("outcome") == "refund":
                lift_freeze(f, note="Dispute resolved for a refund")
                e.refresh_from_db()
                from .common import staff_in

                cm = e.created_by if has_role(e.created_by, "CM", "RV", country=e.country) else \
                    staff_in(e.country, "CM").first()
                if not e.cancel_requested_at and cm is not None:
                    request_cancellation(e, cm, reason="Dispute resolved in favour of a refund")
            else:
                lift_freeze(f, note="Dispute resolved")


def on_incident(payload: dict, opened: bool):
    iid = payload.get("incident_id") or payload.get("id")
    if not iid:
        return
    if opened:
        for e in _escrows_for_payload(payload):
            freeze(e, kind="incident", source_id=iid, reason=payload.get("reason", "A re-check failed"))
    else:
        for f in Freeze.objects.filter(kind="incident", source_id=iid, lifted_at__isnull=True):
            lift_freeze(f, note="Incident closed")


# Re-exported for the API and other modules (fx, bank accounts, statements).
from .bank import (check_bank_position, check_resolution, create_programme_account, decide_programme_account,  # noqa
                   import_statement, record_bank_position, resolve_position, unmatched_lines)
from .fx import (accept_quote, check_conversion_resolution, check_observation, collect_rates,  # noqa
                 comparison_for, create_programme_rate, decide_programme_rate, deposit_routes, enter_observation,
                 issue_quote, prepare_conversion, record_fx_account, resolve_conversion, set_conversion_choice)

__all__ = [n for n in dir() if not n.startswith("_")] + ["DomainError"]
