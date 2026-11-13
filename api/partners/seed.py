"""PTR demo data: the partner bank's API client (dev secret below), the client's
consent to share status with it, metered calls, a webhook subscription and a
partner order waiting for the client. Limits are working assumptions [TO VERIFY]."""
from django.utils import timezone

DEV_CLIENT_ID = "ptr_demo_partner_bank"
DEV_CLIENT_SECRET = "ptr-dev-secret-change-me"  # development only


def run(ctx):
    from administration.models import Partner
    from dataprotection import services as dpr

    from . import services
    from .models import ApiClient, PartnerOrder, WebhookSubscription, secret_hash

    gh, people = ctx["gh"], ctx["people"]
    admin, client = people["admin"], people["client"]
    bank = Partner.objects.filter(country=gh, kind="escrow_bank").first()
    if bank is None:
        return
    c = ApiClient.objects.filter(client_id=DEV_CLIENT_ID).first()
    if c is None:
        c, _raw = services.create_client(admin, country=gh, partner=bank, name="Partner Bank collateral desk",
                                         scopes=["plot_status.read", "report.read", "orders.write", "usage.read",
                                                 "webhooks.manage"], rate_limit_per_minute=60, monthly_quota=5000,
                                         contact_person=people["partner"])
        ApiClient.objects.filter(pk=c.pk).update(client_id=DEV_CLIENT_ID, secret_sha256=secret_hash(DEV_CLIENT_SECRET))
        c.refresh_from_db()
    ctx["partners"] = {"client": c, "client_id": DEV_CLIENT_ID, "client_secret": DEV_CLIENT_SECRET}
    dpr.give_consent(client, purpose="partner_status", text_version="1", partner_client_id=c.pk, country=gh)
    if not WebhookSubscription.objects.filter(client=c).exists():
        services.subscribe_webhook(c, url="https://partner-bank.example/tenmina/webhooks",
                                   events=["verification.status_changed", "order.completed", "consent.withdrawn"])
    if not c.usage.exists():
        from geo.models import Asset

        a = Asset.objects.filter(country=gh, owner=client).first()
        if a is not None:
            services.plot_status(c, plot_reference=a.reference)
        services.plot_status(c, plot_reference="NO-SUCH-PLOT")
    if not PartnerOrder.objects.filter(client=c).exists():
        services.create_order(c, client_email=client.email, locality="Oyarifa", plot_number="OY/112",
                              site_plan_ref="SP-OY-112", seller_name="Kwabena Owusu", seller_phone="+233240000099",
                              partner_reference="LOAN-2026-0042")
    ctx["partners"]["seeded_at"] = timezone.now().isoformat()
