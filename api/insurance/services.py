"""INS Insurer partner lines: the public interface other modules may call.

Behind the `lines.ins` flag (06 2.6), and shown only where a licensed insurer is contracted and Tenmina holds
any intermediary licence the country requires (C-11, US-INS-001 AC2). RUL-25: insurance is the named insurer's
policy; Tenmina collects no premium into its own account and pays or decides no claim.

    line_open(country) -> (bool, reasons)
    create_insurer(by, *, country, partner, ...) / set_insurer_payee(insurer, by, payee)
    record_intermediary_licence(by, *, country, body, reference, valid_until, evidence)
    create_product(by, *, insurer, kind, name, ...) / publish_product(product, by) / withdraw_product(product, by)
    apply(client, *, product, family_member, answers, premium_route) -> Application
    submit_application(app, client) / withdraw_application(app, client)
    record_outcome(app, by, *, outcome, ...) -> Policy | None      # the insurer's answer (IS)
    instruct_premium(premium, by) / report_premium_paid(premium, client, ...) / confirm_premium(premium, by, ...)
    record_renewal(policy, by, *, renews_on, document_evidence=None)
    start_claim(policy, client, *, description, ...) / record_claim_update(claim, by, *, insurer_status, ...)
Jobs (02 7.12): renewal_reminders(), premium_due()

Events published: application.submitted, policy.issued, premium.due, claim.updated.
Events consumed: release.confirmed, release.withdrawn, release.rejected, release.rejected_by_bank,
payee.verified, payee.suspended.
"""
from django.db import transaction
from django.utils import timezone

from administration import flags
from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, RuleBlocked, StateConflict
from core.events import publish
from core.money import q
from core.permissions import has_role

from . import adapters
from .common import (add_period, alert_staff, audit, cfg, days, fmt, is_staff, log, notify, now, resolve_action,
                     staff_in, today)
from .models import (PREMIUM_ROUTES, Application, Claim, ClaimUpdate, Insurer, IntermediaryLicence, Policy, Premium,
                     Product)

DEFAULT_STATEMENT = ("This policy is issued by {insurer}, a licensed insurer. Tenmina is not the insurer: it passes "
                     "your application to {insurer} and keeps your documents. {insurer} decides claims and pays them. "
                     "Premiums go only to {insurer}'s own account, never to Tenmina.")


def _on(country):
    flags.require("lines.ins", country)
    flags.read_only_guard()


def _admin(by, country):
    if not has_role(by, "AD", country=country):
        raise Forbidden("Only an administrator does this.")


def _rul25(message, code="premium-not-to-insurer"):
    return RuleBlocked(message, code=code, blocking_reasons=[{"rule": "RUL-25", "message": message}])


# ----------------------------------------------------------------- the line, insurers and licences (C-11)

def intermediary_licence(country) -> IntermediaryLicence | None:
    return IntermediaryLicence.objects.filter(country=country, status="active", valid_until__gte=today()) \
        .order_by("-valid_until").first()


def line_open(country) -> tuple[bool, list[dict]]:
    """US-INS-001 AC2: no licensed insurer or no intermediary licence for the country: the line is not shown."""
    reasons = []
    if not flags.enabled("lines.ins", country):
        reasons.append({"rule": "06-2.6", "message": "Insurance is not open in this country."})
    if cfg(country, "insurance.intermediary_licence_required", True) and intermediary_licence(country) is None:
        reasons.append({"rule": "C-11", "message": "Tenmina holds no intermediary licence for this country."})
    if not any(insurer_licensed(i) for i in Insurer.objects.filter(country=country, status="active")):
        reasons.append({"rule": "RUL-25", "message": "No licensed insurer partner is contracted for this country."})
    return not reasons, reasons


def insurer_licensed(insurer: Insurer) -> bool:
    return bool(insurer.status == "active" and insurer.licence_number and insurer.licence_valid_until
                and insurer.licence_valid_until >= today() and insurer.partner.status == "active")


def payee_reasons(insurer: Insurer, payee=None) -> list[dict]:
    """RUL-25: premiums only to the insurer's own verified payee record (kind insurer)."""
    p = payee or insurer.payee
    if p is None:
        return [{"rule": "RUL-25", "message": f"{insurer.name} has no verified account on record."}]
    out = []
    if p.kind != "insurer":
        out.append({"rule": "RUL-25", "message": "A premium is paid only to an insurer's account."})
    if p.verification_status != "verified" or p.name_match != "matched":
        out.append({"rule": "RUL-22", "message": f"The account of {insurer.name} is not verified."})
    if insurer.payee_id and p.pk != insurer.payee_id:
        out.append({"rule": "RUL-25", "message": f"This is not {insurer.name}'s account on record."})
    return out


@transaction.atomic
def create_insurer(by, *, country, partner, organisation=None, licence_body="", licence_number="",
                   licence_valid_until=None, licence_evidence=None, claim_contact="", routes=None, payee=None,
                   adapter_path="") -> Insurer:
    _admin(by, country)
    if partner.kind != "insurer" or partner.country_id != country.pk:
        raise Invalid("Choose an insurer partner registered in this country.", code="validation-error")
    routes = list(routes or PREMIUM_ROUTES)
    if any(r not in PREMIUM_ROUTES for r in routes) or not routes:
        raise Invalid(f"Routes are {', '.join(PREMIUM_ROUTES)}.", code="validation-error")
    if Insurer.objects.filter(country=country, partner=partner).exists():
        raise StateConflict("This insurer is already set up.")
    ins = Insurer.objects.create(country=country, partner=partner, organisation=organisation,
                                 licence_body=licence_body or "", licence_number=licence_number or "",
                                 licence_valid_until=licence_valid_until, licence_evidence=licence_evidence,
                                 claim_contact=claim_contact or "", routes=routes, adapter_path=adapter_path or "",
                                 created_by=by)
    if payee is not None:
        set_insurer_payee(ins, by, payee)
    audit(by, "ins_insurer.created", ins, {"partner_id": str(partner.pk), "licensed": bool(licence_number)})
    return ins


@transaction.atomic
def update_insurer(ins: Insurer, by, data: dict) -> Insurer:
    _admin(by, ins.country)
    for f in ("licence_body", "licence_number", "licence_valid_until", "licence_evidence", "claim_contact", "status",
              "organisation", "adapter_path"):
        if f in data and data[f] is not None:
            setattr(ins, f, data[f])
    if data.get("routes") is not None:
        if any(r not in PREMIUM_ROUTES for r in data["routes"]) or not data["routes"]:
            raise Invalid(f"Routes are {', '.join(PREMIUM_ROUTES)}.", code="validation-error")
        ins.routes = list(data["routes"])
    ins.save()
    audit(by, "ins_insurer.updated", ins, {"fields": sorted(k for k, v in data.items() if v is not None)})
    return ins


@transaction.atomic
def set_insurer_payee(ins: Insurer, by, payee) -> Insurer:
    """RUL-25: the only account a premium can go to. Changed later only through a payee change (RUL-28)."""
    _admin(by, ins.country)
    if payee.kind != "insurer" or payee.country_id != ins.country_id:
        raise _rul25("The premium account must be the insurer's own payee record (kind insurer).")
    if ins.payee_id and ins.payee_id != payee.pk:
        raise StateConflict("The insurer's account changes only through a payee change request (RUL-28).",
                            code="payee-locked")
    ins.payee = payee
    ins.save(update_fields=["payee"])
    audit(by, "ins_insurer.payee_set", ins, {"payee_id": str(payee.pk)})
    return ins


@transaction.atomic
def record_intermediary_licence(by, *, country, body, reference, valid_until, evidence) -> IntermediaryLicence:
    _admin(by, country)
    if evidence is None or not (body or "").strip() or not (reference or "").strip():
        raise Invalid("Give the licensing body, the licence reference and the licence itself.", code="validation-error")
    lic = IntermediaryLicence.objects.create(country=country, body=body, reference=reference,
                                             valid_until=valid_until, evidence=evidence, recorded_by=by)
    audit(by, "ins_intermediary_licence.recorded", lic, {"reference": reference})
    return lic


# ----------------------------------------------------------------- products (FR-INS-001)

def statement_for(product: Product) -> str:
    """TC-RUL-25-04: the insurer's name and that Tenmina is not the insurer, from a locked text when published."""
    text = None
    try:
        from administration.selectors import current_locked_text

        lt = current_locked_text("insurance_statement", product.country)
        text = getattr(lt, "text", None)
    except Exception:  # noqa: BLE001 - no such locked text kind yet: use the default wording
        text = None
    return (text or DEFAULT_STATEMENT).replace("{insurer}", product.insurer.name)


@transaction.atomic
def create_product(by, *, insurer, kind, name, terms_evidence, premium_amount, premium_currency=None,
                   premium_period="month", summary="", application_questions=None) -> Product:
    _on(insurer.country)
    if not has_role(by, "CM", "AD", country=insurer.country):
        raise Forbidden("Only Tenmina staff enter an insurer's product.")
    if kind not in Product.KINDS:
        raise Invalid("Kind must be health or funeral.", code="validation-error")
    if terms_evidence is None:
        raise Invalid("Attach the insurer's policy terms.", code="validation-error")
    if q(premium_amount) <= 0:
        raise Invalid("Enter the premium.", code="validation-error")
    p = Product.objects.create(country=insurer.country, insurer=insurer, kind=kind, name=name, summary=summary or "",
                               terms_evidence=terms_evidence, premium_amount=q(premium_amount),
                               premium_currency=(premium_currency or insurer.country.currency).upper(),
                               premium_period=premium_period, application_questions=application_questions or [],
                               created_by=by)
    from evidence.services import link

    link(terms_evidence, "ins_product", p.pk, role="policy_terms", by=by)
    audit(by, "ins_product.created", p, {"kind": kind})
    return p


@transaction.atomic
def publish_product(p: Product, by) -> Product:
    """TC-INS-001-02: refused for an insurer with no licence on record, or with no intermediary licence (C-11)."""
    _on(p.country)
    _admin(by, p.country)
    reasons = []
    if not insurer_licensed(p.insurer):
        reasons.append({"rule": "C-11", "message": f"{p.insurer.name} has no valid insurer licence on record."})
    if cfg(p.country, "insurance.intermediary_licence_required", True) and intermediary_licence(p.country) is None:
        reasons.append({"rule": "C-11", "message": "Tenmina holds no intermediary licence for this country."})
    reasons.extend(payee_reasons(p.insurer))
    if reasons:
        raise RuleBlocked("This product cannot be published.", code="insurer-not-licensed",
                          blocking_reasons=reasons)
    p.published_by, p.published_at = by, now()
    return state.transition(p, "ins_product", "published", actor=by, extra_fields=["published_by", "published_at"])


@transaction.atomic
def withdraw_product(p: Product, by) -> Product:
    _admin(by, p.country)
    return state.transition(p, "ins_product", "withdrawn", actor=by)


def products_for(country):
    ok, _ = line_open(country)
    if not ok:
        return Product.objects.none()
    return Product.objects.filter(country=country, status="published", insurer__status="active") \
        .select_related("insurer", "insurer__partner")


# ----------------------------------------------------------------- applications (FR-INS-002)

def insurer_ids_for(user):
    """The insurers whose users this person is: role IS and a member of the insurer's organisation."""
    if not has_role(user, "IS"):
        return []
    from accounts.selectors import organisations_of

    orgs = list(organisations_of(user).values_list("pk", flat=True))
    return list(Insurer.objects.filter(organisation_id__in=orgs).values_list("pk", flat=True))


def _require_insurer_user(by, insurer):
    if insurer.pk not in insurer_ids_for(by):
        raise NotFound()


def _insurer_users(insurer):
    from accounts.models import Person

    if insurer.organisation_id is None:
        return Person.objects.none()
    return Person.objects.filter(memberships__organisation=insurer.organisation, memberships__status="active",
                                 role_grants__role="IS", role_grants__revoked_at__isnull=True).distinct()


@transaction.atomic
def apply(client, *, product, family_member, answers=None, premium_route="client_direct_to_insurer") -> Application:
    from accounts.selectors import active_family_member

    _on(product.country)
    ok, reasons = line_open(product.country)
    if not ok:
        raise RuleBlocked("Cover is not offered in this country.", code="line-closed", blocking_reasons=reasons)
    if not client.has_tenmina_role("CL"):
        raise Forbidden("Only a client applies for cover.")
    if product.status != "published":
        raise StateConflict("This product is not offered.")
    fm = active_family_member(client, getattr(family_member, "pk", family_member))
    if premium_route not in product.insurer.routes:
        raise Invalid(f"{product.insurer.name} takes premiums by: {', '.join(product.insurer.routes)}.",
                      code="validation-error")
    if premium_route == "held_funds_to_insurer":
        flags.require("escrow.enabled", product.country)
    answers = answers or {}
    missing = [qn["label"] for qn in product.application_questions if qn.get("required") and
               answers.get(qn["key"]) in (None, "")]
    if missing:
        raise Invalid("Answer every required question: " + ", ".join(missing) + ".", code="validation-error")
    app = Application.objects.create(country=product.country, client=client, insured_family_member=fm,
                                     product=product, insurer=product.insurer, answers=answers,
                                     premium_route=premium_route)
    audit(client, "ins_application.created", app, {"product_id": str(product.pk)})
    return app


@transaction.atomic
def submit_application(app: Application, client, *, consent=True) -> Application:
    """US-INS-002 AC1: passed to the insurer in the agreed format; the client sees Sent to insurer."""
    _on(app.country)
    if app.client_id != client.pk:
        raise NotFound()
    if app.status != "draft":
        raise StateConflict("This application was already sent.")
    if not consent:
        raise Invalid("Agree that Tenmina passes your application to the insurer.", code="consent-required")
    res = adapters.insurer_port(app.insurer).submit_application(app)
    app.consent_at = app.submitted_to_insurer_at = now()
    app.insurer_reference, app.sent_via = res.get("reference", ""), res.get("channel", "")
    state.transition(app, "ins_application", "submitted", actor=client, event="application.submitted",
                     extra_fields=["consent_at", "submitted_to_insurer_at", "insurer_reference", "sent_via"],
                     payload={"application_id": app.pk, "insurer_id": app.insurer_id, "client_id": client.pk})
    for u in _insurer_users(app.insurer):
        notify(u, "ins_application_received", f"A new application for {app.product.name} (reference "
               f"{app.insurer_reference}).", obj=app, needs_action=True, link=f"/insurance/applications/{app.pk}",
               channels=("in_app", "email"))
    notify(client, "ins_application_sent", f"Your application was sent to {app.insurer.name}. {app.insurer.name} "
           "decides it and tells us; we tell you.", obj=app, link=f"/insurance/applications/{app.pk}",
           channels=("in_app",))
    return app


@transaction.atomic
def withdraw_application(app: Application, client) -> Application:
    if app.client_id != client.pk:
        raise NotFound()
    return state.transition(app, "ins_application", "withdrawn", actor=client)


@transaction.atomic
def record_outcome(app: Application, by, *, outcome, policy_number="", document_evidence=None, starts_on=None,
                   renews_on=None, claim_contact="", note="") -> Policy | None:
    """US-INS-002, US-INS-003: the insurer accepts with the policy document, or declines. Entered by the insurer
    (IS), or by a case manager from the insurer's own document."""
    _on(app.country)
    staff = has_role(by, "CM", country=app.country)
    if not staff:
        _require_insurer_user(by, app.insurer)
    if app.status != "submitted":
        raise StateConflict("This application is not waiting for the insurer.")
    app.decided_at, app.insurer_note = now(), note or ""
    if outcome == "declined":
        state.transition(app, "ins_application", "declined", actor=by, extra_fields=["decided_at", "insurer_note"])
        notify(app.client, "ins_application_declined", f"{app.insurer.name} declined the application"
               + (f": {note}" if note else "."), obj=app, channels=("in_app", "email"))
        return None
    if outcome != "accepted":
        raise Invalid("Outcome must be accepted or declined.", code="validation-error")
    if document_evidence is None or not policy_number or not starts_on or not renews_on:
        raise Invalid("Give the policy number, the policy document, the start and renewal dates.",
                      code="validation-error")
    if renews_on <= starts_on:
        raise Invalid("The renewal date must be after the start date.", code="validation-error")
    insurer = app.insurer
    reasons = payee_reasons(insurer)
    if reasons:
        raise RuleBlocked("The insurer's account is not verified, so no premium can be scheduled.",
                          code="payee-not-verified", blocking_reasons=reasons)
    state.transition(app, "ins_application", "accepted", actor=by, extra_fields=["decided_at", "insurer_note"])
    pr = app.product
    pol = Policy.objects.create(country=app.country, application=app, client=app.client,
                                insured_family_member=app.insured_family_member, insurer=insurer, product=pr,
                                policy_number=policy_number, document_evidence=document_evidence,
                                insurer_payee=insurer.payee, starts_on=starts_on, renews_on=renews_on,
                                claim_contact=claim_contact or insurer.claim_contact or "the insurer",
                                premium_amount=pr.premium_amount, premium_currency=pr.premium_currency,
                                premium_period=pr.premium_period, premium_route=app.premium_route)
    from evidence.services import link

    link(document_evidence, "ins_policy", pol.pk, role="policy_document", by=by)
    audit(by, "ins_policy.issued", pol, {"policy_number": policy_number, "sha256": document_evidence.sha256})
    publish("policy.issued", pol.pk, {"policy_id": pol.pk, "client_id": pol.client_id, "insurer_id": insurer.pk,
                                      "renews_on": renews_on})
    _due_premium(pol, starts_on)
    notify(app.client, "ins_policy_issued",
           f"{insurer.name} issued policy {policy_number} for {pol.insured_family_member.full_name}. It renews on "
           f"{renews_on:%d %B %Y}. Claims go to {pol.claim_contact}.", obj=pol, link=f"/insurance/policies/{pol.pk}",
           channels=("in_app", "email"))
    return pol


# ----------------------------------------------------------------- premiums (FR-INS-002, RUL-25)

def _due_premium(pol: Policy, due_on) -> Premium:
    pm, created = Premium.objects.get_or_create(
        policy=pol, due_on=due_on, defaults=dict(country=pol.country, amount=pol.premium_amount,
                                                 currency=pol.premium_currency, route=pol.premium_route))
    if created:
        publish("premium.due", pm.pk, {"premium_id": pm.pk, "policy_id": pol.pk, "client_id": pol.client_id,
                                       "due_on": due_on, "route": pm.route})
        if pm.route == "client_direct_to_insurer":
            notify(pol.client, "ins_premium_due",
                   f"A premium of {fmt(pm.amount, pm.currency)} for policy {pol.policy_number} is due on "
                   f"{due_on:%d %B %Y}. Pay {pol.insurer.name}'s own account; never Tenmina.", obj=pm,
                   needs_action=True, link=f"/insurance/premiums/{pm.pk}", channels=("in_app", "email"),
                   category="money")
    return pm


def pay_to(pm: Premium) -> dict:
    """client_direct_to_insurer: the insurer's verified account only (RUL-25, US-INS-002 AC2)."""
    pol = pm.policy
    reasons = payee_reasons(pol.insurer, pol.insurer_payee)
    if reasons:
        raise RuleBlocked("The insurer's account is not verified. Do not pay until it is.",
                          code="payee-not-verified", blocking_reasons=reasons)
    p = pol.insurer_payee
    return {"account_holder": p.legal_name, "bank_name": p.bank_name, "account_name": p.account_name,
            "account_number": p.account_number,
            "amount": {"amount": f"{pm.amount:.2f}", "currency": pm.currency},
            "reference": pol.policy_number,
            "note": f"Pay {pol.insurer.name} directly. Tenmina never receives premiums."}


@transaction.atomic
def instruct_premium(pm: Premium, by):
    """held_funds_to_insurer: the bank pays the insurer's verified payee from the client's held funds, after the
    client and two staff approve (RUL-05, RUL-11, RUL-25)."""
    from escrow import selectors as esel
    from escrow import services as esc

    _on(pm.country)
    if not has_role(by, "CM", "RV", country=pm.country):
        raise Forbidden("Only a case manager prepares a premium instruction.")
    pm = Premium.objects.select_for_update().get(pk=pm.pk)
    pol = pm.policy
    if pm.route != "held_funds_to_insurer":
        raise StateConflict("The client pays this premium to the insurer directly. Tenmina sends no instruction.",
                            code="route-client-direct")
    if pm.status not in ("due", "overdue"):
        raise StateConflict(f"This premium is {pm.status}.")
    if pol.status != "active":
        raise StateConflict("The policy is not active.")
    reasons = payee_reasons(pol.insurer, pol.insurer_payee)
    if reasons:
        raise RuleBlocked("Premiums go only to the insurer's verified account.", code="payee-not-verified",
                          blocking_reasons=reasons)
    e = esel.held_funds_for(pol.client, pm.country, pm.currency)
    if e is None:
        raise StateConflict("There is no amount held at the bank for this client.", code="held-funds-missing")
    ins = esc.request_release(e, payee=pol.insurer_payee, amount=pm.amount, subject_type="premium", subject_id=pm.pk,
                              requested_by=by, reason=f"Premium {pol.policy_number} due {pm.due_on:%d %B %Y}",
                              subject_label=f"Premium for {pol.product.name}, {pol.insurer.name}",
                              family_member_id=pol.insured_family_member_id, currency=pm.currency)
    pm.release_instruction = ins
    state.transition(pm, "ins_premium", "instructed", actor=by, extra_fields=["release_instruction"])
    return pm


@transaction.atomic
def report_premium_paid(pm: Premium, client, *, reference="", evidence=None) -> Premium:
    _on(pm.country)
    if pm.policy.client_id != client.pk:
        raise NotFound()
    if pm.route != "client_direct_to_insurer" or pm.status not in ("due", "overdue"):
        raise StateConflict("This premium is not waiting for your payment.")
    if not reference and evidence is None:
        raise Invalid("Give your transfer reference or upload its confirmation.", code="validation-error")
    pm.client_reported_at, pm.client_transfer_reference, pm.client_transfer_evidence = now(), reference or "", evidence
    state.transition(pm, "ins_premium", "client_reported", actor=client,
                     extra_fields=["client_reported_at", "client_transfer_reference", "client_transfer_evidence"])
    if evidence is not None:
        from evidence.services import link

        link(evidence, "ins_premium", pm.pk, role="client_transfer", by=client)
    resolve_action(pm)
    for u in _insurer_users(pm.policy.insurer):
        notify(u, "ins_premium_confirm", f"The client says they paid the premium for policy "
               f"{pm.policy.policy_number}. Please confirm when you receive it.", obj=pm, needs_action=True,
               channels=("in_app", "email"))
    return pm


@transaction.atomic
def confirm_premium(pm: Premium, by, *, received=True, receipt_evidence=None, note="") -> Premium:
    """The insurer confirms it received a client-direct premium (IS)."""
    _on(pm.country)
    _require_insurer_user(by, pm.policy.insurer)
    if pm.route != "client_direct_to_insurer" or pm.status not in ("due", "overdue", "client_reported"):
        raise StateConflict("This premium is not waiting for the insurer's confirmation.")
    if not received:
        if pm.status == "client_reported":
            state.transition(pm, "ins_premium", "due", actor=by, reason=note or "Not received")
        notify(pm.policy.client, "ins_premium_not_received", f"{pm.policy.insurer.name} has not received the premium"
               + (f": {note}" if note else "."), obj=pm, channels=("in_app", "email"), category="money")
        return pm
    pm.paid_at, pm.confirmed_by, pm.insurer_receipt_evidence = now(), by, receipt_evidence
    state.transition(pm, "ins_premium", "paid", actor=by,
                     extra_fields=["paid_at", "confirmed_by", "insurer_receipt_evidence"])
    if receipt_evidence is not None:
        from evidence.services import link

        link(receipt_evidence, "ins_premium", pm.pk, role="insurer_receipt", by=by)
    notify(pm.policy.client, "ins_premium_paid", f"{pm.policy.insurer.name} confirmed your premium for policy "
           f"{pm.policy.policy_number}.", obj=pm, channels=("in_app",), category="money")
    return pm


@transaction.atomic
def on_release_confirmed(payload: dict):
    if payload.get("subject_type") != "premium":
        return
    pm = Premium.objects.filter(pk=payload.get("subject_id"), status="instructed",
                                release_instruction_id=payload.get("instruction_id")).first()
    if pm is None:
        return
    pm.paid_at = now()
    state.transition(pm, "ins_premium", "paid", extra_fields=["paid_at"])
    notify(pm.policy.client, "ins_premium_paid", f"The bank paid your premium to {pm.policy.insurer.name}.", obj=pm,
           channels=("in_app",), category="money")


@transaction.atomic
def on_release_closed(payload: dict, why: str):
    if payload.get("subject_type") != "premium":
        return
    pm = Premium.objects.filter(pk=payload.get("subject_id"), status="instructed").first()
    if pm is None:
        return
    pm.release_instruction = None
    target = "overdue" if pm.due_on < today() else "due"
    state.transition(pm, "ins_premium", target, reason=why, extra_fields=["release_instruction"])
    alert_staff(pm.country, ("CM",), "ins_premium_stopped",
                f"The premium for policy {pm.policy.policy_number} did not go ahead: {why}.", obj=pm)


def release_check(instruction) -> list[dict]:
    """registry.subject_check("premium"): RUL-25, the instruction pays this premium to this insurer's payee."""
    pm = Premium.objects.filter(pk=instruction.subject_id).select_related("policy", "policy__insurer").first()
    if pm is None:
        return [{"rule": "RUL-25", "code": "premium-unknown", "message": "No such premium."}]
    pol = pm.policy
    out = []
    if pm.route != "held_funds_to_insurer":
        out.append({"rule": "FR-INS-002", "code": "route-client-direct",
                    "message": "This premium is paid by the client directly to the insurer."})
    if instruction.payee_id != pol.insurer_payee_id or (instruction.payee and instruction.payee.kind != "insurer"):
        out.append({"rule": "RUL-25", "code": "premium-not-to-insurer",
                    "message": "A premium is paid only to the insurer's own account on record."})
    if q(instruction.amount) != pm.amount or instruction.currency != pm.currency:
        out.append({"rule": "FR-INS-002", "code": "amount-mismatch", "message": "Not the premium's amount."})
    if instruction.escrow.client_id != pol.client_id:
        out.append({"rule": "RUL-22", "code": "escrow-not-client", "message": "The money held is another client's."})
    if pol.status not in ("active", "renewed"):
        out.append({"rule": "FR-INS-003", "code": "policy-not-active", "message": "The policy is not active."})
    out.extend({**r, "code": "premium-not-to-insurer"} for r in payee_reasons(pol.insurer, pol.insurer_payee))
    return out


# ----------------------------------------------------------------- renewals (FR-INS-003)

@transaction.atomic
def record_renewal(pol: Policy, by, *, renews_on, document_evidence=None, note="") -> Policy:
    """The insurer renews the policy: the new renewal date and, if any, the new document."""
    _on(pol.country)
    _require_insurer_user(by, pol.insurer)
    if renews_on <= pol.renews_on:
        raise Invalid("The new renewal date must be after the current one.", code="validation-error")
    pol.renews_on, pol.status_note = renews_on, note or ""
    if document_evidence is not None:
        pol.document_evidence = document_evidence
        from evidence.services import link

        link(document_evidence, "ins_policy", pol.pk, role="policy_document", by=by)
    pol.save(update_fields=["renews_on", "status_note", "document_evidence"])
    if pol.status == "lapsed":
        state.transition(pol, "ins_policy", "active", actor=by, reason="Renewed by the insurer")
    audit(by, "ins_policy.renewed", pol, {"renews_on": renews_on})
    notify(pol.client, "ins_policy_renewed", f"{pol.insurer.name} renewed policy {pol.policy_number} until "
           f"{renews_on:%d %B %Y}.", obj=pol, channels=("in_app", "email"))
    return pol


def renewal_reminders(on=None) -> dict:
    """insurance.renewal_reminders (daily): remind before renewal; mark lapsed what the insurer has not renewed."""
    t = on or today()
    reminded, lapsed = 0, 0
    for pol in Policy.objects.filter(status="active").select_related("insurer__partner", "client"):
        lead = int(cfg(pol.country, "insurance.renewal_reminder_days", 30) or 30)
        if pol.renews_on < t:
            with transaction.atomic():
                pol.status_note = ("The renewal date passed and the insurer has not confirmed a renewal. Ask "
                                   f"{pol.insurer.name}; Tenmina cannot say whether you are covered.")
                state.transition(pol, "ins_policy", "lapsed", reason="renewal date passed",
                                 extra_fields=["status_note"])
                notify(pol.client, "ins_policy_lapsed", f"Policy {pol.policy_number}: {pol.status_note}", obj=pol,
                       channels=("in_app", "email"))
                lapsed += 1
        elif pol.renews_on - days(lead) <= t and pol.renewal_reminded_for != pol.renews_on:
            pol.renewal_reminded_for = pol.renews_on
            pol.save(update_fields=["renewal_reminded_for"])
            notify(pol.client, "ins_renewal_reminder",
                   f"Policy {pol.policy_number} with {pol.insurer.name} renews on {pol.renews_on:%d %B %Y}.",
                   obj=pol, needs_action=True, link=f"/insurance/policies/{pol.pk}", channels=("in_app", "email"),
                   category="reminder")
            reminded += 1
    return {"reminded": reminded, "lapsed": lapsed}


def premium_due(on=None) -> dict:
    """insurance.premium_due (daily): the next premium falls due; overdue ones are marked; on the held-funds route
    the instruction is prepared and the client is asked to approve it."""
    t = on or today()
    created, overdue, instructed = 0, 0, 0
    for pol in Policy.objects.filter(status="active"):
        last = pol.premiums.order_by("-due_on").first()
        nxt = add_period(last.due_on, pol.premium_period) if last else pol.starts_on
        lead = int(cfg(pol.country, "insurance.premium_lead_days", 14) or 14)
        if nxt < pol.renews_on and nxt - days(lead) <= t:
            with transaction.atomic():
                _due_premium(pol, nxt)
                created += 1
    for pm in Premium.objects.filter(status="due", due_on__lt=t):
        state.transition(pm, "ins_premium", "overdue")
        overdue += 1
    for pm in Premium.objects.filter(status__in=["due", "overdue"], route="held_funds_to_insurer",
                                     release_instruction__isnull=True).select_related("policy"):
        preparer = staff_in(pm.country, "CM").first()
        if preparer is None or not flags.enabled("lines.ins", pm.country):
            continue
        try:
            with transaction.atomic():
                instruct_premium(pm, preparer)
                instructed += 1
        except DomainError as exc:
            log.warning("premium %s not instructed: %s", pm.pk, exc.detail)
    return {"created": created, "overdue": overdue, "instructed": instructed}


# ----------------------------------------------------------------- claims (FR-INS-004)

@transaction.atomic
def start_claim(pol: Policy, client, *, description, event_date=None, documents=()) -> Claim:
    """US-INS-004 AC1: passed to the insurer; the client sees Sent. Tenmina decides nothing."""
    _on(pol.country)
    if pol.client_id != client.pk:
        raise NotFound()
    if pol.status not in ("active", "renewed", "lapsed"):
        raise StateConflict("Claims are made on a policy the insurer issued.")
    if not (description or "").strip():
        raise Invalid("Say what happened.", code="validation-error")
    c = Claim.objects.create(country=pol.country, policy=pol, started_by=client, description=description,
                             event_date=event_date)
    from evidence.services import link

    for ev in documents:
        link(ev, "ins_claim", c.pk, role="claim_document", by=client)
    res = adapters.insurer_port(pol.insurer).submit_claim(c)
    c.submitted_to_insurer_at, c.insurer_reference, c.sent_via = now(), res.get("reference", ""), \
        res.get("channel", "")
    c.save(update_fields=["submitted_to_insurer_at", "insurer_reference", "sent_via"])
    audit(client, "ins_claim.sent", c, {"documents": len(documents)})
    publish("claim.updated", c.pk, {"claim_id": c.pk, "policy_id": pol.pk, "status": "sent",
                                    "client_id": client.pk})
    for u in _insurer_users(pol.insurer):
        notify(u, "ins_claim_received", f"A claim on policy {pol.policy_number} (reference {c.insurer_reference}).",
               obj=c, needs_action=True, channels=("in_app", "email"))
    notify(client, "ins_claim_sent", f"Your claim was sent to {pol.insurer.name}. {pol.insurer.name} decides it; we "
           "show you each answer here.", obj=c, link=f"/insurance/claims/{c.pk}", channels=("in_app",))
    return c


@transaction.atomic
def record_claim_update(c: Claim, by, *, insurer_status, note="", evidence=None, source="insurer_portal") -> Claim:
    """US-INS-004 AC2, TC-RUL-25-03: only the insurer's response is recorded; no Tenmina user can decide a claim."""
    _on(c.country)
    if by is not None and is_staff(by, c.country, ("CM", "RV", "AD")) and c.policy.insurer_id not in \
            insurer_ids_for(by):
        audit(by, "ins_claim.decision_refused", c, {"attempted": insurer_status})
        raise Forbidden("Tenmina does not decide claims. Only the insurer's own response is recorded.")
    if by is not None:
        _require_insurer_user(by, c.policy.insurer)
    elif source != "insurer_adapter":
        raise Forbidden("Only the insurer records a claim response.")
    if insurer_status not in Claim.INSURER_STATUSES:
        raise Invalid(f"Status must be one of {', '.join(Claim.INSURER_STATUSES)}.", code="validation-error")
    ClaimUpdate.objects.create(claim=c, insurer_status=insurer_status, note=note or "", evidence=evidence,
                               recorded_by=by, source=source)
    c.insurer_status, c.insurer_status_at = insurer_status, now()
    if evidence is not None:
        c.outcome_evidence = evidence
        from evidence.services import link

        link(evidence, "ins_claim", c.pk, role="insurer_response", by=by)
    c.save(update_fields=["insurer_status", "insurer_status_at", "outcome_evidence"])
    publish("claim.updated", c.pk, {"claim_id": c.pk, "policy_id": c.policy_id, "status": insurer_status,
                                    "client_id": c.policy.client_id})
    notify(c.policy.client, "ins_claim_update", f"{c.policy.insurer.name} updated your claim: "
           f"{insurer_status.replace('_', ' ')}." + (f" {note}" if note else ""), obj=c,
           link=f"/insurance/claims/{c.pk}", channels=("in_app", "email"))
    return c


def on_payee_status(payee_id, to):
    """A suspended insurer account: premiums cannot be instructed; staff are told."""
    if to not in ("suspended", "revoked"):
        return
    for ins in Insurer.objects.filter(payee_id=payee_id):
        alert_staff(ins.country, ("CM", "AD"), "ins_insurer_payee_suspended",
                    f"{ins.name}'s account is suspended. No premium can be paid to it until it is verified again.",
                    obj=ins)
