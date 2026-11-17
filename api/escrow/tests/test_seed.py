"""The ESC seed builds escrows in every state through the real services."""


def test_seed_states(seeded):
    """FR-ESC-001 to 024: the demo data covers every state a screen shows."""
    from escrow.models import Escrow, ReleaseInstruction

    states = set(Escrow.objects.values_list("status", flat=True))
    assert {"proposed", "funded", "ready_to_release", "released", "frozen", "partly_released"} <= states, states
    assert ReleaseInstruction.objects.filter(status="confirmed").count() >= 3
    assert ReleaseInstruction.objects.filter(status="pending_approval").exists()


def test_seeded_escrows_start_from_released_reports(seeded, api):
    """FR-ESC-001: every seeded escrow that names a report names a released report that exists, and the client can
    read it from the escrow page. When the report is on the client's own case, the portal links
    /property/escrows/:id to /property/reports/:report_id. A listing purchase sits on the seller's report: the
    escrow carries listing_id, the portal links to the listing, and the buyer reads the report there (RUL-14,
    FR-LST-003). The seller's case report itself stays closed to the buyer."""
    from escrow.models import Escrow
    from reports.models import Report

    assert Escrow.objects.filter(kind="purchase").count() >= 5
    own = listed = 0
    for e in Escrow.objects.exclude(report_id=None).select_related("client"):
        r = Report.objects.filter(pk=e.report_id).select_related("case").first()
        assert r is not None and r.status == "released", e.title
        c = api(e.client)
        body = c.get(f"/v1/escrows/{e.pk}").json()
        assert body["report_id"] == str(e.report_id), e.title
        if r.case.client_id == e.client_id:
            own += 1
            assert body["listing_id"] is None, e.title
            assert e.case_id == r.case_id and e.asset_id == r.case.asset_id, e.title
            assert c.get(f"/v1/reports/{e.report_id}").status_code == 200, e.title
        else:
            listed += 1
            assert body["listing_id"], f"{e.title}: not the client's report and no listing to read it through"
            assert c.get(f"/v1/listings/{body['listing_id']}").json()["can_read_report"] is True, e.title
            rep = c.get(f"/v1/listings/{body['listing_id']}/report")
            assert rep.status_code == 200 and rep.json()["report_id"] == str(e.report_id), e.title
            assert c.get(f"/v1/reports/{e.report_id}").status_code == 404, e.title
    assert own >= 9 and listed >= 2, (own, listed)
