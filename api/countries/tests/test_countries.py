import base64
from datetime import date

import pytest
from django.db import connection, transaction

from accounts.models import RoleGrant
from administration import flags
from administration.models import ConfigVersion, LockedTextVersion, Partner
from audit import context
from audit.models import AuditEvent, SecurityAlert
from core.errors import NotFound
from countries import selectors, services
from countries.models import Country, CountryConfig, DirectoryEntry


@pytest.fixture
def admins(seeded, api, mfa):
    p = seeded["people"]
    a, b = api(p["admin"]), api(p["admin2"])
    mfa(a, p["admin"])
    mfa(b, p["admin2"])
    return a, b


def _doc():
    return base64.b64encode(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n").decode()


def _open_country(a, b, code="KE", name="Kenya", currency="KES"):
    """Create a country by copying Ghana and make its configuration publishable."""
    r = a.post("/v1/admin/countries", {"code": code, "name": name, "currency": currency, "cell": "gh-1",
                                       "timezone": "Africa/Nairobi"}, format="json")
    assert r.status_code == 201, r.content
    r = a.post(f"/v1/admin/countries/{code}/config-versions", {"copy_from": "GH"}, format="json")
    assert r.status_code == 201, r.content
    return r.json()


def test_public_list_shows_active_countries_only(seeded, api):
    """FR-CTY-001: clients choose among active countries."""
    codes = [c["code"] for c in api().get("/v1/countries").json()]
    assert codes == ["GH"]


def test_copy_makes_drafts_and_never_points_at_ghana(seeded, admins, gh):
    """FR-CTY-004, TC-CTY-004-01 and 03: every item copied as a draft for the new country; no partners or bank details."""
    a, _ = admins
    cfg = _open_country(a, *admins[1:])
    data = cfg["data"]
    assert cfg["status"] == "draft" and data["currency"] is None and data["data_location"] is None
    assert data["copied_from"]["country"] == "GH" and data["refs"]["partners"] == {}
    ke = Country.objects.get(code="KE")
    for kind, pk in data["refs"]["config_versions"].items():
        cv = ConfigVersion.objects.get(pk=pk)
        assert cv.country_id == ke.pk and cv.state == "draft" and cv.copied_from.country_id == gh.pk
    for kind, pk in data["refs"]["locked_texts"].items():
        lt = LockedTextVersion.objects.get(pk=pk)
        assert lt.country_id == ke.pk and lt.status == "draft" and lt.lawyer_approval_evidence_id is None
    assert not Partner.objects.filter(country=ke).exists()
    assert AuditEvent.objects.filter(action="country_config.copied", country_code="KE").exists()
    assert ke.status == "draft" and not flags.enabled("lines.fee", ke)


def test_publication_refused_until_currency_location_and_texts_are_set(seeded, admins):
    """US-CTY-001a criterion 3, US-CTY-004 criterion 1: the copy cannot be published yet."""
    a, _ = admins
    cfg = _open_country(a, *admins[1:])
    r = a.post(f"/v1/admin/countries/KE/config-versions/{cfg['version']}/submit")
    assert r.status_code == 409 and r.json()["code"] == "config-incomplete"
    rules = {b["rule"] for b in r.json()["blocking_reasons"]}
    assert {"FR-CTY-001", "FR-CTY-002", "FR-ADM-004", "FR-ADM-001"} <= rules


def test_mixing_countries_is_refused(seeded, admins, gh):
    """TC-CTY-001-02: a configuration that uses Ghana's scope text is refused."""
    a, _ = admins
    cfg = _open_country(a, *admins[1:])
    data = dict(cfg["data"], currency="KES", data_location="af-south-1 [TO VERIFY]")
    data["refs"]["locked_texts"]["scope_statement"] = selectors.ref(gh, "locked_texts", "scope_statement")
    a.patch(f"/v1/admin/countries/KE/config-versions/{cfg['version']}", {"data": data}, format="json")
    r = a.post(f"/v1/admin/countries/KE/config-versions/{cfg['version']}/submit")
    assert "belongs to another country" in str(r.json()["blocking_reasons"])


def _make_publishable(a, b, cfg):
    data = dict(cfg["data"], currency="KES", data_location="af-south-1, shared cell [TO VERIFY]")
    for pk in dict.fromkeys(data["refs"]["config_versions"].values()):  # a version two keys name is one copy
        assert a.post(f"/v1/admin/config-versions/{pk}/publish").status_code == 200
    for kind, pk in data["refs"]["locked_texts"].items():
        base = f"/v1/admin/locked-texts/{kind}/versions/{pk}"
        for party in ("lawyer", "insurer"):
            _s = a.post(f"{base}/signoffs", {"party": party, "approved_by_name": "Kenyan counsel",
                                             "document_base64": _doc()}, format="json")
            assert _s.status_code < 300, _s.json()
        _s = a.post(f"{base}/submit")
        assert _s.status_code < 300, _s.json()
        _r = b.post(f"{base}/approvals", {}, format="json"); assert _r.json().get("status") == "published", _r.json()
    r = a.patch(f"/v1/admin/countries/KE/config-versions/{cfg['version']}", {"data": data}, format="json")
    assert r.status_code == 200 and r.json()["publication_blockers"] == []


def test_open_a_new_country_end_to_end(seeded, admins, people):
    """FR-CTY-004, TC-CTY-004-02, J: copy, edit, publish with two admins, record the gate, activate with two admins."""
    a, b = admins
    cfg = _open_country(a, b)
    _make_publishable(a, b, cfg)
    v = cfg["version"]
    assert a.post(f"/v1/admin/countries/KE/config-versions/{v}/submit").json()["status"] == "open"
    r = a.post(f"/v1/admin/countries/KE/config-versions/{v}/approvals", {}, format="json")
    assert r.json()["code"] == "same-approver"
    r = b.post(f"/v1/admin/countries/KE/config-versions/{v}/approvals", {}, format="json")
    assert r.json()["status"] == "published"
    assert selectors.config("KE", "currency") == "KES"
    ke = Country.objects.get(code="KE")
    with pytest.raises(Exception), transaction.atomic():
        CountryConfig.objects.filter(country=ke, version=v).update(data={"tampered": True})

    # activation: blocked without the manual phase and the gate decision
    r = a.post("/v1/admin/countries/KE/activation")
    assert r.status_code == 409 and r.json()["code"] == "country-not-ready"
    a.patch("/v1/admin/countries/KE", {"data_location": "af-south-1, shared cell [TO VERIFY]"}, format="json")
    a.post("/v1/admin/countries/KE/manual-phase", {}, format="json")
    a.post("/v1/admin/countries/KE/validation", {}, format="json")
    r = a.post("/v1/admin/countries/KE/activation")
    assert "No recorded gate decision" in str(r.json()["blocking_reasons"])
    a.post("/v1/admin/countries/KE/gate-decision", {"passed": True, "note": "Day-90 gate passed [TO VERIFY]"},
           format="json")
    assert a.post("/v1/admin/countries/KE/activation").json()["status"] == "open"
    assert a.post("/v1/admin/countries/KE/activation/approvals", {}, format="json").json()["code"] == "same-approver"
    r = b.post("/v1/admin/countries/KE/activation/approvals", {}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert flags.enabled("country.ke")
    assert not flags.enabled("lines.fee", "KE") and flags.enabled("lines.fee", "GH")  # every line starts off
    assert SecurityAlert.objects.filter(kind="country.activated").exists()
    assert SecurityAlert.objects.filter(kind="country_config.published").exists()


def test_database_refuses_activation_without_two_admins(seeded):
    """ADR-16: an active country has an approved activation, enforced in the database."""
    ng = Country.objects.get(code="NG")
    with connection.cursor() as c:
        c.execute("UPDATE cty_country SET status = 'manual_phase' WHERE id = %s", [ng.pk])
    with pytest.raises(Exception), transaction.atomic():
        with connection.cursor() as c:
            c.execute("UPDATE cty_country SET status = 'active' WHERE id = %s", [ng.pk])


def test_data_location_changes_are_logged(seeded, admins):
    """US-CTY-002b criterion 1: the register updates and the change is logged."""
    a, _ = admins
    r = a.patch("/v1/admin/countries/NG", {"data_location": "Lagos, own cell [TO VERIFY]"}, format="json")
    assert r.status_code == 200
    e = AuditEvent.objects.filter(action="country.data_location_changed", country_code="NG").last()
    assert e.data["changes"]["data_location"]["new"] == "Lagos, own cell [TO VERIFY]"
    rows = {r["country"]: r for r in a.get("/v1/admin/data-locations").json()}
    assert rows["NG"]["data_location"] == "Lagos, own cell [TO VERIFY]" and rows["GH"]["region"] == "af-south-1"


def test_cells_and_directory_routing(seeded, admins, api):
    """ADR-16: a new cell is logged; sign-ins route by blind index without revealing accounts."""
    a, _ = admins
    r = a.post("/v1/admin/cells", {"name": "ng-1", "aws_region": "eu-west-1", "api_host": "api.ng.example"},
               format="json")
    assert r.status_code == 201
    ng = Country.objects.get(code="NG")
    a.patch("/v1/admin/countries/NG", {"cell": "ng-1"}, format="json")
    from accounts.services import register

    register(email="bola@example.com", password="a-long-password-1", full_name="Bola", home_country="NG", phone="+2348012345678", legacy=True)
    entry = DirectoryEntry.objects.get(kind="signin", key=services.blind_index("bola@example.com"))
    assert entry.cell.name == "ng-1" and entry.country_id == ng.pk
    assert "bola" not in entry.key
    c = api()
    assert c.post("/v1/directory/lookups", {"signin": "Bola@example.com"}, format="json").json()["cell"] == "ng-1"
    assert c.post("/v1/directory/lookups", {"signin": "nobody@example.com"}, format="json").json()["cell"] == "gh-1"
    ng.refresh_from_db()
    services.register_reference_prefix("TMR-NG-", ng)
    assert c.post("/v1/directory/lookups", {"reference": "TMR-NG-2027-00042"}, format="json").json()["cell"] == "ng-1"
    assert SecurityAlert.objects.filter(kind="cell.deployed").exists()


def test_metrics_split_by_country_and_scoped_viewer(seeded, api, people, gh):
    """FR-CTY-003, TC-CTY-003-01: every count splits by country; a Ghana-scoped viewer sees Ghana only."""
    rows = {r["country"]: r for r in api(people["admin"]).get("/v1/countries/metrics").json()}
    assert set(rows) >= {"GH", "NG"}
    assert rows["GH"]["counts"]["adm_partner"] > 0 and rows["GH"]["counts"]["people"] > 0
    assert "adm_partner" not in rows["NG"]["counts"]
    cm = people["cm"]
    RoleGrant.objects.filter(person=cm).update(country=gh)
    rows = api(cm).get("/v1/countries/metrics").json()
    assert [r["country"] for r in rows] == ["GH"]
    assert api(people["client"]).get("/v1/countries/metrics").status_code == 403


def test_cross_country_access_refused_and_logged(seeded, people, gh):
    """US-CTY-001b criterion 2: a Ghana-scoped case manager asking for Nigeria work gets not-found, and it is logged."""
    cm = people["cm"]
    RoleGrant.objects.filter(person=cm).update(country=gh)
    services.check_access(cm, gh, "CM")
    context.on_request_started(None, environ={"REMOTE_ADDR": "10.1.1.1"})
    with pytest.raises(NotFound), transaction.atomic():
        services.check_access(cm, seeded["ng"], "CM", entity="case", entity_id="ng-case-1")
    context.on_request_finished(None)
    assert AuditEvent.objects.filter(action="security.access.cross_country_refused", entity_id="ng-case-1").exists()


def test_working_days_use_the_country_calendar(seeded, gh):
    """FR-CTY-001: holidays come from configuration. 6 March 2026 is Independence Day in the Ghana seed."""
    assert not selectors.is_working_day(gh, date(2026, 3, 6))
    assert selectors.add_working_days(gh, date(2026, 3, 5), 1) == date(2026, 3, 9)
    assert selectors.working_days_between(gh, date(2026, 11, 13), date(2026, 11, 17)) == 2  # Fri to Tue


def test_pause_one_admin_resume_needs_activation(seeded, admins, people, gh):
    """Stopping is safe with one person; reopening needs two administrators again."""
    a, b = admins
    assert a.post("/v1/admin/countries/GH/pause", {"reason": "Incident drill"}, format="json").json()[
        "status"] == "paused"
    assert a.post("/v1/admin/countries/GH/activation").json()["status"] == "open"
    assert b.post("/v1/admin/countries/GH/activation/approvals", {}, format="json").json()["status"] == "active"
    assert flags.enabled("lines.fee", "GH")  # a resumed country keeps its lines


def test_seeds_are_idempotent(seeded):
    """Seeds use get_or_create and guards: a second run adds nothing."""
    import importlib

    from administration.models import ChangeRequest
    from notifications.models import ConfirmationCode, Message

    def counts():
        return (CountryConfig.objects.count(), ChangeRequest.objects.count(), Message.objects.count(),
                ConfirmationCode.objects.count(), LockedTextVersion.objects.count())

    before = counts()
    for name in ("countries", "administration", "notifications"):
        importlib.import_module(f"{name}.seed").run(seeded)
    assert counts() == before
