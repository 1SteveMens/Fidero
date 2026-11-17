"""Country is configuration (DA-09): screens take a country's name, currency and wording from the API, never from
code. GET /v1/countries gives the wording; GET /v1/me gives the countries a person works in."""


def test_public_countries_carry_their_own_wording(seeded, api):
    r = api().get("/v1/countries")
    assert r.status_code == 200
    gh = next(c for c in r.json() if c["code"] == "GH")
    assert gh["currency"] == "GHS" and gh["phone_prefix"]
    assert gh["digital_address"]["name"] and gh["digital_address"]["example"]
    assert gh["national_id_name"] and gh["land_registry_name"]


def test_me_names_the_countries_a_person_works_in(seeded, api, people):
    staff = api(people["cm"]).get("/v1/me").json()["work_countries"]
    codes = [c["code"] for c in staff]
    # The seeded case manager's grant names no country: every configured country, the home country first.
    assert codes[0] == "GH" and "NG" in codes
    ng = next(c for c in staff if c["code"] == "NG")
    assert ng["currency"] == "NGN" and ng["name"] == "Nigeria"
    client = api(people["client"]).get("/v1/me").json()["work_countries"]
    assert [c["code"] for c in client] == ["GH"]


def test_a_staff_grant_for_one_country_lists_only_that_country(seeded, api, people):
    from accounts.models import RoleGrant

    p = people["qs"]
    RoleGrant.objects.filter(person=p).exclude(role="CL").update(country=seeded["ng"])
    assert [c["code"] for c in api(p).get("/v1/me").json()["work_countries"]] == ["NG"]


def test_inbox_items_carry_the_country_currency(seeded, api, people):
    items = api(people["carer"]).get("/v1/mobile/inbox").json()
    assert items and all(i["currency"] == "GHS" for i in items if i["country"] == "GH")
