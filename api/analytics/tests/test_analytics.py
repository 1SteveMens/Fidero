"""ANL tests (document 05 section 4.19: TC-ANL-001-01, TC-ANL-002-01, TC-ANL-003-01, TC-ANL-003-02).

Hand-computed fixtures live in January to March 2031, after every seeded row,
so each figure below can be checked by hand. Ghana's weekend is Saturday and
Sunday and its seeded holiday calendar covers 2026 only.
"""
import csv
import hashlib
import io
import uuid
from datetime import date, datetime
from datetime import timezone as dt_timezone
from decimal import Decimal

import pytest
from django.db import transaction

from analytics import metrics as m
from analytics import selectors, services
from analytics.models import ExportLog

UTC = dt_timezone.utc
WINDOW = {"date_from": "2031-01-01", "date_to": "2031-03-31", "country": "GH"}


def at(y, mo, d, h=10):
    return datetime(y, mo, d, h, tzinfo=UTC)


def _report(gh, *, client, paid, released, verdict, tier="standard", kind="verification", price="300.00",
            costs=(), status="released", supersedes=None, case=None):
    from cases.models import Case, CostItem
    from geo.models import Asset
    from orders.models import Order
    from reports.models import Report

    tpl = Report.objects.filter(pdf_evidence__isnull=False).order_by("created_at").first()
    tag = uuid.uuid4().hex[:10]
    if case is None:
        from administration.models import ConfigVersion

        order = Order.objects.create(
            reference=f"TMR-GH-ANL-{tag}", client=client, placed_by=client, kind=kind, tier=tier, country=gh,
            status="paid", price_amount=Decimal(price), price_currency="USD", local_price_amount=Decimal("4500.00"),
            local_price_currency="GHS", terms_accepted_at=paid, paid_at=paid, asset_type="plot")
        case = Case.objects.create(
            reference=f"CASE-GH-ANL-{tag}", order=order, asset=tpl.case.asset if tpl else Asset.objects.first(),
            client=client, product_line="land", country=gh, status="released",
            template_version=tpl.case.template_version if tpl else ConfigVersion.objects.first())
        for item_type, amount in costs:
            CostItem.objects.create(case=case, item_type=item_type, amount=Decimal(amount), currency="USD",
                                    incurred_on=paid.date(), country=gh)
    return Report.objects.create(
        case=case, version=2 if supersedes else 1, reference=f"RPT-GH-ANL-{tag}", country=gh,
        template_version=tpl.template_version, scope_text_version=tpl.scope_text_version, overall_verdict=verdict,
        status=status, pdf_sha256="a" * 64, pdf_evidence=tpl.pdf_evidence, released_at=released,
        supersedes=supersedes, correction_reason="Correction for the test" if supersedes else "")


@pytest.fixture
def fx(seeded, gh, people):
    """Three buyer-paid land reports in January 2031, one seller-paid in February, one correction."""
    client, client2, seller = people["client"], people["client2"], people["seller"]
    for p, res in ((client, "GB"), (client2, "GH"), (seller, "GH")):
        p.residence_country = res
        p.save(update_fields=["residence_country"])
    r1 = _report(gh, client=client, paid=at(2031, 1, 6), released=at(2031, 1, 20), verdict="green",
                 costs=[("lawyer", "100.00"), ("travel", "20.00")], status="superseded")
    _report(gh, client=client2, paid=at(2031, 1, 7), released=at(2031, 1, 24), verdict="green",
            costs=[("surveyor", "150.00")])
    _report(gh, client=client, paid=at(2031, 1, 8), released=at(2031, 1, 29), verdict="red", tier="premium")
    _report(gh, client=seller, paid=at(2031, 2, 3), released=at(2031, 2, 17), verdict="amber", tier="",
            kind="listing_verification")
    _report(gh, client=client, paid=None, released=at(2031, 2, 20), verdict="amber", supersedes=r1, case=r1.case)
    return {"client": client, "client2": client2, "seller": seller}


def _f(**kw):
    base = {"date_from": date(2031, 1, 1), "date_to": date(2031, 3, 31), "countries": ["GH"]}
    base.update(kw)
    return m.Filters(**base)


def _get(client, path, **params):
    r = client.get(path, {**WINDOW, **params})
    assert r.status_code == 200, r.content
    return r.json()


# ------------------------------------------------------------------ metric values (TC-ANL-001-01)

def test_reports_and_verdicts_match_hand_count(fx):
    """FR-ANL-001, A9: paid reports per month by tier, first issues only, with the verdict mix."""
    rows = m.METRICS["reports_released"].run(_f())
    assert rows == [
        {"month": "2031-01", "country": "GH", "product_line": "land", "tier": "premium", "reports": 1,
         "seller_paid": 0, "red": 1, "amber": 0, "green": 0},
        {"month": "2031-01", "country": "GH", "product_line": "land", "tier": "standard", "reports": 2,
         "seller_paid": 0, "red": 0, "amber": 0, "green": 2},
        {"month": "2031-02", "country": "GH", "product_line": "land", "tier": "", "reports": 1,
         "seller_paid": 1, "red": 0, "amber": 1, "green": 0},
    ]
    mix = m.METRICS["verdict_mix"].run(_f())
    assert mix == [{"country": "GH", "product_line": "land", "reports": 4, "red": 1, "amber": 1, "green": 2,
                    "red_pct": 25.0, "amber_pct": 25.0, "green_pct": 50.0}]


def test_orders_paid_by_kind_and_tier(fx):
    """A9: paid orders per month by tier and country; money as strings per currency."""
    rows = m.METRICS["orders_paid"].run(_f())
    assert {(r["month"], r["kind"], r["tier"]): (r["orders"], r["value"], r["line"]) for r in rows} == {
        ("2031-01", "verification", "premium"): (1, "300.00", "property"),
        ("2031-01", "verification", "standard"): (2, "600.00", "property"),
        ("2031-02", "listing_verification", ""): (1, "300.00", "property"),
    }


def test_turnaround_in_working_days(fx):
    """A9: turnaround median and 90th percentile, payment to delivery, in the country's working days."""
    rows = m.METRICS["turnaround"].run(_f())
    jan = next(r for r in rows if r["month"] == "2031-01")
    # 10, 13 and 15 working days (weekends excluded); 14, 17 and 21 calendar days.
    assert jan == {"month": "2031-01", "country": "GH", "product_line": "land", "reports": 3,
                   "median_working_days": 13.0, "p90_working_days": 14.6, "max_working_days": 15,
                   "median_calendar_days": 17.0}
    feb = next(r for r in rows if r["month"] == "2031-02")
    assert feb["reports"] == 1 and feb["median_working_days"] == 10.0


def test_cost_per_report_against_price(fx):
    """A9 and validation plan: cost per report, as a share of price, in the same currency."""
    assert m.METRICS["cost_per_report"].run(_f()) == [
        {"month": "2031-01", "country": "GH", "currency": "USD", "reports_costed": 2, "total_cost": "270.00",
         "cost_per_report": "135.00", "price_total": "600.00", "cost_share_pct": 45.0, "gross_margin_pct": 55.0}]


def test_active_and_repeat_clients(fx):
    """Validation plan: active clients, repeat clients and their share; diaspora clients."""
    rows = {r["month"]: r for r in m.METRICS["clients"].run(_f())}
    assert rows["all"] == {"month": "all", "country": "GH", "active_clients": 3, "repeat_clients": 1,
                           "repeat_share_pct": 33.3, "diaspora_clients": 1, "transactions": 4}
    assert rows["2031-01"]["active_clients"] == 2 and rows["2031-01"]["repeat_clients"] == 1
    lines = m.METRICS["transactions_by_line"].run(_f())
    assert {(r["month"], r["line"], r["source"]): (r["transactions"], r["clients"]) for r in lines} == {
        ("2031-01", "property", "order"): (3, 2), ("2031-02", "property", "order"): (1, 1)}


def test_line_and_tier_filters_update_every_tile(fx):
    """US-ANL-001 AC2: a filter changes every tile it applies to; tiles of another line go empty."""
    prem = _f(tier="premium")
    assert sum(r["reports"] for r in m.METRICS["reports_released"].run(prem)) == 1
    assert sum(r["orders"] for r in m.METRICS["orders_paid"].run(prem)) == 1
    fam = _f(line="family")
    assert m.METRICS["reports_released"].run(fam) == []
    assert m.METRICS["turnaround"].run(fam) == []
    assert m.METRICS["clients"].run(fam) == []
    assert m.METRICS["reports_released"].run(_f(countries=["NG"])) == []


def test_day90_review_measures(fx):
    """Validation plan section 6: the go criteria measured from platform data."""
    from escrow.models import Escrow

    rows = {r["measure"]: r for r in m.METRICS["day90_review"].run(_f())}
    assert rows["property_reports_delivered"]["value"] == 3  # seller-paid checks do not count
    assert rows["property_reports_delivered"]["status"] == "not_met"
    assert rows["active_clients"]["value"] == 3
    assert rows["repeat_share_pct"]["value"] == 33.3 and rows["repeat_share_pct"]["status"] == "met"
    assert rows["diaspora_clients"]["value"] == 1
    assert rows["median_turnaround_working_days"]["value"] == 11.5  # 10, 10, 13, 15
    assert rows["median_turnaround_working_days"]["status"] == "met"
    assert rows["cost_share_pct"]["value"] == 45.0 and rows["cost_share_pct"]["status"] == "met"
    assert rows["family_payments_with_receipt"]["value"] == 0
    green = [fx["client"], fx["client2"]]
    with_escrow = sum(1 for c in green if Escrow.objects.filter(client=c, created_at__lt=at(2031, 4, 1, 0)).exists())
    assert rows["green_report_clients_to_escrow_pct"]["value"] == m.pct(with_escrow, 2)


def test_day90_targets_follow_country_configuration(fx, gh, publish_config):
    """Country is configuration: a country may set its own day-90 targets."""
    publish_config(gh, analytics={"day90_targets": {"property_reports_delivered": 3}})
    rows = {r["measure"]: r for r in m.METRICS["day90_review"].run(_f())}
    assert rows["property_reports_delivered"]["target"] == 3
    assert rows["property_reports_delivered"]["status"] == "met"


def test_every_metric_runs_on_seeded_data_with_its_columns(seeded):
    """FR-ANL-001: every tile answers over all seeded modules, with exactly its declared columns."""
    f = m.Filters(date(2020, 1, 1), date(2030, 12, 31), None)
    for name, metric in m.METRICS.items():
        for row in metric.run(f):
            assert set(row) == set(metric.columns), name


def test_metrics_agree_with_module_counts(seeded):
    """A9 sources: totals match plain counts in the owning modules."""
    from disputes.models import Dispute
    from escrow.models import ReleaseInstruction
    from fees.models import Payment
    from mobile.models import FraudFlag, Submission

    f = m.Filters(date(2020, 1, 1), date(2030, 12, 31), None)
    total = lambda name, col: sum(r[col] for r in m.METRICS[name].run(f))  # noqa: E731
    assert total("family_payments", "payments") == Payment.objects.filter(
        status__in=m.PAID_FEE_STATUSES, paid_at__isnull=False).count()
    assert total("releases", "releases") == ReleaseInstruction.objects.filter(
        status="confirmed", kind__in=["release", "partial_release"], bank_confirmation_event__isnull=False).count()
    assert total("disputes", "opened") == Dispute.objects.count()
    assert total("field_flags", "flags") == FraudFlag.objects.count()
    assert total("field_submissions", "submissions") == Submission.objects.count()


def test_percentile_matches_percentile_cont():
    """Median and 90th percentile use linear interpolation, as PostgreSQL percentile_cont."""
    assert m.percentile([10, 13, 15], 0.5) == 13.0
    assert m.percentile([10, 13, 15], 0.9) == 14.6
    assert m.percentile([10, 10, 13, 15], 0.5) == 11.5
    assert m.percentile([], 0.5) is None


# ------------------------------------------------------------------ the dashboard API and roles (FR-ANL-003)

def test_admin_dashboard_shows_every_tile(fx, api, people):
    """US-ANL-001 AC1: paid reports, turnaround, verdict mix and escrow figures on one call."""
    body = _get(api(people["admin"]), "/v1/analytics/metrics")
    names = [t["name"] for t in body["tiles"]]
    for needed in ("orders_paid", "reports_released", "turnaround", "verdict_mix", "escrows", "releases",
                   "release_clock", "held_at_bank", "family_payments", "clients", "disputes", "payment_runs",
                   "field_flags", "day90_review"):
        assert needed in names
    tile = next(t for t in body["tiles"] if t["name"] == "verdict_mix")
    assert tile["rows"][0]["reports"] == 4 and tile["suppression"]["applied"] is False
    assert body["filters"]["countries"] == ["GH"]


def test_case_manager_sees_small_groups_blanked(fx, api, people):
    """TC-ANL-003-01, TC-ANL-003-02: below the minimum group size [TO VERIFY] values are blanked for roles
    without full detail; no names ever appear."""
    body = _get(api(people["cm"]), "/v1/analytics/metrics/reports_released")
    assert body["suppression"]["applied"] is True and body["suppression"]["min_group_size"] == 5
    assert all(r["reports"] is None and r["suppressed"] for r in body["rows"])
    review = _get(api(people["cm"]), "/v1/analytics/review")
    active = next(r for r in review["rows"] if r["measure"] == "active_clients")
    assert active["value"] is None and active["status"] == "suppressed"
    text = str(_get(api(people["cm"]), "/v1/analytics/metrics"))
    for p in (people["client"], people["client2"], people["seller"]):
        assert p.full_name not in text and p.email not in text and str(p.pk) not in text


def test_minimum_group_size_is_configuration(fx, gh, publish_config, api, people):
    """TC-ANL-003-02: the minimum group size is set per country."""
    publish_config(gh, analytics={"min_group_size": 2})
    body = _get(api(people["cm"]), "/v1/analytics/metrics/reports_released")
    rows = {(r["month"], r["tier"]): r for r in body["rows"]}
    assert rows[("2031-01", "standard")]["reports"] == 2
    assert rows[("2031-01", "premium")]["reports"] is None


def test_only_staff_and_analysts_open_the_dashboard(seeded, api, people):
    """FR-ANL-003: clients, professionals and partners get 403."""
    for key in ("client", "lawyer", "partner"):
        assert api(people[key]).get("/v1/analytics/metrics").status_code == 403
    assert api().get("/v1/analytics/metrics").status_code in (401, 403)


@pytest.fixture
def analyst(seeded, gh):
    from accounts.models import Person, RoleGrant

    p = Person.objects.create_user("analyst@tenmina.test", "tenmina-dev-123", full_name="Abena Analyst",
                                   home_country=gh)
    RoleGrant.objects.create(person=p, role="AN", country=gh)
    return p


def test_analyst_is_scoped_to_their_country(fx, api, analyst):
    """FR-CTY-003, US-CTY-003: an analyst sees only their countries; asking for another is refused."""
    c = api(analyst)
    body = c.get("/v1/analytics/metrics/verdict_mix", {"date_from": "2031-01-01", "date_to": "2031-03-31"}).json()
    assert body["filters"]["countries"] == ["GH"]
    r = c.get("/v1/analytics/metrics/verdict_mix", {"country": "NG"})
    assert r.status_code == 403 and r["Content-Type"].startswith("application/problem+json")


def test_bad_filters_are_refused(seeded, api, people):
    """FR-ANL-001: dates, line and metric names are checked."""
    c = api(people["admin"])
    assert c.get("/v1/analytics/metrics", {"date_from": "2031-02-01", "date_to": "2031-01-01"}).status_code == 422
    assert c.get("/v1/analytics/metrics", {"line": "cocoa"}).status_code == 422
    assert c.get("/v1/analytics/metrics/nothing").status_code == 404
    assert c.get("/v1/analytics/metrics", {"date_from": "yesterday"}).status_code == 422


def test_catalogue_lists_metrics_and_the_personal_table(seeded, api, people):
    body = api(people["reviewer"]).get("/v1/analytics/catalogue").json()
    by = {x["name"]: x for x in body}
    assert by["turnaround"]["filters"] == ["date", "country", "line", "tier"]
    assert by["client_register"]["personal_data"] is True


# ------------------------------------------------------------------ exports (TC-ANL-002-01, TC-DPR-005-02)

def test_reviewer_exports_csv_and_the_export_is_logged(fx, api, people):
    """US-ANL-002 AC1, TC-ANL-002-01: the CSV matches the dashboard table and the export is logged and audited."""
    from audit.models import AuditEvent

    rv = people["reviewer"]
    r = api(rv).post("/v1/analytics/exports", {"metric": "verdict_mix", **WINDOW}, format="json")
    assert r.status_code == 200 and r["Content-Type"].startswith("text/csv")
    data = r.content
    rows = list(csv.reader(io.StringIO(data.decode())))
    assert rows[0] == m.METRICS["verdict_mix"].columns
    assert rows[1][:2] == ["GH", "land"]
    log = ExportLog.objects.get(pk=r["Tenmina-Export-Id"])
    assert log.requested_by == rv and log.metric == "verdict_mix" and log.row_count == 1
    assert log.sha256 == hashlib.sha256(data).hexdigest() and log.country.code == "GH"
    assert AuditEvent.objects.filter(action="analytics.exported", entity_id=log.pk).exists()
    listed = api(rv).get("/v1/analytics/exports").json()
    assert str(log.pk) in str(listed)


def test_exports_blank_small_groups_even_for_admins(fx, api, people):
    """FR-ANL-003, I-11: a metric export never carries a group smaller than the minimum."""
    r = api(people["admin"]).post("/v1/analytics/exports", {"metric": "reports_released", **WINDOW}, format="json")
    rows = list(csv.DictReader(io.StringIO(r.content.decode())))
    assert rows and all(row["reports"] == "" for row in rows)
    assert ExportLog.objects.get(pk=r["Tenmina-Export-Id"]).suppressed_cells > 0


def test_case_manager_cannot_export(fx, api, people):
    """FR-ANL-002: exports are for reviewers, administrators and analysts."""
    r = api(people["cm"]).post("/v1/analytics/exports", {"metric": "verdict_mix"}, format="json")
    assert r.status_code == 403
    assert not ExportLog.objects.filter(requested_by=people["cm"]).exists()


def test_personal_data_export_goes_through_two_person_bulk_export(fx, api, people, gh):
    """FR-DPR-005, TC-DPR-005-02, I-11: the client register is never produced by ANL; it becomes a bulk export
    waiting for a second administrator."""
    r = api(people["admin"]).post("/v1/analytics/exports", {"metric": "client_register", "country": "GH",
                                                            "purpose": "Investor diligence",
                                                            "fields": ["full_name", "email"]}, format="json")
    assert r.status_code == 202, r.content
    body = r.json()
    assert body["personal_data"] is True and body["status"] == "sent_for_approval"
    assert body["bulk_export_status"] == "pending_approval"
    log = ExportLog.objects.get(pk=body["id"])
    assert log.bulk_export.approval_request.status == "open" and log.row_count == 0


def test_personal_export_refusals(fx, api, people):
    """FR-DPR-005: only an administrator, one country, known fields; a reviewer cannot pull clients through ANL."""
    rv = api(people["reviewer"]).post("/v1/analytics/exports", {"metric": "client_register", "country": "GH",
                                                                "purpose": "x"}, format="json")
    assert rv.status_code == 403
    ad = api(people["admin"])
    assert ad.post("/v1/analytics/exports", {"metric": "client_register", "purpose": "x"},
                   format="json").status_code == 422
    assert ad.post("/v1/analytics/exports", {"metric": "client_register", "country": "GH", "purpose": "x",
                                             "fields": ["password"]}, format="json").status_code == 422
    with pytest.raises(Exception):
        services.export_csv(people["admin"], "client_register", _f())


def test_export_log_is_append_only(fx, people):
    """FR-ANL-002: the export log cannot be changed or deleted, also in the database."""
    _data, log = services.export_csv(people["reviewer"], "verdict_mix", _f())
    with pytest.raises(Exception), transaction.atomic():
        ExportLog.objects.filter(pk=log.pk).update(row_count=99)
    with pytest.raises(Exception), transaction.atomic():
        ExportLog.objects.filter(pk=log.pk).delete()


def test_filters_default_to_the_last_twelve_months(seeded, people):
    f = selectors.resolve_filters(people["admin"])
    assert f.date_to == date.today() and f.date_from.day == 1 and f.countries is None
    assert (f.date_to.year * 12 + f.date_to.month) - (f.date_from.year * 12 + f.date_from.month) == 11
