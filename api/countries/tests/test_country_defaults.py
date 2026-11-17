"""Country is configuration (CLAUDE.md, FR-CTY-001): no API default names a country. When the caller names none,
the only active country is used; with several active, the field is required (a validation error)."""
import pytest

from accounts.models import Person
from administration import flags
from countries.models import Country
from countries.selectors import country_of_person, country_or_default
from core.errors import Invalid

SIGNUP = {"email": "yaw@example.com", "password": "a-long-password-1", "full_name": "Yaw Boateng",
          "phone": "+447700900777", "residence_country": "GB", "privacy_notice_version": "1.0"}


def _activate(code):
    """Activate a second country as two administrators would (the database checks the approval and config)."""
    from core.models import ApprovalRequest

    c = Country.objects.get(code=code)
    admin = Person.objects.get(email="admin@tenmina.test")
    req = ApprovalRequest.objects.create(subject_type="country_activation", subject_id=c.pk, prepared_by=admin,
                                         required=1, status="approved")
    Country.objects.filter(pk=c.pk).update(current_config=c.configs.first(), activation_request=req)
    for status in ("manual_phase", "validating", "active"):
        Country.objects.filter(pk=c.pk).update(status=status)


@pytest.fixture
def two_active(seeded):
    _activate("NG")
    return Country.objects.get(code="NG")


def test_one_active_country_is_the_default(seeded, gh):
    """FR-CTY-001: with one active country, a request that names none gets that country."""
    assert list(Country.objects.filter(status="active")) == [gh]
    assert country_or_default(None) == gh
    assert country_or_default("ng") == seeded["ng"]
    assert country_or_default("ZZ") is None
    staff = Person.objects.create_user("no.home@example.com", "a-long-password-1", full_name="No Home")
    assert country_of_person(staff) == gh


def test_two_active_countries_require_the_field(two_active, gh):
    """FR-CTY-001: with two active countries nothing is guessed."""
    with pytest.raises(Invalid) as exc:
        country_or_default(None, field="home_country")
    assert exc.value.extra["errors"][0]["pointer"] == "/home_country"
    assert country_or_default("GH") == gh
    staff = Person.objects.create_user("no.home@example.com", "a-long-password-1", full_name="No Home")
    with pytest.raises(Invalid):
        country_of_person(staff)
    staff.home_country = two_active
    assert country_of_person(staff) == two_active


def test_signup_takes_the_only_active_country(seeded, api, gh):
    """FR-ACC-001: sign-up with no home country, one active country: the account is in that country."""
    r = api().post("/v1/auth/signup", SIGNUP)
    assert r.status_code == 201, r.content
    assert Person.objects.get(email="yaw@example.com").home_country == gh


def test_signup_needs_the_country_when_several_are_active(two_active, api, gh):
    """FR-ACC-001: two active countries and no home country: refused with a clear error on the field."""
    r = api().post("/v1/auth/signup", SIGNUP)
    assert r.status_code == 422, r.content
    body = r.json()
    assert body["code"] == "validation-error"
    assert body["errors"] == [{"pointer": "/home_country", "message": body["detail"]}]
    assert not Person.objects.filter(email="yaw@example.com").exists()
    r = api().post("/v1/auth/signup", dict(SIGNUP, home_country="GH"))
    assert r.status_code == 201, r.content
    assert Person.objects.get(email="yaw@example.com").home_country == gh


def test_recheck_draw_country(seeded, api, people, gh, two_active):
    """RUL-32: a re-check draw is for a country. Several active countries and none named: required."""
    rv = api(people["reviewer2"])
    r = rv.post("/v1/rechecks/draws", {"month": "2031-02-01"}, format="json")
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/country"
    r = rv.get("/v1/rechecks", {"month": "2031-02"})
    assert r.status_code == 422
    Country.objects.filter(pk=two_active.pk).update(status="paused")
    r = rv.post("/v1/rechecks/draws", {"month": "2031-02-01"}, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["country"] == gh.code or str(r.json()["country"]) == str(gh.pk)


def test_privacy_notice_and_insurance_line_without_a_country(seeded, api, gh, people):
    """FR-DPR-001, FR-INS-001: public reads with no country use the only active country, else ask for it."""
    assert api().get("/v1/privacy-notices/current").status_code == 200
    assert api(people["client"]).get("/v1/insurance/products/line-status").status_code in (200, 404)
    _activate("NG")
    r = api().get("/v1/privacy-notices/current")
    assert r.status_code == 422 and r.json()["errors"][0]["pointer"] == "/country"
    assert api().get("/v1/privacy-notices/current", {"country": "GH"}).status_code == 200


def test_country_flag_opens_an_active_country_only(seeded, gh):
    """06 2.6: an active country needs no country flag; a draft one needs its `country.<code>` flag."""
    assert flags.enabled("lines.fee", gh)
    assert not flags.enabled("lines.fee", seeded["ng"])
