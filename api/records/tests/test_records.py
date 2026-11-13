"""Records programme (US-REC-001 to US-REC-004, FR-REC-001 to FR-REC-004)."""
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone


def _ev(gh, by, name="scan"):
    import uuid

    from evidence.services import store

    return store(data=f"Register page {name} {uuid.uuid4()}".encode(), country=gh, uploaded_by=by,
                 content_type="text/plain", original_name=f"{name}.txt")


def _square(lng, lat, d=0.001):
    return [[lng, lat], [lng + d, lat], [lng + d, lat + d], [lng, lat + d]]


def _case_with_boundary():
    """An open case whose plot has a boundary; draws one through GEO when the seed has none."""
    from cases.models import OPEN_STATUSES, Case
    from geo.services import save_boundary

    c = Case.objects.filter(status__in=OPEN_STATUSES, asset__current_boundary__isnull=False).select_related(
        "asset__current_boundary").first()
    if c is not None:
        return c
    c = Case.objects.filter(asset__isnull=False).select_related("asset").order_by("created_at").first()
    if c is None:
        pytest.skip("no case with a plot in the seed")
    from accounts.models import Person

    cm = Person.objects.get(email="cm@tenmina.test")
    save_boundary(c.asset, actor=cm, source="drawn", points=_square(-0.1900, 5.6500, 0.0012))
    return Case.objects.select_related("asset__current_boundary").get(pk=c.pk)


def test_capture_and_overlap_flag(seeded, api):
    """FR-REC-001, US-REC-001 AC1 and AC2, TC-REC-001-01: a paper record becomes a plot with boundary, allottee,
    date and scanned document; an overlapping allocation is flagged for review."""
    from records.models import Allocation

    gh, cm = seeded["gh"], seeded["people"]["cm"]
    stool = seeded["records"]["stool"]
    c = api(cm)
    body = {"authority_id": str(stool.pk), "reference": "Test book 9, p. 1", "allottee_name": "Ama Owusu",
            "allocated_on": "2001-05-04", "document_evidence_id": str(_ev(gh, cm).pk),
            "points": _square(-0.30, 5.70)}
    r = c.post("/v1/records/allocations", body, format="json")
    assert r.status_code == 201, r.content
    a = r.json()
    assert a["status"] == "captured" and a["allottee_name"] == "Ama Owusu" and a["document_sha256"]
    assert a["boundary"]["type"] == "MultiPolygon" and Decimal(a["area_sqm"]) > 0
    body.update(reference="Test book 9, p. 2", allottee_name="Kojo Owusu", document_evidence_id=str(_ev(gh, cm).pk),
                points=[[x + 0.0005, y] for x, y in _square(-0.30, 5.70)])
    r = c.post("/v1/records/allocations", body, format="json")
    assert r.status_code == 201 and r.json()["status"] == "flagged" and r.json()["overlaps"]
    r = c.get("/v1/records/allocations?q=Ama Owusu")
    assert any(x["id"] == a["id"] for x in r.json()["items"])
    ov = c.get("/v1/records/allocations?status=flagged").json()["items"][0]["overlaps"][0]
    r = c.post(f"/v1/records/overlaps/{ov['id']}/resolutions", {"note": "Boundary redrawn from the site plan"},
               format="json")
    assert r.status_code == 200 and r.json()["status"] == "resolved"


def test_representative_confirms_own_records_only(seeded, api):
    """FR-REC-004, US-REC-004 AC1 and AC2, TC-REC-004-01: the stool's representative confirms with name and time;
    another authority's record is refused."""
    from records import services

    gh, cm, ar = seeded["gh"], seeded["people"]["cm"], seeded["people"]["authority"]
    stool, family = seeded["records"]["stool"], seeded["records"]["family"]
    mine = services.capture_allocation(cm, authority=stool, reference="Conf test 1", allottee_name="Efua",
                                       allocated_on=date(2010, 1, 1), document_evidence=_ev(gh, cm),
                                       points=_square(-0.40, 5.80))
    other = services.capture_allocation(cm, authority=family, reference="Conf test 2", allottee_name="Yaa",
                                        allocated_on=date(2010, 1, 1), document_evidence=_ev(gh, cm),
                                        points=_square(-0.42, 5.82))
    c = api(ar)
    r = c.post(f"/v1/records/allocations/{mine.pk}/confirm")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "confirmed" and r.json()["confirmed_name"] == ar.full_name
    assert r.json()["confirmed_at"]
    assert c.get(f"/v1/records/allocations/{other.pk}").status_code == 404
    assert c.post(f"/v1/records/allocations/{other.pk}/confirm").status_code == 404
    ids = {a["id"] for a in c.get("/v1/records/allocations?limit=100").json()["items"]}
    assert str(mine.pk) in ids and str(other.pk) not in ids
    assert {a["id"] for a in c.get("/v1/records/authorities").json()["items"]} == {str(stool.pk)}
    assert api(cm).post(f"/v1/records/allocations/{mine.pk}/confirm").status_code == 404
    assert api(seeded["people"]["client"]).get("/v1/records/allocations").json()["items"] == []


def test_match_prefills_chain_for_lawyer(seeded, api):
    """FR-REC-002, US-REC-002 AC1, TC-REC-002-01: a case plot that matches a record gets section 9's chain
    pre-filled, marked as from the records, for the lawyer to confirm."""
    from cases.models import Task
    from records import services
    from records.models import Match

    gh, cm, lawyer = seeded["gh"], seeded["people"]["cm"], seeded["people"]["lawyer"]
    case = _case_with_boundary()
    bv = case.asset.current_boundary
    Match.objects.filter(case=case).delete()
    from records.models import Allocation

    Allocation.objects.filter(geom__intersects=bv.geom).update(status="revoked")
    first = services.capture_allocation(cm, authority=seeded["records"]["stool"], reference="Chain 1",
                                        allottee_name="Old Allottee", allocated_on=date(1990, 1, 1),
                                        document_evidence=_ev(gh, cm), geojson=json.loads(bv.geom.geojson))
    later = services.capture_allocation(cm, authority=seeded["records"]["stool"], reference="Chain 2",
                                        allottee_name="New Allottee", allocated_on=date(2012, 1, 1),
                                        document_evidence=_ev(gh, cm), geojson=json.loads(bv.geom.geojson),
                                        previous=first)
    r = api(cm).post("/v1/records/matches/run", {"case_id": str(case.pk)}, format="json")
    assert r.status_code == 200, r.content
    m = next(x for x in r.json() if x["allocation"] == str(later.pk))
    assert m["kind"] == "exact" and m["status"] == "proposed"
    assert [e["to"] for e in m["prefill"]] == ["Old Allottee", "New Allottee"]
    assert all(e["source"] == "records_programme" for e in m["prefill"])
    assert not any(x["allocation"] == str(first.pk) for x in r.json())
    Task.objects.filter(case=case, owner_role="LW").update(assignee=lawyer)
    lw = api(lawyer)
    assert any(x["id"] == m["id"] for x in lw.get(f"/v1/records/matches?asset_id={case.asset_id}").json()["items"])
    assert api(seeded["people"]["surveyor"]).post(f"/v1/records/matches/{m['id']}/confirm").status_code in (403, 404)
    r = lw.post(f"/v1/records/matches/{m['id']}/confirm", {"note": "Matches the indenture"}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()["status"] == "confirmed"
    if r.json()["applied_to_report_id"]:
        from reports.models import Report

        sec = Report.objects.get(pk=r.json()["applied_to_report_id"]).sections.get(number=9)
        assert sec.findings["chain_from_records"][-1]["to"] == "New Allottee"
    from records.selectors import confirmed_chain

    assert confirmed_chain(case.pk)[-1]["to"] == "New Allottee"


def test_near_match_not_prefilled_and_no_match(seeded):
    """US-REC-002 AC2, TC-REC-002-02: a partial overlap is flagged for review with nothing pre-filled; no overlap
    does nothing."""
    from records import services
    from records.models import Match
    from records.seed import _shifted

    gh, cm = seeded["gh"], seeded["people"]["cm"]
    case = _case_with_boundary()
    bv = case.asset.current_boundary
    Match.objects.filter(case=case).delete()
    from records.models import Allocation

    Allocation.objects.filter(geom__intersects=bv.geom).update(status="revoked")
    assert services.match_case(case) == []
    services.capture_allocation(cm, authority=seeded["records"]["family"], reference="Near 1",
                                allottee_name="Partial", allocated_on=date(2000, 1, 1),
                                document_evidence=_ev(gh, cm), geojson=_shifted(bv.geom, 0.5))
    ms = services.match_case(case)
    assert len(ms) == 1 and ms[0].kind == "near" and ms[0].status == "review" and ms[0].prefill == []
    assert services.match_case(case) == []  # once only


def test_revenue_share(seeded, api):
    """FR-REC-003, US-REC-003 AC1, TC-REC-003-01: each authority's amount from cases that used its records in the
    period; a second administrator approves; the representative sees only their own."""
    from records import services
    from records.models import Match

    gh, admin, admin2 = seeded["gh"], seeded["people"]["admin"], seeded["people"]["admin2"]
    stool = seeded["records"]["stool"]
    case = _case_with_boundary()
    alloc = services.capture_allocation(seeded["people"]["cm"], authority=stool, reference="Share 1",
                                        allottee_name="X", allocated_on=date(2000, 1, 1),
                                        document_evidence=_ev(gh, admin),
                                        geojson=json.loads(case.asset.current_boundary.geom.geojson))
    services.match_case(case)
    m = Match.objects.get(allocation=alloc, case=case)
    Match.objects.filter(pk=m.pk).update(status="confirmed", decided_at=timezone.now())
    start, end = timezone.localdate() - timedelta(days=30), timezone.localdate() + timedelta(days=1)
    r = api(admin).post("/v1/records/revenue-shares/compute", {"country": "GH", "period_start": str(start),
                                                               "period_end": str(end)}, format="json")
    assert r.status_code == 201, r.content
    row = next(x for x in r.json() if x["authority"] == str(stool.pk))
    n = len({i["case_id"] for i in row["cases"]})
    assert row["case_count"] == n >= 1
    assert Decimal(row["amount"]["amount"]) == stool.share_per_case * n
    assert api(admin).post(f"/v1/records/revenue-shares/{row['id']}/approve").status_code == 409
    assert api(admin2).post(f"/v1/records/revenue-shares/{row['id']}/approve").json()["status"] == "approved"
    ar = api(seeded["people"]["authority"]).get("/v1/records/revenue-shares").json()["items"]
    assert ar and all(x["authority"] == str(stool.pk) for x in ar)
    assert api(seeded["people"]["cm"]).post("/v1/records/revenue-shares/compute", {
        "country": "GH", "period_start": str(start), "period_end": str(end)}, format="json").status_code == 403


def test_flag_off(seeded, api, settings):
    settings.TENMINA_FLAG_OVERRIDES = {"records.enabled": False}
    r = api(seeded["people"]["cm"]).get("/v1/records/allocations")
    assert r.status_code == 404 and r.json()["code"] == "feature-off"
