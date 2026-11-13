"""NTF demo data: templates, preferences, an inbox for Ama, a push device,
family confirmations in several states, and the audit anchor."""
import uuid

from django.utils import timezone

from .models import ConfirmationCode, Message, Preference, PushDevice, Template

DEMO_VISIT = uuid.UUID("01936a1e-0000-7000-8000-00000000c001")
DEMO_VISIT_2 = uuid.UUID("01936a1e-0000-7000-8000-00000000c002")
DEMO_DELIVERY = uuid.UUID("01936a1e-0000-7000-8000-00000000e001")


def run(ctx):
    from . import services

    gh = ctx["gh"]
    p = ctx["people"]
    admin, client, client2, family = p["admin"], p["client"], p["client2"], p["family"]

    if not Template.objects.exists():
        services.save_template(code="case_status_changed", channel="email", by=admin,
                               subject="Case {{ case_ref }}: {{ status_label }}",
                               body="Hello {{ first_name }}. Case {{ case_ref }} is now: {{ status_label }}. "
                                    "Open Tenmina to see what happens next.")
        services.save_template(code="case_status_changed", channel="email", by=admin,
                               subject="Case {{ case_ref }}: {{ status_label }}",
                               body="Hello {{ first_name }}. Your case {{ case_ref }} moved to: {{ status_label }}. "
                                    "We will tell you when it moves again.")
        services.save_template(code="case_status_changed", channel="sms", by=admin,
                               body="Tenmina: case {{ case_ref }} is now {{ status_label }}. Open the app.")
        services.save_template(code="case_status_changed", channel="whatsapp", by=admin,
                               whatsapp_template_name="case_status_v1",
                               body="Tenmina: case {{ case_ref }} is now {{ status_label }}. Open the app for details.")
        services.save_template(code="approval_needed", channel="push", by=admin, subject="Tenmina",
                               body="You have something to approve. Open Tenmina to see it.")
        services.save_template(code="case_status_changed", channel="email", language="tw", by=admin,
                               subject="Case {{ case_ref }}: {{ status_label }}",
                               body="Akwaaba {{ first_name }}. Case {{ case_ref }}: {{ status_label }}. [Twi text TO VERIFY]")

    if not Preference.objects.filter(person=client).exists():
        services.set_preferences(client, [
            {"channel": "whatsapp", "enabled": True, "quiet_start": "22:00", "quiet_end": "07:00",
             "timezone": "Europe/London", "muted_categories": [], "address": client.phone or "+447700900001"},
            {"channel": "sms", "enabled": True},
            {"channel": "email", "enabled": True, "muted_categories": ["marketing"]},
            {"channel": "push", "enabled": True},
        ])
        services.set_preferences(client2, [{"channel": "email", "enabled": True},
                                           {"channel": "sms", "enabled": False}])

    if not PushDevice.objects.filter(person=client).exists():
        services.register_device(client, app="client", platform="ios", token="demo-apns-token-ama-0001",
                                 install_id="ama-iphone", app_version="1.2.0", os_version="iOS 18")
        services.register_device(p["runner"], app="field", platform="android", token="demo-fcm-token-runner-01",
                                 install_id="efua-pixel", app_version="1.1.0", os_version="Android 14")

    if not Message.objects.filter(person=client, channel="in_app").exists():
        services.notify(client, "case_status_changed", channels=("in_app", "email"),
                        context={"case_ref": "TMR-GH-2026-00042", "status_label": "site visit done"},
                        link="/cases/demo-42")
        services.notify(client, "approval_needed", channels=("in_app", "push"), needs_action=True,
                        category="approval",
                        context={"subject_label": "School fees for Kwame, term 2",
                                 "amount": {"amount": "4200.00", "currency": "GHS"}},
                        link="/family/invoices/demo-1", subject_type="fee_invoice", subject_id="demo-1")
        services.notify(client, "request_received", channels=("in_app", "email"), needs_action=True,
                        context={"request_label": "Please upload the site plan you hold."},
                        link="/cases/demo-42/requests/1", subject_type="case_document_request",
                        subject_id="demo-req-1")
        m = services.notify(client, "money_update", channels=("in_app",), category="money",
                            context={"subject_label": "The bank paid the school", "amount": {
                                "amount": "3800.00", "currency": "GHS"}, "payee_name": "Achimota School"})[0]
        services.mark_read(client, m.pk)
        services.notify(client2, "case_status_changed", channels=("in_app", "email", "sms"),
                        context={"case_ref": "TMR-GH-2026-00043", "status_label": "report ready"})

    if not ConfirmationCode.objects.exists():
        services.send_confirmation_code(subject_type="care_visit", subject_id=DEMO_VISIT, country=gh,
                                        purpose="care_visit", to_address="+233244000111", channel="sms",
                                        recipient_name="Auntie Comfort", recipient_person=family,
                                        summary="Afia's visit to Mama Esi today, 10:00 to 11:00",
                                        created_by=p["cm"])
        c2 = services.send_confirmation_code(subject_type="care_visit", subject_id=DEMO_VISIT_2, country=gh,
                                             purpose="care_visit", to_address="+233244000111", channel="sms",
                                             recipient_name="Auntie Comfort", summary="Afia's visit yesterday",
                                             created_by=p["cm"])
        services.record_call(c2, by=p["cm"], outcome="confirm",
                             note="Called Auntie Comfort; she confirmed the visit took place.")
        services.check_call(c2, by=p["reviewer"])
        services.send_confirmation_code(subject_type="event_delivery", subject_id=DEMO_DELIVERY, country=gh,
                                        purpose="event_delivery", to_address="+233244000222", channel="whatsapp",
                                        recipient_name="Uncle Kofi", summary="Chairs and canopies delivered",
                                        created_by=p["cm"])

    from audit.models import SecurityAlert
    from audit.services import anchor, raise_alert, run_chain_check

    if not SecurityAlert.objects.filter(kind="demo.burst").exists():
        a = raise_alert("demo.burst", severity="warning", summary="Demo: three wrong confirmation codes on one visit",
                        entity="care_visit", entity_id=str(DEMO_VISIT), country=gh)
        a.acknowledged_by, a.acknowledged_at, a.note = admin, timezone.now(), "Demo alert, no action needed"
        a.save()
    anchor()
    run_chain_check()
