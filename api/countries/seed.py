from django.utils import timezone

from .models import Country, CountryConfig

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
}


def run(ctx):
    gh, _ = Country.objects.get_or_create(code="GH", defaults=dict(
        name="Ghana", currency="GHS", timezone="Africa/Accra", status="active", activated_at=timezone.now(),
        data_location_ruling="Act 843: working assumption, af-south-1 [TO VERIFY]"))
    ng, _ = Country.objects.get_or_create(code="NG", defaults=dict(
        name="Nigeria", currency="NGN", timezone="Africa/Lagos", status="draft"))
    if not gh.configs.exists():
        CountryConfig.objects.create(country=gh, version=1, status="published", data=GHANA_CONFIG,
                                     published_at=timezone.now())
    if not ng.configs.exists():
        data = dict(GHANA_CONFIG, currency="NGN", phone_prefix="+234",
                    national_id={"system": "NIN (NIMC)", "provider": "[TO VERIFY]"},
                    land_registry={"name": "Lagos State Lands Bureau", "search_channel": "[TO VERIFY]"})
        CountryConfig.objects.create(country=ng, version=1, status="draft", data=data)
    ctx["gh"], ctx["ng"] = gh, ng
