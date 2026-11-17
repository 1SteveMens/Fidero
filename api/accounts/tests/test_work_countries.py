"""GET /v1/me work_countries: the countries a staff member works in, from their
role grants, with each country's currency (FR-CTY-001: country is configuration). The
back office takes the country and currency for its forms from here."""
from django.utils import timezone

from accounts.models import RoleGrant
from countries.models import Country


def _ng():
    ng, _ = Country.objects.get_or_create(code="NG", defaults={"name": "Nigeria", "currency": "NGN"})
    return ng


def test_grant_for_every_country_lists_countries_past_draft(seeded, api, people, gh):
    ng = _ng()
    Country.objects.filter(pk=ng.pk).update(status="draft")
    cm = people["cm"]
    cm.role_grants.update(country=None)
    rows = api(cm).get("/v1/me").json()["work_countries"]
    assert {"code": "GH", "name": gh.name, "currency": gh.currency} in rows
    assert "NG" not in [r["code"] for r in rows]


def test_country_grants_list_those_countries_home_first(seeded, api, people, gh):
    ng = _ng()
    cm = people["cm"]
    cm.role_grants.filter(role="CM").update(country=gh)
    RoleGrant.objects.create(person=cm, role="CM", country=ng)
    cm.role_grants.filter(country__isnull=True).update(revoked_at=timezone.now())
    cm.home_country = ng
    cm.save(update_fields=["home_country"])
    rows = api(cm).get("/v1/me").json()["work_countries"]
    assert [r["code"] for r in rows] == ["NG", "GH"]
    assert rows[0]["currency"] == "NGN"


def test_clients_have_no_work_countries(seeded, api, people):
    assert api(people["client"]).get("/v1/me").json()["work_countries"] == []
