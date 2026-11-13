"""ADM services: every write and rule for FR-ADM-001 to 005, FR-APP-006 and
the feature flag rules of document 06 section 2.6.

Two-person changes go through core.approvals with the preparer plus a second
administrator. Nothing changes until the approval closes; the handler then
applies the change (handlers.py).
"""
import hashlib
import hmac
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.conf import settings as dj_settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from audit.services import record, security_event
from core import approvals, state
from core.errors import Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from . import flags, registry
from .models import (
    KILL_SWITCHES, SAFETY_FLAGS_PREFIXES, AppVersion, ChangeRequest, ConfigVersion, FeatureFlag, FxRate,
    LockedTextVersion, Partner, Price, Setting,
)

ADMIN = "AD"


def sha256_json(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _require_admin(person):
    if not has_role(person, ADMIN):
        raise Forbidden("Only an administrator can do this.")


def is_admin_approver(person) -> bool:
    return has_role(person, ADMIN)


# --- Versioned configuration (FR-ADM-001, ADR-11) -----------------------------

def _need_list(content, key, fields, kind):
    items = content.get(key)
    if not isinstance(items, list) or not items:
        raise Invalid(f"A {kind.replace('_', ' ')} needs a non-empty '{key}' list.", code="config-invalid")
    for i, it in enumerate(items):
        if not isinstance(it, dict) or any(not it.get(f) for f in fields):
            raise Invalid(f"Item {i + 1} in '{key}' needs {', '.join(fields)}.", code="config-invalid")
    return items


def validate_config_content(kind: str, content) -> None:
    """A small schema per kind (schema version 1)."""
    if not isinstance(content, dict):
        raise Invalid("Configuration content must be an object.", code="config-invalid")
    if kind == "case_template":
        _need_list(content, "tasks", ("key", "title"), kind)
    elif kind == "report_template":
        _need_list(content, "sections", ("key", "title"), kind)
    elif kind == "condition_set":
        _need_list(content, "conditions", ("key", "text"), kind)
    elif kind == "milestone_schedule":
        items = _need_list(content, "milestones", ("key", "name"), kind)
        try:
            total = sum(Decimal(str(m.get("share_pct", 0))) for m in items)
        except InvalidOperation:
            raise Invalid("Milestone shares must be numbers.", code="config-invalid") from None
        if total != 100:
            raise Invalid(f"Milestone shares must add up to 100 (they add up to {total}).", code="config-invalid")
    elif kind == "tier_catalogue":
        _need_list(content, "tiers", ("code", "name"), kind)
    elif kind in ("checklist", "vetting_checklist", "care_plan_template", "institution_types"):
        _need_list(content, "items", ("key",), kind)
    elif kind == "errand_catalogue":
        _need_list(content, "errands", ("code", "name"), kind)
    elif kind == "holiday_calendar":
        dates = content.get("dates")
        if not isinstance(dates, list):
            raise Invalid("A holiday calendar needs a 'dates' list.", code="config-invalid")
        for d in dates:
            try:
                date.fromisoformat(d["date"] if isinstance(d, dict) else d)
            except (KeyError, TypeError, ValueError):
                raise Invalid(f"'{d}' is not a date (YYYY-MM-DD).", code="config-invalid") from None


@transaction.atomic
def create_config_version(*, kind, content, by, country=None, product_line="", name="", copied_from=None,
                          schema_version="1") -> ConfigVersion:
    flags.read_only_guard()
    if kind not in ConfigVersion.KINDS:
        raise Invalid(f"Unknown configuration kind '{kind}'.", code="config-invalid")
    validate_config_content(kind, content)
    last = ConfigVersion.objects.filter(kind=kind, country=country, product_line=product_line).aggregate(
        m=Max("version"))["m"] or 0
    cv = ConfigVersion.objects.create(kind=kind, country=country, product_line=product_line, version=last + 1,
                                      name=name, content=content, content_sha256=sha256_json(content),
                                      schema_version=schema_version, created_by=by, copied_from=copied_from)
    record(actor=by, action="config_version.created", entity="config_version", entity_id=cv.pk, country=country,
           data={"kind": kind, "version": cv.version, "product_line": product_line, "sha256": cv.content_sha256})
    return cv


@transaction.atomic
def update_config_draft(cv: ConfigVersion, *, by, content=None, name=None) -> ConfigVersion:
    """TC-ADM-001-02: a published version is never edited; make a new version."""
    flags.read_only_guard()
    if cv.state != "draft":
        raise StateConflict("A published version cannot be changed. Create a new version instead.",
                            code="config-published")
    old = cv.content_sha256
    if content is not None:
        validate_config_content(cv.kind, content)
        cv.content, cv.content_sha256 = content, sha256_json(content)
    if name is not None:
        cv.name = name
    cv.save()
    record(actor=by, action="config_version.edited", entity="config_version", entity_id=cv.pk, country=cv.country,
           data={"old_sha256": old, "new_sha256": cv.content_sha256})
    return cv


def validate_for_publication(kind: str, content, country=None) -> None:
    """The owning module's own rules for a template, run when it is published (and again when a country
    configuration naming it is published): CASE for case templates, RPT for report templates, TSK for the
    errand catalogue. Raises Invalid (config-invalid) with the module's message."""
    if kind == "case_template":
        from cases.templates import validate

        validate(content)
    elif kind == "report_template":
        from reports.templates import validate

        validate(content)
    elif kind == "errand_catalogue":
        if country is None:
            return  # a shareable catalogue is checked against each country's currency when a country names it
        from errands.catalogue import validate

        problems = validate((content or {}).get("errands") if isinstance(content, dict) else content, country)
        if problems:
            raise Invalid("Some errands are incomplete: " + "; ".join(
                f"{p['code']}: {' '.join(p['problems'])}" for p in problems), code="config-invalid",
                extra={"problems": problems})


@transaction.atomic
def publish_config_version(cv: ConfigVersion, *, by) -> ConfigVersion:
    flags.read_only_guard()
    _require_admin(by)
    if cv.state != "draft":
        raise StateConflict("Only a draft can be published.")
    validate_for_publication(cv.kind, cv.content, cv.country)
    previous = list(ConfigVersion.objects.filter(kind=cv.kind, country=cv.country, product_line=cv.product_line,
                                                 state="published").exclude(pk=cv.pk))
    cv.published_by, cv.published_at = by, timezone.now()
    state.transition(cv, "config_version", "published", actor=by, event="config.published",
                     payload={"kind": cv.kind, "version": cv.version, "product_line": cv.product_line,
                              "country": getattr(cv.country, "code", None), "config_version_id": cv.pk},
                     extra_fields=["published_by", "published_at"])
    for p in previous:
        state.transition(p, "config_version", "retired", actor=by, payload={"replaced_by": str(cv.pk)})
    return cv


@transaction.atomic
def retire_config_version(cv: ConfigVersion, *, by) -> ConfigVersion:
    _require_admin(by)
    return state.transition(cv, "config_version", "retired", actor=by)


def copy_version_to_country(cv: ConfigVersion, country, *, by) -> ConfigVersion:
    """FR-CTY-004: a draft copy for another country, so it never points at
    the source country's rows."""
    return create_config_version(kind=cv.kind, content=cv.content, by=by, country=country,
                                 product_line=cv.product_line, name=cv.name, copied_from=cv,
                                 schema_version=cv.schema_version)


# --- Prices and exchange-rate guides (FR-ADM-002) -------------------------------

@transaction.atomic
def set_price(*, country, tier, amount, currency, by, product_line="land", audience="standard", note="") -> Price:
    """New orders use the new price; an existing order keeps its quoted amount
    because the old row is closed, never changed (TC-ADM-002-01)."""
    flags.read_only_guard()
    try:
        amt = q(amount)
    except (InvalidOperation, TypeError, ValueError):
        raise Invalid("The price must be a number.", code="price-invalid") from None
    if amt < 0:
        raise Invalid("A price cannot be negative.", code="price-invalid")
    currency = (currency or "").upper()
    if len(currency) != 3:
        raise Invalid("Currency must be an ISO 4217 code.", code="price-invalid")
    if not tier:
        raise Invalid("A price needs a tier.", code="price-invalid")
    now = timezone.now()
    old = Price.objects.select_for_update().filter(country=country, product_line=product_line, tier=tier,
                                                   audience=audience, valid_to__isnull=True).first()
    if old:
        old.valid_to = now
        old.save(update_fields=["valid_to"])
    p = Price.objects.create(country=country, product_line=product_line, tier=tier, audience=audience,
                             price_amount=amt, price_currency=currency, valid_from=now, created_by=by, note=note)
    data = {"tier": tier, "product_line": product_line, "audience": audience,
            "old": {"amount": f"{old.price_amount:.2f}", "currency": old.price_currency} if old else None,
            "new": {"amount": f"{amt:.2f}", "currency": currency}}
    record(actor=by, action="price.changed", entity="price", entity_id=p.pk, country=country, data=data)
    publish("price.changed", p.pk, {"price_id": p.pk, "country": country.code, **data})
    return p


@transaction.atomic
def set_fx_rate(*, country, base, quote, rate, by=None, rate_date=None, source="manual") -> FxRate:
    flags.read_only_guard()
    try:
        r = Decimal(str(rate))
    except (InvalidOperation, TypeError):
        raise Invalid("The rate must be a number.", code="fx-rate-invalid") from None
    if r <= 0:
        raise Invalid("A rate must be above zero.", code="fx-rate-invalid")
    base, quote = (base or "").upper(), (quote or "").upper()
    if len(base) != 3 or len(quote) != 3 or base == quote:
        raise Invalid("Give two different ISO 4217 currency codes.", code="fx-rate-invalid")
    rate_date = rate_date or timezone.localdate()
    fx = FxRate.objects.create(country=country, base_currency=base, quote_currency=quote, rate=r.quantize(
        Decimal("0.000001")), rate_date=rate_date, source=source, created_by=by)
    record(actor=by, action="fx_rate.updated", entity="fx_rate", entity_id=fx.pk, country=country,
           data={"pair": f"{base}/{quote}", "rate": str(fx.rate), "date": str(rate_date), "source": source})
    publish("fx_rate.updated", fx.pk, {"country": country.code, "base": base, "quote": quote, "rate": str(fx.rate),
                                       "rate_date": str(rate_date)})
    return fx


def refresh_fx(countries=None) -> list[FxRate]:
    """07.12 administration.refresh_fx: guide rates from the day's reference
    source (fake adapter until IF-14 is contracted)."""
    from core.adapters import get_adapter
    from countries.models import Country

    src = get_adapter("fx_guide_source", default="administration.adapters.FakeGuideRateSource")
    out = []
    for c in countries or Country.objects.filter(status__in=("active", "manual_phase", "validating")):
        price_currency = (c.config() or {}).get("price_currency") or "USD"
        if price_currency == c.currency:
            continue
        rate = src.rate(price_currency, c.currency)
        if rate:
            out.append(set_fx_rate(country=c, base=price_currency, quote=c.currency, rate=rate,
                                   source=getattr(src, "name", "reference")))
    return out


# --- Partner registry (FR-ADM-003) ---------------------------------------------

BANK_FIELDS = ("bank_name", "bank_branch", "account_name", "account_number")
PLAIN_FIELDS = ("name", "organisation", "person", "adapter_port", "adapter_path", "contact_name", "contact_email",
                "contact_phone", "licence_number", "licence_body", "is_national_id_system", "details")
OPERATING_KINDS = {"operating_bank", "operating_mobile_money"}
CLIENT_MONEY_KINDS = {"escrow_bank"}


def account_bidx(number: str) -> str:
    """Keyed hash of an account number for equality checks without the value."""
    digits = "".join(ch for ch in (number or "") if ch.isalnum()).upper()
    if not digits:
        return ""
    return hmac.new(dj_settings.SECRET_KEY.encode(), f"acct:{digits}".encode(), hashlib.sha256).hexdigest()


def _check_operating_not_escrow(kind, bidx, exclude_pk=None):
    """ADR-23, RUL-27: Tenmina's operating account is never an escrow account."""
    if not bidx:
        return
    other = OPERATING_KINDS if kind in CLIENT_MONEY_KINDS else CLIENT_MONEY_KINDS if kind in OPERATING_KINDS else None
    if other and Partner.objects.filter(kind__in=other, account_number_bidx=bidx).exclude(pk=exclude_pk).exists():
        raise RuleBlocked("This account is already recorded as a client-money account (or the reverse).",
                          blocking_reasons=[{"rule": "RUL-27", "message": "Operating and escrow accounts must differ."}])


@transaction.atomic
def create_partner(*, country, kind, name, by, bank=None, reason="", **fields) -> tuple[Partner, ChangeRequest | None]:
    """Created active with its plain details at once. Bank details, if given,
    wait for a second administrator like any change to them."""
    flags.read_only_guard()
    _require_admin(by)
    if kind not in Partner.KINDS:
        raise Invalid(f"Unknown partner kind '{kind}'.", code="validation-error")
    if not name:
        raise Invalid("A partner needs a name.", code="validation-error")
    clean = {k: v for k, v in fields.items() if k in PLAIN_FIELDS and v is not None}
    p = Partner.objects.create(country=country, kind=kind, name=name, created_by=by, **clean)
    record(actor=by, action="partner.created", entity="partner", entity_id=p.pk, country=country,
           data={"kind": kind, "name": name, "fields": sorted(clean)})
    publish("partner.created", p.pk, {"partner_id": p.pk, "kind": kind, "country": country.code})
    cr = None
    if bank and any(bank.get(f) for f in BANK_FIELDS):
        cr = request_bank_change(p, by=by, reason=reason or "Bank details for a new partner", **bank)
    return p, cr


@transaction.atomic
def update_partner(p: Partner, *, by, **fields) -> Partner:
    """TC-ADM-003-04: details other than bank details change with one
    administrator, audited with old and new values."""
    flags.read_only_guard()
    _require_admin(by)
    if any(f in fields for f in BANK_FIELDS):
        raise Invalid("Bank details change only through a bank change request.", code="bank-change-needs-approval")
    changes = {}
    for k, v in fields.items():
        if k not in PLAIN_FIELDS or v is None:
            continue
        old = getattr(p, k)
        old_cmp = getattr(old, "pk", old)
        new_cmp = getattr(v, "pk", v)
        if old_cmp != new_cmp:
            changes[k] = {"old": str(old_cmp) if old_cmp is not None else None,
                          "new": str(new_cmp) if new_cmp is not None else None}
            setattr(p, k, v)
    if changes:
        p.save()
        record(actor=by, action="partner.updated", entity="partner", entity_id=p.pk, country=p.country,
               data={"changes": changes})
    return p


@transaction.atomic
def request_bank_change(p: Partner, *, by, bank_name="", bank_branch="", account_name="", account_number="",
                        reason="") -> ChangeRequest:
    """FR-ADM-003: a change to bank details waits for a second administrator;
    the old details stay in use until then (TC-ADM-003-02)."""
    flags.read_only_guard()
    _require_admin(by)
    if not (account_name and account_number and bank_name):
        raise Invalid("Give the bank, the account name and the account number.", code="validation-error")
    bidx = account_bidx(account_number)
    _check_operating_not_escrow(p.kind, bidx, exclude_pk=p.pk)
    if ChangeRequest.objects.filter(kind="partner_bank", target=str(p.pk), status="pending").exists():
        raise StateConflict("A bank change for this partner is already waiting for approval.")
    new = {"bank_name": bank_name, "bank_branch": bank_branch, "account_name": account_name,
           "account_number": account_number}
    old = {f: getattr(p, f) for f in BANK_FIELDS}
    cr = ChangeRequest.objects.create(kind="partner_bank", target=str(p.pk), country=p.country,
                                      old_value=_mask_bank(old), new_value=new, reason=reason, requested_by=by)
    cr.approval_request = approvals.request_approval(
        "partner_bank_change", cr.pk, by, required=1, country=p.country,
        summary=f"Bank details for {p.name}: {bank_name}, account ending {account_number[-4:]}")
    cr.save(update_fields=["approval_request"])
    record(actor=by, action="partner.bank_change_requested", entity="partner", entity_id=p.pk, country=p.country,
           data={"change_request_id": str(cr.pk), "bank_name": bank_name, "account_last4": account_number[-4:]})
    return cr


def _mask_bank(d: dict) -> dict:
    out = dict(d)
    num = out.get("account_number") or ""
    out["account_number"] = ("*" * max(len(num) - 4, 0) + num[-4:]) if num else ""
    return out


def _apply_partner_bank(cr: ChangeRequest, approvers):
    p = Partner.objects.select_for_update().get(pk=cr.target)
    new = cr.new_value
    bidx = account_bidx(new["account_number"])
    _check_operating_not_escrow(p.kind, bidx, exclude_pk=p.pk)
    for f in BANK_FIELDS:
        setattr(p, f, new.get(f, ""))
    p.account_number_bidx = bidx
    p.bank_change_request = cr
    p.save()
    security_event("partner_bank.changed", actor=approvers[-1] if approvers else None, entity="partner",
                   entity_id=p.pk, country=p.country,
                   data={"requested_by": str(cr.requested_by_id), "approved_by": [str(a.pk) for a in approvers],
                         "account_last4": new["account_number"][-4:]},
                   summary=f"Bank details changed for partner {p.name}")
    publish("partner.bank_details_changed", p.pk, {"partner_id": p.pk, "change_request_id": cr.pk})


@transaction.atomic
def set_partner_status(p: Partner, *, active: bool, by, reason="") -> Partner:
    """US-ADM-003: deactivation is logged; a deactivated partner cannot be assigned."""
    flags.read_only_guard()
    _require_admin(by)
    to = "active" if active else "inactive"
    p.deactivated_at = None if active else timezone.now()
    state.transition(p, "partner", to, actor=by, reason=reason,
                     event="partner.reactivated" if active else "partner.deactivated",
                     payload={"partner_id": str(p.pk), "kind": p.kind}, extra_fields=["deactivated_at"])
    return p


# --- Locked texts (FR-ADM-004, RUL-04) ------------------------------------------

REQUIRED_SIGNOFFS = {
    "scope_statement": ("lawyer", "insurer"),
    "terms": ("lawyer",),
    "escrow_terms": ("lawyer",),
    "privacy_notice": ("lawyer",),
    "insurance_statement": ("lawyer", "insurer"),
    "no_advice_statement": ("lawyer",),
}


def missing_signoffs(ltv: LockedTextVersion) -> list[str]:
    out = []
    for party in REQUIRED_SIGNOFFS.get(ltv.kind, ()):
        if not getattr(ltv, f"{party}_approval_evidence_id"):
            out.append(party)
    return out


@transaction.atomic
def propose_locked_text(*, kind, country, text, by, title="", copied_from=None) -> LockedTextVersion:
    flags.read_only_guard()
    if kind not in LockedTextVersion.KINDS:
        raise Invalid(f"Unknown locked text kind '{kind}'.", code="validation-error")
    if not (text or "").strip():
        raise Invalid("The text cannot be empty.", code="validation-error")
    last = LockedTextVersion.objects.filter(kind=kind, country=country).aggregate(m=Max("version"))["m"] or 0
    ltv = LockedTextVersion.objects.create(kind=kind, country=country, version=last + 1, title=title, text=text,
                                           text_sha256=hashlib.sha256(text.encode()).hexdigest(), proposed_by=by,
                                           copied_from=copied_from)
    record(actor=by, action="locked_text.proposed", entity="locked_text", entity_id=ltv.pk, country=country,
           data={"kind": kind, "version": ltv.version, "sha256": ltv.text_sha256})
    return ltv


@transaction.atomic
def edit_locked_text(ltv: LockedTextVersion, *, by, text=None, title=None) -> LockedTextVersion:
    if ltv.status != "draft":
        raise StateConflict("Only a draft can be edited. Propose a new version instead.")
    if text is not None:
        if not text.strip():
            raise Invalid("The text cannot be empty.")
        ltv.text, ltv.text_sha256 = text, hashlib.sha256(text.encode()).hexdigest()
        # a changed text needs fresh sign-offs
        for party in ("lawyer", "insurer"):
            setattr(ltv, f"{party}_approval_evidence", None)
            setattr(ltv, f"{party}_approved_by", "")
            setattr(ltv, f"{party}_approved_at", None)
    if title is not None:
        ltv.title = title
    ltv.save()
    record(actor=by, action="locked_text.edited", entity="locked_text", entity_id=ltv.pk, country=ltv.country,
           data={"sha256": ltv.text_sha256})
    return ltv


@transaction.atomic
def record_signoff(ltv: LockedTextVersion, *, party, approved_by_name, evidence, by) -> LockedTextVersion:
    """Record the lawyer's or insurer's written approval of this exact text."""
    if party not in ("lawyer", "insurer"):
        raise Invalid("party must be 'lawyer' or 'insurer'.")
    if ltv.status not in ("draft", "pending_approval"):
        raise StateConflict("This version is already closed.")
    if evidence is None:
        raise Invalid("Attach the written approval.", code="validation-error")
    if evidence.country_id != ltv.country_id:
        raise Invalid("The approval document belongs to another country.", code="country-mismatch")
    setattr(ltv, f"{party}_approval_evidence", evidence)
    setattr(ltv, f"{party}_approved_by", approved_by_name)
    setattr(ltv, f"{party}_approved_at", timezone.now())
    ltv.save()
    from evidence.services import link

    link(evidence, "locked_text", ltv.pk, role=f"{party}_approval", by=by)
    record(actor=by, action=f"locked_text.{party}_approval_recorded", entity="locked_text", entity_id=ltv.pk,
           country=ltv.country, data={"approved_by": approved_by_name, "evidence_id": str(evidence.pk),
                                      "text_sha256": ltv.text_sha256})
    return ltv


@transaction.atomic
def submit_locked_text(ltv: LockedTextVersion, *, by):
    """One administrator proposes; a second, different administrator approves."""
    flags.read_only_guard()
    _require_admin(by)
    if ltv.status != "draft":
        raise StateConflict("Only a draft can be sent for approval.")
    _signoffs_or_block(ltv)
    req = approvals.request_approval("locked_text_change", ltv.pk, by, required=1, country=ltv.country,
                                     summary=f"{ltv.get_kind_display()} version {ltv.version}")
    ltv.approval_request = req
    state.transition(ltv, "locked_text", "pending_approval", actor=by, extra_fields=["approval_request"])
    return req


def _signoffs_or_block(ltv):
    missing = missing_signoffs(ltv)
    if missing:
        raise RuleBlocked("The lawyer's and insurer's approvals must be recorded first.",
                          blocking_reasons=[{"rule": "RUL-04", "message": f"No recorded {m} approval"}
                                            for m in missing])


def decide_locked_text(ltv: LockedTextVersion, approver, *, decision="approve", mfa_at=None, note=""):
    if ltv.status != "pending_approval" or not ltv.approval_request_id:
        raise StateConflict("This version is not waiting for approval.")
    if decision == "approve":
        _signoffs_or_block(ltv)
    return approvals.decide(ltv.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=is_admin_approver)


def _publish_locked_text(ltv: LockedTextVersion, approvers):
    ltv = LockedTextVersion.objects.select_for_update().get(pk=ltv.pk)
    if ltv.status != "pending_approval":
        return ltv
    if missing_signoffs(ltv) or any(not is_admin_approver(a) for a in approvers):
        state.transition(ltv, "locked_text", "draft", reason="Approval did not meet RUL-04 or FR-ADM-004")
        security_event("locked_text.invalid_approval", entity="locked_text", entity_id=ltv.pk, country=ltv.country)
        return ltv
    for old in LockedTextVersion.objects.filter(kind=ltv.kind, country=ltv.country, status="published"):
        state.transition(old, "locked_text", "superseded", payload={"replaced_by": str(ltv.pk)})
    ltv.published_at = timezone.now()
    state.transition(ltv, "locked_text", "published", event="locked_text.published",
                     payload={"kind": ltv.kind, "version": ltv.version, "country": ltv.country.code,
                              "locked_text_id": str(ltv.pk), "approved_by": [str(a.pk) for a in approvers]},
                     extra_fields=["published_at"])
    return ltv


# --- Change requests: settings, flags, app versions, bank details ---------------

SUBJECT_FOR_KIND = {"partner_bank": "partner_bank_change", "feature_flag": "feature_flag_change",
                    "app_version": "setting_change"}


def _open_change(kind, target, country, old, new, by, reason, subject_type, summary) -> ChangeRequest:
    if ChangeRequest.objects.filter(kind=kind, target=target, country=country, status="pending").exists():
        raise StateConflict("A change to this value is already waiting for a second administrator.",
                            code="change-pending")
    cr = ChangeRequest.objects.create(kind=kind, target=target, country=country, old_value=old, new_value=new,
                                      reason=reason, requested_by=by)
    cr.approval_request = approvals.request_approval(subject_type, cr.pk, by, required=1, country=country,
                                                     summary=summary)
    cr.save(update_fields=["approval_request"])
    record(actor=by, action=f"{kind}.change_requested", entity="change_request", entity_id=cr.pk, country=country,
           data={"target": target, "old": old, "new": new, "reason": reason})
    return cr


def subject_type_of(cr: ChangeRequest) -> str:
    if cr.kind == "setting":
        return "release_setting_change" if registry.definition(cr.target).affects_release else "setting_change"
    return SUBJECT_FOR_KIND[cr.kind]


def decide_change(cr: ChangeRequest, approver, *, decision="approve", mfa_at=None, note=""):
    if cr.status != "pending" or not cr.approval_request_id:
        raise StateConflict("This change is not waiting for approval.")
    return approvals.decide(cr.approval_request, approver, decision=decision, mfa_at=mfa_at, note=note,
                            allowed=is_admin_approver)


@transaction.atomic
def withdraw_change(cr: ChangeRequest, *, by) -> ChangeRequest:
    if cr.requested_by_id != by.pk and not has_role(by, ADMIN):
        raise Forbidden()
    if cr.approval_request_id:
        approvals.withdraw(cr.approval_request, by)
    return state.transition(cr, "adm_change", "withdrawn", actor=by)


def apply_approved_change(cr: ChangeRequest, approvers):
    """Called by the approval handler. Checks the approvers again, because the
    generic approvals endpoint does not know this module's rule."""
    cr = ChangeRequest.objects.select_for_update().get(pk=cr.pk)
    if cr.status != "pending":
        return cr
    if any(not is_admin_approver(a) for a in approvers):
        state.transition(cr, "adm_change", "rejected", reason="Approved by someone who is not an administrator")
        security_event("change_request.invalid_approval", entity="change_request", entity_id=cr.pk,
                       country=cr.country)
        return cr
    if cr.kind == "setting":
        _apply_setting(cr.target, cr.new_value, cr.country, by=cr.requested_by, cr=cr, approvers=approvers)
    elif cr.kind == "feature_flag":
        _apply_flag(cr.target, cr.new_value, cr.country, by=cr.requested_by, approvers=approvers)
    elif cr.kind == "app_version":
        _apply_app_version(cr, approvers)
    elif cr.kind == "partner_bank":
        _apply_partner_bank(cr, approvers)
    cr.applied_at = timezone.now()
    state.transition(cr, "adm_change", "applied", actor=approvers[-1] if approvers else None,
                     payload={"kind": cr.kind, "target": cr.target}, extra_fields=["applied_at"])
    return cr


# --- Settings (FR-ADM-005) -----------------------------------------------------

@transaction.atomic
def change_setting(*, key, value, by, country=None, reason="") -> tuple[Setting | None, ChangeRequest | None]:
    """A value that affects a release, or one that needs a second administrator,
    waits for approval and rules keep the old value until then. Others apply
    at once. Every change is logged with old and new value."""
    flags.read_only_guard()
    _require_admin(by)
    d = registry.definition(key)
    if country is not None and not d.per_country:
        raise Invalid(f"{key} is a platform value, not a country value.")
    new = registry.validate(key, value)
    from .selectors import setting as current

    old = current(key, country)
    if d.affects_release or d.second_admin:
        st = "release_setting_change" if d.affects_release else "setting_change"
        cr = _open_change("setting", key, country, old, new, by, reason, st,
                          f"{key}: {old} to {new}" + (f" in {country.code}" if country else ""))
        return None, cr
    return _apply_setting(key, new, country, by=by), None


def _apply_setting(key, new, country, *, by, cr=None, approvers=()):
    d = registry.definition(key)
    row = Setting.objects.select_for_update().filter(key=key, country=country).first()
    old = row.value if row else d.default
    if row is None:
        row = Setting(key=key, country=country)
    row.value, row.affects_release, row.confirmed, row.changed_by, row.change_request = (
        new, d.affects_release, True, by, cr)
    row.save()
    data = {"key": key, "old": old, "new": new, "approved_by": [str(a.pk) for a in approvers]}
    record(actor=approvers[-1] if approvers else by, action="setting.changed", entity="setting", entity_id=row.pk,
           country=country, data=data)
    publish("setting.changed", row.pk, {"key": key, "country": getattr(country, "code", None), "old": old,
                                        "new": new})
    return row


# --- Feature flags (06 section 2.6) ----------------------------------------------

def flag_policy(name: str) -> str:
    """'kill_switch', 'safety' (two people to switch on) or 'plain'."""
    if name in KILL_SWITCHES:
        return "kill_switch"
    if name.startswith(SAFETY_FLAGS_PREFIXES) or name == "app.fee_payment_mode":
        return "safety"
    return "plain"


KILL_SWITCH_ROLES = {"maintenance.read_only": ("AD",), "escrow.instructions_paused": ("AD", "RV"),
                     "pro.payment_runs_paused": ("AD", "RV")}


@transaction.atomic
def change_flag(*, name, enabled, by, country=None, value=None, reason="") -> tuple[FeatureFlag | None,
                                                                                  ChangeRequest | None]:
    """Safety flags need two people to switch on, both named in the audit log;
    switching one off needs one person. Kill switches need one person, except
    that resuming professional payment runs needs a second person."""
    if not name:
        raise Invalid("Name the flag.")
    if country is not None and not name.startswith("lines."):
        raise Invalid("Only lines.* flags have a value per country.")
    policy = flag_policy(name)
    row = FeatureFlag.objects.filter(name=name, country=country).first()
    old = {"enabled": row.enabled if row else False, "value": row.value if row else ""}
    new = {"enabled": bool(enabled), "value": old["value"] if value is None else str(value),
           "reason": reason}
    if policy == "kill_switch":
        if not has_role(by, *KILL_SWITCH_ROLES[name]):
            raise Forbidden("You cannot pull this switch.")
        if name == "pro.payment_runs_paused" and old["enabled"] and not new["enabled"]:
            cr = _open_change("feature_flag", name, country, old, new, by, reason, "feature_flag_change",
                              "Resume professional payment runs")
            return None, cr
        return _apply_flag(name, new, country, by=by), None
    _require_admin(by)
    if policy == "safety" and (new["enabled"] and (not old["enabled"] or new["value"] != old["value"])):
        _block_unset_settings(name, country)
        cr = _open_change("feature_flag", name, country, old, new, by, reason, "feature_flag_change",
                          f"Switch on {name}" + (f" in {country.code}" if country else ""))
        return None, cr
    return _apply_flag(name, new, country, by=by), None


def _block_unset_settings(name, country):
    """US-ADM-005 criterion 2: go-live is blocked while a value it needs is
    still an unset [TO VERIFY] default."""
    from .selectors import unset_settings

    base = name if name in registry.FLAG_REQUIRES else None
    keys = registry.FLAG_REQUIRES.get(base, []) if base else []
    missing = unset_settings(keys, country)
    if missing:
        raise RuleBlocked(f"Set these values before switching on {name}: {', '.join(missing)}.",
                          code="setting-unset",
                          blocking_reasons=[{"rule": "FR-ADM-005", "message": f"{k} is still [TO VERIFY]"}
                                            for k in missing])


def _apply_flag(name, new, country, *, by, approvers=()):
    row = FeatureFlag.objects.select_for_update().filter(name=name, country=country).first()
    old = {"enabled": row.enabled, "value": row.value} if row else {"enabled": False, "value": ""}
    if row is None:
        row = FeatureFlag(name=name, country=country)
    row.enabled, row.value, row.changed_by = new["enabled"], new.get("value", ""), by
    row.reason = new.get("reason", "") or row.reason
    row.save()
    people = [str(by.pk)] + [str(a.pk) for a in approvers]
    data = {"name": name, "country": getattr(country, "code", None), "old": old,
            "new": {"enabled": row.enabled, "value": row.value}, "people": people}
    record(actor=approvers[-1] if approvers else by, action="feature_flag.changed", entity="feature_flag",
           entity_id=row.pk, country=country, data=data)
    if flag_policy(name) != "plain":
        security_event("feature_flag.changed", actor=by, entity="feature_flag", entity_id=row.pk, country=country,
                       data=data, summary=f"{name} switched {'on' if row.enabled else 'off'}")
    publish("feature_flag.changed", row.pk, {"name": name, "country": getattr(country, "code", None),
                                             "enabled": row.enabled, "value": row.value})
    return row


# --- App versions (FR-APP-006) ---------------------------------------------------

def parse_version(v: str) -> tuple:
    parts = []
    for p in str(v or "0").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits or 0))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


@transaction.atomic
def set_app_version(*, app, platform, by, min_version=None, latest_version=None, store_url=None,
                    reason="") -> tuple[AppVersion, ChangeRequest | None]:
    """Lowering the minimum or changing the latest version or store link applies
    at once. Raising the minimum locks out older installs, so it needs a
    second administrator (02 6.8, TC-APP-006-03)."""
    _require_admin(by)
    if app not in AppVersion.APPS or platform not in AppVersion.PLATFORMS:
        raise Invalid("app must be client or field; platform must be ios or android.")
    av, _ = AppVersion.objects.select_for_update().get_or_create(app=app, platform=platform)
    changed = {}
    if latest_version is not None and latest_version != av.latest_version:
        changed["latest_version"] = {"old": av.latest_version, "new": latest_version}
        av.latest_version = latest_version
    if store_url is not None and store_url != av.store_url:
        changed["store_url"] = {"old": av.store_url, "new": store_url}
        av.store_url = store_url
    cr = None
    if min_version is not None and min_version != av.min_version:
        if parse_version(min_version) > parse_version(av.latest_version or "0"):
            raise Invalid("The minimum cannot be above the latest version in the stores.")
        if parse_version(min_version) > parse_version(av.min_version):
            cr = _open_change("app_version", f"{app}/{platform}", None, {"min_version": av.min_version},
                              {"min_version": min_version, "app": app, "platform": platform}, by, reason,
                              "setting_change", f"Raise the minimum {app} app version on {platform} to {min_version}")
        else:
            changed["min_version"] = {"old": av.min_version, "new": min_version}
            av.min_version = min_version
    if changed:
        av.changed_by = by
        av.save()
        record(actor=by, action="app_version.changed", entity="app_version", entity_id=av.pk,
               data={"app": app, "platform": platform, "changes": changed})
        if "min_version" in changed:
            security_event("min_app_version.changed", actor=by, entity="app_version", entity_id=av.pk,
                           data={"app": app, "platform": platform, **changed["min_version"]})
    return av, cr


def _apply_app_version(cr: ChangeRequest, approvers):
    new = cr.new_value
    av = AppVersion.objects.select_for_update().get(app=new["app"], platform=new["platform"])
    old = av.min_version
    av.previous_min_version, av.min_version = old, new["min_version"]
    av.min_raised_at, av.changed_by, av.change_request = timezone.now(), cr.requested_by, cr
    av.save()
    data = {"app": av.app, "platform": av.platform, "old": old, "new": av.min_version,
            "people": [str(cr.requested_by_id)] + [str(a.pk) for a in approvers]}
    record(actor=approvers[-1] if approvers else None, action="app_version.min_raised", entity="app_version",
           entity_id=av.pk, data=data)
    security_event("min_app_version.changed", actor=approvers[-1] if approvers else None, entity="app_version",
                   entity_id=av.pk, data=data)
    publish("app_version.changed", av.pk, data)


def fee_payment_mode(country=None, platform=None) -> str:
    """FR-APP-005: 'web' or 'in_app_provider' (web until Q-23 is answered)."""
    from .selectors import setting_row

    row = setting_row("app_fee_payment_mode", country)
    mode = row.value if row is not None else flags.setting("app.fee_payment_mode", country, "web")
    return mode if mode in ("web", "in_app_provider") else "web"


def get_change(pk) -> ChangeRequest:
    cr = ChangeRequest.objects.filter(pk=pk).first()
    if not cr:
        raise NotFound()
    return cr

