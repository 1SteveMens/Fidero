from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from administration.models import FeatureFlag
from audit.models import AuditEvent
from core.events import publish  # noqa: F401
from core.ids import uuid7
from core.models import OutboxEvent
from orders import services
from orders.models import Order, ReferralCode, ReferralReward, TermsAcceptance

from .helpers import order_body, place_order, site_plan, terms


# ---------------------------------------------------------------- catalogue (US-ORD-002)


def test_tiers_and_prices_come_from_country_config(seeded, api):
    """FR-ORD-002: tiers configured by an administrator, card price in USD, mobile money in GHS, guides only."""
    r = api().get("/v1/catalogue/tiers?country=GH&residence=GB")
    assert r.status_code == 200
    tiers = {t["tier"]: t for t in r.json()}
    assert set(tiers) == {"basic", "standard", "premium"}
    std = tiers["standard"]
    assert std["price"] == {"amount": "350.00", "currency": "USD"}
    assert std["local_price"] == {"amount": "5425.00", "currency": "GHS"}
    assert std["guide_for_you"]["currency"] == "GBP"
    assert std["source"] == "country_config:report_tiers"


def test_building_tiers_add_the_structural_check(seeded, api):
    """J-08: a house check costs more than a land check (working assumption)."""
    r = api().get("/v1/catalogue/tiers?country=GH&asset_type=building")
    assert {t["tier"]: t["price"]["amount"] for t in r.json()}["standard"] == "500.00"


def test_products_show_which_lines_are_open(seeded, api, gh):
    r = api().get("/v1/catalogue/products?country=GH")
    products = {p["kind"]: p for p in r.json()}
    assert products["family_plan"]["available"] is True
    assert products["extra_inspection"]["price"] == {"amount": "120.00", "currency": "USD"}
    FeatureFlag.objects.filter(name="lines.fee", country__isnull=True).update(enabled=False)
    products = {p["kind"]: p for p in api().get("/v1/catalogue/products?country=GH").json()}
    assert products["family_plan"]["available"] is False


def test_terms_endpoint_gives_versions(seeded, api):
    r = api().get("/v1/catalogue/terms?country=GH")
    assert r.json()["terms_version"] and r.json()["scope"]["text"]


# ---------------------------------------------------------------- ordering (US-ORD-001, 003, 005)


def test_order_journey_saves_details_documents_and_terms(seeded, api, people, gh):
    """US-ORD-001, US-ORD-003, US-ORD-005: order with plot, seller, site plan, lead source and accepted terms."""
    c = api(people["client"])
    o = place_order(c, people["client"], gh)
    assert o["status"] == "awaiting_payment"
    assert o["reference"].startswith("TMR-GH-")
    assert o["price"] == {"amount": "350.00", "currency": "USD"}
    assert o["asset"]["locality"] == "Kasoa" and o["asset"]["ghana_post_gps"] == ""
    assert o["seller"]["name"] == "Kojo Owusu"
    assert o["lead_source"] == "webinar"
    assert o["product_line"] == "land"
    assert o["terms"]["current"] is True and o["terms"]["accepted_at"]
    acc = TermsAcceptance.objects.get(order_id=o["id"])
    assert acc.terms_version == terms(gh)["terms_version"] and acc.person == people["client"]
    docs = c.get(f"/v1/orders/{o['id']}/documents").json()
    assert len(docs) == 1
    assert OutboxEvent.objects.filter(topic="order.created", aggregate_id=o["id"]).count() == 1
    assert o["next"]["pay"] == f"/v1/orders/{o['id']}/payments"


def test_missing_fields_are_named_and_nothing_is_saved(seeded, api, people, gh):
    """US-ORD-001 AC2: a missing required field is named and the order is not saved."""
    body = order_body(gh, asset={"type": "plot", "plot_number": "12"}, seller={})
    body.pop("lead_source")
    before = Order.objects.count()
    r = api(people["client"]).post("/v1/orders", body, format="json")
    assert r.status_code == 422
    pointers = {e["pointer"] for e in r.json()["errors"]}
    assert {"/asset/locality", "/asset/site_plan_ref", "/seller/name", "/seller/phone", "/lead_source",
            "/upload_ids"} <= pointers
    assert Order.objects.count() == before


def test_draft_is_kept_and_completed_later(seeded, api, people, gh):
    """US-ORD-001 AC3: details are kept as a draft when the client leaves mid-form."""
    c = api(people["client"])
    r = c.post("/v1/orders", {"country": "GH", "kind": "verification", "draft": True,
                              "asset": {"locality": "Kasoa"}}, format="json")
    assert r.status_code == 201
    o = r.json()
    assert o["status"] == "draft" and o["missing"]
    r = c.patch(f"/v1/orders/{o['id']}", {"asset": {"plot_number": "7", "site_plan_ref": "SP-7"}, "tier": "basic",
                                          "seller": {"name": "Ama Seller", "email": "s@example.com"},
                                          "lead_source": "association"}, format="json")
    assert r.status_code == 200 and r.json()["asset"]["locality"] == "Kasoa"
    assert r.json()["price"] == {"amount": "150.00", "currency": "USD"}
    from django.core.files.uploadedfile import SimpleUploadedFile

    up = SimpleUploadedFile("plan.pdf", b"%PDF-1.4 site plan", content_type="application/pdf")
    r = c.post(f"/v1/orders/{o['id']}/documents", {"file": up, "role": "site_plan"}, format="multipart")
    assert r.status_code == 201, r.content
    r = c.post(f"/v1/orders/{o['id']}/submit", terms(gh), format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "awaiting_payment"


def test_empty_or_unsupported_documents_are_refused(seeded, api, people, gh):
    """TC-ORD-001-02: a 0-byte file or an unsupported type is refused."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    c = api(people["client"])
    o = c.post("/v1/orders", {"country": "GH", "kind": "verification", "draft": True}, format="json").json()
    empty = SimpleUploadedFile("plan.pdf", b"", content_type="application/pdf")
    r = c.post(f"/v1/orders/{o['id']}/documents", {"file": empty}, format="multipart")
    assert r.status_code in (400, 422)
    txt = SimpleUploadedFile("plan.exe", b"MZ...", content_type="application/x-msdownload")
    r = c.post(f"/v1/orders/{o['id']}/documents", {"file": txt}, format="multipart")
    assert r.status_code == 422 and r.json()["code"] == "evidence-rejected"


def test_building_order_uses_the_building_line(seeded, api, people, gh):
    """US-ORD-001 AC4, TC-ORD-001-03: a building order uses the building case template line."""
    o = place_order(api(people["client"]), people["client"], gh,
                    asset={"type": "building", "locality": "East Legon", "site_plan_ref": "SP-9"},
                    details={"building_permit_number": "AMA/BP/2019/221"})
    assert o["product_line"] == "building"
    assert o["price"]["amount"] == "500.00"
    paid_payload = services.order_payload(Order.objects.get(pk=o["id"]))
    assert paid_payload["product_line"] == "building"


def test_price_in_request_is_ignored_and_audited(seeded, api, people, gh):
    """TC-ORD-002-02: the server recalculates; a tampered price is ignored and audited."""
    o = place_order(api(people["client"]), people["client"], gh, price={"amount": "1.00", "currency": "USD"})
    assert o["price"]["amount"] == "350.00"
    assert AuditEvent.objects.filter(action="order.client_price_ignored").exists()


def test_terms_must_be_accepted_in_their_current_version(seeded, api, people, gh):
    """FR-ORD-003, RUL-04: no submission without acceptance; an old version is refused."""
    c = api(people["client"])
    ev = site_plan(people["client"], gh)
    body = order_body(gh, upload_ids=[str(ev.pk)])
    body.pop("accept_terms")
    r = c.post("/v1/orders", body, format="json")
    assert r.status_code == 422 and r.json()["code"] == "terms-not-accepted"
    body = order_body(gh, upload_ids=[str(ev.pk)], terms_version="client-terms-2020-v0")
    r = c.post("/v1/orders", body, format="json")
    assert r.status_code == 409 and r.json()["code"] == "terms-outdated"


def test_terms_acceptance_cannot_be_edited(seeded, api, people, gh):
    """FR-ORD-003: the acceptance record is append-only in the database."""
    o = place_order(api(people["client"]), people["client"], gh)
    with pytest.raises(Exception), transaction.atomic():
        TermsAcceptance.objects.filter(order_id=o["id"]).update(terms_version="forged")


def test_submitted_price_is_locked_in_the_database(seeded, api, people, gh):
    """FR-ORD-002 AC3: the amount charged equals the amount shown; the DB refuses a change."""
    o = place_order(api(people["client"]), people["client"], gh)
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.filter(pk=o["id"]).update(price_amount=Decimal("1.00"))


def test_lead_source_summary_for_staff(seeded, api, people, gh):
    """US-ORD-005: the founder sees which channels bring orders and paying clients."""
    def webinar():
        rows = api(people["cm"]).get("/v1/orders/lead-sources?country=GH").json()
        return next((r for r in rows if r["lead_source"] == "webinar"), {"orders": 0, "paid": 0})

    start = webinar()
    o = place_order(api(people["client"]), people["client"], gh)
    services.mark_paid(o["id"], payment_id=uuid7(), method="card")
    end = webinar()
    assert (end["orders"] - start["orders"], end["paid"] - start["paid"]) == (1, 1)
    assert api(people["client"]).get("/v1/orders/lead-sources").status_code == 403


def test_reopen_change_tier_and_resubmit(seeded, api, people, gh):
    c = api(people["client"])
    o = place_order(c, people["client"], gh)
    assert c.post(f"/v1/orders/{o['id']}/edit").json()["status"] == "draft"
    c.patch(f"/v1/orders/{o['id']}", {"tier": "premium"}, format="json")
    r = c.post(f"/v1/orders/{o['id']}/submit", {}, format="json")
    assert r.json()["price"]["amount"] == "650.00"
    assert OutboxEvent.objects.filter(topic="order.created", aggregate_id=o["id"]).count() == 1


def test_cancel_unpaid_but_not_paid_orders(seeded, api, people, gh):
    c = api(people["client"])
    o = place_order(c, people["client"], gh)
    assert c.post(f"/v1/orders/{o['id']}/cancel", {"reason": ""}, format="json").status_code == 400
    r = c.post(f"/v1/orders/{o['id']}/cancel", {"reason": "Seller sold to someone else"}, format="json")
    assert r.json()["status"] == "cancelled"
    o2 = place_order(c, people["client"], gh)
    services.mark_paid(o2["id"], payment_id=uuid7())
    r = c.post(f"/v1/orders/{o2['id']}/cancel", {"reason": "changed my mind"}, format="json")
    assert r.status_code == 409


def test_clients_see_only_their_own_orders(seeded, api, people, gh):
    """FR-ACC-007: object-level scoping."""
    o = place_order(api(people["client"]), people["client"], gh)
    other = api(people["client2"])
    assert other.get(f"/v1/orders/{o['id']}").status_code == 404
    assert o["id"] not in {x["id"] for x in other.get("/v1/orders").json()["items"]}
    assert api(people["cm"]).get(f"/v1/orders/{o['id']}").status_code == 200
    assert other.post(f"/v1/orders/{o['id']}/cancel", {"reason": "x"}, format="json").status_code == 404


def test_mark_paid_is_idempotent_and_publishes_order_paid_once(seeded, api, people, gh):
    """FR-ORD-004: only PAY's confirmation marks the order paid; duplicates change nothing."""
    o = place_order(api(people["client"]), people["client"], gh)
    pid = uuid7()
    services.mark_paid(o["id"], payment_id=pid, method="card")
    services.mark_paid(o["id"], payment_id=pid, method="card")
    services.mark_paid(o["id"], payment_id=uuid7(), method="card")
    assert OutboxEvent.objects.filter(topic="order.paid", aggregate_id=o["id"]).count() == 1
    ev = OutboxEvent.objects.get(topic="order.paid", aggregate_id=o["id"])
    assert ev.payload["asset"]["locality"] == "Kasoa" and ev.payload["product_line"] == "land"
    order = Order.objects.get(pk=o["id"])
    assert order.status == "paid" and order.paid_payment_id == pid


def test_cancelled_order_is_never_marked_paid(seeded, api, people, gh):
    c = api(people["client"])
    o = place_order(c, people["client"], gh)
    c.post(f"/v1/orders/{o['id']}/cancel", {"reason": "No longer buying"}, format="json")
    services.mark_paid(o["id"], payment_id=uuid7())
    assert Order.objects.get(pk=o["id"]).status == "cancelled"


def test_case_created_event_links_the_case(seeded, api, people, gh):
    o = place_order(api(people["client"]), people["client"], gh)
    case_id = uuid7()
    publish("case.created", case_id, {"case_id": case_id, "order_id": o["id"]})
    assert str(Order.objects.get(pk=o["id"]).case_id) == str(case_id)


# ---------------------------------------------------------------- referrals (US-ORD-006)


def test_referral_code_discount_and_reward(seeded, api, people, gh):
    """US-ORD-006 AC1: a valid code is linked to the referrer and the reward owed is recorded on payment."""
    code = api(people["client2"]).get("/v1/me/referral-code?country=GH").json()
    assert code["code"].startswith("TM-")
    c = api(people["client"])
    o = place_order(c, people["client"], gh, referral_code=code["code"])
    assert o["referral_code"] == code["code"]
    assert o["price"]["amount"] == "315.00" and o["discount"]["amount"] == "35.00"
    assert not ReferralReward.objects.filter(order_id=o["id"]).exists()
    services.mark_paid(o["id"], payment_id=uuid7())
    reward = ReferralReward.objects.get(order_id=o["id"])
    assert reward.referrer == people["client2"] and reward.status == "owed"
    mine = api(people["client2"]).get("/v1/referral-rewards").json()["items"]
    assert [x["status"] for x in mine if x["order"] == o["id"]] == ["owed"]
    # Only an administrator records the payment of a reward.
    assert api(people["cm"]).post(f"/v1/referral-rewards/{reward.pk}/paid", {"reference": "OPS-1"},
                                  format="json").status_code == 403
    r = api(people["admin"]).post(f"/v1/referral-rewards/{reward.pk}/paid", {"reference": "OPS-1"}, format="json")
    assert r.json()["status"] == "paid"


def test_invalid_expired_own_and_reused_codes_are_refused(seeded, api, people, gh):
    """US-ORD-006 AC2, TC-ORD-006-02: the client is told and the price is unchanged."""
    from django.utils import timezone

    c = api(people["client"])
    ev = site_plan(people["client"], gh)
    r = c.post("/v1/orders", order_body(gh, upload_ids=[str(ev.pk)], referral_code="NOPE-123"), format="json")
    assert r.status_code == 422 and r.json()["code"] == "referral-invalid"
    expired = services.create_referral_code(people["cm"], country="GH", owner_label="Diaspora Association UK",
                                            code="ASSOC-OLD", valid_until=timezone.now() - timezone.timedelta(days=1))
    assert expired.code == "ASSOC-OLD"
    draft = c.post("/v1/orders", {"country": "GH", "kind": "verification", "draft": True, "tier": "standard"},
                   format="json").json()
    r = c.post(f"/v1/orders/{draft['id']}/referral", {"code": "ASSOC-OLD"}, format="json")
    assert r.status_code == 422
    assert c.get(f"/v1/orders/{draft['id']}").json()["price"]["amount"] == "350.00"
    own = c.get("/v1/me/referral-code?country=GH").json()["code"]
    assert c.post(f"/v1/orders/{draft['id']}/referral", {"code": own}, format="json").status_code == 422
    friend = services.my_referral_code(people["client2"], gh).code
    o = place_order(c, people["client"], gh, referral_code=friend)
    services.mark_paid(o["id"], payment_id=uuid7())
    r = c.post(f"/v1/orders/{draft['id']}/referral", {"code": friend}, format="json")
    assert r.status_code == 422


def test_staff_create_association_codes(seeded, api, people):
    r = api(people["cm"]).post("/v1/referral-codes", {"country": "GH", "owner_label": "Ghana Union Leeds",
                                                      "code": "LEEDS26"}, format="json")
    assert r.status_code == 201 and r.json()["code"] == "LEEDS26"
    assert api(people["client"]).post("/v1/referral-codes", {"country": "GH", "owner_label": "x"},
                                      format="json").status_code == 403
    assert ReferralCode.objects.filter(code="LEEDS26").exists()


# ---------------------------------------------------------------- other lines and extra inspections


def test_extra_inspection_at_the_configured_price(seeded, api, people, gh):
    """US-ORD-007, FR-ORD-007: an extra inspection on a build is ordered at the configured price."""
    from construction.models import Project

    # A real active build of Ama's (BLD refuses a made-up project id, and another client's project).
    project_id = Project.objects.filter(client=people["client"], status="active", type="construction").first().pk
    assert api(people["client"]).post(f"/v1/projects/{uuid7()}/extra-inspections",
                                      {"concern": "x", "country": "GH", **terms(gh)},
                                      format="json").status_code == 404
    r = api(people["client"]).post(f"/v1/projects/{project_id}/extra-inspections",
                                   {"concern": "Cracks in the ring beam", "country": "GH", **terms(gh)},
                                   format="json")
    assert r.status_code == 201, r.content
    o = r.json()
    assert o["kind"] == "extra_inspection" and o["status"] == "awaiting_payment"
    assert o["price"] == {"amount": "120.00", "currency": "USD"}
    assert o["subject_type"] == "project" and o["subject_id"] == str(project_id)
    FeatureFlag.objects.filter(name="building.construction", country__isnull=True).update(enabled=False)
    r = api(people["client"]).post(f"/v1/projects/{project_id}/extra-inspections",
                                   {"concern": "x", "country": "GH", **terms(gh)}, format="json")
    assert r.status_code == 404 and r.json()["code"] == "feature-off"


def test_family_plan_and_line_orders(seeded, people, gh):
    """Two front doors: the family payments fee and monthly plan are fee orders the FEE line creates."""
    from core.errors import FeatureOff, Invalid

    t = terms(gh)
    with pytest.raises(Invalid):
        services.create_line_order(client=people["client"], kind="family_plan", country=gh,
                                   accepted_terms=(t["terms_version"], t["scope_version"]))
    o = services.create_line_order(client=people["client"], kind="family_plan", country=gh,
                                   details={"period_month": "2026-12"},
                                   accepted_terms=(t["terms_version"], t["scope_version"]))
    assert o.status == "awaiting_payment" and o.price_amount == Decimal("15.00")
    fee = services.create_line_order(client=people["client"], kind="family_payment_fee", country=gh,
                                     subject_type="fee_invoice", subject_id=uuid7())
    assert fee.status == "draft" and fee.price_amount == Decimal("5.00")
    FeatureFlag.objects.filter(name="lines.fee", country__isnull=True).update(enabled=False)
    with pytest.raises(FeatureOff):
        services.create_line_order(client=people["client"], kind="family_plan", country=gh,
                                   details={"period_month": "2026-12"})


def test_extra_plot_same_seller_tier_needs_an_earlier_order(seeded, api, people, gh, publish_config):
    """FR-ORD-002: the 'extra plot, same seller' tier applies only after a check with that seller."""
    publish_config(gh, order_catalogue={"verification.plot": {"tiers": {
        "diaspora_standard": {"name": "Diaspora standard", "price": "450.00"},
        "extra_plot_same_seller": {"name": "Extra plot, same seller", "price": "300.00",
                                   "requires_same_seller": True}}}})
    c = api(people["client"])
    ev = site_plan(people["client"], gh)
    r = c.post("/v1/orders", order_body(gh, tier="extra_plot_same_seller", upload_ids=[str(ev.pk)]), format="json")
    assert r.status_code == 422
    first = place_order(c, people["client"], gh, tier="diaspora_standard")
    assert first["price"]["amount"] == "450.00"
    services.mark_paid(first["id"], payment_id=uuid7())
    second = place_order(c, people["client"], gh, tier="extra_plot_same_seller")
    assert second["price"]["amount"] == "300.00"


def test_client_cannot_order_a_seller_paid_check(seeded, api, people, gh):
    ev = site_plan(people["client"], gh)
    r = api(people["client"]).post("/v1/orders", order_body(gh, kind="listing_verification",
                                                            upload_ids=[str(ev.pk)]), format="json")
    assert r.status_code == 403


def test_authority_orders_check_for_family_or_stool_listing(seeded, api, people, gh):
    """US-LST-009, FR-LST-009: an authority representative (AR) orders the seller-paid check for a family or
    stool plot, billed to the authority's own organisation; nobody else's organisation, and no client."""
    from accounts.models import Membership, Organisation

    ar = people["authority"]
    stool = Organisation.objects.create(name="Teshie Stool (demo)", kind="authority", country=gh)
    Membership.objects.create(organisation=stool, person=ar, org_role="admin")
    ev = site_plan(ar, gh, data=b"%PDF-1.4 stool plot TS-9")
    r = api(ar).post("/v1/orders", order_body(gh, kind="listing_verification", organisation_id=str(stool.pk),
                                              upload_ids=[str(ev.pk)]), format="json")
    assert r.status_code == 201, r.content
    assert r.json()["kind"] == "listing_verification"
    other = Organisation.objects.create(name="Other Stool (demo)", kind="authority", country=gh)
    ev2 = site_plan(ar, gh, data=b"%PDF-1.4 stool plot TS-10")
    r = api(ar).post("/v1/orders", order_body(gh, kind="listing_verification", organisation_id=str(other.pk),
                                              upload_ids=[str(ev2.pk)]), format="json")
    assert r.status_code == 403  # not a member
    seller = people["seller"]
    Membership.objects.create(organisation=other, person=seller, org_role="admin")
    ev3 = site_plan(seller, gh, data=b"%PDF-1.4 stool plot TS-11")
    r = api(seller).post("/v1/orders", order_body(gh, kind="listing_verification", organisation_id=str(other.pk),
                                                  upload_ids=[str(ev3.pk)]), format="json")
    assert r.status_code == 422  # a seller does not bill an authority
