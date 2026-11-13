"""ADM demo data: flags, versioned templates, prices, guide rates, partners,
locked texts, settings, app versions and changes in several states.
Every price, rate and threshold is a working assumption [TO VERIFY]."""
from datetime import timedelta

from django.utils import timezone

from .models import (
    AppVersion, ChangeRequest, ConfigVersion, FeatureFlag, FxRate, LockedTextVersion, Partner, Price,
)

# Development defaults: every line on so the whole workflow can be tried.
# Production defaults are Off (document 06, 2.6); see docs.
DEV_ON = [
    "escrow.enabled", "escrow.manual_confirmation", "escrow.bank_statement_import", "escrow.partial_release",
    "listings.enabled", "payments.mobile_money", "identity.provider_check", "geo.satellite_monitoring",
    "geo.ghana_post_gps", "partner_api.enabled", "mobile.capture", "projects.funds", "building.construction",
    "lines.fee", "lines.care", "lines.pmg", "lines.tsk", "lines.ins", "lines.evt", "listings.family_and_stool",
    "records.enabled",
]
DEV_OFF = ["escrow.bank_api", "maintenance.read_only", "escrow.instructions_paused", "pro.payment_runs_paused",
           "country.ng"]

def _case_template():
    """The land case template in CASE's own format, so it passes cases.templates.validate at publication."""
    from cases.templates import DEFAULT_TEMPLATES

    return DEFAULT_TEMPLATES["land"]


def _errand_catalogue():
    """TSK's complete demo catalogue (every item orderable), so it passes errands.catalogue.validate."""
    from errands.seed import CATALOGUE

    return CATALOGUE


def _report_template():
    """The land report template in RPT's format (sections 1 to 14, section 12 locked)."""
    from reports.templates import DEFAULT_TEMPLATES

    return DEFAULT_TEMPLATES["land"]


CONDITION_SET = {"conditions": [
    {"key": "family_consent", "text": "Family consent recorded"},
    {"key": "fresh_search", "text": "Fresh official search within the window"},
    {"key": "indenture_signed", "text": "Indenture signed by the vendor and witnessed"},
]}
MILESTONE_SCHEDULE = {"milestones": [  # standard schedule, shares are assumptions [TO VERIFY]
    {"key": "mobilisation", "name": "Mobilisation", "share_pct": 10},
    {"key": "foundation", "name": "Foundation", "share_pct": 15},
    {"key": "blocks", "name": "Blockwork", "share_pct": 20},
    {"key": "lintel", "name": "Lintel", "share_pct": 10},
    {"key": "roof", "name": "Roof", "share_pct": 15},
    {"key": "finishing", "name": "Finishing", "share_pct": 15},
    {"key": "handover", "name": "Handover", "share_pct": 10},
    {"key": "retention", "name": "Retention", "share_pct": 5},
]}
TIERS = {"tiers": [{"code": "basic", "name": "Basic check"}, {"code": "standard", "name": "Standard verification"},
                   {"code": "premium", "name": "Premium verification with survey"}]}

SCOPE_TEXT = ("This report records what Tenmina's professionals found in the official records and on site on the "
              "dates shown. It is not a guarantee of title. It covers only the plot and documents named. "
              "[Working text, TO VERIFY by the lawyer and insurer.]")
TERMS_TEXT = ("Tenmina verifies, shows evidence and sends payment instructions to a licensed bank. Tenmina never "
              "holds your money. [Working text, TO VERIFY by the lawyer.]")
PRIVACY_TEXT = "How Tenmina uses and keeps your personal data. [Working text, TO VERIFY by the lawyer.]"
ESCROW_TEXT = ("The partner bank holds the money as escrow agent and pays only on the instructions approved under "
               "these terms. [Working text, TO VERIFY by the lawyer.]")


def _flags():
    for name in DEV_ON:
        FeatureFlag.objects.get_or_create(name=name, country=None, defaults={"enabled": True, "owner": "founder"})
    for name in DEV_OFF:
        FeatureFlag.objects.get_or_create(name=name, country=None, defaults={"enabled": False, "owner": "founder"})
    FeatureFlag.objects.get_or_create(name="app.fee_payment_mode", country=None,
                                      defaults={"enabled": True, "value": "web"})


def _approve(req, approver):
    from core import approvals

    return approvals.decide(req, approver, mfa_at=timezone.now(), note="Seed approval")


def _evidence(gh, admin, name):
    from evidence.services import store

    return store(data=f"Signed approval: {name} [demo document]".encode(), country=gh, uploaded_by=admin,
                 content_type="text/plain", original_name=f"{name}.txt", description=name)


def _published_text(kind, gh, admin, admin2, text, title, insurer=False):
    from . import services

    ltv = services.propose_locked_text(kind=kind, country=gh, text=text, title=title, by=admin)
    services.record_signoff(ltv, party="lawyer", approved_by_name="Counsel for Tenmina [TO VERIFY]",
                            evidence=_evidence(gh, admin, f"lawyer-{kind}"), by=admin)
    if insurer or kind == "scope_statement":
        services.record_signoff(ltv, party="insurer", approved_by_name="Insurer partner [TO VERIFY]",
                                evidence=_evidence(gh, admin, f"insurer-{kind}"), by=admin)
    req = services.submit_locked_text(ltv, by=admin)
    _approve(req, admin2)
    ltv.refresh_from_db()
    return ltv


def run(ctx):
    from countries.services import seed_publish

    from . import services

    _flags()
    gh, ng = ctx["gh"], ctx["ng"]
    people = ctx["people"]
    admin, admin2 = people["admin"], people["admin2"]

    # Versioned configuration (FR-ADM-001)
    refs = {"config_versions": {}, "locked_texts": {}, "partners": {}}
    if not ConfigVersion.objects.filter(country=gh).exists():
        case_template = _case_template()
        for kind, content, line in (("case_template", case_template, "land"),
                                    ("report_template", _report_template(), "land"),
                                    ("condition_set", CONDITION_SET, "land"),
                                    ("milestone_schedule", MILESTONE_SCHEDULE, "building"),
                                    ("tier_catalogue", TIERS, "land"),
                                    ("holiday_calendar", {"dates": gh.config().get("holiday_calendar", [])}, ""),
                                    ("errand_catalogue", {"errands": _errand_catalogue()}, "tsk")):
            cv = services.create_config_version(kind=kind, content=content, by=admin, country=gh, product_line=line,
                                                name=f"Ghana {kind.replace('_', ' ')}")
            services.publish_config_version(cv, by=admin)
        draft = dict(case_template, tasks=case_template["tasks"] + [
            {"key": "recheck", "title": "Random re-check by a different professional", "role": "RV", "due_days": 20,
             "evidence": [], "after": [], "site_visit": False, "search": "", "review": False,
             "client_message": "A different professional re-checked the file on {date}."}])
        services.create_config_version(kind="case_template", content=draft, by=admin, country=gh,
                                       product_line="land", name="Ghana case template with re-check (draft)")
    for cv in ConfigVersion.objects.filter(country=gh, state="published"):
        refs["config_versions"][cv.kind] = str(cv.pk)

    # Prices and guide rates (FR-ADM-002); an old standard price shows history.
    if not Price.objects.filter(country=gh).exists():
        services.set_price(country=gh, tier="standard", amount="300.00", currency="USD", by=admin,
                           note="Launch price [TO VERIFY]")
        for tier, amt in (("basic", "150.00"), ("standard", "350.00"), ("premium", "650.00")):
            services.set_price(country=gh, tier=tier, amount=amt, currency="USD", by=admin, note="[TO VERIFY]")
        services.set_price(country=gh, tier="standard", amount="300.00", currency="USD", by=admin,
                           audience="diaspora", note="Diaspora launch offer [TO VERIFY]")
        services.set_price(country=gh, product_line="fee", tier="per_payment", amount="12.00", currency="USD",
                           by=admin, note="Family payment service charge [TO VERIFY]")
        services.set_price(country=gh, product_line="care", tier="monthly", amount="90.00", currency="USD",
                           by=admin, note="[TO VERIFY]")
    if not FxRate.objects.filter(country=gh).exists():
        services.set_fx_rate(country=gh, base="USD", quote="GHS", rate="15.20", by=admin,
                             rate_date=timezone.localdate() - timedelta(days=1), source="manual")
        services.refresh_fx([gh])
        services.set_fx_rate(country=gh, base="GBP", quote="GHS", rate="19.60", by=admin, source="manual")

    # Partner registry (FR-ADM-003)
    if not Partner.objects.filter(country=gh).exists():
        bank, _ = services.create_partner(country=gh, kind="escrow_bank", name="Tenmina Partner Bank [TO VERIFY]",
                                          by=admin, contact_email="escrow@partnerbank.example",
                                          adapter_port="bank_instructions",
                                          details={"agreement": "three-party escrow [TO VERIFY]"})
        cr = services.request_bank_change(bank, by=admin, bank_name="Partner Bank [TO VERIFY]",
                                          bank_branch="Head office", account_name="Partner Bank Escrow Programme",
                                          account_number="9040001234567", reason="Programme escrow account")
        _approve(cr.approval_request, admin2)
        op, _ = services.create_partner(country=gh, kind="operating_bank", name="Tenmina operating account",
                                        by=admin, details={"file_format": "bank CSV [TO VERIFY]"})
        services.request_bank_change(op, by=admin, bank_name="Operating Bank [TO VERIFY]", account_name="Tenmina Ltd",
                                     account_number="1020009876543", reason="Pays professionals (ADR-23)")
        services.create_partner(country=gh, kind="payment_provider", name="Card and mobile money provider [TO VERIFY]",
                                by=admin, adapter_port="payments")
        services.create_partner(country=gh, kind="identity", name="National Identification Authority", by=admin,
                                is_national_id_system=True, adapter_port="national_id")
        services.create_partner(country=gh, kind="messaging", name="SMS and WhatsApp provider [TO VERIFY]",
                                by=admin, adapter_port="messaging")
        services.create_partner(country=gh, kind="registry", name="Lands Commission", by=admin,
                                details={"tenmina_account_ref": "[TO VERIFY]", "channels": ["online", "office"]})
        services.create_partner(country=gh, kind="insurer", name="Insurer partner [TO VERIFY]", by=admin)
        services.create_partner(country=gh, kind="rate_source", name="Reference rate source [TO VERIFY]", by=admin,
                                details={"publishes": "reference", "corridors": ["USD/GHS", "GBP/GHS"]})
        services.create_partner(country=gh, kind="professional", name="Nana Lawyer", by=admin,
                                person=people["lawyer"], licence_body="General Legal Council",
                                licence_number="[TO VERIFY]")
        services.create_partner(country=gh, kind="inspector", name="Kwesi Inspector", by=admin,
                                person=people["inspector"])
        sup, _ = services.create_partner(country=gh, kind="supplier", name="Old Cement Supplier", by=admin,
                                         contact_phone="+233200000001")
        services.set_partner_status(sup, active=False, by=admin, reason="Failed the background check (demo)")
    for p in Partner.objects.filter(country=gh, status="active", kind__in=("escrow_bank", "identity", "messaging",
                                                                        "registry", "payment_provider")):
        refs["partners"][p.kind] = str(p.pk)

    # Locked texts (FR-ADM-004)
    if not LockedTextVersion.objects.filter(country=gh).exists():
        _published_text("scope_statement", gh, admin, admin2, SCOPE_TEXT, "Scope and limitations", insurer=True)
        _published_text("terms", gh, admin, admin2, TERMS_TEXT, "Terms of service")
        _published_text("privacy_notice", gh, admin, admin2, PRIVACY_TEXT, "Privacy notice")
        _published_text("escrow_terms", gh, admin, admin2, ESCROW_TEXT, "Escrow terms")
        v2 = services.propose_locked_text(kind="scope_statement", country=gh, by=admin, title="Scope and limitations",
                                          text=SCOPE_TEXT + " It does not cover customary claims not on record.")
        services.record_signoff(v2, party="lawyer", approved_by_name="Counsel for Tenmina [TO VERIFY]",
                                evidence=_evidence(gh, admin, "lawyer-scope-v2"), by=admin)
    if not LockedTextVersion.objects.filter(country=gh, kind="insurance_statement").exists():
        # Texts INS and PRJ show word for word (RUL-25, FR-PRJ-005); the modules' constants are the fallback.
        from insurance.services import DEFAULT_STATEMENT
        from projectfunds.models import NO_ADVICE_STATEMENT

        _published_text("insurance_statement", gh, admin, admin2, DEFAULT_STATEMENT, "Insurance statement",
                        insurer=True)
        _published_text("no_advice_statement", gh, admin, admin2, NO_ADVICE_STATEMENT, "No investment advice")
    for lt in LockedTextVersion.objects.filter(country=gh, status="published"):
        refs["locked_texts"][lt.kind] = str(lt.pk)

    # Ghana configuration v2 names its templates, texts and partners (FR-CTY-001).
    current = gh.configs.filter(status="published").order_by("-version").first()
    if current is not None and "refs" not in current.data:
        seed_publish(gh, dict(current.data, refs=refs), by=admin)

    # Settings (FR-ADM-005): one applied by one admin, one release-affecting change waiting.
    from .models import Setting

    if not Setting.objects.exists():
        services.change_setting(key="ntf_amount_threshold", value={"amount": "500.00", "currency": "USD"}, by=admin,
                                reason="Working threshold [TO VERIFY]")
        services.change_setting(key="receipt_target_days", value=10, by=admin, country=gh)
        services.change_setting(key="checkin_radius_m", value=100, by=admin, country=gh)
        _, cr = services.change_setting(key="payee_cooling_off_hours", value=72, by=admin, country=gh)
        _approve(cr.approval_request, admin2)
        services.change_setting(key="fresh_search_window_days", value=21, by=admin, country=gh,
                                reason="Lawyer suggests 21 days [TO VERIFY]")

    # App versions (FR-APP-006): store links [TO VERIFY].
    if not AppVersion.objects.exists():
        for app in ("client", "field"):
            for platform in ("ios", "android"):
                AppVersion.objects.create(app=app, platform=platform, min_version="1.0.0", latest_version="1.2.0",
                                          store_url=f"https://stores.example/{app}/{platform} [TO VERIFY]",
                                          changed_by=admin)
        services.set_app_version(app="field", platform="android", min_version="1.1.0", by=admin,
                                 reason="1.0 loses queued items on Android 8 (demo)")

    # A safety flag waiting for a second administrator (06 2.6).
    if not ChangeRequest.objects.filter(kind="feature_flag").exists():
        services.change_flag(name="escrow.bank_api", enabled=True, by=admin, reason="Bank API passed UAT (demo)")
    ctx["admin_refs"] = refs
