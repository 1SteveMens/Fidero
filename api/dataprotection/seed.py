"""DPR development and demo data: the privacy notice and its acceptances,
retention rules per data class (periods [TO VERIFY], Q-08), data
locations, the catalogue for acc_ and dpr_ tables, consents, subject
requests, a legal hold and a bulk export waiting for approval."""
from datetime import timedelta

from django.utils import timezone

from accounts.seed import demo_id, open_request

from .models import (BulkExport, Consent, DataCatalogueEntry, DataLocation, DataRequest, LegalHold,
                     PrivacyAcceptance, PrivacyNotice, RetentionRule)

NOTICE_V1 = """How Tenmina uses your data (version 1.0, working draft for legal review [TO VERIFY])

We collect your name, email, phone number and the details of the work you ask us to do.
We use them to check land, houses and institutions, to arrange payments through a licensed bank,
and to keep you informed. A licensed bank holds your money, not Tenmina.
We keep records as the law requires, then delete or anonymise them.
You can ask for a copy of your data, ask us to correct it, or delete your account at any time."""

# data class, period_days (None = [TO VERIFY]), anchor, action, kept_on_deletion, description, reason
RULES = [
    ("case", None, "case_release", "anonymise", True, "Reports, evidence and signatures of your cases",
     "The law and our insurer need these records for the limitation period."),
    ("consent_recordings", None, "case_release", "delete", True, "Consent videos recorded on your cases",
     "They prove that recordings were lawful and are kept as long as the case."),
    ("escrow_payment", None, "escrow_close", "anonymise", True, "Escrow records, instructions and receipts",
     "Tax and banking law require them."),
    ("professional_payables", None, "tax_year_end", "anonymise", True, "Pay records of contracted professionals",
     "Tax law requires them."),
    ("account", None, "account_closure", "anonymise", False, "Your profile and preferences", ""),
    ("family", None, "removal", "anonymise", False, "Family members you added", ""),
    ("safety", None, "creation", "delete", True, "Safety incidents and threat logs",
     "They protect staff and are kept with restricted access."),
    ("health_care", None, "creation", "delete", True, "Hospital invoices, care plans and visit records",
     "They are kept with restricted access for as long as health law requires."),
    ("tenancy", None, "tenancy_end", "anonymise", True, "Tenancy agreements and rent records",
     "They may be needed after the tenancy ends."),
    ("identity_documents", None, "handover", "delete", False, "Identity documents handled in errands", ""),
    ("insurance", None, "policy_end", "delete", True, "Insurance applications and policy documents",
     "The insurer's policy terms require them."),
    ("audit", None, "creation", "anonymise", True, "The audit log",
     "It holds record numbers, not your name, and proves who did what."),
    ("marketing", 730, "last_contact", "delete", False, "Leads and marketing consent",
     "24 months from last contact (working assumption from 01 C5.2)."),
    ("payee", None, "escrow_close", "anonymise", True, "Bank details of people and institutions paid",
     "Banking law requires them."),
]

TABLE_PURPOSES = {
    "acc_person": ("account", True, "Identify, sign in and contact the account holder"),
    "acc_role_grant": ("account", False, "Decide what each person may see and do"),
    "acc_rights_request": ("account", False, "Two administrators grant release and payment rights"),
    "acc_refresh_token": ("account", False, "Keep app users signed in"),
    "acc_one_time_code": ("account", False, "Confirm email and phone, sign in by code"),
    "acc_invitation": ("account", True, "Invite staff, professionals and sellers"),
    "acc_organisation": ("account", False, "Organisation accounts"),
    "acc_membership": ("account", False, "People who work for an organisation"),
    "acc_professional_licence": ("account", True, "Only licensed professionals sign (RUL-20)"),
    "acc_identity_check": ("account", True, "The client's own identity check (FR-ACC-004)"),
    "acc_national_id_check": ("case", True, "National identity checks of parties and payees (RUL-31)"),
    "acc_representative_grant": ("account", True, "Read-only representatives (FR-ACC-008)"),
    "acc_family_member": ("family", True, "People the client pays for or cares for"),
    "acc_bank_account": ("payee", True, "The client's own account, e.g. for rent (RUL-24)"),
    "acc_vetting": ("account", True, "Vetting of carers and agents"),
    "dpr_privacy_notice": ("account", False, "Privacy notice versions"),
    "dpr_privacy_acceptance": ("account", True, "Proof of notice acceptance"),
    "dpr_consent": ("consent_recordings", True, "Consents given and withdrawn"),
    "dpr_request": ("account", True, "Access, correction and deletion requests"),
    "dpr_retention_rule": ("audit", False, "Retention configuration"),
    "dpr_retention_run": ("audit", False, "Retention sweep log"),
    "dpr_legal_hold": ("case", False, "Legal holds"),
    "dpr_bulk_export": ("audit", False, "Bulk export approvals"),
    "dpr_data_catalogue": ("audit", False, "The data catalogue"),
    "dpr_data_location": ("audit", False, "Where data lives"),
}
NON_PERSONAL = {"id", "created_at", "updated_at", "row_version", "status", "country_id"}


def _notice(people):
    n = PrivacyNotice.objects.filter(country__isnull=True, version="1.0").first()
    if n is None:
        n = PrivacyNotice.objects.create(version="1.0", title="How Tenmina uses your data",
                                         summary="What we collect, why, who holds your money, and your rights.",
                                         text=NOTICE_V1, status="published", published_at=timezone.now(),
                                         published_by=people["admin"])
    for p in people.values():
        PrivacyAcceptance.objects.get_or_create(person=p, notice=n, defaults={"version": n.version,
                                                                             "source": "signup"})
    return n


def _rules(people):
    for dc, days, anchor, action, kept, desc, reason in RULES:
        RetentionRule.objects.get_or_create(country=None, data_class=dc, status="active", defaults=dict(
            period_days=days, anchor=anchor, action=action, kept_on_deletion=kept, description=desc, reason=reason,
            updated_by=people["admin"]))


def _locations(gh):
    for service, vendor, region, classes in [
        ("Database", "AWS RDS PostgreSQL", "af-south-1 [TO VERIFY]", ["account", "case", "escrow_payment"]),
        ("Evidence store", "AWS S3 with Object Lock", "af-south-1 [TO VERIFY]", ["case", "consent_recordings"]),
        ("Backups", "AWS Backup", "second region [TO VERIFY]", ["account", "case"]),
        ("Email", "Email provider [TO VERIFY]", "[TO VERIFY]", ["account"]),
        ("SMS and WhatsApp", "Messaging provider [TO VERIFY]", "[TO VERIFY]", ["account", "family"]),
        ("National identity checks", "NIA verification platform [TO VERIFY]", "Ghana", ["case"]),
    ]:
        DataLocation.objects.get_or_create(country=gh, service=service, defaults=dict(
            vendor=vendor, region=region, cell="gh-1", data_classes=classes,
            transfer_basis="Act 843 [TO VERIFY]"))


def _catalogue():
    from django.apps import apps

    for model in apps.get_models():
        t = model._meta.db_table
        if t not in TABLE_PURPOSES:
            continue
        dc, personal, purpose = TABLE_PURPOSES[t]
        for f in model._meta.concrete_fields:
            DataCatalogueEntry.objects.get_or_create(table_name=t, field_name=f.column, defaults=dict(
                purpose=purpose, data_class=dc, personal=personal and f.column not in NON_PERSONAL))


def _consents(gh, people):
    from accounts.seed import _evidence

    client = people["client"]
    if not Consent.objects.filter(person=client, purpose="partner_status").exists():
        Consent.objects.create(country=gh, person=client, purpose="partner_status", text_version="1",
                               partner_client_id=demo_id("partner:bank"), recorded_by=client)
        Consent.objects.create(country=gh, person=client, purpose="marketing", text_version="1", recorded_by=client,
                               withdrawn_at=timezone.now(), withdrawn_by=client)
    video = _evidence(gh, people["lawyer"], "consent-video-family-head-demo.txt",
                      "Stand-in for a consent video of the family head (demo)")
    if not Consent.objects.filter(purpose="video_recording", recording_evidence=video).exists():
        Consent.objects.create(country=gh, subject_name="Nana Kofi Asare (family head)", purpose="video_recording",
                               text_version="1", recording_evidence=video, case_id=demo_id("case:ama-plot"),
                               role_in_recording="family head", recorded_by=people["lawyer"])


def _requests(gh, people):
    today = timezone.localdate()
    if not DataRequest.objects.filter(subject=people["client2"], type="access").exists():
        DataRequest.objects.create(country=gh, subject=people["client2"], requested_by=people["client2"],
                                   type="access", source="portal", details="Please send me a copy of my data.",
                                   due_on=today + timedelta(days=30))
    if not DataRequest.objects.filter(subject=people["client"], type="correction").exists():
        DataRequest.objects.create(country=gh, subject=people["client"], requested_by=people["admin"],
                                   type="correction", source="staff", details="Correct the spelling of the name.",
                                   due_on=today + timedelta(days=30), status="completed",
                                   completed_at=timezone.now(), completed_by=people["admin"],
                                   corrections=[{"field": "full_name", "at": timezone.now().isoformat()}])
    case_id = demo_id("case:disputed-plot")
    if not LegalHold.objects.filter(subject_type="case", subject_id=case_id).exists():
        LegalHold.objects.create(country=gh, subject_type="case", subject_id=case_id, placed_by=people["lawyer"],
                                 reason="Seller has threatened a claim over the boundary (demo).")
    if not BulkExport.objects.filter(purpose__startswith="Demo").exists():
        be = BulkExport.objects.create(country=gh, requested_by=people["admin"],
                                       purpose="Demo: client list for the webinar invitation (opted in only)",
                                       scope={"roles": ["CL"], "fields": ["full_name", "email"]})
        be.approval_request = open_request("bulk_export", be.pk, people["admin"], country=gh,
                                           summary="Bulk export of full_name, email for CL")
        be.save(update_fields=["approval_request"])


def run(ctx):
    people = ctx["people"]
    gh = ctx["gh"]
    ctx["privacy_notice"] = _notice(people)
    _rules(people)
    _locations(gh)
    _catalogue()
    _consents(gh, people)
    _requests(gh, people)
    ctx["dpr_demo_hold_case_id"] = demo_id("case:disputed-plot")

