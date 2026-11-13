import base64
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone

from administration import appversion, flags, selectors, services
from administration.models import (
    AppVersion, ChangeRequest, ConfigVersion, FeatureFlag, LockedTextVersion, Partner, Price, Setting,
)
from audit.models import AuditEvent, SecurityAlert
from core.errors import FeatureOff, Forbidden, Invalid, RuleBlocked, SameApprover, StateConflict


@pytest.fixture
def admins(seeded, api, mfa):
    p = seeded["people"]
    a, b = api(p["admin"]), api(p["admin2"])
    mfa(a, p["admin"])
    mfa(b, p["admin2"])
    return a, b


def _sql_fails(sql, params=()):
    with pytest.raises(Exception), transaction.atomic():
        with connection.cursor() as c:
            c.execute(sql, params)


# --- FR-ADM-001 versioned configuration ------------------------------------------

def test_publish_creates_new_version_and_keeps_old(seeded, admins, gh):
    """FR-ADM-001, TC-ADM-001-01: a new version is created on publish and the old one kept."""
    a, _ = admins
    old = selectors.current_config("case_template", gh, "land")
    content = {"tasks": [{"key": "intake", "title": "Intake", "role": "CM", "due_days": 1, "evidence": []},
                         {"key": "visit", "title": "Site visit", "role": "RN", "due_days": 5,
                          "evidence": ["site_photo"], "after": ["intake"], "site_visit": True}]}
    r = a.post("/v1/admin/config-versions", {"kind": "case_template", "country": "GH", "product_line": "land",
                                             "content": content}, format="json")
    assert r.status_code == 201, r.content
    new_id = r.json()["id"]
    assert selectors.current_config("case_template", gh, "land").pk == old.pk  # a draft is not used
    assert a.post(f"/v1/admin/config-versions/{new_id}/publish").status_code == 200
    cur = selectors.current_config("case_template", gh, "land")
    assert str(cur.pk) == new_id and cur.version > old.version
    old.refresh_from_db()
    assert old.state == "retired" and old.content["tasks"]  # kept, not deleted


def test_published_version_cannot_be_edited(seeded, admins, gh):
    """FR-ADM-001, TC-ADM-001-02: editing v1 in place is refused, by the API and by the database."""
    a, _ = admins
    cv = selectors.current_config("report_template", gh, "land")
    r = a.patch(f"/v1/admin/config-versions/{cv.pk}", {"content": {"sections": [{"key": "x", "title": "X"}]}},
                format="json")
    assert r.status_code == 409 and r.json()["code"] == "config-published"
    _sql_fails("UPDATE adm_config_version SET content = '{}' WHERE id = %s", [cv.pk])


def test_publish_runs_the_owning_modules_rules(seeded, admins, people, gh):
    """FR-ADM-001, TC-CASE-002-02, TC-RPT-001-02, TC-TSK-001-02: a case template without owner roles or
    evidence lists, a report template without sections 1 to 14, or an incomplete errand catalogue is refused
    at publication (cases.templates, reports.templates, errands.catalogue)."""
    a, _ = admins
    bad = {
        "case_template": {"tasks": [{"key": "intake", "title": "Intake"}]},
        "report_template": {"sections": [{"key": "summary", "title": "Summary"}]},
        "errand_catalogue": {"errands": [{"code": "probate", "name": "Probate"}]},
    }
    for kind, content in bad.items():
        cv = services.create_config_version(kind=kind, content=content, by=people["admin"], country=gh,
                                            product_line="land")
        r = a.post(f"/v1/admin/config-versions/{cv.pk}/publish")
        assert r.status_code == 422 and r.json()["code"] == "config-invalid", (kind, r.content)
        cv.refresh_from_db()
        assert cv.state == "draft"


def test_country_config_naming_an_invalid_template_is_refused(seeded, people, gh):
    """FR-CTY-001, FR-ADM-001: a country configuration is published only when every template it names passes
    its module's rules, and its errand catalogue is complete."""
    from administration.models import ConfigVersion
    from countries import services as cty
    from core.errors import RuleBlocked

    bad = ConfigVersion.objects.create(kind="case_template", country=gh, product_line="vendor_verification",
                                       version=99, content={"tasks": [{"key": "x", "title": "X"}]},
                                       content_sha256="0" * 64, state="published")
    draft = cty.create_config(gh, by=people["admin"])
    refs = dict(draft.data["refs"], config_versions={**draft.data["refs"]["config_versions"],
                                                     "case_template:vendor_verification": str(bad.pk)})
    cty.update_config(draft, by=people["admin"], data={**draft.data, "refs": refs,
                                                      "errand_catalogue": [{"code": "probate", "name": "Probate"}]})
    with pytest.raises(RuleBlocked) as ei:
        cty.submit_config(draft, by=people["admin"])
    messages = " ".join(r["message"] for r in ei.value.blocking_reasons)
    assert "case template:vendor verification is not valid" in messages and "errand catalogue" in messages


def test_country_config_keys_are_settings_to_verify(seeded, people, gh):
    """FR-ADM-005, 06 2.6: the keys line modules read from the country configuration are in the settings registry,
    marked [TO VERIFY]; an administrator's value is used where the configuration sets none."""
    from administration import registry
    from countries.selectors import config

    keys = ["fees.payment_route", "fees.service_fee", "fees.term_months", "construction.payment_route",
            "pmg.repair_single_quote_max_amount", "pmg.inspection_interval_months", "evt.deposit_share_pct",
            "insurance.renewal_reminder_days", "insurance.premium_lead_days",
            "insurance.intermediary_licence_required"]
    for k in keys:
        assert registry.REGISTRY[k].to_verify, k
    assert config(gh, "fees.term_months", 4) == 4
    services.change_setting(key="fees.term_months", value=3, by=people["admin"], country=gh)
    assert config(gh, "fees.term_months", 4) == 3
    with pytest.raises(Invalid):
        services.change_setting(key="fees.term_months", value=40, by=people["admin"], country=gh)
    assert registry.validate("insurance.intermediary_licence_required", "false") is False
    _, cr = services.change_setting(key="fees.payment_route", value="held_funds", by=people["admin"], country=gh)
    assert cr is not None and config(gh, "fees.payment_route", "client_direct") == "client_direct"  # waits


def test_records_flag_and_locked_statements(seeded, gh):
    """06 2.6: `records.enabled` is a safety flag; RUL-25 and FR-PRJ-005 statements are locked texts that INS and
    PRJ read."""
    from administration.models import SAFETY_FLAGS_PREFIXES, FeatureFlag, LockedTextVersion
    from insurance.models import Product
    from insurance.services import statement_for
    from projectfunds.services import no_advice_statement

    assert FeatureFlag.objects.filter(name="records.enabled").exists()
    assert "records.enabled".startswith(SAFETY_FLAGS_PREFIXES)
    assert {"insurance_statement", "no_advice_statement"} <= set(LockedTextVersion.KINDS)
    ins = selectors.current_locked_text("insurance_statement", gh)
    nad = selectors.current_locked_text("no_advice_statement", gh)
    assert ins and nad and nad.text == no_advice_statement(gh)
    product = Product.objects.filter(country=gh).first()
    if product is not None:
        assert statement_for(product) == ins.text.replace("{insurer}", product.insurer.name)


def test_config_content_is_checked(seeded, people, gh):
    """FR-ADM-001: a milestone schedule must add up to 100."""
    with pytest.raises(Invalid):
        services.create_config_version(kind="milestone_schedule", by=people["admin"], country=gh,
                                       content={"milestones": [{"key": "a", "name": "A", "share_pct": 60}]})


# --- FR-ADM-002 prices and guide rates ----------------------------------------------

def test_new_price_for_new_orders_old_orders_keep_theirs(seeded, admins, gh):
    """FR-ADM-002, TC-ADM-002-01: a price change closes the old row; the quoted row is unchanged."""
    a, _ = admins
    quoted = selectors.current_price(gh, "premium")
    r = a.put("/v1/admin/prices", {"country": "GH", "items": [
        {"tier": "premium", "price": {"amount": "700.00", "currency": "USD"}}]}, format="json")
    assert r.status_code == 200, r.content
    assert r.json()[0]["price"] == {"amount": "700.00", "currency": "USD"}
    assert selectors.current_price(gh, "premium").price_amount == 700
    quoted.refresh_from_db()
    assert quoted.price_amount == 650 and quoted.valid_to is not None
    assert AuditEvent.objects.filter(action="price.changed", data__old__amount="650.00").exists()
    _sql_fails("UPDATE adm_price SET price_amount = 1 WHERE id = %s", [quoted.pk])


def test_negative_price_and_zero_rate_refused(seeded, admins):
    """FR-ADM-002, TC-ADM-002-02."""
    a, _ = admins
    r = a.put("/v1/admin/prices", {"country": "GH", "items": [
        {"tier": "basic", "price": {"amount": "-1.00", "currency": "USD"}}]}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "price-invalid"
    r = a.put("/v1/admin/fx-rates", {"country": "GH", "base_currency": "USD", "quote_currency": "GHS", "rate": "0"},
              format="json")
    assert r.status_code == 422 and r.json()["code"] == "fx-rate-invalid"


def test_guide_rate_shows_its_date(seeded, admins, api):
    """US-ADM-002 criterion 2: the guide rate is shown with its date; it is public and not a quote."""
    a, _ = admins
    a.put("/v1/admin/fx-rates", {"country": "GH", "base_currency": "EUR", "quote_currency": "GHS", "rate": "16.90",
                                 "rate_date": "2026-11-10"}, format="json")
    r = api().get("/v1/fx-guides", {"country": "GH"})
    eur = next(g for g in r.json() if g["base_currency"] == "EUR")
    assert eur["rate_date"] == "2026-11-10" and "Not a quote" in eur["note"]


# --- FR-ADM-003 partners --------------------------------------------------------------

def test_partner_kinds_created_with_status(seeded, admins):
    """FR-ADM-003, TC-ADM-003-01."""
    a, _ = admins
    for kind in ("escrow_bank", "professional", "contractor", "inspector", "supplier", "api_partner"):
        r = a.post("/v1/admin/partners", {"country": "GH", "kind": kind, "name": f"New {kind}"}, format="json")
        assert r.status_code == 201 and r.json()["status"] == "active"


def test_bank_change_needs_second_admin_old_details_used_until_then(seeded, admins, people):
    """FR-ADM-003, TC-ADM-003-02 and 03: pending until B approves; A or a case manager cannot approve."""
    a, b = admins
    bank = Partner.objects.get(kind="escrow_bank", country__code="GH")
    old_number = bank.account_number
    r = a.post(f"/v1/admin/partners/{bank.pk}/bank-changes", {
        "bank_name": "Partner Bank", "account_name": "Partner Bank Escrow Programme",
        "account_number": "9040007777777"}, format="json")
    assert r.status_code == 201
    cr_id = r.json()["id"]
    bank.refresh_from_db()
    assert bank.account_number == old_number
    r = a.post(f"/v1/admin/change-requests/{cr_id}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    assert a.get(f"/v1/admin/partners/{bank.pk}").json()["pending_bank_change"] == cr_id
    r = b.post(f"/v1/admin/change-requests/{cr_id}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "applied"
    bank.refresh_from_db()
    assert bank.account_number == "9040007777777"
    ev = AuditEvent.objects.filter(action="security.partner_bank.changed", entity_id=str(bank.pk)).last()
    assert ev.data["requested_by"] == str(people["admin"].pk)
    assert ev.data["approved_by"] == [str(people["admin2"].pk)]
    assert SecurityAlert.objects.filter(kind="partner_bank.changed", channel="founder").exists()


def test_case_manager_cannot_approve_bank_change_even_by_the_generic_endpoint(seeded, admins, api, mfa, people):
    """TC-ADM-003-03: the change stays pending; an approval by a non-administrator is not applied."""
    a, _ = admins
    p = Partner.objects.get(kind="payment_provider", country__code="GH")
    cr = services.request_bank_change(p, by=people["admin"], bank_name="B", account_name="Provider",
                                      account_number="5550001112")
    cm = api(people["cm"])
    mfa(cm, people["cm"])
    assert cm.post(f"/v1/admin/change-requests/{cr.pk}/approvals", {}, format="json").status_code == 403
    r = cm.post(f"/v1/approvals/{cr.approval_request_id}/decisions", {"decision": "approve"}, format="json")
    assert r.status_code == 200
    cr.refresh_from_db()
    p.refresh_from_db()
    assert cr.status == "rejected" and p.account_number == ""


def test_plain_partner_fields_need_one_admin_and_are_audited(seeded, admins):
    """TC-ADM-003-04: a supplier's phone number is applied at once, with old and new values audited."""
    a, _ = admins
    p = Partner.objects.get(kind="identity", country__code="GH")
    r = a.patch(f"/v1/admin/partners/{p.pk}", {"contact_phone": "+233302000000"}, format="json")
    assert r.status_code == 200 and r.json()["contact_phone"] == "+233302000000"
    assert AuditEvent.objects.filter(action="partner.updated", entity_id=str(p.pk),
                                     data__changes__contact_phone__new="+233302000000").exists()
    r = a.patch(f"/v1/admin/partners/{p.pk}", {"account_number": "123"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "bank-change-needs-approval"


def test_database_refuses_bank_details_without_approval(seeded):
    """FR-ADM-003 enforced twice: a direct update of bank details is refused."""
    p = Partner.objects.get(kind="escrow_bank", country__code="GH")
    _sql_fails("UPDATE adm_partner SET account_number = '1' WHERE id = %s", [p.pk])


def test_deactivated_partner_cannot_be_assigned(seeded, admins):
    """US-ADM-003: deactivation is logged and the partner cannot be assigned."""
    a, _ = admins
    p = Partner.objects.get(kind="inspector", country__code="GH")
    assert a.post(f"/v1/admin/partners/{p.pk}/deactivate", {"reason": "Licence lapsed"},
                  format="json").json()["status"] == "inactive"
    with pytest.raises(StateConflict):
        selectors.assignable_partner(p.pk)
    assert AuditEvent.objects.filter(action="partner.inactive", entity_id=str(p.pk)).exists()
    a.post(f"/v1/admin/partners/{p.pk}/reactivate", {}, format="json")
    assert selectors.assignable_partner(p.pk).pk == p.pk


def test_operating_account_can_never_be_an_escrow_account(seeded, people):
    """ADR-23, RUL-27: an operating account matching the escrow account is refused."""
    op = Partner.objects.get(kind="operating_bank", country__code="GH")
    ChangeRequest.objects.filter(target=str(op.pk), status="pending").update(status="withdrawn")
    with pytest.raises(RuleBlocked):
        services.request_bank_change(op, by=people["admin"], bank_name="X", account_name="Tenmina",
                                     account_number="9040001234567")


# --- FR-ADM-004 locked texts -------------------------------------------------------------

def _doc():
    return base64.b64encode(b"%PDF-1.4 signed approval").decode()


def test_scope_statement_journey_two_admins_and_signoffs(seeded, admins, api, gh):
    """FR-ADM-004, TC-ADM-004-01: A proposes, lawyer and insurer approvals recorded, B approves; new reports only."""
    a, b = admins
    before = selectors.current_locked_text("scope_statement", gh)
    r = a.post("/v1/admin/locked-texts/scope_statement/versions",
               {"country": "GH", "title": "Scope", "text": "New scope wording [TO VERIFY]."}, format="json")
    assert r.status_code == 201
    vid = r.json()["id"]
    base = f"/v1/admin/locked-texts/scope_statement/versions/{vid}"
    for party in ("lawyer", "insurer"):
        r = a.post(f"{base}/signoffs", {"party": party, "approved_by_name": f"The {party}",
                                        "document_base64": _doc()}, format="json")
        assert r.status_code == 200, r.content
    assert a.post(f"{base}/submit").json()["status"] == "open"
    r = a.post(f"{base}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    r = b.post(f"{base}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "published"
    before.refresh_from_db()
    assert before.status == "superseded"
    pub = api().get("/v1/legal-texts/scope_statement/current", {"country": "GH"}).json()
    assert pub["id"] == vid and pub["text"] == "New scope wording [TO VERIFY]."
    _sql_fails("UPDATE adm_locked_text_version SET text = 'changed' WHERE id = %s", [vid])


def test_scope_statement_without_insurer_approval_is_refused(seeded, admins, people, gh):
    """FR-ADM-004, TC-ADM-004-02, RUL-04: no recorded insurer approval, no approval."""
    a, _ = admins
    r = a.post("/v1/admin/locked-texts/scope_statement/versions", {"country": "GH", "text": "Text"}, format="json")
    base = f"/v1/admin/locked-texts/scope_statement/versions/{r.json()['id']}"
    a.post(f"{base}/signoffs", {"party": "lawyer", "approved_by_name": "L", "document_base64": _doc()},
           format="json")
    r = a.post(f"{base}/submit")
    assert r.status_code == 409 and r.json()["code"] == "release-blocked"
    assert r.json()["blocking_reasons"][0]["rule"] == "RUL-04"


def test_pending_scope_v2_cannot_be_forced_published_in_the_database(seeded):
    """RUL-04 enforced twice: the trigger refuses publishing without approvals."""
    v2 = LockedTextVersion.objects.get(kind="scope_statement", status="draft", country__code="GH")
    with connection.cursor() as c:
        c.execute("UPDATE adm_locked_text_version SET status = 'pending_approval' WHERE id = %s", [v2.pk])
    _sql_fails("UPDATE adm_locked_text_version SET status = 'published', published_at = now() WHERE id = %s",
               [v2.pk])


# --- FR-ADM-005 settings -----------------------------------------------------------------

def test_value_that_does_not_affect_a_release_needs_one_admin(seeded, admins):
    """TC-ADM-005-05: the SMS money threshold applies at once and is audited."""
    a, _ = admins
    r = a.put("/v1/admin/settings/ntf_amount_threshold", {"value": {"amount": "300.00", "currency": "USD"}},
              format="json")
    assert r.status_code == 200 and r.json()["status"] == "applied"
    assert selectors.setting("ntf_amount_threshold")["amount"] == "300.00"


def test_release_value_waits_for_second_admin_and_rules_keep_old_value(seeded, admins, people, gh):
    """FR-ADM-005, TC-ADM-005-03 and 04: pending until B approves; A cannot approve; old value used meanwhile."""
    a, b = admins
    r = a.put("/v1/admin/settings/release_bank_pay_working_days", {"value": 3, "country": "GH"}, format="json")
    assert r.status_code == 202 and r.json()["status"] == "pending_approval"
    cr_id = r.json()["change_request"]["id"]
    assert selectors.setting("release_bank_pay_working_days", gh) == 2
    pending = a.get("/v1/admin/change-requests").json()["items"]
    assert cr_id in [c["id"] for c in pending]
    assert a.post(f"/v1/admin/change-requests/{cr_id}/approvals", {}, format="json").status_code == 409
    assert b.post(f"/v1/admin/change-requests/{cr_id}/approvals", {}, format="json").json()["status"] == "applied"
    assert selectors.setting("release_bank_pay_working_days", gh) == 3
    e = AuditEvent.objects.filter(action="setting.changed", data__key="release_bank_pay_working_days").last()
    assert e.data["old"] == 2 and e.data["new"] == 3 and e.data["approved_by"] == [str(people["admin2"].pk)]


def test_unsafe_values_refused_with_range(seeded, admins):
    """TC-ADM-005-02: zero or negative windows and a buffer above its maximum are refused."""
    a, _ = admins
    for key, value in (("fresh_search_window_days", 0), ("fresh_search_window_days", -3),
                       ("fx_hold_buffer_pct", "75")):
        r = a.put(f"/v1/admin/settings/{key}", {"value": value}, format="json")
        assert r.status_code == 422 and r.json()["code"] == "setting-out-of-range"
        assert "allowed" in r.json()


def test_comparison_providers_need_second_admin(seeded, admins, gh):
    """TC-ADM-005-06: providers in the rate comparison need a second administrator."""
    a, b = admins
    r = a.put("/v1/admin/settings/fx_comparison_providers", {"value": ["P1", "P2", "P3"], "country": "GH"},
              format="json")
    assert r.status_code == 202
    assert selectors.setting("fx_comparison_providers", gh) == []
    b.post(f"/v1/admin/change-requests/{r.json()['change_request']['id']}/approvals", {}, format="json")
    assert selectors.setting("fx_comparison_providers", gh) == ["P1", "P2", "P3"]


def test_database_refuses_release_setting_without_approval(seeded, people):
    """FR-ADM-005 enforced twice."""
    with pytest.raises(Exception), transaction.atomic():
        Setting.objects.create(key="fx_hold_buffer_pct", value="9", affects_release=True)


# --- Feature flags (06 2.6) -----------------------------------------------------------

def test_safety_flag_needs_two_people_both_named(seeded, admins, people):
    """06 2.6: switching a safety flag on needs two people, both named in the audit log."""
    a, b = admins
    r = a.post("/v1/admin/feature-flags/changes", {"name": "partner_api.enabled", "enabled": False}, format="json")
    assert r.json()["status"] == "applied"  # switching off: one person
    assert not flags.enabled("partner_api.enabled")
    r = a.post("/v1/admin/feature-flags/changes", {"name": "partner_api.enabled", "enabled": True,
                                                   "reason": "Partner contract signed"}, format="json")
    assert r.status_code == 202
    assert not flags.enabled("partner_api.enabled")
    b.post(f"/v1/admin/change-requests/{r.json()['change_request']['id']}/approvals", {}, format="json")
    assert flags.enabled("partner_api.enabled")
    e = AuditEvent.objects.filter(action="feature_flag.changed", data__name="partner_api.enabled").last()
    assert e.data["people"] == [str(people["admin"].pk), str(people["admin2"].pk)]


def test_kill_switch_one_person_and_resume_payment_runs_needs_two(seeded, api, people):
    """06 2.6: a reviewer pulls a kill switch alone; resuming payment runs needs a second person."""
    rv = api(people["reviewer"])
    assert rv.post("/v1/admin/feature-flags/changes", {"name": "escrow.instructions_paused", "enabled": True},
                   format="json").json()["status"] == "applied"
    assert flags.instructions_paused()
    rv.post("/v1/admin/feature-flags/changes", {"name": "pro.payment_runs_paused", "enabled": True}, format="json")
    r = rv.post("/v1/admin/feature-flags/changes", {"name": "pro.payment_runs_paused", "enabled": False},
                format="json")
    assert r.status_code == 202 and flags.enabled("pro.payment_runs_paused")
    with pytest.raises(Forbidden):
        services.change_flag(name="maintenance.read_only", enabled=True, by=people["cm"])


def test_flag_go_live_blocked_until_to_verify_values_are_set(seeded, people, gh):
    """US-ADM-005 criterion 2: a feature cannot go live while a value it needs is still [TO VERIFY]."""
    services.change_flag(name="lines.care", enabled=False, by=people["admin"])
    with pytest.raises(RuleBlocked) as exc:
        services.change_flag(name="lines.care", enabled=True, by=people["admin"])
    assert "checkin_radius_m" in str(exc.value.detail)
    services.change_setting(key="checkin_radius_m", value=120, by=people["admin"])
    _, cr = services.change_flag(name="lines.care", enabled=True, by=people["admin"])
    assert cr.status == "pending"


def test_lines_flags_per_country(seeded, people, gh):
    """06 2.6: a line is on in a country only when the platform, country and line values are on."""
    ng = seeded["ng"]
    assert flags.enabled("lines.fee", gh)
    assert not flags.enabled("lines.fee", ng)  # country.ng is off
    services.change_flag(name="lines.fee", enabled=False, by=people["admin"], country=gh)
    with pytest.raises(FeatureOff):
        flags.require("lines.fee", gh)


# --- App versions (FR-APP-006) ------------------------------------------------------

def test_raising_minimum_needs_second_admin_and_old_app_gets_426(seeded, admins, api):
    """FR-APP-006, TC-APP-006-01 and 03."""
    a, b = admins
    r = a.put("/v1/admin/app-versions", {"app": "client", "platform": "ios", "min_version": "1.2.0"}, format="json")
    assert r.status_code == 202
    appversion.check("client/ios/1.0.5")  # still allowed: the raise waits
    b.post(f"/v1/admin/change-requests/{r.json()['change_request']['id']}/approvals", {}, format="json")
    with pytest.raises(appversion.AppVersionUnsupported) as exc:
        appversion.check("client/ios/1.0.5")
    assert exc.value.status == 426 and exc.value.code == "app-version-unsupported"
    cfg = api().get("/v1/app-config", {"app": "client", "platform": "ios", "version": "1.0.5"}).json()
    assert cfg["update_required"] is True and cfg["min_version"] == "1.2.0" and cfg["fee_payment_mode"] == "web"
    assert api().get("/v1/app-config", {"app": "client", "platform": "ios", "version": "1.2.0"}).json()[
        "update_required"] is False


def test_evidence_captured_before_raise_still_accepted(seeded, people):
    """FR-APP-006, TC-APP-006-02: items captured before the raise are accepted for the grace period."""
    av = AppVersion.objects.get(app="field", platform="ios")
    av.previous_min_version, av.min_version = "1.0.0", "1.2.0"
    av.min_raised_at = timezone.now() - timedelta(days=2)
    av.save()
    appversion.check("field/ios/1.1.0", captured_at=timezone.now() - timedelta(days=3))
    with pytest.raises(appversion.AppVersionUnsupported):
        appversion.check("field/ios/1.1.0", captured_at=timezone.now())
    av.min_raised_at = timezone.now() - timedelta(days=40)
    av.save()
    with pytest.raises(appversion.AppVersionUnsupported):
        appversion.check("field/ios/1.1.0", captured_at=timezone.now() - timedelta(days=41))


def test_lowering_minimum_applies_at_once(seeded, admins):
    a, _ = admins
    r = a.put("/v1/admin/app-versions", {"app": "field", "platform": "android", "min_version": "1.0.0"},
              format="json")
    assert r.status_code == 200 and r.json()["app_version"]["min_version"] == "1.0.0"


def test_middleware_answers_426(seeded, rf):
    """FR-APP-006: the optional middleware answers 426 with problem JSON."""
    from administration.middleware import AppVersionMiddleware

    AppVersion.objects.filter(app="client", platform="android").update(min_version="2.0.0", latest_version="2.0.0")
    mw = AppVersionMiddleware(lambda req: None)
    resp = mw(rf.get("/v1/cases", HTTP_TENMINA_APP="client/android/1.9.0"))
    assert resp.status_code == 426 and b"app-version-unsupported" in resp.content
    assert mw(rf.get("/v1/app-config", HTTP_TENMINA_APP="client/android/1.9.0")) is None


def test_withdraw_change(seeded, admins):
    a, _ = admins
    cr = ChangeRequest.objects.filter(status="pending", kind="setting").first()
    assert a.post(f"/v1/admin/change-requests/{cr.pk}/withdraw").json()["status"] == "withdrawn"


def test_admin_endpoints_refuse_non_admins(seeded, api, people):
    c = api(people["cm"])
    for url in ("/v1/admin/settings", "/v1/admin/partners", "/v1/admin/config-versions", "/v1/admin/prices"):
        assert c.get(url).status_code == 403
    with pytest.raises(Forbidden):
        services.publish_config_version(ConfigVersion.objects.filter(state="draft").first(), by=people["cm"])


def test_seeded_states(seeded):
    """Seeds cover several states of each workflow."""
    assert ConfigVersion.objects.filter(state="draft").exists()
    assert ConfigVersion.objects.filter(state="published").count() >= 7
    assert Price.objects.filter(valid_to__isnull=False).exists()
    assert ChangeRequest.objects.filter(status="pending").count() >= 3
    assert ChangeRequest.objects.filter(status="applied").exists()
    assert Partner.objects.filter(status="inactive").exists()
    assert FeatureFlag.objects.filter(name="escrow.bank_api", enabled=False).exists()
