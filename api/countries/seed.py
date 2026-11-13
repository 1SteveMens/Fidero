"""Countries, the first cell and their configuration. Every figure and date
here is a working assumption to verify, not verified data."""
from django.utils import timezone

from .models import Cell, Country, CountryConfig

# Public holidays: from memory of the usual calendar, [TO VERIFY] against the gazette each year.
GHANA_HOLIDAYS_2026 = ["2026-01-01", "2026-01-07", "2026-03-06", "2026-04-03", "2026-04-06", "2026-05-01",
                       "2026-07-01", "2026-08-04", "2026-09-21", "2026-12-04", "2026-12-25", "2026-12-26",
                       "2027-01-01", "2027-01-07", "2027-03-06"]

GHANA_CONFIG = {
    # Every figure here is a working assumption to verify, not verified data.
    "currency": "GHS",
    "languages": ["en", "tw"],
    "phone_prefix": "+233",
    "national_id": {"system": "Ghana Card (NIA)", "provider": "NIA IVSP", "format": "GHA-#########-#"},
    "land_registry": {"name": "Lands Commission", "search_channel": "Tenmina registry account"},
    "payee_lock_cooling_off_hours": 72,
    "release": {"staff_approvals_within_working_days": 1, "bank_pays_within_working_days": 2,
                "client_promise_working_days": 3},
    "fresh_search_window_days": 30,
    "report_tiers": {"basic": {"price": "150.00"}, "standard": {"price": "350.00"}, "premium": {"price": "650.00"}},
    "price_currency": "USD",
    "withholding_tax_rate": "0.075",
    "errand_catalogue": [
        {"code": "birth_cert", "name": "Birth certificate copy", "agency": "Births and Deaths Registry"},
        {"code": "passport_renewal", "name": "Passport renewal support", "agency": "Passport Office"},
        {"code": "land_search", "name": "Official land search", "agency": "Lands Commission"},
        {"code": "business_reg", "name": "Business registration", "agency": "Office of the Registrar of Companies"},
        {"code": "utility_transfer", "name": "Utility account transfer", "agency": "ECG / Ghana Water"},
    ],
    "care_visit_minutes": 60,
    "aml_threshold": {"amount": "10000.00", "currency": "USD"},
    "retention_years": {"case": 7, "evidence": 7, "audit": 10},
    "data_location": "af-south-1 (Cape Town), shared Ghana cell. Act 843 position [TO VERIFY]",
    "weekend_days": [5, 6],
    "holiday_calendar": GHANA_HOLIDAYS_2026,
    "licence_bodies": {"lawyer": "General Legal Council", "surveyor": "Ghana Institution of Surveyors",
                       "quantity_surveyor": "Ghana Institution of Surveyors"},
}


def run(ctx):
    cell, _ = Cell.objects.get_or_create(name="gh-1", defaults=dict(
        aws_region="af-south-1", aws_account="[TO VERIFY]", api_host="api.tenmina.example",
        portal_host="app.tenmina.example", status="active",
        data_location_notes="First cell. Hosts Ghana. Region accepted under Act 843 [TO VERIFY]."))
    gh, _ = Country.objects.get_or_create(code="GH", defaults=dict(
        name="Ghana", currency="GHS", timezone="Africa/Accra", status="active", activated_at=timezone.now(),
        cell=cell, data_location="af-south-1 (Cape Town), shared cell gh-1",
        data_location_ruling="Act 843: working assumption, af-south-1 [TO VERIFY]", evidence_prefix="GH/",
        backup_location="af-south-1 second account [TO VERIFY]", kms_key_alias="alias/tenmina-gh",
        gate_passed=True, gate_decided_at=timezone.now(),
        gate_note="Launch country. R0 manual phase is the gate record [TO VERIFY]."))
    ng, _ = Country.objects.get_or_create(code="NG", defaults=dict(
        name="Nigeria", currency="NGN", timezone="Africa/Lagos", status="draft", cell=cell,
        data_location_ruling="Lawyer's opinion awaited; pattern B assumed until then [TO VERIFY]"))
    if not gh.configs.exists():
        cfg = CountryConfig.objects.create(country=gh, version=1, status="published", data=GHANA_CONFIG,
                                           published_at=timezone.now())
        gh.current_config = cfg
        gh.save(update_fields=["current_config"])
    if not ng.configs.exists():
        data = dict(GHANA_CONFIG, currency="NGN", phone_prefix="+234",
                    national_id={"system": "NIN (NIMC)", "provider": "[TO VERIFY]"},
                    land_registry={"name": "Lagos State Lands Bureau", "search_channel": "[TO VERIFY]"},
                    data_location=None, holiday_calendar=[])
        CountryConfig.objects.create(country=ng, version=1, status="draft", data=data)
    ctx["gh"], ctx["ng"], ctx["cell"] = gh, ng, cell
