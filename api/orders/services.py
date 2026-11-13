"""ORD Orders: the public interface other modules may call.

FR-ORD-001 order with plot details, seller contact and documents, kept as a draft
FR-ORD-002 tier quote from configuration, price fixed before payment
FR-ORD-003 scope statement and terms accepted with time and version (RUL-04)
FR-ORD-004 paid only on PAY's confirmation; the case is created by CASE on order.paid
FR-ORD-005 lead source on every order
FR-ORD-006 referral codes and the reward owed
FR-ORD-007 extra inspection on a project at the configured price
"""
import secrets
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from administration import flags
from audit.services import record
from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict
from core.events import publish
from core.permissions import has_role
from countries.models import Country
from countries.selectors import config

from . import catalogue, legal, pricing
from .access import is_staff_for, organisation_ids
from .models import Order, ReferenceCounter, ReferralCode, ReferralReward, TermsAcceptance

EDITABLE = ["asset_type", "locality", "plot_number", "site_plan_ref", "ghana_post_gps", "seller_name", "seller_phone",
            "seller_email", "subject_type", "subject_id", "details", "notes", "tier", "lead_source",
            "lead_source_detail"]
TAMPER_KEYS = {"price", "amount", "price_amount", "local_price", "discount", "currency", "status", "purpose"}
DOCUMENT_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/heic", "image/webp", "image/tiff"}
ORDER_SUBJECT = "order"


def _country(value) -> Country:
    if isinstance(value, Country):
        return value
    c = Country.objects.filter(code=str(value or "").upper()).first()
    if c is None:
        raise Invalid("Choose a country Tenmina works in.", extra={"errors": [
            {"pointer": "/country", "message": "Unknown country."}]})
    return c


def _require_open(country: Country, product):
    flags.read_only_guard()
    if country.status not in ("active", "manual_phase"):
        raise DomainError(f"Tenmina does not take orders in {country.name} yet.", code="feature-off", status=404)
    if product.flag:
        flags.require(product.flag, country)


def next_reference(country: Country) -> str:
    year = timezone.now().year
    with transaction.atomic():
        ReferenceCounter.objects.get_or_create(country_code=country.code, year=year)
        c = ReferenceCounter.objects.select_for_update().get(country_code=country.code, year=year)
        c.last += 1
        c.save(update_fields=["last"])
    return f"TMR-{country.code}-{year}-{c.last:05d}"


def lead_sources(country) -> list[str]:
    return list(config(country, "lead_sources", catalogue.LEAD_SOURCES) or catalogue.LEAD_SOURCES)


# ---------------------------------------------------------------- creating


def _may_order(actor, product, on_behalf_of):
    if on_behalf_of is not None and on_behalf_of != actor:
        if not has_role(actor, "CM", "AD"):
            raise Forbidden("Only a case manager can place an order for someone else.")
        return
    if not has_role(actor, *product.roles):
        raise Forbidden("Your account cannot place this kind of order.")


def _organisation_for(actor, product, organisation_id):
    if product.bill_to != "organisation":
        return None
    from accounts.models import Organisation

    if not organisation_id:
        orgs = organisation_ids(actor)
        if len(orgs) == 1:
            organisation_id = orgs[0]
        else:
            raise Invalid("Choose the organisation that pays for this check.", extra={"errors": [
                {"pointer": "/organisation_id", "message": "This field is required."}]})
    org = Organisation.objects.filter(pk=organisation_id).first()
    if org is None or (org.pk not in organisation_ids(actor) and not has_role(actor, "CM", "AD")):
        raise Forbidden("You can only order for an organisation you belong to.")
    kinds = ("seller", "developer")
    if org.kind == "authority" and has_role(actor, "AR", "CM", "AD"):
        kinds = ("seller", "developer", "authority")  # a family or stool listing (US-LST-009)
    if org.kind not in kinds:
        raise Invalid("Only a seller or developer organisation, or a family or stool authority for its own "
                      "listings, pays for checked plots.")
    return org


def _apply_fields(order: Order, data: dict, actor):
    tampered = sorted(k for k in data if k in TAMPER_KEYS)
    if tampered:
        # TC-ORD-002-02: the server recalculates; a price in the request is ignored and audited.
        record(actor=actor, action="order.client_price_ignored", entity="order", entity_id=order.pk or "new",
               data={"fields": tampered}, country=order.country)
    asset = data.get("asset") or {}
    seller = data.get("seller") or {}
    flat = dict(data)
    for k in ("type", "locality", "plot_number", "site_plan_ref", "ghana_post_gps"):
        if k in asset:
            flat["asset_type" if k == "type" else k] = asset[k]
    for k in ("name", "phone", "email"):
        if k in seller:
            flat[f"seller_{k}"] = seller[k]
    for f in EDITABLE:
        if f in flat:
            value = flat[f]
            if f == "details":
                value = {**(order.details or {}), **(value or {})}
            elif f == "subject_id":
                value = value or None
            elif value is None:
                value = ""
            setattr(order, f, value)


@transaction.atomic
def create_order(*, actor, country, kind, data: dict, draft=False, on_behalf_of=None, ip=None, user_agent=""):
    """Create an order. With draft=True only kind and country are needed (US-ORD-001 AC3)."""
    product = catalogue.product(kind)
    c = _country(country)
    _require_open(c, product)
    _may_order(actor, product, on_behalf_of)
    client = on_behalf_of or actor
    org = _organisation_for(actor, product, data.get("organisation_id"))
    order = Order(country=c, reference=next_reference(c), client=client, placed_by=actor, kind=kind,
                  bill_to=product.bill_to, organisation=org, product_code=pricing.product_code(kind))
    if kind in ("verification", "listing_verification", "fresh_search") and not data.get("asset", {}).get("type") \
            and not data.get("asset_type"):
        order.asset_type = "plot"
    _apply_fields(order, data, actor)
    if data.get("parent_order_id"):
        order.parent_order = _parent_order(data["parent_order_id"], client)
    order.save()
    record(actor=actor, action="order.drafted", entity="order", entity_id=order.pk,
           data={"kind": kind, "reference": order.reference, "on_behalf_of": str(client.pk)}, country=c)
    if data.get("upload_ids"):
        link_uploads(order, actor, data["upload_ids"])
    if data.get("referral_code"):
        apply_referral(order, actor, data["referral_code"])
    if data.get("accept_terms"):
        accept_terms(order, actor, data.get("terms_version", ""), data.get("scope_version", ""), ip=ip,
                     user_agent=user_agent)
    _refresh_quote(order)
    if not draft:
        order = submit(order, actor)
    return order


def create_line_order(*, client, kind, country, subject_type="", subject_id=None, details=None, placed_by=None,
                      tier=None, lead_source="other", accepted_terms: tuple | None = None):
    """For other lines (FEE, CARE, TSK, PMG, EVT): create the fee order for a service.

    Returns a draft unless the client's acceptance of the current terms is passed
    as (terms_version, scope_version); then it is ready to pay."""
    data = {"subject_type": subject_type, "subject_id": subject_id, "details": details or {}, "tier": tier or "",
            "lead_source": lead_source}
    order = create_order(actor=placed_by or client, country=country, kind=kind, data=data, draft=True,
                         on_behalf_of=client if placed_by and placed_by != client else None)
    if accepted_terms:
        accept_terms(order, client, *accepted_terms)
        order = submit(order, placed_by or client)
    return order


def _parent_order(parent_id, client):
    parent = Order.objects.filter(pk=parent_id, client=client).first()
    if parent is None:
        raise NotFound("We could not find that earlier order.")
    return parent


def _editable(order: Order, actor):
    if order.status != "draft":
        raise StateConflict("Only a draft order can be changed. Use edit to reopen an unpaid order.")
    if actor != order.client and actor != order.placed_by and not has_role(actor, "CM", "AD"):
        raise Forbidden()


@transaction.atomic
def update_draft(order: Order, actor, data: dict):
    order = Order.objects.select_for_update().get(pk=order.pk)
    _editable(order, actor)
    flags.read_only_guard()
    _apply_fields(order, data, actor)
    if "parent_order_id" in data:
        order.parent_order = _parent_order(data["parent_order_id"], order.client) if data["parent_order_id"] else None
    order.save()
    if data.get("upload_ids"):
        link_uploads(order, actor, data["upload_ids"])
    if "referral_code" in data:
        if data["referral_code"]:
            apply_referral(order, actor, data["referral_code"])
        else:
            remove_referral(order, actor)
    _refresh_quote(order)
    return order


def _refresh_quote(order: Order):
    """Show the price on a draft as soon as there is enough to price it."""
    product = catalogue.product(order.kind)
    if product.tiered and not order.tier:
        return
    try:
        _lock_quote(order)
    except Invalid:
        return
    order.save()


def _lock_quote(order: Order):
    q = pricing.quote(order.country, order.kind, order.tier or None, asset_type=order.asset_type,
                      details=order.details, residence=getattr(order.client, "residence_country", ""))
    order.product_code = q.code
    order.tier_name = q.tier_name if order.tier else ""
    order.list_price_amount, order.list_price_currency = q.price.amount, q.price.currency
    order.guides = {"rates_per": q.price.currency, "amounts": q.guides, "guide_for_you": q.guide_for_you,
                    "note": "Guides only. You are charged the price shown."}
    order.price_source, order.config_version, order.turnaround_days = q.source, q.config_version, q.turnaround_days
    order.quoted_at = timezone.now()
    code = order.referral_code
    if code is not None and code.discount_pct:
        price, local, off = pricing.apply_discount(q, code.discount_pct)
        order.discount_amount = off.amount
    else:
        price, local = q.price, q.local_price
        order.discount_amount = Decimal("0")
    order.price_amount, order.price_currency = price.amount, price.currency
    order.local_price_amount = local.amount if local else None
    order.local_price_currency = local.currency if local else ""
    return q


# ---------------------------------------------------------------- documents


def link_uploads(order: Order, actor, upload_ids):
    from evidence.models import Evidence
    from evidence.services import link

    ids = [str(i) for i in upload_ids]
    found = list(Evidence.objects.filter(pk__in=ids, uploaded_by__in=[actor, order.client]))
    if len(found) != len(set(ids)):
        raise Invalid("Some uploads were not found. Upload them again.", code="evidence-rejected")
    existing = set(order_documents(order).values_list("pk", flat=True))
    for i, ev in enumerate(found):
        if ev.pk not in existing:
            if ev.size_bytes == 0:
                raise Invalid("The file is empty.", code="evidence-rejected")
            link(ev, ORDER_SUBJECT, order.pk, role="site_plan" if i == 0 and not existing else "document", by=actor)


def add_document(order: Order, actor, *, data: bytes, content_type: str, name: str = "", role="document"):
    """Upload a site plan or another document to the order (FR-ORD-001)."""
    from evidence.services import link, store

    if order.status not in ("draft", "awaiting_payment"):
        raise StateConflict("Documents can be added only before payment. Send later documents to your case.")
    if actor != order.client and actor != order.placed_by and not has_role(actor, "CM"):
        raise Forbidden()
    if not data:
        raise Invalid("The file is empty.", code="evidence-rejected")
    if content_type not in DOCUMENT_TYPES:
        raise Invalid("Upload a PDF or a photo (JPEG, PNG, HEIC, WebP or TIFF).", code="evidence-rejected")
    if role not in ("site_plan", "indenture", "seller_id", "building_permit", "document"):
        raise Invalid("Unknown document role.")
    ev = store(data=data, country=order.country, uploaded_by=actor, content_type=content_type, original_name=name,
               source="upload", description=f"Order {order.reference}: {role.replace('_', ' ')}")
    link(ev, ORDER_SUBJECT, order.pk, role=role, by=actor)
    return ev


def order_documents(order: Order):
    from evidence.services import for_subject

    return for_subject(ORDER_SUBJECT, order.pk)


# ---------------------------------------------------------------- terms


@transaction.atomic
def accept_terms(order: Order, actor, terms_version: str, scope_version: str, *, ip=None, user_agent=""):
    """FR-ORD-003, RUL-04: record acceptance of the current locked texts, with time and version."""
    if order.status not in ("draft", "awaiting_payment"):
        raise StateConflict("Terms are accepted before payment.")
    if actor != order.client and actor != order.placed_by:
        raise Forbidden("Only the person ordering can accept the terms.")
    cur = legal.current(order.country)
    if not terms_version or not scope_version:
        raise Invalid("Read and accept the scope statement and terms first.", code="terms-not-accepted", extra={
            "errors": [{"pointer": "/terms_version", "message": "Accept the terms."}],
            "terms_version": cur["terms_version"], "scope_version": cur["scope_version"]})
    if terms_version != cur["terms_version"] or scope_version != cur["scope_version"]:
        raise DomainError("The terms changed since you read them. Read the new version and accept again.",
                          code="terms-outdated", status=409,
                          extra={"terms_version": cur["terms_version"], "scope_version": cur["scope_version"]})
    now = timezone.now()
    TermsAcceptance.objects.create(order=order, country=order.country, person=actor, terms_version=terms_version,
                                   scope_version=scope_version, accepted_at=now, ip_address=ip or None,
                                   user_agent=(user_agent or "")[:500])
    order.terms_version, order.scope_version, order.terms_accepted_at = terms_version, scope_version, now
    order.save(update_fields=["terms_version", "scope_version", "terms_accepted_at"])
    record(actor=actor, action="order.terms_accepted", entity="order", entity_id=order.pk,
           data={"terms_version": terms_version, "scope_version": scope_version}, country=order.country)
    return order


def terms_current(order: Order) -> bool:
    """True when the client accepted the versions in force now (checked again before payment)."""
    if not order.terms_accepted_at:
        return False
    cur = legal.current(order.country)
    return order.terms_version == cur["terms_version"] and order.scope_version == cur["scope_version"]


# ---------------------------------------------------------------- submit


def validation_errors(order: Order) -> list[dict]:
    product = catalogue.product(order.kind)
    errors = []

    def need(pointer, ok, message="This field is required."):
        if not ok:
            errors.append({"pointer": pointer, "message": message})

    if product.needs_asset:
        need("/asset/type", order.asset_type in product.asset_types,
             f"Choose one of: {', '.join(product.asset_types)}.")
        need("/asset/locality", bool(order.locality.strip()))
        if order.asset_type == "plot":
            need("/asset/plot_number", bool(order.plot_number.strip()))
            need("/asset/site_plan_ref", bool(order.site_plan_ref.strip()))
    if product.needs_seller:
        need("/seller/name", bool(order.seller_name.strip()))
        need("/seller/phone", bool(order.seller_phone.strip() or order.seller_email.strip()),
             "Give the seller's phone number or email.")
    if product.tiered:
        need("/tier", bool(order.tier))
    if product.subject_type and order.kind != "family_plan":
        need("/subject_id", order.subject_id is not None)
    for d in product.required_details:
        need(f"/details/{d}", bool((order.details or {}).get(d)))
    if order.kind == "fresh_search":
        need("/parent_order_id", order.parent_order_id is not None or order.asset_id is not None,
             "Choose the earlier order or asset to search again.")
    need("/lead_source", bool(order.lead_source), "Tell us how you heard about Tenmina.")
    if order.lead_source and order.lead_source not in lead_sources(order.country):
        errors.append({"pointer": "/lead_source", "message": "Choose one of the listed sources."})
    if product.needs_documents:
        need("/upload_ids", order_documents(order).exists(), "Upload the site plan.")
    return errors


def _same_seller_ok(order: Order) -> bool:
    prior = Order.objects.filter(client=order.client, kind__in=["verification", "listing_verification"],
                                 status__in=["paid", "refunded"]).exclude(pk=order.pk)
    phone = order.seller_phone.strip()
    name = order.seller_name.strip().lower()
    return any((phone and o.seller_phone.strip() == phone) or (name and o.seller_name.strip().lower() == name)
               for o in prior)


@transaction.atomic
def submit(order: Order, actor):
    """Draft to awaiting payment: every required field, a fixed price and a current terms acceptance."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    _editable(order, actor)
    flags.read_only_guard()
    errors = validation_errors(order)
    if errors:
        raise Invalid("Some details are missing.", extra={"errors": errors})
    q = _lock_quote(order)
    if q.requires_same_seller and not _same_seller_ok(order):
        raise Invalid("This tier is for a further plot from a seller you already had checked with us.",
                      extra={"errors": [{"pointer": "/tier", "message": "No earlier order with this seller."}]})
    if not terms_current(order):
        cur = legal.current(order.country)
        raise Invalid("Read and accept the scope statement and terms first.", code="terms-not-accepted",
                      extra={"terms_version": cur["terms_version"], "scope_version": cur["scope_version"]})
    first = order.submitted_at is None
    order.submitted_at = order.submitted_at or timezone.now()
    order.save()
    state.transition(order, "order", "awaiting_payment", actor=actor,
                     event="order.created" if first else "order.status_changed",
                     payload=order_payload(order))
    return order


@transaction.atomic
def reopen(order: Order, actor):
    """Back to draft to change details or tier, if no payment is in progress."""
    order = Order.objects.select_for_update().get(pk=order.pk)
    if actor != order.client and actor != order.placed_by and not has_role(actor, "CM", "AD"):
        raise Forbidden()
    if order.status != "awaiting_payment":
        raise StateConflict("Only an unpaid order can be reopened.")
    if order.last_payment_status in ("initiated", "pending_approval"):
        raise StateConflict("A payment is in progress. Wait for it to finish or fail first.")
    return state.transition(order, "order", "draft", actor=actor)


@transaction.atomic
def cancel(order: Order, actor, reason: str):
    order = Order.objects.select_for_update().get(pk=order.pk)
    staff = has_role(actor, "CM", "AD") and is_staff_for(actor, order.country)
    if actor != order.client and actor != order.placed_by and not staff:
        raise Forbidden()
    if order.status not in ("draft", "awaiting_payment"):
        raise StateConflict("A paid order is closed through its case, with a refund decision (FR-CASE-012).")
    if order.last_payment_status in ("initiated", "pending_approval"):
        raise StateConflict("A payment is in progress. Wait for it to finish or fail first.")
    if not (reason or "").strip():
        raise Invalid("Give a reason.", extra={"errors": [{"pointer": "/reason", "message": "Required."}]})
    order.cancelled_at, order.cancel_reason = timezone.now(), reason.strip()
    return state.transition(order, "order", "cancelled", actor=actor, reason=reason.strip(),
                            event="order.cancelled", payload={"order_id": order.pk, "reference": order.reference},
                            extra_fields=["cancelled_at", "cancel_reason"])


# ---------------------------------------------------------------- payment side (called by PAY and handlers)


def payable(order: Order) -> dict:
    """What PAY needs to start a payment. Raises if the order cannot be paid now."""
    if order.status != "awaiting_payment":
        raise StateConflict("This order cannot be paid now.", extra={"order_status": order.status})
    if not terms_current(order):
        cur = legal.current(order.country)
        raise Invalid("Read and accept the scope statement and terms before you pay.", code="terms-not-accepted",
                      extra={"terms_version": cur["terms_version"], "scope_version": cur["scope_version"]})
    product = catalogue.product(order.kind)
    return {"purpose": product.purpose, "price": (order.price_amount, order.price_currency),
            "local_price": (order.local_price_amount, order.local_price_currency) if order.local_price_amount else None}


def note_payment(order_id, status: str, message: str = ""):
    """PAY tells the order how the latest payment attempt stands, for the client's screen."""
    Order.objects.filter(pk=order_id).update(last_payment_status=status, last_payment_message=message[:500],
                                             updated_at=timezone.now())


def order_payload(order: Order) -> dict:
    return {
        "order_id": order.pk, "reference": order.reference, "country": order.country.code,
        "country_id": order.country_id, "client_id": order.client_id, "placed_by_id": order.placed_by_id,
        "kind": order.kind, "product_line": catalogue.product_line(order.kind, order.asset_type),
        "bill_to": order.bill_to, "organisation_id": order.organisation_id,
        "asset": {"type": order.asset_type, "asset_id": order.asset_id, "locality": order.locality,
                  "plot_number": order.plot_number, "site_plan_ref": order.site_plan_ref,
                  "ghana_post_gps": order.ghana_post_gps},
        "seller": {"name": order.seller_name, "phone": order.seller_phone, "email": order.seller_email},
        "subject_type": order.subject_type, "subject_id": order.subject_id,
        "parent_order_id": order.parent_order_id, "tier": order.tier, "details": order.details,
        "price": {"amount": order.price_amount, "currency": order.price_currency},
        "local_price": {"amount": order.local_price_amount, "currency": order.local_price_currency},
        "lead_source": order.lead_source, "turnaround_days": order.turnaround_days,
    }


@transaction.atomic
def mark_paid(order_id, *, payment_id, method="", actor=None):
    """FR-ORD-004: only PAY's confirmation (provider or offline with proof) marks an order paid.

    Idempotent. Publishes order.paid, which CASE (and the line modules) consume."""
    order = Order.objects.select_for_update().filter(pk=order_id).first()
    if order is None or order.status == "paid" and order.paid_payment_id == payment_id:
        return order
    if order.status != "awaiting_payment":
        return order  # PAY raises a reconciliation issue for a payment on a closed or paid order
    order.paid_at, order.paid_payment_id, order.paid_method = timezone.now(), payment_id, method
    order.last_payment_status, order.last_payment_message = "confirmed", ""
    state.transition(order, "order", "paid", actor=actor, event="order.paid",
                     payload={**order_payload(order), "payment_id": payment_id, "method": method},
                     extra_fields=["paid_at", "paid_payment_id", "paid_method", "last_payment_status",
                                   "last_payment_message"])
    _record_reward(order)
    return order


@transaction.atomic
def mark_refunded(order_id, *, actor=None):
    order = Order.objects.select_for_update().filter(pk=order_id).first()
    if order is None or order.status != "paid":
        return order
    order.refunded_at = timezone.now()
    return state.transition(order, "order", "refunded", actor=actor, event="order.refunded",
                            payload={"order_id": order.pk, "reference": order.reference},
                            extra_fields=["refunded_at"])


def attach_case(order_id, case_id):
    """CASE calls this (or publishes case.created with order_id) when it creates the case."""
    Order.objects.filter(pk=order_id, case_id__isnull=True).update(case_id=case_id, updated_at=timezone.now())


def attach_asset(order_id, asset_id):
    """GEO calls this when it creates or matches the geo_asset for the order."""
    Order.objects.filter(pk=order_id, asset_id__isnull=True).update(asset_id=asset_id, updated_at=timezone.now())


# ---------------------------------------------------------------- referrals (FR-ORD-006)


def _referral_settings(country):
    cfg = config(country, "referrals", {}) or {}
    reward = cfg.get("reward") or {"amount": "25.00", "currency": "USD"}  # [TO VERIFY]
    return {"discount_pct": Decimal(str(cfg.get("discount_pct", "10"))),  # [TO VERIFY]
            "reward_amount": Decimal(str(reward["amount"])), "reward_currency": reward["currency"],
            "valid_days": cfg.get("valid_days")}


def check_referral(code_str: str, client, country) -> ReferralCode:
    code = ReferralCode.objects.filter(code__iexact=(code_str or "").strip()).first()
    now = timezone.now()
    if code is None or not code.active or code.country_id != _country(country).pk:
        raise Invalid("That referral code is not valid. Your price has not changed.", code="referral-invalid")
    if (code.valid_from and code.valid_from > now) or (code.valid_until and code.valid_until < now):
        raise Invalid("That referral code has expired. Your price has not changed.", code="referral-invalid")
    if code.owner_id == client.pk:
        raise Invalid("You cannot use your own referral code.", code="referral-invalid")
    if code.max_uses is not None and code.rewards.exclude(status="void").count() >= code.max_uses:
        raise Invalid("That referral code has been used up. Your price has not changed.", code="referral-invalid")
    used = Order.objects.filter(client=client, referral_code__isnull=False, status__in=["paid", "refunded"])
    if used.exists():
        raise Invalid("A referral code can be used on your first paid order only.", code="referral-invalid")
    return code


@transaction.atomic
def apply_referral(order: Order, actor, code_str: str):
    if order.status not in ("draft",):
        raise StateConflict("Add a referral code before you submit the order.")
    try:
        code = check_referral(code_str, order.client, order.country)
    except Invalid:
        record(actor=actor, action="order.referral_refused", entity="order", entity_id=order.pk,
               data={"code": (code_str or "")[:32]}, country=order.country)
        raise
    order.referral_code = code
    if not order.lead_source:
        order.lead_source = "referral"
    order.save(update_fields=["referral_code", "lead_source"])
    _refresh_quote(order)
    record(actor=actor, action="order.referral_applied", entity="order", entity_id=order.pk,
           data={"code": code.code}, country=order.country)
    return order


@transaction.atomic
def remove_referral(order: Order, actor):
    if order.status != "draft":
        raise StateConflict("The referral code can be changed only on a draft.")
    order.referral_code = None
    order.save(update_fields=["referral_code"])
    _refresh_quote(order)
    return order


def _record_reward(order: Order):
    code = order.referral_code
    if code is None or ReferralReward.objects.filter(order=order).exists():
        return None
    reward = ReferralReward.objects.create(
        country=order.country, referral_code=code, referrer=code.owner, referred_client=order.client, order=order,
        amount=code.reward_amount, currency=code.reward_currency)
    record(action="referral_reward.owed", entity="referral_reward", entity_id=reward.pk,
           data={"order": order.reference, "code": code.code, "amount": reward.amount, "currency": reward.currency},
           country=order.country)
    publish("referral.reward_owed", reward.pk, {"reward_id": reward.pk, "order_id": order.pk,
                                                "referrer_id": code.owner_id, "amount": reward.amount,
                                                "currency": reward.currency})
    if code.owner_id:
        from notifications.services import notify

        notify(code.owner, "referral_reward_owed", subject="Someone you referred has ordered",
               body=f"Thank you. A reward of {reward.currency} {reward.amount:.2f} is owed to you for a referral.",
               link="/referrals", subject_obj=reward)
    return reward


def _new_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    while True:
        c = "TM-" + "".join(secrets.choice(alphabet) for _ in range(6))
        if not ReferralCode.objects.filter(code=c).exists():
            return c


@transaction.atomic
def my_referral_code(person, country) -> ReferralCode:
    c = _country(country)
    code = ReferralCode.objects.filter(owner=person, country=c, active=True).first()
    if code:
        return code
    s = _referral_settings(c)
    code = ReferralCode.objects.create(country=c, code=_new_code(), owner=person, owner_label=person.full_name,
                                       discount_pct=s["discount_pct"], reward_amount=s["reward_amount"],
                                       reward_currency=s["reward_currency"], valid_from=timezone.now(),
                                       created_by=person)
    record(actor=person, action="referral_code.created", entity="referral_code", entity_id=code.pk,
           data={"code": code.code}, country=c)
    return code


@transaction.atomic
def create_referral_code(actor, *, country, owner_label, code=None, owner=None, discount_pct=None,
                         reward_amount=None, reward_currency=None, valid_until=None, max_uses=None):
    """Staff create a code for an association, webinar or remittance partner."""
    if not has_role(actor, "CM", "AD"):
        raise Forbidden()
    c = _country(country)
    s = _referral_settings(c)
    value = (code or _new_code()).strip().upper()
    if ReferralCode.objects.filter(code__iexact=value).exists():
        raise Invalid("That code is already taken.", extra={"errors": [{"pointer": "/code", "message": "Taken."}]})
    rc = ReferralCode.objects.create(
        country=c, code=value, owner=owner, owner_label=owner_label,
        discount_pct=s["discount_pct"] if discount_pct is None else discount_pct,
        reward_amount=s["reward_amount"] if reward_amount is None else reward_amount,
        reward_currency=reward_currency or s["reward_currency"], valid_from=timezone.now(),
        valid_until=valid_until, max_uses=max_uses, created_by=actor)
    record(actor=actor, action="referral_code.created", entity="referral_code", entity_id=rc.pk,
           data={"code": rc.code, "owner_label": owner_label}, country=c)
    return rc


def deactivate_referral_code(actor, code: ReferralCode):
    if not has_role(actor, "CM", "AD") and code.owner_id != actor.pk:
        raise Forbidden()
    code.active = False
    code.save(update_fields=["active"])
    record(actor=actor, action="referral_code.deactivated", entity="referral_code", entity_id=code.pk,
           data={"code": code.code}, country=code.country)
    return code


@transaction.atomic
def mark_reward_paid(actor, reward: ReferralReward, reference: str):
    """Rewards are paid from Tenmina's operating account; the administrator records the payment."""
    if not has_role(actor, "AD"):
        raise Forbidden("Only an administrator records reward payments.")
    if not (reference or "").strip():
        raise Invalid("Give the payment reference.")
    reward.paid_at, reward.paid_reference, reward.decided_by = timezone.now(), reference.strip(), actor
    return state.transition(reward, "referral_reward", "paid", actor=actor, event="referral.reward_paid",
                            extra_fields=["paid_at", "paid_reference", "decided_by"])


@transaction.atomic
def void_reward(actor, reward: ReferralReward, reason: str):
    if not has_role(actor, "CM", "AD"):
        raise Forbidden()
    if not (reason or "").strip():
        raise Invalid("Give a reason.")
    reward.void_reason, reward.decided_by = reason.strip(), actor
    return state.transition(reward, "referral_reward", "void", actor=actor, reason=reason,
                            extra_fields=["void_reason", "decided_by"])


# ---------------------------------------------------------------- extra inspection (FR-ORD-007)


ACTIVE_PROJECT_STATUSES = {"active", "in_progress", "started", "mobilised", "underway"}


def _project(project_id):
    from django.apps import apps

    try:
        model = apps.get_model("construction", "Project")
    except LookupError:
        return None, False
    return model.objects.filter(pk=project_id).first(), True


@transaction.atomic
def order_extra_inspection(*, actor, project_id, data: dict, ip=None, user_agent=""):
    """A client orders an extra inspection on an active build at the configured price.

    BLD creates the inspection task for a conflict-free inspector on order.paid."""
    project, known = _project(project_id)
    country = data.get("country")
    if known:
        if project is None or getattr(project, "client_id", None) != actor.pk:
            raise NotFound("We could not find that project.")
        if str(getattr(project, "status", "active")) not in ACTIVE_PROJECT_STATUSES:
            raise StateConflict("Extra inspections can be ordered only on an active build.")
        country = getattr(project, "country", None) or country
    country = country or getattr(actor, "home_country", None)
    if country is None:
        raise Invalid("Choose the country of the project.")
    payload = {**data, "subject_type": "project", "subject_id": project_id,
               "details": {**(data.get("details") or {}), "concern": data.get("concern", "")}}
    payload.setdefault("lead_source", "other")
    return create_order(actor=actor, country=country, kind="extra_inspection", data=payload,
                        draft=not data.get("accept_terms"), ip=ip, user_agent=user_agent)
