"""Staff people picker: GET /v1/people?search= (back office forms that ask for a person)."""
from accounts.models import Person, RoleGrant
from countries.models import Country


def test_staff_search_people_by_name_with_masked_email(seeded, api, people):
    r = api(people["cm"]).get("/v1/people", {"search": "ama"})
    assert r.status_code == 200, r.content
    rows = r.json()["items"]
    ama = next(x for x in rows if x["id"] == str(people["client"].pk))
    assert ama["full_name"] == "Ama Mensah"
    assert ama["roles"] == ["CL"]
    assert ama["email_masked"] == "a•••@example.com"
    assert set(ama) == {"id", "full_name", "roles", "email_masked"}


def test_search_needs_two_characters(seeded, api, people):
    r = api(people["cm"]).get("/v1/people", {"search": "a"})
    assert r.status_code == 422 and r.json()["code"] == "search-too-short"


def test_role_filter(seeded, api, people):
    r = api(people["admin"]).get("/v1/people", {"search": "example.com", "role": "IN"})
    assert r.status_code == 200
    rows = r.json()["items"]
    assert "Kwesi Inspector" in [x["full_name"] for x in rows]
    assert all("IN" in x["roles"] for x in rows)


def test_only_staff_may_search(seeded, api, people):
    assert api(people["client"]).get("/v1/people", {"search": "ama"}).status_code == 403
    assert api(people["lawyer"]).get("/v1/people", {"search": "ama"}).status_code == 403
    assert api().get("/v1/people", {"search": "ama"}).status_code in (401, 403)


def test_list_endpoints_take_search(seeded, api, people):
    """The other pickers use each module's own list with ?search= (it only narrows what the caller sees)."""
    from cases.models import Case
    from escrow.models import Payee

    cm = api(people["cm"])
    case = Case.objects.order_by("created_at").first()
    rows = cm.get("/v1/cases", {"search": case.reference}).json()["items"]
    assert [r["id"] for r in rows] == [str(case.pk)]
    payee = Payee.objects.order_by("created_at").first()
    rows = cm.get("/v1/payees", {"search": payee.legal_name[:6]}).json()["items"]
    assert str(payee.pk) in [r["id"] for r in rows]
    assert all(payee.legal_name[:6].lower() in (r["legal_name"] + r.get("account_name", "")).lower() for r in rows)
    assert cm.get("/v1/organisations", {"search": "zzz-no-such"}).json()["items"] == []
    assert api(people["admin"]).get("/v1/admin/partners", {"search": "zzz-no-such"}).json()["items"] == []
    for path in ("/v1/reports", "/v1/carers", "/v1/errand-agents", "/v1/panel-members", "/v1/insurance/insurers"):
        assert cm.get(path, {"search": "zzz-no-such"}).json()["items"] == [], path
    # A client's search never reaches other clients' cases.
    other = Case.objects.exclude(client=people["client"]).exclude(client=None).first()
    if other:
        assert api(people["client"]).get("/v1/cases", {"search": other.reference}).json()["items"] == []


def test_staff_see_only_people_in_their_countries(seeded, api, people, gh):
    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria", "currency": "NGN"})
    outsider = Person.objects.create_user("chidi@example.com", "a-long-password-1", full_name="Chidi Okafor",
                                          home_country=ng)
    RoleGrant.objects.create(person=outsider, role="CL", country=ng)
    cm = people["cm"]
    cm.role_grants.filter(role="CM").update(country=gh)
    r = api(cm).get("/v1/people", {"search": "chidi"})
    assert r.status_code == 200 and r.json()["items"] == []
    r = api(cm).get("/v1/people", {"search": "ama"})
    assert any(x["full_name"] == "Ama Mensah" for x in r.json()["items"])
    # An administrator with a grant for every country sees both.
    admin = people["admin"]
    if admin.role_grants.filter(role="AD", country__isnull=True).exists():
        r = api(admin).get("/v1/people", {"search": "chidi"})
        assert [x["full_name"] for x in r.json()["items"]] == ["Chidi Okafor"]
