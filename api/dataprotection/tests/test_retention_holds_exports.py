"""Retention, legal holds and bulk exports (US-DPR-004a/b, US-DPR-005;
TC-DPR-004, TC-DPR-005)."""
from datetime import timedelta

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import FamilyMember, Person
from audit.models import AuditEvent
from dataprotection import services
from dataprotection.models import BulkExport, Consent, LegalHold, RetentionRule


def _age_removed_uncle(seeded, days=400):
    fm = seeded["family_members"]["uncle"]
    FamilyMember.objects.filter(pk=fm.pk).update(removed_at=timezone.now() - timedelta(days=days))
    return fm


def test_period_to_verify_deletes_nothing(seeded, api, people):
    """US-DPR-004a AC2: a period still [TO VERIFY] (Q-08) deletes nothing."""
    fm = _age_removed_uncle(seeded)
    r = api(people["admin"]).post("/v1/dpr/retention-runs")
    assert r.status_code == 201
    assert r.json()["results"]["family:all"]["skipped"].startswith("Period is [TO VERIFY]")
    assert FamilyMember.objects.get(pk=fm.pk).status == "removed"


def test_expired_records_are_anonymised_and_logged(seeded, api, people):
    """US-DPR-004a AC1, TC-DPR-004-01."""
    fm = _age_removed_uncle(seeded)
    rule = RetentionRule.objects.get(data_class="family", country__isnull=True, status="active")
    c = api(people["admin"])
    r = c.patch(f"/v1/dpr/retention-rules/{rule.pk}", {"period_days": 365}, format="json")
    assert r.status_code == 200 and r.json()["period_label"] == "365 days"
    r = c.post("/v1/dpr/retention-runs")
    assert r.json()["results"]["family:all"]["applied"] == 1
    fm.refresh_from_db()
    assert fm.status == "anonymised" and fm.full_name == "Removed family member" and fm.phone == ""
    assert AuditEvent.objects.filter(action="retention.anonymise", entity_id=str(fm.pk)).exists()
    assert AuditEvent.objects.filter(action="retention.sweep").exists()
    assert api(people["cm"]).post("/v1/dpr/retention-runs").status_code == 403


def test_marketing_consent_expires(seeded, people):
    ama = people["client"]
    c = services.give_consent(ama, purpose="marketing", text_version="1")
    Consent.objects.filter(pk=c.pk).update(given_at=timezone.now() - timedelta(days=800))
    services.run_retention()
    c.refresh_from_db()
    assert c.withdrawn_at is not None


def test_closed_accounts_are_anonymised_after_the_period(seeded, people):
    from accounts.services import close_account

    kofi = people["client2"]
    close_account(kofi)
    Person.objects.filter(pk=kofi.pk).update(closed_at=timezone.now() - timedelta(days=40))
    services.save_rule(people["admin"], data_class="account", period_days=30, anchor="account_closure")
    services.run_retention()
    assert Person.objects.get(pk=kofi.pk).status == "anonymised"


def test_country_rule_overrides_platform_rule(seeded, people, gh):
    fm = _age_removed_uncle(seeded, days=100)
    services.save_rule(people["admin"], data_class="family", period_days=50)
    services.save_rule(people["admin"], data_class="family", period_days=200, country=gh)
    run = services.run_retention()
    assert run.results["family:all"]["applied"] == 0 and run.results["family:GH"]["applied"] == 0
    assert FamilyMember.objects.get(pk=fm.pk).status == "removed"


def test_legal_hold_blocks_retention_until_lifted_by_two(seeded, api, people, mfa):
    """US-DPR-004b AC1-2, TC-DPR-004-02: held items are kept and the hold
    reason logged; a lift needs two people; then normal rules apply."""
    fm = _age_removed_uncle(seeded)
    services.save_rule(people["admin"], data_class="family", period_days=365)
    lw = people["lawyer"]
    r = api(lw).post("/v1/dpr/legal-holds", {"subject_type": "person", "subject_id": str(people["client"].pk),
                                            "reason": "Boundary claim by the seller", "country": "GH"},
                     format="json")
    assert r.status_code == 201, r.content
    hid = r.json()["id"]
    run = services.run_retention()
    res = run.results["family:all"]
    assert res["held"] == 1 and res["holds"][0]["reason"] == "Boundary claim by the seller"
    assert FamilyMember.objects.get(pk=fm.pk).status == "removed"
    assert api(people["client"]).post("/v1/dpr/legal-holds", {}, format="json").status_code == 403
    r = api(lw).post(f"/v1/dpr/legal-holds/{hid}/lift-requests", {"reason": "Claim settled"}, format="json")
    assert r.json()["status"] == "lift_pending"
    c = api(lw)
    mfa(c, lw)
    assert c.post(f"/v1/dpr/legal-holds/{hid}/approvals", {}, format="json").json()["code"] == "same-approver"
    for key in ("admin", "reviewer"):
        c = api(people[key])
        mfa(c, people[key])
        r = c.post(f"/v1/dpr/legal-holds/{hid}/approvals", {}, format="json")
    assert r.json()["status"] == "lifted"
    services.run_retention()
    assert FamilyMember.objects.get(pk=fm.pk).status == "anonymised"


def test_database_refuses_lift_or_delete_without_approval(seeded):
    h = LegalHold.objects.first()
    with pytest.raises(IntegrityError), transaction.atomic():
        LegalHold.objects.filter(pk=h.pk).update(status="lift_pending")
        LegalHold.objects.filter(pk=h.pk).update(status="lifted")
    with pytest.raises(Exception), transaction.atomic():
        LegalHold.objects.filter(pk=h.pk).delete()


def test_bulk_export_needs_a_different_administrator(seeded, api, people, mfa):
    """US-DPR-005 AC1, TC-DPR-005-01/02."""
    admin = people["admin"]
    c = api(admin)
    r = c.post("/v1/dpr/bulk-exports", {"purpose": "Webinar invitations", "country": "GH", "roles": ["CL"],
                                        "fields": ["full_name", "email"]}, format="json")
    assert r.status_code == 201, r.content
    bid = r.json()["id"]
    mfa(c, admin)
    assert c.post(f"/v1/dpr/bulk-exports/{bid}/approvals", {}, format="json").json()["code"] == "same-approver"
    assert c.get(f"/v1/dpr/bulk-exports/{bid}/download").status_code == 409
    rv = api(people["reviewer"])
    mfa(rv, people["reviewer"])
    assert rv.post(f"/v1/dpr/bulk-exports/{bid}/approvals", {}, format="json").status_code == 403
    for key in ("admin2", "admin3"):
        a = api(people[key])
        mfa(a, people[key])
        r = a.post(f"/v1/dpr/bulk-exports/{bid}/approvals", {}, format="json")
    assert r.json()["status"] == "produced" and r.json()["row_count"] >= 2
    assert api(people["admin2"]).get(f"/v1/dpr/bulk-exports/{bid}/download").status_code == 403
    r = c.get(f"/v1/dpr/bulk-exports/{bid}/download")
    assert r.status_code == 200 and b"ama@example.com" in r.content and b"rv1@tenmina.test" not in r.content
    assert AuditEvent.objects.filter(action="bulk_export.downloaded", entity_id=bid).exists()
    BulkExport.objects.filter(pk=bid).update(link_expires_at=timezone.now() - timedelta(minutes=1))
    assert c.get(f"/v1/dpr/bulk-exports/{bid}/download").status_code == 410


def test_bulk_export_fields_are_limited_and_db_needs_approval(seeded, api, people):
    r = api(people["admin"]).post("/v1/dpr/bulk-exports", {"purpose": "x", "country": "GH",
                                                           "fields": ["mfa_secret"]}, format="json")
    assert r.status_code == 400
    be = BulkExport.objects.first()
    with pytest.raises(IntegrityError), transaction.atomic():
        BulkExport.objects.filter(pk=be.pk).update(status="produced")


def test_catalogue_and_locations(seeded, api, people):
    """NFR-PRIV-01, NFR-PRIV-02: every acc_ and dpr_ field has a purpose."""
    assert services.uncatalogued_fields() == []
    c = api(people["admin3"])
    r = c.post("/v1/dpr/data-catalogue/sync")
    assert r.status_code == 200 and r.json()["uncatalogued"] == []
    assert c.get("/v1/dpr/data-locations").json()["items"]
    r = c.post("/v1/dpr/data-locations", {"service": "Push", "vendor": "APNs and FCM", "region": "global",
                                          "data_classes": ["account"]}, format="json")
    assert r.status_code == 201
