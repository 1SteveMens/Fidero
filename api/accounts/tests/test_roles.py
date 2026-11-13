"""Invitations, role administration and release and payment rights
(US-ACC-006, US-ACC-007, 01 C2, 02 6.4 and 10.4)."""
import re
import uuid

import pytest
from django.db import IntegrityError, transaction

from accounts import services
from accounts.models import Invitation, Person, RightsRequest, RoleGrant
from audit.models import AuditEvent
from notifications.models import Message


def _token_from_email(email):
    body = Message.objects.filter(to_address=email, template="invitation").latest("created_at").body
    return re.search(r"token=([A-Za-z0-9_\-]+)", body).group(1)


def test_admin_invites_and_role_is_audited(seeded, api, people):
    """US-ACC-006 AC1-2, TC-ACC-006-01: single-use link, roles on acceptance,
    audit names the administrator."""
    admin = people["admin"]
    r = api(admin).post("/v1/admin/users/invitations", {"email": "new.surveyor@example.com",
                                                        "full_name": "Ewurabena Surveyor", "roles": ["SV"],
                                                        "country": "GH"}, format="json")
    assert r.status_code == 201, r.content
    token = _token_from_email("new.surveyor@example.com")
    r = api().post("/v1/auth/invitations/accept", {"token": token, "password": "a-long-password-1",
                                                   "privacy_notice_version": "1.0"})
    assert r.status_code == 200, r.content
    p = Person.objects.get(email="new.surveyor@example.com")
    assert "SV" in p.roles() and p.email_verified_at
    ev = AuditEvent.objects.filter(action="role.granted", entity_id=str(p.pk)).latest("seq")
    assert ev.data["granted_by_name"] == admin.full_name
    r = api().post("/v1/auth/invitations/accept", {"token": token, "password": "a-long-password-1"})
    assert r.status_code == 422 and r.json()["code"] == "invitation-invalid"


def test_expired_invitation_is_refused(seeded, people):
    from django.utils import timezone

    inv, raw = services.invite(by=people["admin"], email="late@example.com", roles=["RN"])
    Invitation.objects.filter(pk=inv.pk).update(expires_at=timezone.now())
    with pytest.raises(Exception) as e:
        services.accept_invitation(token=raw, password="a-long-password-1", privacy_notice_version="1.0")
    assert getattr(e.value, "code", "") == "invitation-invalid"
    assert services.expire_invitations() == 1


def test_case_manager_invites_only_sellers_to_a_case(seeded, api, people):
    """FR-ACC-006, TC-ACC-006-02."""
    c = api(people["cm"])
    r = c.post("/v1/admin/users/invitations", {"email": "x@example.com", "roles": ["LW"]}, format="json")
    assert r.status_code == 403
    r = c.post("/v1/admin/users/invitations", {"email": "seller2@example.com", "roles": ["SE"],
                                               "case_id": str(uuid.uuid4())}, format="json")
    assert r.status_code == 201
    r = api(people["client"]).post("/v1/admin/users/invitations", {"email": "y@example.com", "roles": ["SE"]},
                                   format="json")
    assert r.status_code == 403


def test_rights_cannot_be_invited_or_granted_directly(seeded, api, people):
    admin = people["admin"]
    r = api(admin).post("/v1/admin/users/invitations", {"email": "z@example.com", "roles": ["RV", "RR"]},
                        format="json")
    assert r.status_code == 409 and r.json()["code"] == "rights-need-two-administrators"
    r = api(admin).post(f"/v1/admin/people/{people['cm'].pk}/roles", {"role": "RR"}, format="json")
    assert r.status_code == 409
    r = api(people["cm"]).post(f"/v1/admin/people/{people['lawyer'].pk}/roles", {"role": "SV"}, format="json")
    assert r.status_code == 403


def test_database_refuses_rights_without_two_administrators(seeded, people):
    """02 6.4 CHECK and trigger: release rights need an approved request."""
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleGrant.objects.create(person=people["cm"], role="RR")


def test_release_rights_journey_with_two_administrators(seeded, api, people, mfa):
    """01 C2: one administrator asks, two other administrators approve with MFA."""
    admin, admin2, admin3 = people["admin"], people["admin2"], people["admin3"]
    target = Person.objects.create_user("rv3@tenmina.test", "tenmina-dev-123", full_name="Kweku Reviewer")
    RoleGrant.objects.create(person=target, role="RV")
    c1 = api(admin)
    r = c1.post("/v1/admin/rights-requests", {"person": str(target.pk), "right": "RR"}, format="json")
    assert r.status_code == 201, r.content
    rid = r.json()["id"]
    mfa(c1, admin)
    r = c1.post(f"/v1/admin/rights-requests/{rid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    c2 = api(admin2)
    r = c2.post(f"/v1/admin/rights-requests/{rid}/approvals", {"decision": "approve"}, format="json")
    assert r.status_code == 401 and r.json()["code"] == "mfa-required"
    mfa(c2, admin2)
    assert c2.post(f"/v1/admin/rights-requests/{rid}/approvals", {}, format="json").json()["status"] == "pending"
    c3 = api(admin3)
    mfa(c3, admin3)
    r = c3.post(f"/v1/admin/rights-requests/{rid}/approvals", {}, format="json")
    assert r.json()["status"] == "granted"
    assert "RR" in target.roles()


def test_rights_approvers_must_be_administrators(seeded, api, people, mfa):
    rr = services.request_rights(by=people["admin"], person=people["admin3"], right="PY")
    c = api(people["reviewer"])
    mfa(c, people["reviewer"])
    r = c.post(f"/v1/admin/rights-requests/{rr.pk}/approvals", {}, format="json")
    assert r.status_code == 403  # not an administrator
    c = api(people["admin3"])
    mfa(c, people["admin3"])
    r = c.post(f"/v1/admin/rights-requests/{rr.pk}/approvals", {}, format="json")
    assert r.status_code == 403  # the person who would receive the rights


def test_generic_approval_endpoint_cannot_bypass_the_rule(seeded, api, people, mfa):
    """Approvals given through /v1/approvals by non-administrators are not applied."""
    rr = services.request_rights(by=people["admin"], person=people["admin3"], right="PY")
    for key in ("reviewer", "reviewer2"):
        c = api(people[key])
        mfa(c, people[key])
        c.post(f"/v1/approvals/{rr.approval_request_id}/decisions", {"decision": "approve"}, format="json")
    rr.refresh_from_db()
    assert rr.status == "rejected" and "PY" not in people["admin3"].roles()


def test_separation_of_duties(seeded, people):
    """6.4 acc.no_money_roles(): no release rights for a client, relative,
    carer or contractor; no payment rights for a professional."""
    ama = people["client"]
    RoleGrant.objects.create(person=ama, role="RV")
    with pytest.raises(Exception) as e:
        services.request_rights(by=people["admin"], person=ama, right="RR")
    assert e.value.code == "separation-of-duties"
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleGrant.objects.create(person=people["reviewer"], role="CL")
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleGrant.objects.create(person=people["reviewer"], role="LW")  # holds PY
    with pytest.raises(Exception) as e:
        services.grant_role(people["reviewer"], "CE", granted_by=people["admin"])
    assert e.value.code == "separation-of-duties"


def test_revoke_role_ends_access(seeded, api, people):
    lw = people["lawyer"]
    g = lw.role_grants.get(role="LW")
    r = api(people["admin"]).post(f"/v1/admin/role-grants/{g.pk}/revoke", {"reason": "Left the panel"},
                                  format="json")
    assert r.status_code == 200 and "LW" not in lw.roles()
    assert AuditEvent.objects.filter(action="role.revoked", entity_id=str(lw.pk)).exists()


def test_staff_scope_by_country(seeded, people):
    """US-ACC-007 AC3: a Ghana case manager sees only Ghana."""
    from accounts.selectors import scope_to_staff_countries, staff_country_codes
    from accounts.models import FamilyMember
    from countries.models import Country

    cm = people["cm"]
    assert staff_country_codes(cm) is None
    g = cm.role_grants.get(role="CM")
    g.country = Country.objects.get(code="GH")
    g.save()
    assert staff_country_codes(cm) == {"GH"}
    ng = Country.objects.get(code="NG")
    FamilyMember.objects.create(country=ng, client=people["client2"], full_name="Lagos Aunt", relationship="aunt")
    qs = scope_to_staff_countries(FamilyMember.objects.all(), cm)
    assert not qs.filter(country=ng).exists() and qs.exists()


def test_suspend_and_reactivate(seeded, api, people):
    kofi = people["client2"]
    c = api(people["admin"])
    assert c.post(f"/v1/admin/people/{kofi.pk}/suspend", {"reason": "Fraud review"}, format="json").status_code == 200
    r = api().post("/v1/auth/login", {"identifier": kofi.email, "password": "tenmina-dev-123"})
    assert r.status_code == 403 and r.json()["code"] == "account-inactive"
    assert c.post(f"/v1/admin/people/{kofi.pk}/reactivate").status_code == 200
    assert api(people["cm"]).get("/v1/admin/people").status_code == 403


def test_rights_request_listing(seeded, api, people):
    r = api(people["admin"]).get("/v1/admin/rights-requests")
    assert r.status_code == 200 and any(i["status"] == "pending" for i in r.json()["items"])
    assert RightsRequest.objects.filter(status="pending").exists()


def test_seeds_are_idempotent(seeded):
    """Seeds run twice leave the same data (CONVENTIONS: get_or_create)."""
    import accounts.seed
    import dataprotection.seed
    from accounts.models import BankAccount, NationalIdCheck
    from dataprotection.models import Consent, RetentionRule

    models = (Person, RoleGrant, BankAccount, NationalIdCheck, Consent, RetentionRule)
    before = [m.objects.count() for m in models]
    accounts.seed.run(seeded)
    dataprotection.seed.run(seeded)
    assert before == [m.objects.count() for m in models]
