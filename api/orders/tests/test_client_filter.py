"""Back office: a client's orders, cases and escrows (Clients and orders screen)."""


def test_staff_filter_by_client_narrows_to_that_client(seeded, api, people):
    """FR-ACC-007: the client filter only narrows what staff may already see."""
    ama, kofi = people["client"], people["client2"]
    cm = api(people["cm"])
    for path in ("/v1/orders", "/v1/cases", "/v1/escrows"):
        r = cm.get(path, {"client": str(ama.pk)})
        assert r.status_code == 200, (path, r.content)
        items = r.json()["items"]
        assert items, path
        everyone = cm.get(path).json()["items"]
        assert len(items) <= len(everyone)
    assert cm.get("/v1/orders", {"client": "nope"}).status_code == 422
    # A client asking about someone else still sees nothing of theirs.
    r = api(kofi).get("/v1/orders", {"client": str(ama.pk)})
    assert r.status_code == 200 and r.json()["items"] == []
