"""PTR Partner API: the public interface other modules may call
(document 02: 5.6, 7.3, 7.8; FR-PTR-001 to FR-PTR-004; RUL-16; journey J-06).

    create_client(by, *, country, partner, name, scopes, ...) -> (ApiClient, raw_secret)
    rotate_secret / set_client_status / update_client
    issue_token(client_id, client_secret, scope=None) -> dict          OAuth 2.0 client credentials, 15 minutes
    authenticate(raw_token) -> AccessToken
    meter(client, endpoint, ...) and check_rate(client)                 FR-PTR-004: every call metered; 429 over
    plot_status(client, *, plot_reference=None, point=None) -> dict     FR-PTR-001, FR-PTR-002 (consent at read time)
    full_report(client, report_id) -> dict                              FR-PTR-002, RUL-16: specific consent only
    create_order / confirm_order / decline_order                        FR-PTR-003
    subscribe_webhook / delete_webhook / enqueue / deliver_due           7.3 outbound webhooks
    usage(client, month) / close_month(client, month, by)               US-PTR-004 AC1

Everything is behind `partner_api.enabled` for the partner's country. The partner
API mounts at /v1/partner/... (02 7.4 names /partner/v1; every module mounts under /v1/).
Events published: partner.order_created. Consumed: report.released, consent.changed.
"""
import json
import logging
import secrets
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.utils import timezone

from administration import flags
from audit.services import record
from core import state
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict
from core.events import publish
from core.ids import uuid7
from core.permissions import has_role

from . import adapters
from .models import (SCOPES, WEBHOOK_EVENTS, AccessToken, ApiClient, PartnerOrder, UsageEvent, UsageStatement,
                     WebhookDelivery, WebhookSubscription, secret_hash)

log = logging.getLogger(__name__)
FLAG = "partner_api.enabled"
TOKEN_TTL = timedelta(minutes=15)
WEBHOOK_WINDOW = timedelta(hours=24)  # assumption (7.3)
OPEN_CASE = ("paid", "in_progress", "on_hold", "in_review")


class RateLimited(DomainError):
    status = 429
    code = "rate-limited"
    title = "Too many requests"


class Unauthenticated(DomainError):
    status = 401
    code = "unauthenticated"
    title = "Missing or expired credentials"


def _now():
    return timezone.now()


def _audit(actor, action, obj, data=None):
    record(actor=actor, action=action, entity=obj.__class__.__name__.lower(), entity_id=obj.pk, data=data or {},
           country=getattr(obj, "country", None))


def _notify(person, template, body, *, obj=None, link="", needs_action=False, category="status"):
    from notifications.services import notify

    if person is None:
        return
    try:
        notify(person, template, body=body, subject_obj=obj, link=link, needs_action=needs_action, category=category)
    except Exception:  # noqa: BLE001
        log.exception("notification %s failed", template)


def _alert_admins(country, body):
    from accounts.models import Person

    for p in Person.objects.filter(Q(role_grants__country__isnull=True) | Q(role_grants__country=country),
                                   role_grants__role="AD", role_grants__revoked_at__isnull=True).distinct():
        _notify(p, "partner_webhook_failing", body, needs_action=True, category="task")


def _admin(by, country):
    if not has_role(by, "AD", country=country):
        raise Forbidden("Only an administrator manages partner API clients.")


def require_on(client: ApiClient):
    flags.require(FLAG, client.country)


# =========================================================================== clients and tokens (EN-36, FR-PTR-004)

def _check_scopes(scopes):
    bad = sorted(set(scopes or []) - set(SCOPES))
    if bad:
        raise Invalid(f"Unknown scopes: {', '.join(bad)}.", code="validation-error")
    return sorted(set(scopes or []))


@transaction.atomic
def create_client(by, *, country, partner, name, scopes, rate_limit_per_minute=60, monthly_quota=None,
                  contact_person=None):
    """Returns the client and its secret. The secret is shown once and stored only as a hash."""
    _admin(by, country)
    if partner.country_id != country.pk or partner.kind not in ("api_partner", "escrow_bank", "insurer",
                                                                "developer", "bank_api"):
        raise Invalid("Choose a partner from the registry in this country.", code="validation-error")
    if contact_person is not None and not contact_person.has_tenmina_role("PT"):
        raise Invalid("The contact must hold the partner role.", code="validation-error")
    raw = secrets.token_urlsafe(32)
    c = ApiClient.objects.create(country=country, partner=partner, name=name.strip(),
                                 client_id=f"ptr_{secrets.token_hex(12)}", secret_sha256=secret_hash(raw),
                                 scopes=_check_scopes(scopes), rate_limit_per_minute=rate_limit_per_minute,
                                 monthly_quota=monthly_quota, contact_person=contact_person, created_by=by)
    _audit(by, "ptr_client.created", c, {"scopes": c.scopes, "partner": str(partner.pk)})
    return c, raw


@transaction.atomic
def update_client(c: ApiClient, by, *, scopes=None, rate_limit_per_minute=None, monthly_quota=..., name=None):
    _admin(by, c.country)
    if scopes is not None:
        c.scopes = _check_scopes(scopes)
    if rate_limit_per_minute is not None:
        c.rate_limit_per_minute = rate_limit_per_minute
    if monthly_quota is not ...:
        c.monthly_quota = monthly_quota
    if name:
        c.name = name
    c.save()
    _audit(by, "ptr_client.updated", c, {"scopes": c.scopes, "rate_limit": c.rate_limit_per_minute})
    return c


@transaction.atomic
def rotate_secret(c: ApiClient, by):
    _admin(by, c.country)
    if c.status == "revoked":
        raise StateConflict("This client is revoked.")
    raw = secrets.token_urlsafe(32)
    c.secret_sha256, c.secret_rotated_at = secret_hash(raw), _now()
    c.save(update_fields=["secret_sha256", "secret_rotated_at"])
    AccessToken.objects.filter(client=c, revoked_at__isnull=True).update(revoked_at=_now())
    _audit(by, "ptr_client.secret_rotated", c)
    return c, raw


@transaction.atomic
def set_client_status(c: ApiClient, by, status, reason=""):
    _admin(by, c.country)
    if status == "revoked":
        c.revoked_at = _now()
    state.transition(c, "ptr_api_client", status, actor=by, reason=reason, extra_fields=["revoked_at"])
    if status != "active":
        AccessToken.objects.filter(client=c, revoked_at__isnull=True).update(revoked_at=_now())
    return c


@transaction.atomic
def issue_token(client_id, client_secret, scope=None) -> dict:
    """OAuth 2.0 client credentials grant (5.6): a 15-minute token with the requested scopes."""
    c = ApiClient.objects.filter(client_id=client_id or "").select_related("country").first()
    if c is None or not secrets.compare_digest(c.secret_sha256, secret_hash(client_secret or "")):
        raise Unauthenticated("The client credentials are not valid.", code="invalid-client")
    if c.status != "active":
        raise Unauthenticated("This client is not active.", code="invalid-client")
    require_on(c)
    wanted = c.scopes if not scope else [s for s in str(scope).split() if s]
    if set(wanted) - set(c.scopes):
        raise Forbidden("A requested scope is not granted to this client.", code="invalid-scope")
    raw = secrets.token_urlsafe(32)
    AccessToken.objects.create(client=c, token_sha256=secret_hash(raw), scopes=sorted(wanted),
                               expires_at=_now() + TOKEN_TTL)
    return {"access_token": raw, "token_type": "Bearer", "expires_in": int(TOKEN_TTL.total_seconds()),
            "scope": " ".join(sorted(wanted))}


def authenticate(raw: str) -> AccessToken:
    tok = AccessToken.objects.select_related("client", "client__country").filter(
        token_sha256=secret_hash(raw or "")).first()
    if tok is None or tok.revoked_at or tok.expires_at < _now() or tok.client.status != "active":
        raise Unauthenticated("The access token is missing, expired or revoked.")
    return tok


def require_scope(tok: AccessToken, scope):
    if scope not in tok.scopes:
        raise Forbidden(f"This token does not carry the scope {scope}.", code="scope-missing")


# =========================================================================== metering and limits (FR-PTR-004)

def meter(client, endpoint, method, result_class, status_code, *, billable=True, **refs) -> UsageEvent:
    ev = UsageEvent.objects.create(client=client, country=client.country, endpoint=endpoint, method=method,
                                   result_class=result_class, status_code=status_code, billable=billable, **refs)
    ApiClient.objects.filter(pk=client.pk).update(last_used_at=_now())
    return ev


def check_rate(client, endpoint, method):
    """US-PTR-004 AC2: a call over the limit is refused with a retry time, and metered as not billable."""
    now = _now()
    window = now - timedelta(minutes=1)
    used = UsageEvent.objects.filter(client=client, occurred_at__gte=window).exclude(
        result_class__in=["rate_limited", "quota_exceeded"]).count()
    if used >= client.rate_limit_per_minute:
        first = UsageEvent.objects.filter(client=client, occurred_at__gte=window).order_by("occurred_at").first()
        retry = max(1, int(60 - (now - first.occurred_at).total_seconds())) if first else 60
        meter(client, endpoint, method, "rate_limited", 429, billable=False)
        raise RateLimited(f"The limit of {client.rate_limit_per_minute} calls a minute is reached.",
                          extra={"retry_after": retry})
    if client.monthly_quota:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if UsageEvent.objects.filter(client=client, occurred_at__gte=start, billable=True).count() \
                >= client.monthly_quota:
            meter(client, endpoint, method, "quota_exceeded", 429, billable=False)
            nxt = (start + timedelta(days=32)).replace(day=1)
            raise RateLimited("The monthly quota is used up.", extra={"retry_after": int((nxt - now).total_seconds())})


def usage(client, month: date) -> dict:
    start = month.replace(day=1)
    end = (start + timedelta(days=32)).replace(day=1)
    qs = UsageEvent.objects.filter(client=client, occurred_at__date__gte=start, occurred_at__date__lt=end)
    by = {r["result_class"]: r["n"] for r in qs.values("result_class").annotate(n=Count("id"))}
    return {"client_id": client.client_id, "partner": client.name, "month": start.isoformat(),
            "call_count": qs.count(), "billable_count": qs.filter(billable=True).count(),
            "order_count": qs.filter(result_class="order_created").count(), "by_result": by,
            "closed": UsageStatement.objects.filter(client=client, month=start).exists()}


@transaction.atomic
def close_month(client, month: date, by) -> UsageStatement:
    """US-PTR-004 AC1: when the month ends, each partner's count is fixed for invoicing."""
    _admin(by, client.country)
    start = month.replace(day=1)
    if (start + timedelta(days=32)).replace(day=1) > timezone.localdate():
        raise StateConflict("The month has not ended yet.")
    if UsageStatement.objects.filter(client=client, month=start).exists():
        raise StateConflict("This month is already closed.")
    u = usage(client, start)
    st = UsageStatement.objects.create(country=client.country, client=client, month=start,
                                       call_count=u["call_count"], billable_count=u["billable_count"],
                                       order_count=u["order_count"], by_result=u["by_result"], closed_by=by)
    _audit(by, "ptr_usage.month_closed", st, {"month": start.isoformat(), "billable": u["billable_count"]})
    return st


# =========================================================================== plot status (FR-PTR-001, FR-PTR-002)

def _assets(client, plot_reference=None, point=None):
    from geo.models import Asset
    from geo.selectors import assets_at_point

    if plot_reference:
        ref = str(plot_reference).strip()
        return list(Asset.objects.filter(country=client.country).filter(
            Q(reference__iexact=ref) | Q(site_plan_ref__iexact=ref) | Q(plot_number__iexact=ref)
            | Q(ghana_post_gps__iexact=ref))[:5])
    return list(assets_at_point(client.country, point["lng"], point["lat"])[:5])


def has_status_consent(person, client) -> str | None:
    from dataprotection.selectors import active_consents

    c = active_consents(person, "partner_status").filter(partner_client_id=client.pk).first()
    return str(c.pk) if c else None


def full_report_consent(person, client, report_id) -> str | None:
    from dataprotection.selectors import active_consents

    c = active_consents(person, "partner_full_report").filter(partner_client_id=client.pk,
                                                             report_id=report_id).first()
    return str(c.pk) if c else None


def plot_status(client, *, plot_reference=None, point=None, endpoint="/v1/partner/plot-status-queries") -> dict:
    """J-06, 7.8: no_report, in_progress, report_exists (no consent), verified with verdict and date (consent),
    or ambiguous when more than one plot matches. Consent is read at the moment of the call."""
    from cases.models import Case
    from reports.selectors import latest_released_for_asset

    if not plot_reference and not point:
        raise Invalid("Send plot_reference or point.", code="validation-error")
    assets = _assets(client, plot_reference, point)
    if len(assets) > 1:
        meter(client, endpoint, "POST", "ambiguous", 200)
        return {"status": "ambiguous"}
    if not assets:
        meter(client, endpoint, "POST", "no_report", 200)
        return {"status": "no_report"}
    asset = assets[0]
    report = latest_released_for_asset(asset.pk)
    if report is None:
        busy = Case.objects.filter(asset=asset, status__in=OPEN_CASE).exists()
        res = "in_progress" if busy else "no_report"
        meter(client, endpoint, "POST", res, 200, asset_id=asset.pk)
        return {"status": res}
    person = report.case.client
    consent = has_status_consent(person, client) if person else None
    if consent is None:
        meter(client, endpoint, "POST", "report_exists", 200, asset_id=asset.pk, report_id=report.pk)
        return {"status": "report_exists"}
    full = bool(full_report_consent(person, client, report.pk))
    meter(client, endpoint, "POST", "verified", 200, asset_id=asset.pk, report_id=report.pk, consent_id=consent)
    record(action="ptr.status_shared", entity="report", entity_id=report.pk, country=client.country,
           data={"client_id": client.client_id, "consent_id": consent})
    out = {"status": "verified", "verdict": report.overall_verdict,
           "report_date": report.released_at.date().isoformat(), "report_reference": report.reference,
           "full_report_available": full}
    if full:
        out["report_id"] = str(report.pk)
    return out


def full_report(client, report_id, *, endpoint="/v1/partner/reports") -> dict:
    """RUL-16, US-PTR-002 AC3, TC-RUL-16-01 to 03: the full report only with the client's specific consent for
    this partner and this report; the access is logged with the consent id."""
    from reports.models import Report

    r = Report.objects.filter(pk=report_id, country=client.country, status="released").select_related(
        "case__client").first()
    consent = full_report_consent(r.case.client, client, r.pk) if (r and r.case.client) else None
    if consent is None:
        meter(client, endpoint, "GET", "consent_missing", 403, billable=False, report_id=r.pk if r else None)
        raise Forbidden("The client has not consented to share this full report with you.", code="consent-required")
    meter(client, endpoint, "GET", "full_report", 200, report_id=r.pk, consent_id=consent)
    record(action="ptr.full_report_shared", entity="report", entity_id=r.pk, country=client.country,
           data={"client_id": client.client_id, "consent_id": consent})
    return {"report_reference": r.reference, "verdict": r.overall_verdict,
            "report_date": r.released_at.date().isoformat(), "pdf_sha256": r.pdf_sha256, "consent_id": consent,
            "sections": [{"number": s.label, "title": s.title, "verdict": s.verdict,
                          "findings": s.findings.get("text", "") if isinstance(s.findings, dict) else ""}
                         for s in r.sections.order_by("position")]}


# =========================================================================== partner orders (FR-PTR-003)

def _ref(country):
    base = f"PTO-{country.code}-{_now().year}-"
    n = PartnerOrder.objects.filter(reference__startswith=base).count() + 1
    return f"{base}{n:05d}"


@transaction.atomic
def create_order(client, *, client_email, locality, plot_number="", site_plan_ref="", asset_type="plot",
                 seller_name="", seller_phone="", tier="standard", partner_reference="") -> PartnerOrder:
    """A partner orders for a client who has consented to share with it. An unknown client and a client with no
    consent get the same refusal, so a partner learns nothing about who uses Tenmina."""
    from accounts.models import Person

    person = Person.objects.filter(email__iexact=(client_email or "").strip()).first()
    consent = has_status_consent(person, client) if person else None
    if consent is None:
        meter(client, "/v1/partner/orders", "POST", "consent_missing", 403, billable=False)
        raise Forbidden("No consent on file from this client for your organisation.", code="consent-required")
    if not (locality or "").strip():
        raise Invalid("Give the plot's locality.", code="validation-error")
    o = PartnerOrder.objects.create(country=client.country, reference=_ref(client.country), client=client,
                                    person=person, consent_id=consent, partner_reference=partner_reference or "",
                                    asset_type=asset_type, locality=locality.strip(), plot_number=plot_number or "",
                                    site_plan_ref=site_plan_ref or "", seller_name=seller_name or "",
                                    seller_phone=seller_phone or "", tier=tier or "standard")
    meter(client, "/v1/partner/orders", "POST", "order_created", 201, consent_id=consent)
    record(action="ptr_order.created", entity="ptr_partner_order", entity_id=o.pk, country=o.country,
           data={"client_id": client.client_id})
    publish("partner.order_created", o.pk, {"partner_order_id": o.pk, "client_id": client.pk,
                                            "person_id": person.pk, "country": o.country.code})
    _notify(person, "partner_order_confirm",
            f"{client.name} asked Tenmina to check a plot at {o.locality} for you. Confirm it in Tenmina.",
            obj=o, link=f"/partner-orders/{o.pk}", needs_action=True, category="request")
    return o


@transaction.atomic
def confirm_order(o: PartnerOrder, person) -> PartnerOrder:
    """The client confirms in the portal: a draft verification order is created for them, billed to the partner
    (the order carries bill_to_partner; the partner's invoice is recorded as an offline payment in PAY)."""
    from orders.services import create_order as ord_create

    if o.person_id != person.pk:
        raise NotFound()
    if o.status != "awaiting_client":
        raise StateConflict("This request is already decided.")
    if has_status_consent(person, o.client) is None:
        raise StateConflict("You withdrew your consent for this partner.", code="consent-required")
    order = ord_create(actor=person, country=o.country, kind="verification", draft=True, data={
        "asset": {"type": o.asset_type, "locality": o.locality, "plot_number": o.plot_number,
                  "site_plan_ref": o.site_plan_ref},
        "seller": {"name": o.seller_name, "phone": o.seller_phone}, "tier": o.tier, "lead_source": "other",
        "lead_source_detail": f"partner:{o.client.name}",
        "details": {"partner_order_id": str(o.pk), "partner_client_id": str(o.client_id), "bill_to_partner": True,
                    "partner_reference": o.partner_reference}})
    o.order_id, o.decided_at = order.pk, _now()
    state.transition(o, "ptr_partner_order", "confirmed", actor=person, extra_fields=["order_id", "decided_at"])
    enqueue(o.client, "verification.status_changed",
            {"partner_order_id": str(o.pk), "partner_reference": o.partner_reference, "status": "confirmed"})
    return o


@transaction.atomic
def decline_order(o: PartnerOrder, person) -> PartnerOrder:
    if o.person_id != person.pk:
        raise NotFound()
    if o.status != "awaiting_client":
        raise StateConflict("This request is already decided.")
    o.decided_at = _now()
    state.transition(o, "ptr_partner_order", "declined", actor=person, extra_fields=["decided_at"])
    enqueue(o.client, "verification.status_changed",
            {"partner_order_id": str(o.pk), "partner_reference": o.partner_reference, "status": "declined"})
    return o


# =========================================================================== webhooks (7.3)

@transaction.atomic
def subscribe_webhook(client, *, url, events) -> tuple[WebhookSubscription, str]:
    if not str(url).startswith("https://"):
        raise Invalid("Webhook URLs must use https.", code="validation-error")
    bad = sorted(set(events or []) - set(WEBHOOK_EVENTS))
    if bad or not events:
        raise Invalid(f"Events must be from: {', '.join(WEBHOOK_EVENTS)}.", code="validation-error")
    secret = "whsec_" + secrets.token_urlsafe(24)
    s = WebhookSubscription.objects.create(country=client.country, client=client, url=url, events=sorted(set(events)),
                                           secret=secret)
    record(action="ptr_webhook.subscribed", entity="ptr_webhook_subscription", entity_id=s.pk,
           country=client.country, data={"client_id": client.client_id, "events": s.events})
    return s, secret


@transaction.atomic
def delete_webhook(client, sub: WebhookSubscription):
    if sub.client_id != client.pk:
        raise NotFound()
    sub.status, sub.deleted_at = "deleted", _now()
    sub.save(update_fields=["status", "deleted_at"])
    return sub


def enqueue(client, event_type, data: dict, *, event_id=None) -> list[WebhookDelivery]:
    """A minimal envelope with ids only; the partner fetches details through the API so consent is checked at
    read time (7.3)."""
    if not flags.enabled(FLAG, client.country):
        return []
    eid = event_id or uuid7()
    body = json.dumps({"id": str(eid), "type": event_type, "created": _now().isoformat(), "data": data},
                      sort_keys=True)
    out = []
    for sub in client.webhooks.filter(status__in=["active", "failing"]):
        if event_type not in sub.events:
            continue
        try:
            with transaction.atomic():
                out.append(WebhookDelivery.objects.create(subscription=sub, event_id=eid, event_type=event_type,
                                                          body=body, next_attempt_at=_now()))
        except IntegrityError:
            continue
    return out


def _backoff(attempts) -> timedelta:
    return timedelta(minutes=min(2 ** max(attempts - 1, 0), 240))


def deliver(d: WebhookDelivery) -> WebhookDelivery:
    sub = d.subscription
    ts = int(_now().timestamp())
    headers = {"Tenmina-Signature": adapters.sign(sub.secret, ts, d.body), "Tenmina-Event-Id": str(d.event_id),
               "Tenmina-Event-Type": d.event_type}
    code = adapters.transport().post(sub.url, d.body, headers)
    d.attempts += 1
    d.last_status_code = code or None
    if 200 <= (code or 0) < 300:
        d.status, d.delivered_at, d.last_error = "delivered", _now(), ""
        if sub.status == "failing":
            sub.status, sub.failing_since = "active", None
            sub.save(update_fields=["status", "failing_since"])
    else:
        d.last_error = f"HTTP {code}" if code else "No response"
        if _now() - d.created_at >= WEBHOOK_WINDOW:
            d.status = "failed"
            if sub.status != "failing":
                sub.status, sub.failing_since = "failing", _now()
                sub.save(update_fields=["status", "failing_since"])
                _notify(sub.client.contact_person, "partner_webhook_failing",
                        f"Tenmina could not deliver webhooks to {sub.url} for 24 hours. Check your endpoint.",
                        obj=sub)
                _alert_admins(sub.country, f"Webhooks to {sub.client.name} have failed for 24 hours.")
        else:
            d.next_attempt_at = _now() + _backoff(d.attempts)
    d.save()
    return d


def deliver_due(now=None) -> int:
    n = 0
    for d in WebhookDelivery.objects.filter(status="pending", next_attempt_at__lte=now or _now()).select_related(
            "subscription__client")[:500]:
        deliver(d)
        n += 1
    return n


# =========================================================================== event reactions

def on_report_released(payload: dict):
    """A partner whose client consented hears that the status changed; it reads the verdict through the API."""
    from cases.models import Case

    case = Case.objects.filter(pk=payload.get("case_id")).first()
    if case is None or case.client_id is None:
        return
    from dataprotection.selectors import active_consents

    ids = set(active_consents(case.client, "partner_status").values_list("partner_client_id", flat=True))
    for c in ApiClient.objects.filter(pk__in=[i for i in ids if i], status="active"):
        enqueue(c, "verification.status_changed", {"asset_id": str(case.asset_id) if case.asset_id else None,
                                                   "report_id": str(payload.get("report_id"))})
    for o in PartnerOrder.objects.filter(Q(order_id=case.order_id) | Q(case_id=case.pk), status="confirmed"):
        o.case_id = case.pk
        state.transition(o, "ptr_partner_order", "completed", extra_fields=["case_id"])
        enqueue(o.client, "order.completed", {"partner_order_id": str(o.pk), "partner_reference": o.partner_reference,
                                              "report_id": str(payload.get("report_id"))})


def on_consent_changed(payload: dict):
    if payload.get("status") != "withdrawn" or payload.get("purpose") not in ("partner_status",
                                                                              "partner_full_report"):
        return
    c = ApiClient.objects.filter(pk=payload.get("partner_client_id")).first()
    if c is None:
        return
    enqueue(c, "consent.withdrawn", {"consent_id": str(payload.get("consent_id")), "purpose": payload.get("purpose"),
                                     "report_id": str(payload["report_id"]) if payload.get("report_id") else None},
            event_id=None)
