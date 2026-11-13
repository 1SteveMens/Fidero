"""Family members, home dashboard, client bank accounts, organisations,
representatives and vetting (US-ACC-008, 011, 012; RUL-22, RUL-24, RUL-31;
TC-ACC-008, TC-ACC-011, TC-ACC-012)."""
import uuid

import pytest
from django.db import IntegrityError, transaction

from accounts import home, selectors, services
from accounts.models import BankAccount, FamilyMember, Membership, Person, RoleGrant, Vetting
from core.errors import Invalid, PayeeNotVerified, RuleBlocked


# ---------------------------------------------------------------- family and home (US-ACC-012)

def test_family_member_add_edit_remove(seeded, api, people):
    """US-ACC-012 AC1 and AC3, TC-ACC-012-02."""
    c = api(people["client"])
    r = c.post("/v1/family-members", {"full_name": "Kofi Mensah Jnr", "relationship": "son",
                                      "phone": "+233240000200", "address": "Kumasi", "may_confirm_visits": True},
               format="json")
    assert r.status_code == 201, r.content
    fid = r.json()["id"]
    r = c.post("/v1/family-members", {"full_name": "X", "relationship": "aunt", "health_notes": "diabetic"},
               format="json")
    assert r.status_code == 400  # only catalogued fields
    r = c.post("/v1/family-members", {"full_name": "Y", "relationship": "aunt", "may_confirm_visits": True},
               format="json")
    assert r.status_code == 422  # a confirmer needs a phone
    assert c.patch(f"/v1/family-members/{fid}", {"relationship": "grandson"}, format="json").json()[
        "relationship"] == "grandson"
    assert api(people["client2"]).get(f"/v1/family-members/{fid}").status_code == 404
    r = c.delete(f"/v1/family-members/{fid}")
    assert r.status_code == 200 and r.json()["status"] == "removed"
    assert FamilyMember.objects.filter(pk=fid).exists()  # kept under retention rules
    with pytest.raises(Invalid) as e:
        selectors.active_family_member(people["client"], fid)
    assert e.value.code == "family-member-removed"


def test_family_member_is_never_a_payee(seeded, people):
    """RUL-22: matching by account, name or phone."""
    ama = people["client"]
    assert selectors.is_relative_or_representative(ama, name="AKOSUA MENSAH")
    assert selectors.is_relative_or_representative(ama, phone="+233 24 000 0101")
    assert selectors.is_relative_or_representative(ama, person=people["family"])  # representative
    assert not selectors.is_relative_or_representative(ama, name="Accra Hills School")


def test_home_dashboard_registry(seeded, api, people):
    """US-ACC-012 AC2, TC-ACC-012-01: everything running, own items only;
    providers from other modules plug in."""

    def provider(person):
        if person.pk != people["client"].pk:
            return []
        return [home.item(kind="fee_payment", id=uuid.uuid4(), title="School fees for Kojo", status="awaiting_client",
                          status_text="Waiting for your approval", needs_action=True, line="fee")]

    def broken(person):
        raise RuntimeError("module down")

    home.register(provider)
    home.register(broken)
    try:
        r = api(people["client"]).get("/v1/home")
        d = r.json()
        assert r.status_code == 200
        kinds = [i["kind"] for i in d["items"]]
        assert "fee_payment" in kinds and "bank_account" in kinds
        assert d["items"][0]["needs_action"] is True
        assert {f["full_name"] for f in d["family_members"]} == {"Akosua Mensah", "Kojo Mensah"}
        other = api(people["client2"]).get("/v1/home").json()
        assert "fee_payment" not in [i["kind"] for i in other["items"]]
        assert not {f["full_name"] for f in other["family_members"]} & {"Akosua Mensah", "Kojo Mensah"}
    finally:
        home.unregister(provider)
        home.unregister(broken)


# ---------------------------------------------------------------- bank accounts (RUL-24)

def test_bank_account_verification_two_steps(seeded, api, people, mfa, gh):
    """RUL-24: name check, preparer, two other staff with MFA."""
    from evidence.services import store

    ama = people["client"]
    letter = store(data=b"letter", country=gh, uploaded_by=ama, content_type="text/plain")
    r = api(ama).post("/v1/bank-accounts", {"bank_name": "Partner Bank", "account_number": "1234567890",
                                            "account_name": "Mrs Ama Mensah", "evidence": str(letter.pk)},
                      format="json")
    assert r.status_code == 201 and r.json()["name_match"] == "matched"
    assert "account_number" not in r.json() and r.json()["account_number_last4"] == "7890"
    aid = r.json()["id"]
    assert api(ama).post(f"/v1/bank-accounts/{aid}/verifications", {}, format="json").status_code == 403
    cm = api(people["cm"])
    r = cm.post(f"/v1/bank-accounts/{aid}/verifications", {}, format="json")
    assert r.status_code == 200 and r.json()["verification_status"] == "pending"
    mfa(cm, people["cm"])
    assert cm.post(f"/v1/bank-accounts/{aid}/approvals", {}, format="json").json()["code"] == "same-approver"
    for key in ("reviewer", "reviewer2"):
        c = api(people[key])
        mfa(c, people[key])
        r = c.post(f"/v1/bank-accounts/{aid}/approvals", {}, format="json")
    assert r.json()["verification_status"] == "verified"
    assert selectors.verified_bank_account(ama, aid)
    r = api(ama).patch(f"/v1/bank-accounts/{aid}", {"account_number": "1234567899"}, format="json")
    assert r.json()["verification_status"] == "pending"  # any change needs verifying again


def test_professional_adds_own_pay_account(seeded, api, people, mfa, gh):
    """FR-PRO-006, RUL-24 pattern: a professional Tenmina contracts (LW, SV, RN, IN, QS, CE) adds their own pay
    account, in their own name, verified like a client's: a preparer and two other staff."""
    from evidence.services import store

    insp = people["inspector"]
    letter = store(data=b"pay letter", country=gh, uploaded_by=insp, content_type="text/plain")
    body = {"bank_name": "Partner Bank", "account_number": "5566778899", "account_name": insp.full_name.upper(),
            "evidence": str(letter.pk)}
    r = api(insp).post("/v1/bank-accounts", body, format="json")
    assert r.status_code == 201, r.content
    assert r.json()["purpose"] == "professional_pay" and r.json()["name_match"] == "matched"
    aid = r.json()["id"]
    r = api(insp).post("/v1/bank-accounts", {**body, "purpose": "rent_destination"}, format="json")
    assert r.status_code == 403  # a rent account is a client's
    assert api(people["seller"]).post("/v1/bank-accounts", body, format="json").status_code == 403
    other = api(insp).post("/v1/bank-accounts", {**body, "account_name": "Someone Else"}, format="json").json()
    assert other["name_match"] == "mismatch"
    cm = api(people["cm"])
    assert cm.post(f"/v1/bank-accounts/{other['id']}/verifications", {},
                   format="json").json()["code"] == "payee-not-verified"  # nobody overrides a mismatch
    assert cm.post(f"/v1/bank-accounts/{aid}/verifications", {}, format="json").status_code == 200
    for key in ("reviewer", "reviewer2"):
        c = api(people[key])
        mfa(c, people[key])
        r = c.post(f"/v1/bank-accounts/{aid}/approvals", {}, format="json")
    assert r.json()["verification_status"] == "verified"
    assert api(people["client"]).get(f"/v1/bank-accounts/{aid}").status_code == 404


def test_bank_account_name_mismatch_cannot_be_verified(seeded, people):
    """RUL-24, 9.2: nobody can override a mismatch."""
    acct = seeded["bank_accounts"]["wrong"]
    with pytest.raises(PayeeNotVerified):
        services.prepare_bank_verification(acct, people["cm"], evidence=None) if acct.evidence else \
            services.prepare_bank_verification(acct, people["cm"], evidence=seeded["bank_accounts"]["rent"].evidence)
    with pytest.raises(IntegrityError), transaction.atomic():
        BankAccount.objects.filter(pk=acct.pk).update(name_match="matched")
    with pytest.raises(IntegrityError), transaction.atomic():
        BankAccount.objects.filter(pk=acct.pk).update(verification_status="verified")


def test_database_resets_verification_when_number_changes(seeded):
    acct = seeded["bank_accounts"]["rent"]
    BankAccount.objects.filter(pk=acct.pk).update(account_number="0000000001")
    acct.refresh_from_db()
    assert acct.verification_status == "pending"
    with pytest.raises(Exception):
        selectors.verified_bank_account(acct.holder, acct.pk)


# ---------------------------------------------------------------- organisations (US-ACC-011)

def test_organisation_with_several_users(seeded, api, people):
    """US-ACC-011 AC1 and AC3, TC-ACC-011-01."""
    dev = people["developer"]
    c = api(dev)
    r = c.post("/v1/organisations", {"name": "Palm Grove Estates", "kind": "developer", "country": "GH"},
               format="json")
    assert r.status_code == 201 and r.json()["my_org_role"] == "admin"
    oid = r.json()["id"]
    r = c.post("/v1/organisations", {"name": "Not mine", "kind": "insurer", "country": "GH"}, format="json")
    assert r.status_code == 403
    colleague = Person.objects.create_user("sales@example.com", "tenmina-dev-123", full_name="Sales Lead")
    r = c.post(f"/v1/organisations/{oid}/members", {"email": colleague.email}, format="json")
    assert r.status_code == 201 and r.json()["membership"]["person"]["id"] == str(colleague.pk)
    assert selectors.is_member(colleague, oid) and colleague.has_tenmina_role("DV")
    assert api(colleague).get(f"/v1/organisations/{oid}").status_code == 200
    assert api(colleague).post(f"/v1/organisations/{oid}/members", {"email": "a@b.com"},
                               format="json").status_code == 403
    r = c.post(f"/v1/organisations/{oid}/members", {"email": "newhire@example.com"}, format="json")
    assert r.json()["invitation_id"]
    mid = r.json() and Membership.objects.get(organisation_id=oid, person=colleague).pk
    assert c.delete(f"/v1/organisations/{oid}/members/{mid}").status_code == 200
    assert not selectors.is_member(colleague, oid)
    assert api(colleague).get(f"/v1/organisations/{oid}").status_code == 404
    m = Membership.objects.get(organisation_id=oid, person=dev)
    with pytest.raises(Exception):
        services.remove_member(m, dev)  # last administrator


# ---------------------------------------------------------------- representatives (US-ACC-008)

def _own_case(api, people, gh):
    """A real case of the seeded client: the cases module checks that the client owns the subject."""
    from cases.tests.helpers import paid_case

    return paid_case(api, people, gh).pk


def test_representative_named_and_revoked(seeded, api, people, gh):
    """US-ACC-008 AC1 and AC3, TC-ACC-008-01."""
    case = _own_case(api, people, gh)
    other_case = _own_case(api, people, gh)
    ama = people["client"]
    r = api(ama).post("/v1/me/representatives", {"email": "cousin@example.com", "full_name": "Cousin Ekua",
                                                 "subject_type": "case", "subject_id": str(case)}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "pending" and r.json()["read_only"] is True
    p = services.register(email="cousin@example.com", password="a-long-password-1", full_name="Cousin Ekua",
                          phone="+233240000300", privacy_notice_version="1.0")
    assert selectors.is_representative(p, "case", case)
    assert not selectors.is_representative(p, "case", other_case)
    assert api(p).get("/v1/me/represented").json()[0]["subject_id"] == str(case)
    gid = r.json()["id"]
    assert api(people["client2"]).delete(f"/v1/me/representatives/{gid}").status_code == 404
    assert api(ama).delete(f"/v1/me/representatives/{gid}").status_code == 204
    assert not selectors.is_representative(p, "case", case)


def test_representative_cannot_hold_release_rights_or_be_staff(seeded, api, people, gh):
    """TC-ACC-008-02."""
    r = api(people["client"]).post("/v1/me/representatives", {"email": people["reviewer"].email,
                                                              "subject_type": "case",
                                                              "subject_id": str(_own_case(api, people, gh))},
                                   format="json")
    assert r.status_code == 409
    fam = people["family"]
    RoleGrant.objects.create(person=fam, role="RV")
    with pytest.raises(Exception) as e:
        services.request_rights(by=people["admin"], person=fam, right="RR")
    assert e.value.code == "separation-of-duties"


def test_owner_check_registry(seeded, api, people):
    previous = services._owner_checks.get("project")  # PRJ's own check, if built, is put back afterwards
    services.register_owner_check("project", lambda person, sid: False)
    try:
        r = api(people["client"]).post("/v1/me/representatives", {"email": "x@example.com", "subject_type": "project",
                                                                  "subject_id": str(uuid.uuid4())}, format="json")
        assert r.status_code == 404
        r = api(people["client"]).post("/v1/me/representatives", {"email": "x@example.com", "subject_type": "case",
                                                                  "subject_id": str(uuid.uuid4())}, format="json")
        assert r.status_code == 404  # the cases module refuses a case the client does not own
    finally:
        services._owner_checks.pop("project")
        if previous is not None:
            services.register_owner_check("project", previous)


# ---------------------------------------------------------------- vetting (FR-CARE-002, RUL-31)

def test_vetting_needs_national_id_references_and_background(seeded, api, people, gh):
    from evidence.services import store

    agent = people["agent"]
    v = Vetting.objects.get(person=agent, kind="errand_agent")
    cm = api(people["cm"])
    r = cm.post(f"/v1/vettings/{v.pk}/complete")
    assert r.status_code == 409 and len(r.json()["blocking_reasons"]) == 2
    ev1 = store(data=b"refs", country=gh, uploaded_by=people["cm"], content_type="text/plain")
    ev2 = store(data=b"police", country=gh, uploaded_by=people["cm"], content_type="text/plain")
    r = cm.patch(f"/v1/vettings/{v.pk}", {"references_evidence": str(ev1.pk),
                                          "background_check_evidence": str(ev2.pk)}, format="json")
    assert r.status_code == 200, r.content
    r = cm.post(f"/v1/vettings/{v.pk}/complete")
    assert r.status_code == 200 and r.json()["status"] == "vetted" and r.json()["valid_until"]
    assert selectors.is_vetted(agent, "errand_agent")
    assert api(agent).get("/v1/vettings").json()["items"][0]["id"] == str(v.pk)
    assert api(agent).post(f"/v1/vettings/{v.pk}/revoke", {"reason": "x"}, format="json").status_code == 403
    r = cm.post(f"/v1/vettings/{v.pk}/revoke", {"reason": "Complaint upheld"}, format="json")
    assert r.json()["status"] == "revoked"


def test_vetting_blocked_by_failed_national_id(seeded, people, gh):
    """TC-RUL-31-04."""
    from evidence.services import store

    newbie = Person.objects.create_user("carer2@example.com", "tenmina-dev-123", full_name="New Carer")
    ev = store(data=b"x", country=gh, uploaded_by=people["cm"], content_type="text/plain")
    v = services.create_vetting(people["cm"], newbie, kind="carer", national_id_check=seeded["national_id_checks"][
        "consenting"], references_evidence=ev, background_check_evidence=ev)
    with pytest.raises(RuleBlocked) as e:
        services.complete_vetting(v, people["cm"])
    assert e.value.blocking_reasons[0]["rule"] == "RUL-31"
    with pytest.raises(Exception):
        services.create_vetting(people["cm"], newbie, kind="carer")  # one live vetting per kind
