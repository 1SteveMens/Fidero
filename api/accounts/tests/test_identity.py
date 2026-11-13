"""Client identity checks, national identity checks and licences
(US-ACC-004a/b, US-ACC-013, US-ACC-005; RUL-20, RUL-31; TC-ACC-004,
TC-ACC-005, TC-ACC-013, TC-RUL-20, TC-RUL-31)."""
from datetime import date, timedelta

import pytest
from django.apps import apps
from django.db import IntegrityError, transaction

from accounts import services
from accounts.adapters import FakeNationalIdProvider
from accounts.models import IdentityCheck, NationalIdCheck, Person, ProfessionalLicence
from audit.models import AuditEvent
from core.errors import DomainError, RuleBlocked


def _ev(gh, by, name="doc.txt"):
    from evidence.services import store

    return store(data=name.encode(), country=gh, uploaded_by=by, content_type="text/plain", original_name=name)


# ---------------------------------------------------------------- client identity (FR-ACC-004)

def test_provider_pass_sets_status_and_reference(seeded, api, people):
    """US-ACC-004a AC2, TC-ACC-004-01."""
    kofi = people["client2"]
    IdentityCheck.objects.filter(person=kofi).delete()
    Person.objects.filter(pk=kofi.pk).update(id_check_status="none")
    r = api(kofi).post("/v1/me/identity-checks", {"document_type": "passport", "document_number": "P1234567"},
                       format="json")
    assert r.status_code == 201 and r.json()["status"] == "passed"
    assert r.json()["provider_reference"].startswith("IDP-") and r.json()["document_number"].endswith("4567")
    kofi.refresh_from_db()
    assert kofi.id_check_status == "passed"
    services.require_client_identity(kofi)


def test_provider_fail_goes_to_manual_queue_and_manual_check(seeded, api, people, gh):
    """US-ACC-004a AC3, US-ACC-004b AC1-2, TC-ACC-004-03."""
    kofi = people["client2"]
    IdentityCheck.objects.filter(person=kofi).delete()
    Person.objects.filter(pk=kofi.pk).update(id_check_status="none")
    r = api(kofi).post("/v1/me/identity-checks", {"document_type": "passport", "document_number": "P0000000"},
                       format="json")
    assert r.json()["status"] == "manual_review"
    kofi.refresh_from_db()
    with pytest.raises(RuleBlocked) as e:
        services.require_client_identity(kofi)
    assert e.value.blocking_reasons[0]["rule"] == "FR-ACC-004"
    cm = people["cm"]
    q = api(cm).get("/v1/identity-checks?status=manual_review").json()["items"]
    chk = next(i for i in q if i["person"]["id"] == str(kofi.pk))
    ev = _ev(gh, cm, "passport-copy.txt")
    r = api(kofi).post(f"/v1/identity-checks/{chk['id']}/manual-decision", {}, format="json")
    assert r.status_code == 403
    r = api(cm).post(f"/v1/identity-checks/{chk['id']}/manual-decision",
                     {"document_type": "passport", "document_number": "P0000000", "outcome": "passed",
                      "evidence": str(ev.pk)}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "manual_passed"
    assert r.json()["reviewed_by"] == str(cm.pk)
    from evidence.models import EvidenceLink

    assert EvidenceLink.objects.filter(subject_id=chk["id"], role="identity_document_restricted").exists()
    assert AuditEvent.objects.filter(action="identity_check.manual_passed").exists()
    kofi.refresh_from_db()
    services.require_client_identity(kofi)


def test_staff_record_manual_check_without_provider(seeded, api, people):
    kofi = people["client2"]
    IdentityCheck.objects.filter(person=kofi).delete()
    r = api(people["cm"]).post("/v1/identity-checks", {"person": str(kofi.pk), "document_type": "national_id",
                                                       "document_number": "GHA-123", "outcome": "failed"},
                               format="json")
    assert r.status_code == 201 and r.json()["status"] == "manual_failed"


# ---------------------------------------------------------------- national identity (FR-ACC-013, RUL-31)

def _nid(api, by, **data):
    body = {"subject_role": "seller", "subject_name": "Kofi Seller", "id_number": "GHA-711111111-1", **data}
    return api(by).post("/v1/national-id-checks", body, format="json")


def test_party_checks_store_result_reference_time_only(seeded, api, people):
    """US-ACC-013 AC2, TC-ACC-013-01, TC-RUL-31-01: no biometric data kept."""
    r = _nid(api, people["cm"])
    assert r.status_code == 201, r.content
    d = r.json()
    assert d["result"] == "match" and d["provider_reference"] and d["checked_at"]
    assert d["id_number"].endswith("11-1") and "711111111" not in d["id_number"]
    chk = NationalIdCheck.objects.get(pk=d["id"])
    assert len(chk.response_sha256) == 64
    for model in apps.get_app_config("accounts").get_models():
        for f in model._meta.concrete_fields:
            for bad in ("photo", "biometric", "finger", "face", "selfie", "portrait"):
                assert bad not in f.column, f"{model._meta.db_table}.{f.column}"


def test_no_match_and_not_found_fail_and_alert(seeded, api, people):
    """TC-ACC-013-05: a different name is a no match; an unknown number is not found."""
    from notifications.models import Message

    r = _nid(api, people["cm"], subject_name="Somebody Else", id_number="GHA-700000001-1")
    assert r.json()["result"] == "no_match"
    r = _nid(api, people["cm"], id_number="GHA-700000099-0")
    assert r.json()["result"] == "not_found"
    assert Message.objects.filter(person=people["reviewer"], template="national_id_failed").exists()


def test_service_down_stays_pending_and_retries(seeded, api, people, monkeypatch):
    """US-ACC-013 AC4, TC-ACC-013-04, TC-RUL-31-03: pending while down, case
    manager alerted, release blocked with no override, passes on retry."""
    from notifications.models import Message

    monkeypatch.setattr(FakeNationalIdProvider, "down", True)
    r = _nid(api, people["cm"], id_number="GHA-712345678-1")
    assert r.json()["result"] == "unavailable"
    assert Message.objects.filter(person=people["cm"], template="national_id_unavailable").exists()
    with pytest.raises(RuleBlocked) as e:
        services.require_national_id({"Seller Kofi Seller": r.json()["id"]}, "Report release")
    assert "pending" in e.value.blocking_reasons[0]["message"]
    NationalIdCheck.objects.filter(pk=r.json()["id"]).update(last_attempt_at=None)
    monkeypatch.setattr(FakeNationalIdProvider, "down", False)
    assert services.retry_national_id_checks() >= 1
    assert NationalIdCheck.objects.get(pk=r.json()["id"]).result == "match"


def test_photocopy_is_never_proof(seeded, api, people, gh):
    """US-ACC-013 AC3, TC-ACC-013-03, TC-RUL-31-02."""
    ev = _ev(gh, people["cm"], "card-scan.txt")
    r = _nid(api, people["cm"], evidence_id=str(ev.pk))
    assert r.status_code == 422 and r.json()["code"] == "document-not-proof"
    assert AuditEvent.objects.filter(action="national_id_check.document_refused").exists()
    chk = NationalIdCheck.objects.create(country=gh, subject_role="seller", subject_name="X", subject_name_bidx="x",
                                         id_number="N", id_number_bidx="n", requested_by=people["cm"])
    with pytest.raises(IntegrityError), transaction.atomic():
        NationalIdCheck.objects.filter(pk=chk.pk).update(result="match")  # no reference from the channel


def test_final_result_cannot_change(seeded, api, people):
    r = _nid(api, people["cm"])
    with pytest.raises(IntegrityError), transaction.atomic():
        NationalIdCheck.objects.filter(pk=r.json()["id"]).update(provider_reference="NIA-FAKE")


def test_staff_portal_result_checks_number_and_replay(seeded, api, people):
    """TC-RUL-31-05: a pass for another person or a replayed reference is refused."""
    cm = people["cm"]
    r = _nid(api, cm, adapter="staff_portal", id_number="GHA-720000000-1")
    cid = r.json()["id"]
    assert r.json()["result"] == "pending"
    url = f"/v1/national-id-checks/{cid}/staff-result"
    r = api(cm).post(url, {"id_number": "GHA-799999999-9", "result": "match", "provider_reference": "NIA-P-1",
                           "returned_name": "Kofi Seller"}, format="json")
    assert r.status_code == 422 and r.json()["code"] == "identity-result-mismatch"
    r = api(cm).post(url, {"id_number": "GHA-720000000-1", "result": "match", "provider_reference": "NIA-DEMO-SELLER",
                           "returned_name": "Kofi Seller"}, format="json")
    assert r.status_code == 422  # reference already used (seed)
    r = api(cm).post(url, {"id_number": "GHA-720000000-1", "result": "match", "provider_reference": "NIA-P-2",
                           "returned_name": "Someone Else"}, format="json")
    assert r.status_code == 422
    r = api(cm).post(url, {"id_number": "GHA-720000000-1", "result": "match", "provider_reference": "NIA-P-2",
                           "returned_name": "KOFI  SELLER"}, format="json")
    assert r.status_code == 200 and r.json()["result"] == "match" and r.json()["checked_by"] == str(cm.pk)


def test_who_may_run_checks(seeded, api, people):
    """02 10.4: runners never; lawyers for parties only."""
    assert _nid(api, people["runner"]).status_code == 403
    assert _nid(api, people["client"]).status_code == 403
    assert _nid(api, people["lawyer"]).status_code == 201
    assert _nid(api, people["lawyer"], subject_role="payee").status_code == 403


def test_blockers_name_each_missing_check(seeded, people):
    """US-ACC-013 AC1, TC-ACC-013-02."""
    checks = {"Seller": seeded["national_id_checks"]["seller"],
              "Consenting party": seeded["national_id_checks"]["consenting"], "Grantor 2": None}
    reasons = services.national_id_blockers(checks)
    assert [r["rule"] for r in reasons] == ["RUL-31", "RUL-31"]
    assert "Consenting party" in reasons[0]["message"] and "Grantor 2" in reasons[1]["message"]


def test_same_number_on_two_sides_raises_reviewer_item(seeded, people, gh):
    import uuid
    from core.models import OutboxEvent

    case = uuid.uuid4()
    services.request_national_id_check(by=people["cm"], country=gh, subject_role="seller", subject_name="A Seller",
                                       id_number="GHA-733333333-3", context_type="case", context_id=case)
    services.request_national_id_check(by=people["cm"], country=gh, subject_role="grantor", subject_name="B Grantor",
                                       id_number="GHA-733333333-3", context_type="case", context_id=case)
    assert OutboxEvent.objects.filter(topic="national_id_check.duplicate").exists()


# ---------------------------------------------------------------- licences (FR-ACC-005, RUL-20)

def test_licence_journey_and_signing_rule(seeded, api, people):
    """US-ACC-005 AC1-3, TC-ACC-005-01/02, TC-RUL-20-01/02/03."""
    lw = Person.objects.create_user("lw2@example.com", "tenmina-dev-123", full_name="Second Lawyer")
    from accounts.models import RoleGrant

    RoleGrant.objects.create(person=lw, role="LW")
    with pytest.raises(DomainError) as e:
        services.require_valid_licence(lw, "LW")
    assert e.value.code == "licence-invalid"
    r = api(lw).post("/v1/licences", {"role": "LW", "body": "General Legal Council", "number": "GLC/9",
                                      "expires_on": str(date.today() + timedelta(days=90))}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "submitted"
    with pytest.raises(DomainError) as e:
        services.require_valid_licence(lw, "LW")
    assert "not verified" in e.value.detail
    assert api(lw).post(f"/v1/admin/licences/{r.json()['id']}/verify").status_code == 403
    r = api(people["admin"]).post(f"/v1/admin/licences/{r.json()['id']}/verify")
    assert r.status_code == 200 and r.json()["verified_by"] == str(people["admin"].pk) and r.json()["verified_on"]
    assert services.require_valid_licence(lw, "LW")
    with pytest.raises(DomainError):
        services.require_valid_licence(lw, "SV")  # wrong role (TC-RUL-20-03)
    with pytest.raises(DomainError) as e:
        services.require_valid_licence(lw, "LW", on=date.today() + timedelta(days=91))
    assert e.value.blocking_reasons[0]["rule"] == "RUL-20"


def test_expiry_job_expires_and_alerts(seeded, people):
    from notifications.models import Message

    lic = ProfessionalLicence.objects.get(person=people["lawyer"])
    ProfessionalLicence.objects.filter(pk=lic.pk).update(expires_on=date.today() - timedelta(days=1))
    assert services.expire_licences() == 1
    lic.refresh_from_db()
    assert lic.status == "expired"
    assert Message.objects.filter(person=people["lawyer"], template="licence_expired").exists()
    with pytest.raises(DomainError) as e:
        services.require_valid_licence(people["lawyer"], "LW")
    assert "expired" in e.value.detail
    assert Message.objects.filter(person=people["qs"], template="licence_expiring").exists()


def test_expired_licence_cannot_be_verified(seeded, people):
    lic = ProfessionalLicence.objects.get(person=people["inspector"])
    ProfessionalLicence.objects.filter(pk=lic.pk).update(expires_on=date.today() - timedelta(days=1))
    lic.refresh_from_db()
    with pytest.raises(DomainError) as e:
        services.verify_licence(lic, people["admin"])
    assert e.value.code == "licence-invalid"
