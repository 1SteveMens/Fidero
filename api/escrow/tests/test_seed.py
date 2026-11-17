"""The ESC seed builds escrows in every state through the real services."""


def test_seed_states(seeded):
    """FR-ESC-001 to 024: the demo data covers every state a screen shows."""
    from escrow.models import Escrow, ReleaseInstruction

    states = set(Escrow.objects.values_list("status", flat=True))
    assert {"proposed", "funded", "ready_to_release", "released", "frozen", "partly_released"} <= states, states
    assert ReleaseInstruction.objects.filter(status="confirmed").count() >= 3
    assert ReleaseInstruction.objects.filter(status="pending_approval").exists()


def test_seeded_escrows_start_from_released_reports(seeded, api):
    """FR-ESC-001: every seeded escrow that names a report names a released report that exists. When the report is
    on the client's own case, the client can open it (the portal links /property/escrows/:id to
    /property/reports/:report_id). A listing purchase sits on the seller's report, which the buyer reads through
    the listing instead."""
    from escrow.models import Escrow
    from reports.models import Report

    assert Escrow.objects.filter(kind="purchase").count() >= 5
    own = 0
    for e in Escrow.objects.exclude(report_id=None).select_related("client"):
        r = Report.objects.filter(pk=e.report_id).select_related("case").first()
        assert r is not None and r.status == "released", e.title
        if r.case.client_id == e.client_id:
            own += 1
            assert e.case_id == r.case_id and e.asset_id == r.case.asset_id, e.title
            assert api(e.client).get(f"/v1/reports/{e.report_id}").status_code == 200, e.title
    assert own >= 9
