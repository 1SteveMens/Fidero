"""Seeded people for development. Password for all: tenmina-dev-123.
MFA secret for staff and professionals is fixed so tests and demos can
compute codes. Release and payment rights are recorded as asked for by the
founder and approved by two other administrators.

Also seeds ACC demo journeys in several states: organisations and
memberships, licences, identity checks, national identity checks,
family members, bank accounts, vetting, an invitation, a representative
and a waiting rights request. Every figure is a working assumption."""
import uuid
from datetime import date, timedelta

from django.utils import timezone

from core.models import Approval, ApprovalRequest

from . import services
from .models import (BankAccount, FamilyMember, IdentityCheck, Invitation, Membership, NationalIdCheck,
                     Organisation, Person, ProfessionalLicence, RepresentativeGrant, RightsRequest, RoleGrant, Vetting)
from .normalise import bidx, normalise_name

DEV_PASSWORD = "tenmina-dev-123"
DEV_MFA_SECRET = "JBSWY3DPEHPK3PXP"
NS = uuid.UUID("6f1d0c1e-7e2a-4c55-9a51-1e3f0a7b5c01")  # demo ids are uuid5 under this namespace

# key, email, name, roles, residence, phone (all phone numbers are fictional)
PEOPLE = [
    ("client", "ama@example.com", "Ama Mensah", ["CL"], "GB", "+447700900101"),
    ("client2", "kofi@example.com", "Kofi Boateng", ["CL"], "US", "+12025550142"),
    ("cm", "cm@tenmina.test", "Esi Case Manager", ["CM"], "GH", "+233200000001"),
    ("reviewer", "rv1@tenmina.test", "Yaw Reviewer", ["RV", "RR", "PY"], "GH", "+233200000002"),
    ("reviewer2", "rv2@tenmina.test", "Akosua Reviewer", ["RV", "RR", "PY"], "GH", "+233200000003"),
    ("admin", "admin@tenmina.test", "Kwame Admin", ["AD", "RR", "PY"], "GH", "+233200000004"),
    ("admin2", "admin2@tenmina.test", "Abena Admin", ["AD", "RR", "PY"], "GH", "+233200000005"),
    ("admin3", "admin3@tenmina.test", "Ekow Admin", ["AD", "DPO"], "GH", "+233200000006"),
    ("founder", "founder@tenmina.test", "Nii Founder", ["AD"], "GH", "+233200000007"),
    ("lawyer", "lawyer@example.com", "Nana Lawyer", ["LW"], "GH", "+233240000001"),
    ("surveyor", "surveyor@example.com", "Kojo Surveyor", ["SV"], "GH", "+233240000002"),
    ("runner", "runner@example.com", "Efua Runner", ["RN"], "GH", "+233240000003"),
    ("inspector", "inspector@example.com", "Kwesi Inspector", ["IN"], "GH", "+233240000004"),
    ("qs", "qs@example.com", "Adjoa Quantity Surveyor", ["QS"], "GH", "+233240000005"),
    ("carer", "carer@example.com", "Afia Carer", ["CE"], "GH", "+233240000006"),
    ("agent", "agent@example.com", "Yaa Errand Agent", ["CE"], "GH", "+233240000007"),
    ("seller", "seller@example.com", "Ato Estates Ltd", ["SE"], "GH", "+233240000008"),
    ("contractor", "builder@example.com", "Kobby Builders", ["CT"], "GH", "+233240000009"),
    ("family", "auntie@example.com", "Auntie Comfort", ["FM"], "GH", "+233240000010"),
    ("institution", "bursar@example.com", "School Bursar", ["IC"], "GH", "+233240000011"),
    ("partner", "partner@example.com", "Partner Bank API", ["PT"], "GH", "+233240000012"),
    ("insurer", "insurer@example.com", "Insurer Partner", ["IS"], "GH", "+233240000013"),
    ("tenant", "tenant@example.com", "Tenant Kwabena", ["TN"], "GH", "+233240000014"),
    ("developer", "dev@example.com", "Off-plan Developer", ["DV"], "GH", "+233240000015"),
    ("authority", "stool@example.com", "Stool Secretary", ["AR"], "GH", "+233240000016"),
]


def demo_id(name):
    return uuid.uuid5(NS, name)


def _approved_request(subject_type, subject_id, preparer, approvers, country=None, summary=""):
    req = ApprovalRequest.objects.filter(subject_type=subject_type, subject_id=subject_id, status="approved").first()
    if req:
        return req
    now = timezone.now()
    req = ApprovalRequest.objects.create(subject_type=subject_type, subject_id=subject_id, prepared_by=preparer,
                                         required=2, status="approved", closed_at=now, summary=summary,
                                         country=country)
    for i, a in enumerate(approvers):
        Approval.objects.create(request=req, slot=f"approver_{i + 1}", approver=a, decision="approve", mfa_at=now)
    return req


def open_request(subject_type, subject_id, preparer, country=None, summary=""):
    """Seed only: an open approval request without an audit entry, so a fresh
    database starts with an empty audit chain."""
    req = ApprovalRequest.objects.filter(subject_type=subject_type, subject_id=subject_id, status="open").first()
    return req or ApprovalRequest.objects.create(subject_type=subject_type, subject_id=subject_id,
                                                 prepared_by=preparer, required=2, summary=summary, country=country)


def _evidence(gh, by, name, text):
    """Seed only: the same hashing and write-once storage as
    evidence.services.store(), without an audit entry (see open_request)."""
    import hashlib

    from core.adapters import get_adapter
    from core.ids import uuid7
    from evidence.models import Evidence

    ev = Evidence.objects.filter(original_name=name, country=gh).first()
    if ev:
        return ev
    data = text.encode()
    eid = uuid7()
    key = f"{gh.code}/seed/{eid}"
    get_adapter("evidence_store").put(key, data)
    return Evidence.objects.create(id=eid, country=gh, sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                                   content_type="text/plain", original_name=name, storage_key=key, source="upload",
                                   uploaded_by=by, scan_status="clean", description=name)


def _people(ctx, gh):
    now = timezone.now()
    for key, email, name, roles, residence, phone in PEOPLE:
        p = Person.objects.filter(email=email).first()
        if not p:
            p = Person.objects.create_user(email, DEV_PASSWORD, full_name=name, home_country=gh,
                                           residence_country=residence, email_verified_at=now)
            for r in roles:
                if r not in ("RR", "PY"):
                    RoleGrant.objects.create(person=p, role=r)
        fields = []
        if not p.email_verified_at:
            p.email_verified_at = now
            fields.append("email_verified_at")
        if not p.phone and not Person.objects.filter(phone=phone).exists():
            p.phone, p.phone_verified_at = phone, now
            fields += ["phone", "phone_verified_at"]
        if services.MFA_REQUIRED_ROLES & set(roles) and not p.mfa_enabled:
            p.mfa_secret, p.mfa_enabled = DEV_MFA_SECRET, True
            fields += ["mfa_secret", "mfa_enabled"]
        if fields:
            p.save(update_fields=fields)
        ctx["people"][key] = p
    people = ctx["people"]
    admin = people["admin"]
    if not admin.is_superuser:
        admin.is_staff = admin.is_superuser = True
        admin.save(update_fields=["is_staff", "is_superuser"])
    # Release and payment rights, each approved by two administrators other than the person.
    for key, _email, _name, roles, _res, _ph in PEOPLE:
        p = people[key]
        for right in ("RR", "PY"):
            if right in roles and right not in p.roles():
                approvers = [people[k] for k in ("admin", "admin2", "admin3") if k != key][:2]
                preparer = people["founder"]
                req = _approved_request("release_rights_grant" if right == "RR" else "payment_rights_grant", p.pk,
                                        preparer, approvers, summary=f"{right} for {p.full_name} (seed)")
                RoleGrant.objects.create(person=p, role=right, granted_by=preparer, approval_request=req)
    return people


def _organisations(gh, people):
    orgs = {}
    for key, name, kind, member in [
        ("ato", "Ato Estates Ltd", "seller", "seller"),
        ("kobby", "Kobby Builders", "contractor", "contractor"),
        ("bank", "Tenmina Partner Bank [TO VERIFY]", "bank", None),
        ("school", "Accra Hills School (demo)", "institution", "institution"),
        ("insurer", "Insurer Partner Ltd (demo)", "insurer", "insurer"),
        ("developer", "Sunrise Homes Developers (demo)", "developer", "developer"),
    ]:
        org, _ = Organisation.objects.get_or_create(name=name, kind=kind, country=gh)
        orgs[key] = org
        if member and not Membership.objects.filter(organisation=org, person=people[member]).exists():
            Membership.objects.create(organisation=org, person=people[member], org_role="admin",
                                      added_by=people["admin"])
    return orgs


def _licences(gh, people):
    today = date.today()
    rows = [("lawyer", "LW", "General Legal Council", "GLC/DEMO/0001", today + timedelta(days=300), "verified"),
            ("surveyor", "SV", "Ghana Institution of Surveyors [TO VERIFY]", "GHIS/DEMO/0002",
             today + timedelta(days=200), "verified"),
            ("qs", "QS", "Ghana Institution of Surveyors [TO VERIFY]", "GHIS/DEMO/0003", today + timedelta(days=20),
             "verified"),
            ("inspector", "IN", "Engineering Council [TO VERIFY]", "EC/DEMO/0004", today + timedelta(days=400),
             "submitted")]
    for key, role, body, number, expires, status in rows:
        if ProfessionalLicence.objects.filter(body=body, number=number).exists():
            continue
        lic = ProfessionalLicence.objects.create(person=people[key], role=role, country=gh, body=body, number=number,
                                                 expires_on=expires)
        if status == "verified":
            lic.status, lic.verified_by, lic.verified_on = "verified", people["admin"], today
            lic.save(update_fields=["status", "verified_by", "verified_on"])


def _identity(gh, people):
    client, client2, cm = people["client"], people["client2"], people["cm"]
    if not IdentityCheck.objects.filter(person=client).exists():
        IdentityCheck.objects.create(country=gh, person=client, method="provider", provider="fake-identity-provider",
                                     provider_reference="IDP-DEMO-0001", provider_result="passed",
                                     document_type="passport", document_number="DEMO12345671", status="passed",
                                     requested_by=client)
        client.id_check_status = "passed"
        client.save(update_fields=["id_check_status"])
    if not IdentityCheck.objects.filter(person=client2).exists():
        IdentityCheck.objects.create(country=gh, person=client2, method="provider", provider="fake-identity-provider",
                                     provider_result="inconclusive", document_type="passport",
                                     document_number="DEMO98765435", status="manual_review", requested_by=client2)
        client2.id_check_status = "manual_review"
        client2.save(update_fields=["id_check_status"])
    checks = {}
    for key, role, name, number, result in [
        ("seller", "seller", "Kwabena Owusu", "GHA-700000001-1", "match"),
        ("grantor", "grantor", "Akua Asantewaa", "GHA-700000002-2", "match"),
        ("consenting", "consenting_party", "Yaw Boateng", "GHA-700000010-0", "not_found"),
        ("carer", "carer", "Afia Carer", "GHA-700000003-3", "match"),
        ("agent", "errand_agent", "Yaa Errand Agent", "GHA-700000005-5", "match"),
        ("payee_down", "payee", "Kojo Mensah", "GHA-700000004-9", "unavailable"),
    ]:
        chk = NationalIdCheck.objects.filter(id_number_bidx=bidx(number), subject_role=role).first()
        if chk is None:
            final = result in ("match", "no_match", "not_found")
            chk = NationalIdCheck.objects.create(
                country=gh, subject_role=role, subject_name=name, subject_name_bidx=bidx(normalise_name(name)),
                id_number=number, id_number_bidx=bidx(number), channel="Ghana Card (NIA)", requested_by=cm,
                result=result, attempts=1, last_attempt_at=timezone.now(),
                provider_reference=f"NIA-DEMO-{key.upper()}" if final else None,
                checked_at=timezone.now() if final else None,
                person=people.get(key) if key in ("carer", "agent") else None,
                context_type="case" if key in ("seller", "grantor", "consenting") else "",
                context_id=demo_id("case:ama-plot") if key in ("seller", "grantor", "consenting") else None)
        checks[key] = chk
    return checks


def _family_and_accounts(gh, people, orgs):
    client = people["client"]
    fams = {}
    for key, name, rel, phone, confirm, status in [
        ("mother", "Akosua Mensah", "mother", "+233240000101", True, "active"),
        ("nephew", "Kojo Mensah", "nephew", "+233240000102", False, "active"),
        ("uncle", "Kwaku Mensah", "uncle", "", False, "removed"),
    ]:
        fm = FamilyMember.objects.filter(client=client, full_name=name).first()
        if fm is None:
            fm = FamilyMember.objects.create(country=gh, client=client, full_name=name, relationship=rel, phone=phone,
                                             address="East Legon, Accra", may_confirm_visits=confirm,
                                             latitude="5.635800", longitude="-0.161400", status=status,
                                             removed_at=timezone.now() if status == "removed" else None)
        fams[key] = fm
    accounts = {}
    letter = _evidence(gh, client, "bank-letter-ama-demo.txt", "Demo bank letter: account name AMA MENSAH")
    for key, number, name, status in [("rent", "0012345678901", "AMA MENSAH", "verified"),
                                      ("second", "0098765432109", "Ama Mensah", "pending"),
                                      ("wrong", "0055555555555", "A. Mensah Enterprise", "unverified")]:
        acct = BankAccount.objects.filter(holder=client, account_number=number).first()
        if acct is None:
            match = "matched" if normalise_name(name) == normalise_name(client.full_name) else "mismatch"
            acct = BankAccount.objects.create(country=gh, holder=client, bank_name="Partner Bank [TO VERIFY]",
                                              account_number=number, account_name=name,
                                              account_name_norm=normalise_name(name), name_match=match,
                                              evidence=letter if status != "unverified" else None,
                                              name_source="bank_letter" if status != "unverified" else "",
                                              verification_status="unverified")
            if status in ("pending", "verified"):
                acct.verification_status = "pending"
                acct.prepared_by = people["cm"]
                acct.save(update_fields=["verification_status", "prepared_by"])
            if status == "verified":
                req = _approved_request("bank_account_verification", acct.pk, people["cm"],
                                        [people["reviewer"], people["reviewer2"]], country=gh)
                acct.approval_request = req
                acct.verification_status = "verified"
                acct.verified_at = timezone.now()
                acct.save(update_fields=["approval_request", "verification_status", "verified_at"])
            elif status == "pending":
                acct.approval_request = open_request("bank_account_verification", acct.pk, people["cm"], country=gh,
                                                     summary="Verify Ama Mensah's second account")
                acct.save(update_fields=["approval_request"])
        accounts[key] = acct
    return fams, accounts


def _vetting(gh, people, checks):
    refs = _evidence(gh, people["cm"], "carer-references-demo.txt", "Two references for Afia Carer (demo)")
    police = _evidence(gh, people["cm"], "carer-police-report-demo.txt", "Police report for Afia Carer (demo)")
    out = {}
    if not Vetting.objects.filter(person=people["carer"], kind="carer").exists():
        out["carer"] = Vetting.objects.create(
            country=gh, person=people["carer"], kind="carer", national_id_check=checks["carer"],
            references_evidence=refs, background_check_evidence=police, checklist_version="[TO VERIFY]",
            status="vetted", created_by=people["cm"], vetted_by=people["reviewer"], vetted_at=timezone.now(),
            valid_until=date.today() + timedelta(days=360))
    if not Vetting.objects.filter(person=people["agent"], kind="errand_agent").exists():
        out["agent"] = Vetting.objects.create(country=gh, person=people["agent"], kind="errand_agent",
                                              national_id_check=checks["agent"], checklist_version="[TO VERIFY]",
                                              created_by=people["cm"])
    return out


def _misc(gh, people):
    admin = people["admin"]
    if not Invitation.objects.filter(email="new.lawyer@example.com").exists():
        Invitation.objects.create(email="new.lawyer@example.com", full_name="Adwoa New Lawyer", roles=["LW"],
                                  country=gh, token_hash=uuid.uuid4().hex, invited_by=admin,
                                  expires_at=timezone.now() + timedelta(hours=72))
    client = people["client"]
    if not RepresentativeGrant.objects.filter(client=client).exists():
        RepresentativeGrant.objects.create(client=client, representative=people["family"],
                                           invited_email=people["family"].email, invited_name="Auntie Comfort",
                                           subject_type="case", subject_id=demo_id("case:ama-plot"), status="active")
        RepresentativeGrant.objects.create(client=client, invited_email="brother.kwesi@example.com",
                                           invited_name="Kwesi Mensah", subject_type="case",
                                           subject_id=demo_id("case:ama-plot"), status="pending")
    if not RightsRequest.objects.filter(person=people["admin3"]).exists():
        rr = RightsRequest.objects.create(person=people["admin3"], right="RR", country=gh, requested_by=admin,
                                          reason="Third approver for releases while staff are on leave")
        rr.approval_request = open_request("release_rights_grant", rr.pk, admin, country=gh,
                                           summary="Give Ekow Admin release rights")
        rr.save(update_fields=["approval_request"])


def run(ctx):
    gh = ctx["gh"]
    people = _people(ctx, gh)
    orgs = _organisations(gh, people)
    _licences(gh, people)
    checks = _identity(gh, people)
    fams, accounts = _family_and_accounts(gh, people, orgs)
    _vetting(gh, people, checks)
    _misc(gh, people)
    ctx["orgs"] = orgs
    ctx["family_members"] = fams
    ctx["bank_accounts"] = accounts
    ctx["national_id_checks"] = checks
    ctx["demo_case_id"] = demo_id("case:ama-plot")
