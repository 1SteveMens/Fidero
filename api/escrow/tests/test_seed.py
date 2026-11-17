"""The ESC seed builds escrows in every state through the real services."""


def test_seed_states(seeded):
    """FR-ESC-001 to 024: the demo data covers every state a screen shows."""
    from escrow.models import Escrow, ReleaseInstruction

    states = set(Escrow.objects.values_list("status", flat=True))
    assert {"proposed", "funded", "ready_to_release", "released", "frozen", "partly_released"} <= states, states
    assert ReleaseInstruction.objects.filter(status="confirmed").count() >= 3
    assert ReleaseInstruction.objects.filter(status="pending_approval").exists()


def test_seed_has_a_payee_change_waiting_for_the_client(seeded, people):
    """RUL-28, FR-ESC-016: a change of account whose checks passed waits for the client's approval, first, and is
    on her home screen (the client app's payee change sheet has data)."""
    from accounts import home
    from escrow.models import PayeeChange

    ch = PayeeChange.objects.get(pk=seeded["escrow"]["payee_change_waiting"].pk)
    assert ch.status == "checks_passed" and ch.escrow.client == people["client"]
    assert ch.approval_request_id is None  # staff approve only after the client
    links = [i["link"] for i in home.items_for(people["client"]) if i["kind"] == "payee_change"]
    assert f"/payee-changes/{ch.pk}" in links


def test_waiting_change_shows_the_old_account_next_to_the_new(seeded, people, api):
    """RUL-28: before the change is applied, the client compares the payee's current account with the new one."""
    from escrow.models import PayeeChange

    ch = PayeeChange.objects.get(pk=seeded["escrow"]["payee_change_waiting"].pk)
    r = api(people["client"]).get(f"/v1/payee-changes/{ch.pk}")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["previous_last4"] == ch.payee.account_number[-4:] and body["previous_account_name"]
    assert body["account_last4"] == ch.account_number[-4:] != body["previous_last4"]


def test_escrow_says_whether_the_client_can_open_its_case(seeded, people, api):
    """FR-ESC-001: a reservation on a listing sits on the seller's checked case, which the buyer cannot open; the
    escrow says so, so the app offers "Open the case" only for the client's own case."""
    from cases.models import Case
    from escrow.models import Escrow

    seen = set()
    for e in Escrow.objects.filter(client=people["client"]).exclude(case_id=None):
        own = Case.objects.get(pk=e.case_id).client_id == e.client_id
        r = api(people["client"]).get(f"/v1/escrows/{e.pk}")
        assert r.status_code == 200 and r.json()["case_is_clients"] is own
        if own:
            assert api(people["client"]).get(f"/v1/cases/{e.case_id}").status_code == 200
        seen.add(own)
    assert seen == {True, False}
