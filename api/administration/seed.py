from .models import FeatureFlag

# Development defaults: every line on so the whole workflow can be tried.
# Production defaults are Off (document 06, 2.6); see docs.
DEV_ON = [
    "escrow.enabled", "escrow.manual_confirmation", "escrow.bank_statement_import", "escrow.partial_release",
    "listings.enabled", "payments.mobile_money", "identity.provider_check", "geo.satellite_monitoring",
    "geo.ghana_post_gps", "partner_api.enabled", "mobile.capture", "projects.funds", "building.construction",
    "lines.fee", "lines.care", "lines.pmg", "lines.tsk", "lines.ins", "lines.evt", "listings.family_and_stool",
]
DEV_OFF = ["escrow.bank_api", "maintenance.read_only", "escrow.instructions_paused", "pro.payment_runs_paused",
           "country.ng"]


def run(ctx):
    for name in DEV_ON:
        FeatureFlag.objects.get_or_create(name=name, country=None, defaults={"enabled": True, "owner": "founder"})
    for name in DEV_OFF:
        FeatureFlag.objects.get_or_create(name=name, country=None, defaults={"enabled": False, "owner": "founder"})
    FeatureFlag.objects.get_or_create(name="app.fee_payment_mode", country=None,
                                      defaults={"enabled": True, "value": "web"})
