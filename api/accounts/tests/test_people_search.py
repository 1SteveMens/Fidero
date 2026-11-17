"""People pickers in the back office: GET /v1/people?search=&role= for staff (CM, RV, AD), scoped to their
countries, with only id, name, roles and a masked email; at least 2 characters; rate-limited; audited. Professionals,
carers and errand agents lists take ?search= too (FR-ACC-007 scoping, FR-AUD-003)."""
import uuid

import pytest

from accounts.models import Person, RoleGrant
from accounts.selectors import mask_email
from audit.models import AuditEvent


@pytest.fixture(autouse=True)
def _fresh_throttle():
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _person(country, name, role="CL", grant_country=None):
    p = Person.objects.create(email=f"{name.split()[0].lower()}.{uuid.uuid4().hex[:6]}@example.com",
                              full_name=name, home_country=country)
    RoleGrant.objects.create(person=p, role=role, country=grant_country)
    return p


def test_staff_find_people_with_only_safe_fields(seeded, api, people):
    """Staff search by part of a name; each row has id, name, roles and a masked email, nothing else."""
    r = api(people["cm"]).get("/v1/people", {"search": "lawy"})
    assert r.status_code == 200, r.content
    rows = r.json()["items"]
    row = next(x for x in rows if x["id"] == str(people["lawyer"].pk))
    assert set(row) == {"id", "name", "roles", "email_masked"}
    assert row["name"] == "Nana Lawyer" and "LW" in row["roles"]
    assert row["email_masked"] == "l***@example.com" and "lawyer@example.com" not in str(r.json())
    assert mask_email("ama.mensah@example.com") == "a***@example.com" and mask_email("") == ""


def test_role_filter_and_country_scope(seeded, api, people):
    """?role= keeps only people holding it; a Ghana case manager never sees someone who neither lives nor works in
    Ghana; an administrator for every country does."""
    gh, ng = seeded["gh"], seeded["ng"]
    abroad = _person(ng, "Chidi Okafor", role="SV", grant_country=ng)
    ghana_cm = _person(gh, "Dede Case Manager", role="CM", grant_country=gh)
    cm = api(ghana_cm)
    rows = cm.get("/v1/people", {"search": "o", "role": "SV"})
    assert rows.status_code == 422  # one character is not enough
    rows = cm.get("/v1/people", {"search": "ok", "role": "SV"}).json()["items"]
    assert all("SV" in x["roles"] for x in rows)
    assert str(people["surveyor"].pk) not in {x["id"] for x in cm.get("/v1/people", {"search": "kojo",
                                                                                     "role": "LW"}).json()["items"]}
    assert str(abroad.pk) not in {x["id"] for x in cm.get("/v1/people", {"search": "chidi"}).json()["items"]}
    assert str(people["lawyer"].pk) in {x["id"] for x in cm.get("/v1/people", {"search": "nana"}).json()["items"]}
    everywhere = api(people["admin"])  # the seeded administrator works in every country
    assert str(abroad.pk) in {x["id"] for x in everywhere.get("/v1/people", {"search": "chidi"}).json()["items"]}
    row = next(x for x in everywhere.get("/v1/people", {"search": "chidi"}).json()["items"])
    assert row["roles"] == ["SV"]


def test_people_search_refusals(seeded, api, people):
    """Only CM, RV and AD; at least 2 characters; an unknown role is refused."""
    for who in ("client", "lawyer", "carer"):
        assert api(people[who]).get("/v1/people", {"search": "ama"}).status_code == 403
    cm = api(people["cm"])
    r = cm.get("/v1/people", {"search": " a "})
    assert r.status_code == 422 and r.json()["code"] == "search-too-short"
    assert cm.get("/v1/people").status_code == 422
    assert cm.get("/v1/people", {"search": "ama", "role": "XX"}).status_code == 422


def test_people_search_is_audited_and_rate_limited(seeded, api, people):
    """FR-AUD-003: each search is in the audit log with the term and how many came back; more than the rate
    [TO VERIFY] in a minute is refused with 429."""
    rv = api(people["reviewer"])
    assert rv.get("/v1/people", {"search": "esi"}).status_code == 200
    a = AuditEvent.objects.filter(action="people.searched", actor_id=people["reviewer"].pk).last()
    assert a.data["search"] == "esi" and a.data["results"] >= 1
    codes = [rv.get("/v1/people", {"search": "esi"}).status_code for _ in range(35)]
    assert 429 in codes


def test_professional_carer_and_agent_lists_take_search(seeded, api, people):
    """Picker lists in their modules: ?search= by name, at least 2 characters."""
    cm = api(people["cm"])
    for url, hit in (("/v1/panel-members", "Kobby"), ("/v1/carers", "Afia"), ("/v1/errand-agents", "Bonsu")):
        r = cm.get(url, {"search": hit.lower()})
        assert r.status_code == 200, (url, r.content)
        items = r.json()["items"]
        assert items, url
        miss = cm.get(url, {"search": "zzqq-nobody"}).json()["items"]
        assert miss == [], url
        assert cm.get(url, {"search": "k"}).status_code == 422, url
