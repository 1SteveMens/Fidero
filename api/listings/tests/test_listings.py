"""LST: publish rule, badge, search and map, reservations, expiry and suspension, removal, sold, enquiries,
family listings and established sellers (FR-LST-001 to FR-LST-010, RUL-12, RUL-13, RUL-14, J-04)."""
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone
from freezegun import freeze_time

from core.errors import DomainError, FeatureOff, Forbidden, RuleBlocked, StateConflict
from core.events import publish
from core.models import OutboxEvent
from listings import services
from orders import legal
from listings.models import Listing, Removal, Reservation, SellerScreening


def L(seeded, key):
    return Listing.objects.get(pk=seeded["listings"][key].pk)


def test_seeded_journeys_in_every_state(seeded):
    """J-04: the seed builds listings in each state through the services."""
    states = {k: L(seeded, k).status for k in ("live", "reserved", "suspended", "sold", "rejected",
                                               "in_verification", "draft")}
    assert states == {"live": "live", "reserved": "reserved", "suspended": "suspended", "sold": "sold",
                      "rejected": "rejected", "in_verification": "in_verification", "draft": "draft"}


# --------------------------------------------------------------------------- RUL-12 publish rule

def test_publish_rule_refuses_amber_old_and_other_plot(seeded, people):
    """RUL-12, TC-RUL-12-02, -03, -04, TC-LST-002-02: amber, too old, or another plot's report is refused."""
    live, rejected = L(seeded, "live"), L(seeded, "rejected")
    assert rejected.status == "rejected" and "amber" in rejected.status_reason  # TC-E2E-J04-02
    assert not services.publish_blockers(live, live.report)  # green, in date: TC-RUL-12-01
    limit = services.max_report_age_days(live.country)
    with freeze_time(live.report.released_at + timedelta(days=limit, hours=1)):
        assert not services.publish_blockers(live, live.report)  # on the day
    with freeze_time(live.report.released_at + timedelta(days=limit + 1, hours=1)):
        reasons = services.publish_blockers(live, live.report)
        assert any("too old" in r["message"] for r in reasons)
    other = L(seeded, "in_verification")
    with pytest.raises(RuleBlocked) as e:
        services.attach_report(other, people["developer"], live.report_id)
    assert e.value.code == "publish-rule" and "different plot" in e.value.blocking_reasons[0]["message"]


def test_database_refuses_live_without_green_report(seeded):
    """RUL-12 enforced again by trigger lst_publish_rule: an amber report never goes live."""
    x, amber = L(seeded, "in_verification"), L(seeded, "rejected").report
    with pytest.raises(IntegrityError), transaction.atomic():
        Listing.objects.filter(pk=x.pk).update(status="live", report=amber,
                                               badge_expires_at=timezone.now() + timedelta(days=30))
    with pytest.raises(IntegrityError), transaction.atomic():
        Listing.objects.filter(pk=x.pk).update(status="live", report=L(seeded, "live").report,
                                               badge_expires_at=timezone.now() + timedelta(days=30))


def test_draft_cannot_jump_to_live(seeded):
    """TC-STM-LST-14, -15, -18: no publish without fee and verification; no relisting a sold or rejected one."""
    for key in ("draft", "rejected", "sold"):
        with pytest.raises(StateConflict):
            services._move(L(seeded, key), "live")


# --------------------------------------------------------------------------- RUL-14 badge and report

def test_badge_date_and_report_for_any_signed_in_buyer(seeded, api, people):
    """US-LST-003, TC-LST-003-01, TC-RUL-14-01: the badge, the check date and the released report."""
    live = L(seeded, "live")
    r = api().get(f"/v1/listings/{live.pk}")
    assert r.status_code == 200, r.content
    badge = r.json()["badge"]
    assert badge["label"] == "Tenmina Verified" and badge["checks_date"] == live.checks_date.isoformat()
    assert badge["report_link"] == f"/v1/listings/{live.pk}/report"
    assert r.json()["disclosure"] and r.json()["seller"]["established"] is True
    assert api().get(f"/v1/listings/{live.pk}/report").status_code in (401, 403)
    rep = api(people["client2"]).get(f"/v1/listings/{live.pk}/report")
    assert rep.status_code == 200, rep.content
    body = rep.json()
    assert body["reference"] == live.report.reference and body["verdict"] == "green"
    assert body["pdf"]["url"].startswith("/v1/evidence-files/")  # the released PDF behind the badge (AC2)
    assert api(people["client2"]).get(body["pdf"]["url"]).status_code == 200


def test_no_badge_when_not_live(seeded, api, people):
    """TC-LST-003-02, TC-RUL-13-02: a suspended listing shows no badge and is not public."""
    sus = L(seeded, "suspended")
    assert api().get(f"/v1/listings/{sus.pk}").status_code == 404
    r = api(people["seller"]).get(f"/v1/listings/{sus.pk}")
    assert r.status_code == 200 and r.json()["badge"] is None
    assert r.json()["owner_view"]["suspensions"][0]["kind"] == "misconduct"


def test_seller_cannot_extend_badge_or_swap_report(seeded, api, people):
    """TC-LST-006-02, TC-RUL-14-02: the badge and the report link are system-set."""
    live = L(seeded, "live")
    c = api(people["seller"])
    later = (timezone.now() + timedelta(days=900)).isoformat()
    assert c.patch(f"/v1/listings/{live.pk}", {"badge_expires_at": later}, format="json").status_code == 403
    assert c.patch(f"/v1/listings/{live.pk}", {"report_id": str(L(seeded, "rejected").report_id)},
                   format="json").status_code == 403
    r = c.patch(f"/v1/listings/{live.pk}", {"description": "Now with a borehole."}, format="json")
    assert r.status_code == 200 and r.json()["description"] == "Now with a borehole."
    assert api(people["client2"]).patch(f"/v1/listings/{live.pk}", {"description": "x"},
                                        format="json").status_code == 404
    assert Listing.objects.get(pk=live.pk).badge_expires_at == live.badge_expires_at


# --------------------------------------------------------------------------- FR-LST-004 search, map, SEO

def test_search_filters_only_live(seeded, api):
    """US-LST-004a, TC-LST-004-01: filters; expired, suspended, reserved and sold never show."""
    live = L(seeded, "live")
    ids = [x["id"] for x in api().get("/v1/listings?country=GH").json()["items"]]
    assert str(live.pk) in ids
    for key in ("suspended", "reserved", "sold", "rejected", "draft", "in_verification"):
        assert str(L(seeded, key).pk) not in ids
    q = api().get(f"/v1/listings?locality=Afienya&min_price=100000&max_price=200000&kind=plot"
                  f"&verified_since={live.checks_date.isoformat()}").json()["items"]
    assert [x["id"] for x in q] == [str(live.pk)]
    assert api().get("/v1/listings?max_price=1000").json()["items"] == []
    assert api().get("/v1/listings?kind=offplan_unit").json()["items"] == []
    assert str(live.pk) in [x["id"] for x in api().get("/v1/listings?q=serviced plot").json()["items"]]


def test_map_points_and_list_without_location(seeded, api):
    """US-LST-004b: each listing at its location; one without coordinates stays in the list only."""
    from django.contrib.gis.geos import Point

    from geo.models import Asset

    live = L(seeded, "live")
    Asset.objects.filter(pk=live.asset_id).update(location=None)
    assert api().get("/v1/listings/map").json()["features"] == []
    Asset.objects.filter(pk=live.asset_id).update(location=Point(0.02, 5.79, srid=4326))
    fc = api().get("/v1/listings/map?country=GH").json()
    assert fc["type"] == "FeatureCollection"
    assert fc["features"][0]["geometry"]["coordinates"] == [0.02, 5.79]
    assert api().get("/v1/listings/map?bbox=-1,4,1,6").json()["features"]
    assert api().get("/v1/listings/map?bbox=1,9,2,10").json()["features"] == []


def test_listing_page_is_server_rendered_and_not_indexed_when_not_live(seeded, api):
    """US-LST-010, TC-LST-010-01, -02: title and description in HTML; non-live pages 404 with noindex."""
    live = L(seeded, "live")
    r = api().get(f"/v1/listings/{live.pk}/page")
    assert r.status_code == 200 and b"<title>" in r.content and b"Tenmina Verified" in r.content
    assert b"meta name=description" in r.content and b"application/ld+json" in r.content
    for key in ("draft", "suspended", "sold"):
        r = api().get(f"/v1/listings/{L(seeded, key).pk}/page")
        assert r.status_code == 404 and r["X-Robots-Tag"] == "noindex"
    photo = live.media.filter(kind="photo").first()
    assert api().get(f"/v1/listings/{live.pk}/photos/{photo.pk}").status_code == 200


# --------------------------------------------------------------------------- RUL-13 expiry and suspension

def test_badge_expiry_read_time_and_job(seeded, api):
    """US-LST-006 AC1, TC-RUL-13-01, TC-RUL-13-03: hidden at read time even before the job runs."""
    live = L(seeded, "live")
    with freeze_time(live.badge_expires_at + timedelta(minutes=1)):
        r = api().get("/v1/listings")
        assert str(live.pk) not in [x["id"] for x in r.json()["items"]]
        assert api().get(f"/v1/listings/{live.pk}").json()["badge"] is None
        assert services.expire_badges() >= 1
        assert Listing.objects.get(pk=live.pk).status == "expired"
        assert OutboxEvent.objects.filter(topic="listing.expired", aggregate_id=live.pk).exists()


def test_monitoring_alert_suspends_and_resolution_restores(seeded):
    """US-LST-006 AC2, TC-RUL-13-02, TC-STM-LST-04, -06."""
    import uuid

    live = L(seeded, "live")
    alert = uuid.uuid4()
    publish("monitoring.alert_raised", alert, {"alert_id": str(alert), "asset_id": str(live.asset_id)})
    assert Listing.objects.get(pk=live.pk).status == "suspended"
    publish("monitoring.alert_resolved", alert, {"alert_id": str(alert), "asset_id": str(live.asset_id),
                                                 "resolution": "change_confirmed"})
    assert Listing.objects.get(pk=live.pk).status == "suspended"  # confirmed change: a reviewer decides
    publish("monitoring.alert_resolved", uuid.uuid4(), {"alert_id": str(alert), "resolution": "no_change"})
    assert Listing.objects.get(pk=live.pk).status == "live"


def test_only_a_reviewer_lifts_a_suspension(seeded, api, people):
    """TC-STM-LST-16: the seller cannot lift it; a case manager cannot; a reviewer can, with a note."""
    sus = L(seeded, "suspended")
    assert api(people["seller"]).post(f"/v1/listings/{sus.pk}/reinstatements", {"note": "fixed"},
                                      format="json").status_code == 403
    assert api(people["cm"]).post(f"/v1/listings/{sus.pk}/reinstatements", {"note": "fixed"},
                                  format="json").status_code == 403
    r = api(people["reviewer"]).post(f"/v1/listings/{sus.pk}/reinstatements",
                                     {"note": "The seller withdrew the outside advert."}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "live" and r.json()["badge"]


def test_dispute_suspends_and_its_end_restores(seeded):
    """RUL-15, TC-STM-LST-04: a dispute on a reserved listing suspends it and keeps the reservation."""
    import uuid

    x = L(seeded, "reserved")
    d = uuid.uuid4()
    publish("dispute.opened", d, {"dispute_id": str(d), "listing_id": str(x.pk)})
    x.refresh_from_db()
    assert x.status == "suspended" and x.reservations.filter(status="active").exists()
    publish("dispute.withdrawn", d, {"dispute_id": str(d), "listing_id": str(x.pk)})
    assert Listing.objects.get(pk=x.pk).status == "reserved"


# --------------------------------------------------------------------------- FR-LST-005 reservations

def test_reserve_starts_fresh_search_and_escrow(seeded, api, people):
    """US-LST-005 AC1, TC-LST-005-01, -02, TC-STM-LST-10, -12, -13, -19."""
    from cases.models import Case
    from escrow.models import Escrow

    live = L(seeded, "live")
    r = api(people["client"]).post(f"/v1/listings/{live.pk}/reservations", {}, format="json")
    assert r.status_code == 201, r.content
    res = Reservation.objects.get(pk=r.json()["id"])
    assert Listing.objects.get(pk=live.pk).status == "reserved"
    fs = Case.objects.get(product_line="fresh_search", origin="reservation", origin_ref=res.pk)
    assert res.fresh_search_case_id == fs.pk
    e = Escrow.objects.get(pk=res.escrow_id)
    assert e.status == "proposed" and e.kind == "purchase" and e.report_id == live.report_id
    assert e.parties.filter(role="seller", organisation=live.organisation).exists()
    ev = OutboxEvent.objects.get(topic="reservation.created", aggregate_id=res.pk)
    assert ev.payload["asset_id"] == str(live.asset_id) and ev.payload["escrow_id"] == str(e.pk)
    second = api(people["client2"]).post(f"/v1/listings/{live.pk}/reservations", {}, format="json")
    assert second.status_code in (404, 409)
    with pytest.raises(StateConflict) as exc:
        services.reserve(Listing.objects.get(pk=live.pk), people["client2"])
    assert exc.value.code == "listing-reserved"
    w = api(people["client"]).post(f"/v1/reservations/{res.pk}/withdrawals", {"reason": "changed plans"},
                                   format="json")
    assert w.status_code == 409 and w.json()["code"] == "fresh-search-pending"
    services.on_fresh_search_completed({"origin": "reservation", "origin_ref": str(res.pk), "case_id": str(fs.pk),
                                        "registry_result_date": timezone.localdate().isoformat()})
    w = api(people["client"]).post(f"/v1/reservations/{res.pk}/withdrawals", {"reason": "changed plans"},
                                   format="json")
    assert w.status_code == 200, w.content
    assert Listing.objects.get(pk=live.pk).status == "live"
    assert Escrow.objects.get(pk=e.pk).status == "cancelled"
    assert api(people["seller"]).get(f"/v1/reservations/{res.pk}").json()["buyer_name"] is None


def test_reserve_refused_when_not_live(seeded, people):
    """TC-STM-LST-17, TC-E2E-J04-03: suspended or expired listings cannot be reserved; nor your own."""
    with pytest.raises(StateConflict):
        services.reserve(L(seeded, "suspended"), people["client"])
    live = L(seeded, "live")
    with pytest.raises(Forbidden):
        services.reserve(live, people["seller"])
    with freeze_time(live.badge_expires_at + timedelta(hours=1)):
        with pytest.raises(StateConflict) as e:
            services.reserve(live, people["client"])
        assert e.value.code == "listing-not-live"


def test_lapse_frees_only_after_passed_fresh_search(seeded):
    """US-LST-005 AC2, TC-STM-LST-12, -13: a lapsed reservation frees the listing once the search passed."""
    x = L(seeded, "reserved")
    res = x.reservations.get(status="active")
    with freeze_time(res.expires_at + timedelta(hours=1)):
        assert services.lapse_reservations() == 0  # still waiting for the fresh search
        services.on_fresh_search_completed({"origin": "reservation", "origin_ref": str(res.pk),
                                            "registry_result_date": timezone.localdate().isoformat()})
        assert services.lapse_reservations() == 1
    assert Reservation.objects.get(pk=res.pk).status == "lapsed"
    assert Listing.objects.get(pk=x.pk).status == "live"


def test_failed_fresh_search_ends_reservation(seeded, api, people):
    """TC-E2E-J04-04, TC-STM-LST-05: reservation ends, listing suspended, unfunded escrow cancelled."""
    from escrow.models import Escrow

    x = L(seeded, "reserved")
    res = x.reservations.get(status="active")
    body = {"outcome": "failed", "note": "A caveat was lodged at the registry yesterday."}
    assert api(people["client"]).post(f"/v1/reservations/{res.pk}/fresh-search-results", body,
                                      format="json").status_code == 403
    r = api(people["cm"]).post(f"/v1/reservations/{res.pk}/fresh-search-results", body, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "ended" and r.json()["fresh_search_status"] == "failed"
    assert Listing.objects.get(pk=x.pk).status == "suspended"
    assert Escrow.objects.get(pk=res.escrow_id).status == "cancelled"


def test_sold_on_release_publishes_for_payments_and_geo(seeded):
    """US-LST-007, TC-LST-007-01, TC-E2E-J04-01: sold when the bank confirms; listing.sold carries the ids PAY
    and GEO need; the success fee waits for Q-31 (off by default)."""
    from audit.models import AuditEvent
    from geo.models import MonitoringEnrolment

    sold = L(seeded, "sold")
    assert sold.sold_at and sold.reservations.get().status == "completed"
    ev = OutboxEvent.objects.filter(topic="listing.sold", aggregate_id=sold.pk).get()
    for k in ("listing_id", "asset_id", "organisation_id", "submitted_by"):
        assert ev.payload[k]
    assert AuditEvent.objects.filter(action="seller_invoice.success_fee_not_charged",
                                     entity_id=str(sold.pk)).exists()
    assert not MonitoringEnrolment.objects.filter(source_id=sold.pk, status="active").exists()
    for topic in ("listing.submitted", "listing.live"):
        assert OutboxEvent.objects.filter(topic=topic, aggregate_id=sold.pk).exists()


# --------------------------------------------------------------------------- FR-LST-008 removal

def test_removal_by_reviewer_with_reason(seeded, api, people):
    """US-LST-008, TC-LST-008-01, -02: a case manager cannot remove; no reason is refused; a reviewer removes the
    seller and all their listings, and the seller cannot list again."""
    live = L(seeded, "live")
    url = f"/v1/listings/{live.pk}/removals"
    assert api(people["cm"]).post(url, {"reason": "Fake documents"}, format="json").status_code == 403
    assert api(people["reviewer"]).post(url, {"reason": ""}, format="json").status_code == 400
    r = api(people["reviewer"]).post(url, {"reason": "Sold the same plot twice outside Tenmina.",
                                           "scope": "seller"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["listings_removed"] >= 4
    for key in ("live", "reserved", "suspended", "rejected"):
        assert L(seeded, key).status == "removed"
    assert L(seeded, "sold").status == "sold"
    assert Removal.objects.get(pk=r.json()["id"]).reason.startswith("Sold the same plot")
    with pytest.raises(Forbidden):
        services.create_listing(actor=people["seller"], country=live.country, data={
            "organisation_id": live.organisation_id, "title": "Another plot", "price": {"amount": "1000"},
            "asset": {"locality": "Afienya", "plot_number": "Z-1", "site_plan_ref": "Z"}})


# --------------------------------------------------------------------------- FR-LST-001 submit and J-04

def test_developer_submits_pays_and_goes_live(seeded, api, people, gh):
    """US-LST-001 AC1, TC-LST-001-01, TC-STM-LST-01, -03, sequence 5.5: submit, fees, case, green report, live."""
    from cases.models import Case
    from geo.models import MonitoringEnrolment
    from listings.seed import check_invoice, doc, listing_fee_invoice, pay_invoice, release_report
    from orders import legal

    dev = api(people["developer"])
    r = dev.post("/v1/listings", {
        "country": "GH", "kind": "offplan_unit", "title": "One-bedroom unit, Sunrise Gardens block C",
        "price": {"amount": "310000.00", "currency": "GHS"}, "size_sqm": "62.00",
        "organisation_id": str(seeded["orgs"]["developer"].pk),
        "asset": {"locality": "Sunrise Gardens, Oyibi", "plot_number": "SG-C-07", "site_plan_ref": "GA/OYI/C07",
                  "location": {"lng": -0.10, "lat": 5.80}}}, format="json")
    assert r.status_code == 201, r.content
    lid = r.json()["id"]
    assert dev.post(f"/v1/listings/{lid}/submissions", {}, format="json").json()["code"] == "terms-not-accepted"
    site_plan = doc(people["developer"], gh, "sg-c-07.pdf")
    assert dev.post(f"/v1/listings/{lid}/media", {"kind": "site_plan", "evidence_id": str(site_plan.pk)},
                    format="json").status_code == 201
    t = legal.current(gh)
    r = dev.post(f"/v1/listings/{lid}/submissions", {"terms_version": t["terms_version"],
                                                    "scope_version": t["scope_version"]}, format="json")
    assert r.status_code == 200, r.content
    x = Listing.objects.get(pk=lid)
    assert x.status == "draft" and x.verification_order_id and x.fee_invoice_id
    ev = OutboxEvent.objects.get(topic="listing.submitted", aggregate_id=x.pk)
    assert ev.payload["organisation_id"] == str(x.organisation_id) and ev.payload["submitted_by"]
    pay_invoice(listing_fee_invoice(x), people["developer"])
    assert Listing.objects.get(pk=lid).status == "in_verification"
    pay_invoice(check_invoice(x), people["developer"])
    case = Case.objects.get(order_id=x.verification_order_id)
    assert case.asset_id == x.asset_id
    release_report(case, gh, people, "green")
    x.refresh_from_db()
    assert x.status == "live" and x.badge_expires_at and x.checks_date
    assert MonitoringEnrolment.objects.filter(source_id=x.pk, reason="listing", status="active").exists()
    assert str(x.pk) in [i["id"] for i in api().get("/v1/listings?kind=offplan_unit").json()["items"]]


def test_listings_flag_off_and_roles(seeded, settings, people, gh):
    """US-LST-001 AC2 (C-04): with listings.enabled off, submission is switched off; buyers cannot list."""
    data = {"title": "Plot", "price": {"amount": "1000"}, "asset": {"locality": "Afienya", "plot_number": "Q",
                                                                      "site_plan_ref": "Q"}}
    with pytest.raises(Forbidden):
        services.create_listing(actor=people["client"], country=gh, data=data)
    settings.TENMINA_FLAG_OVERRIDES = {"listings.enabled": False}
    with pytest.raises(FeatureOff):
        services.create_listing(actor=people["seller"], country=gh, data=data)


def test_family_and_stool_listing_behind_its_flag(seeded, settings, people, gh):
    """US-LST-009, TC-LST-009-01: an authority representative lists; the same verification rule applies."""
    from accounts.models import Membership, Organisation

    org = Organisation.objects.create(name="Nungua Stool (demo)", kind="authority", country=gh)
    Membership.objects.create(organisation=org, person=people["authority"], org_role="admin")
    data = {"origin": "stool", "organisation_id": org.pk, "title": "Stool land plot 4", "price": {"amount": "90000"},
            "asset": {"locality": "Nungua", "plot_number": "NS-4", "site_plan_ref": "NS/4"}}
    with pytest.raises(Forbidden):
        services.create_listing(actor=people["seller"], country=gh, data=data)
    settings.TENMINA_FLAG_OVERRIDES = {"listings.family_and_stool": False}
    with pytest.raises(FeatureOff):
        services.create_listing(actor=people["authority"], country=gh, data=data)
    settings.TENMINA_FLAG_OVERRIDES = {}
    x = services.create_listing(actor=people["authority"], country=gh, data=data)
    services.add_media(x, people["authority"], kind="site_plan",
                       data=b"%PDF-1.4 stool site plan NS-4", content_type="application/pdf", name="site-plan.pdf")
    t = legal.current(gh)
    services.submit(x, people["authority"], terms_version=t["terms_version"], scope_version=t["scope_version"])
    x.refresh_from_db()
    # The same verification rule: the authority orders the same check of the plot, billed to the authority.
    assert x.submitted_at and x.verification_order_id
    assert x.verification_order.kind == "listing_verification" and x.verification_order.organisation_id == org.pk
    assert x.verification_order.client_id == people["authority"].pk


# --------------------------------------------------------------------------- enquiries and established sellers

def test_enquiries_go_through_tenmina(seeded, api, people):
    """FR-LST-005, 01 B9: no direct chat; the seller sees the question, not the buyer."""
    live = L(seeded, "live")
    r = api(people["client"]).post(f"/v1/listings/{live.pk}/enquiries", {"message": "Is there a title deed?"},
                                   format="json")
    assert r.status_code == 201, r.content
    eid = r.json()["id"]
    seen = api(people["seller"]).get(f"/v1/enquiries/{eid}").json()
    assert seen["message"] == "Is there a title deed?" and seen["buyer_name"] is None
    assert api(people["client2"]).get(f"/v1/enquiries/{eid}").status_code == 404
    a = api(people["cm"]).post(f"/v1/enquiries/{eid}/replies", {"answer": "Yes, a registered lease."},
                               format="json")
    assert a.status_code == 200 and a.json()["status"] == "answered"
    g = api(people["client2"]).post("/v1/enquiries", {"country": "GH", "message": "Looking near Tema.",
                                                      "budget": {"amount": "200000", "currency": "GHS"}},
                                    format="json")
    assert g.status_code == 201 and g.json()["listing_id"] is None


def test_established_seller_screening(seeded, people):
    """Decision 2026-11-12: established only when every check passed, decided by a different reviewer."""
    sunrise = seeded["orgs"]["developer"]
    s = SellerScreening.objects.get(organisation=sunrise)
    with pytest.raises(RuleBlocked):
        services.decide_screening(s, people["reviewer"], outcome="established")
    with pytest.raises(DomainError):
        services.record_screening_check(s, people["cm"], key="court_search", status="passed")  # no evidence
    assert services.is_established(seeded["orgs"]["ato"].pk) is True
    assert services.is_established(sunrise.pk) is False
