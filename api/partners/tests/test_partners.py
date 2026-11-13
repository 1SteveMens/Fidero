"""Partner API (US-PTR-001 to US-PTR-004, RUL-16, J-06, 02 7.3 and 7.8)."""
import json
import time
from datetime import timedelta

import pytest
from django.utils import timezone

from partners.seed import DEV_CLIENT_ID, DEV_CLIENT_SECRET


@pytest.fixture
def ptr(seeded):
    from partners.models import ApiClient

    return ApiClient.objects.get(client_id=DEV_CLIENT_ID)


def _token(api, scope=None):
    body = {"grant_type": "client_credentials", "client_id": DEV_CLIENT_ID, "client_secret": DEV_CLIENT_SECRET}
    if scope:
        body["scope"] = scope
    r = api().post("/v1/partner/oauth/token", body, format="json")
    assert r.status_code == 200, r.content
    c = api()
    c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access_token']}")
    return c


def _released_asset():
    from reports.models import Report

    r = Report.objects.filter(status="released", case__asset__isnull=False, case__client__isnull=False).select_related(
        "case__asset", "case__client").first()
    if r is None:
        pytest.skip("no released report on an asset in the seed")
    return r


def _consent(person, client, purpose="partner_status", report=None):
    from dataprotection import services as dpr

    return dpr.give_consent(person, purpose=purpose, text_version="1", partner_client_id=client.pk,
                            report_id=report.pk if report else None)


def test_token_and_bad_keys(seeded, api, ptr):
    """FR-PTR-004, TC-PTR-001-02, TC-E2E-J06-04: a bad or revoked key gets 401."""
    from partners import services

    r = api().post("/v1/partner/oauth/token", {"grant_type": "client_credentials", "client_id": DEV_CLIENT_ID,
                                               "client_secret": "wrong"}, format="json")
    assert r.status_code == 401
    assert api().post("/v1/partner/plot-status-queries", {"plot_reference": "x"}, format="json").status_code == 401
    c = _token(api)
    services.set_client_status(ptr, seeded["people"]["admin"], "revoked", "Contract ended")
    assert c.post("/v1/partner/plot-status-queries", {"plot_reference": "x"}, format="json").status_code == 401
    # A person's own session never works on the partner API.
    assert api(seeded["people"]["partner"]).post("/v1/partner/plot-status-queries", {"plot_reference": "x"},
                                                 format="json").status_code == 401


def test_scope_missing(seeded, api, ptr):
    c = _token(api, scope="usage.read")
    r = c.post("/v1/partner/plot-status-queries", {"plot_reference": "x"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "scope-missing"


def test_status_with_and_without_consent(seeded, api, ptr):
    """US-PTR-001 AC1, US-PTR-002 AC1 and AC2, TC-RUL-16-02, TC-RUL-16-03, TC-E2E-J06-01 to 03: without consent
    only 'report exists'; with consent verdict and date; withdrawn consent stops it at once."""
    from dataprotection import services as dpr
    from dataprotection.models import Consent

    rep = _released_asset()
    owner = rep.case.client
    Consent.objects.filter(person=owner, partner_client_id=ptr.pk).update(withdrawn_at=timezone.now())
    c = _token(api)
    r = c.post("/v1/partner/plot-status-queries", {"plot_reference": rep.case.asset.reference}, format="json")
    assert r.status_code == 200 and r.json() == {"status": "report_exists"}
    consent = _consent(owner, ptr)
    r = c.post("/v1/partner/plot-status-queries", {"plot_reference": rep.case.asset.reference}, format="json")
    body = r.json()
    assert body["status"] == "verified" and body["report_reference"] and body["report_date"]
    assert body["verdict"] == rep.overall_verdict and body["full_report_available"] is False
    dpr.withdraw_consent(consent, owner)
    r = c.post("/v1/partner/plot-status-queries", {"plot_reference": rep.case.asset.reference}, format="json")
    assert r.json() == {"status": "report_exists"}
    r = c.post("/v1/partner/plot-status-queries", {"plot_reference": "NOT-A-PLOT"}, format="json")
    assert r.json() == {"status": "no_report"}


def test_status_by_point(seeded, api, ptr):
    """US-PTR-001 AC2: coordinates inside a plot's current boundary return that plot's status."""
    from geo.models import Asset

    asset = Asset.objects.filter(country=seeded["gh"], current_boundary__isnull=False).first()
    if asset is None:
        pytest.skip("no asset with a boundary in the seed")
    pt = asset.current_boundary.centroid
    r = _token(api).post("/v1/partner/plot-status-queries", {"point": {"lat": pt.y, "lng": pt.x}}, format="json")
    assert r.status_code == 200
    assert r.json()["status"] in ("no_report", "in_progress", "report_exists", "verified", "ambiguous")
    r = _token(api).post("/v1/partner/plot-status-queries", {"point": {"lat": 0.0, "lng": 0.0}}, format="json")
    assert r.json() == {"status": "no_report"}


def test_full_report_needs_specific_consent(seeded, api, ptr):
    """FR-PTR-002, RUL-16, US-PTR-002 AC3, TC-RUL-16-01: the full report only with consent for this partner and
    this report; the access is logged with the consent id."""
    from audit.models import AuditEvent

    rep = _released_asset()
    c = _token(api)
    r = c.get(f"/v1/partner/reports/{rep.pk}")
    assert r.status_code == 403 and r.json()["code"] == "consent-required"
    consent = _consent(rep.case.client, ptr, "partner_full_report", rep)
    r = c.get(f"/v1/partner/reports/{rep.pk}")
    assert r.status_code == 200 and r.json()["consent_id"] == str(consent.pk) and r.json()["sections"]
    assert AuditEvent.objects.filter(action="ptr.full_report_shared", entity_id=str(rep.pk)).exists()


def test_rate_limit_and_metering(seeded, api, ptr):
    """FR-PTR-004, US-PTR-004 AC1 and AC2, TC-PTR-004-01: calls are metered per partner; over the limit they are
    refused with a retry time; the month's count is available and can be closed for invoicing."""
    from partners import services
    from partners.models import UsageEvent

    ptr.rate_limit_per_minute = 3
    ptr.save(update_fields=["rate_limit_per_minute"])
    UsageEvent.objects.filter(client=ptr).count()
    c = _token(api)
    codes = [c.post("/v1/partner/plot-status-queries", {"plot_reference": "X"}, format="json") for _ in range(5)]
    assert [r.status_code for r in codes].count(429) >= 2
    limited = next(r for r in codes if r.status_code == 429)
    assert int(limited["Retry-After"]) >= 1 and limited.json()["code"] == "rate-limited"
    u = services.usage(ptr, timezone.localdate())
    assert u["call_count"] >= 5 and u["by_result"].get("rate_limited", 0) >= 2
    r = api(seeded["people"]["admin"]).get(f"/v1/admin/partner-clients/{ptr.pk}/usage")
    assert r.status_code == 200 and r.json()["call_count"] == u["call_count"]
    last = (timezone.localdate().replace(day=1) - timedelta(days=1))
    r = api(seeded["people"]["admin"]).post(f"/v1/admin/partner-clients/{ptr.pk}/usage-statements",
                                            {"month": f"{last:%Y-%m}"}, format="json")
    assert r.status_code == 201
    r = api(seeded["people"]["admin"]).post(f"/v1/admin/partner-clients/{ptr.pk}/usage-statements",
                                            {"month": f"{timezone.localdate():%Y-%m}"}, format="json")
    assert r.status_code == 409


def test_usage_log_append_only(seeded, ptr):
    from django.db import transaction
    from django.db.utils import DatabaseError

    from partners import services
    from partners.models import UsageEvent

    ev = services.meter(ptr, "/x", "GET", "ok", 200)
    with pytest.raises(DatabaseError), transaction.atomic():
        UsageEvent.objects.filter(pk=ev.pk).update(billed=True, billable=False)


def test_partner_order_journey(seeded, api, ptr):
    """FR-PTR-003, US-PTR-003 AC1, TC-PTR-003-01: a partner orders for a consenting client; the client confirms
    in the portal and a draft verification order is created, marked billed to the partner. An unknown or
    non-consenting client gets the same refusal."""
    people = seeded["people"]
    c = _token(api)
    r = c.post("/v1/partner/orders", {"client_email": people["client2"].email, "locality": "Tema"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "consent-required"
    r = c.post("/v1/partner/orders", {"client_email": "nobody@example.com", "locality": "Tema"}, format="json")
    assert r.status_code == 403 and r.json()["code"] == "consent-required"
    _consent(people["client"], ptr)
    r = c.post("/v1/partner/orders", {"client_email": people["client"].email, "locality": "Tema",
                                      "plot_number": "T/1", "site_plan_ref": "SP-T-1", "seller_name": "Ato",
                                      "seller_phone": "+233240000001", "partner_reference": "LN-1"}, format="json")
    assert r.status_code == 201, r.content
    oid = r.json()["id"]
    home = api(people["client"]).get("/v1/home").json()
    items = home.get("items", home) if isinstance(home, dict) else home
    assert any(i.get("kind") == "partner_order" for i in items)
    assert api(people["client2"]).post(f"/v1/partner-orders/{oid}/confirm").status_code == 404
    r = api(people["client"]).post(f"/v1/partner-orders/{oid}/confirm")
    assert r.status_code == 200 and r.json()["status"] == "confirmed" and r.json()["order_id"]
    from orders.models import Order

    order = Order.objects.get(pk=r.json()["order_id"])
    assert order.details["bill_to_partner"] is True and order.client_id == people["client"].pk
    assert c.get(f"/v1/partner/orders/{oid}").json()["status"] == "confirmed"


def test_webhooks_signed_and_retried(seeded, api, ptr):
    """02 7.3: deliveries are signed with HMAC-SHA256 over timestamp.body, retried with back-off and marked
    failing after 24 hours; a withdrawn consent sends consent.withdrawn."""
    from dataprotection import services as dpr
    from partners import adapters, services
    from partners.models import WebhookDelivery

    c = _token(api)
    r = c.post("/v1/partner/webhooks", {"url": "https://bank.example/fail-hook", "events": ["consent.withdrawn"]},
               format="json")
    assert r.status_code == 201 and r.json()["secret"].startswith("whsec_")
    secret = r.json()["secret"]
    assert c.post("/v1/partner/webhooks", {"url": "http://insecure.example/h", "events": ["consent.withdrawn"]},
                  format="json").status_code == 422
    adapters.RecordingWebhookTransport.SENT.clear()
    consent = _consent(seeded["people"]["client2"], ptr)
    dpr.withdraw_consent(consent, seeded["people"]["client2"])
    services.deliver_due()
    sent = adapters.RecordingWebhookTransport.SENT
    assert sent, "a webhook should have been attempted"
    msg = sent[-1]
    assert json.loads(msg["body"])["type"] == "consent.withdrawn"
    assert set(json.loads(msg["body"])["data"]) >= {"consent_id"}
    good = [m for m in sent if "fail" not in m["url"]]
    for m in good:
        hook = ptr.webhooks.get(url=m["url"])
        assert adapters.verify(hook.secret, m["headers"]["Tenmina-Signature"], m["body"], now=int(time.time()))
    d = WebhookDelivery.objects.filter(subscription__url="https://bank.example/fail-hook").latest("created_at")
    assert d.status == "pending" and d.attempts == 1 and d.next_attempt_at > timezone.now()
    WebhookDelivery.objects.filter(pk=d.pk).update(created_at=timezone.now() - timedelta(hours=25),
                                                   next_attempt_at=timezone.now())
    services.deliver_due()
    d.refresh_from_db()
    assert d.status == "failed" and d.subscription.status == "failing"
    assert adapters.verify(secret, adapters.sign(secret, 100, "{}"), "{}", now=100)
    r = c.delete(f"/v1/partner/webhooks/{d.subscription_id}")
    assert r.status_code == 204


def test_flag_off(seeded, api, ptr, settings):
    """06 2.6 partner_api.enabled: off means no partner call works."""
    settings.TENMINA_FLAG_OVERRIDES = {"partner_api.enabled": False}
    r = api().post("/v1/partner/oauth/token", {"grant_type": "client_credentials", "client_id": DEV_CLIENT_ID,
                                               "client_secret": DEV_CLIENT_SECRET}, format="json")
    assert r.status_code == 404 and r.json()["code"] == "feature-off"


def test_admin_manages_clients(seeded, api):
    from administration.models import Partner

    admin = api(seeded["people"]["admin"])
    bank = Partner.objects.filter(kind="escrow_bank").first()
    r = admin.post("/v1/admin/partner-clients", {"country": "GH", "partner_id": str(bank.pk), "name": "Test desk",
                                                 "scopes": ["plot_status.read"]}, format="json")
    assert r.status_code == 201 and r.json()["client_secret"]
    cid = r.json()["id"]
    r = admin.post(f"/v1/admin/partner-clients/{cid}/rotate-secret")
    assert r.status_code == 200 and r.json()["client_secret"]
    assert api(seeded["people"]["cm"]).get("/v1/admin/partner-clients").json()["items"] == []
    r = api(seeded["people"]["client"]).get("/v1/partner-directory")
    assert r.status_code == 200 and any(x["id"] == cid for x in r.json())
