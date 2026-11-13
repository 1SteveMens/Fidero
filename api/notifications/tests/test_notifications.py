import json
import re
from datetime import date, datetime, timedelta, timezone as dt_tz

import pytest
from django.utils import timezone

from audit.models import AuditEvent, SecurityAlert
from core.events import publish
from core.models import OutboxEvent
from notifications import policy, reminders, services
from notifications.adapters import ConsoleMessaging, ConsolePush, sign
from notifications.models import ConfirmationCode, Message, PushDevice, Template


@pytest.fixture(autouse=True)
def _clean_outbox():
    ConsoleMessaging.outbox = []
    ConsoleMessaging.fail_channels = set()
    ConsolePush.sent = []
    yield
    ConsoleMessaging.fail_channels = set()


def _code_from_outbox(to):
    body = [m for m in ConsoleMessaging.outbox if m["to"] == to][-1]["body"]
    return re.search(r"\b(\d{6})\b", body).group(1), re.search(r"/confirm/(\S+?)\.?(\s|$)", body).group(1)


# --- notify(), preferences, fallbacks (FR-NTF-001) ----------------------------------

def test_notify_stays_backward_compatible(seeded, people):
    """FR-NTF-001: the foundation call still sends one message per channel and returns them."""
    out = services.notify(people["client2"], "case_update", body="Your case moved.", channels=("in_app", "email"))
    assert [m.channel for m in out] == ["in_app", "email"]
    assert out[0].status == "delivered" and out[1].status == "sent" and out[1].to_address == "kofi@example.com"
    assert out[1].body == "Your case moved."


def test_preferences_suppress_but_money_and_safety_always_in_app(seeded, people):
    """FR-NTF-001: opt-outs are respected; money and safety messages always go in-app."""
    kofi = people["client2"]  # SMS turned off in the seed
    out = services.notify(kofi, "generic", body="x", channels=("sms",))
    assert out[0].status == "suppressed" and out[0].error == "opted_out"
    services.set_preferences(kofi, [{"channel": "email", "enabled": True, "muted_categories": ["money"]}])
    out = services.notify(kofi, "money_update", channels=("email",), category="money",
                          context={"subject_label": "The bank paid the school"})
    assert {m.channel: m.status for m in out} == {"email": "suppressed", "in_app": "delivered"}


def test_whatsapp_preference_and_fallback_on_failure(seeded, people):
    """US-NTF-001b, TC-NTF-001-01 and 02: WhatsApp per preference; on failure the next allowed channel, logged."""
    ama = people["client"]
    services.set_preferences(ama, [{"channel": "whatsapp", "enabled": True, "address": "+447700900001"},
                                   {"channel": "sms", "enabled": True, "address": "+447700900001"}])
    chans = services.preferred_channels(ama)
    assert "whatsapp" in chans and "sms" not in chans
    ConsoleMessaging.fail_channels = {"whatsapp"}
    out = services.notify(ama, "case_status_changed", channels=("whatsapp",),
                          context={"case_ref": "TMR-GH-2026-00050", "status_label": "in review"})
    wa = out[0]
    assert wa.status == "failed" and "unavailable" in wa.error
    fb = Message.objects.get(fallback_of=wa)
    assert fb.channel == "sms" and fb.status == "sent" and fb.group_id == wa.group_id
    assert AuditEvent.objects.filter(action="notification.fallback", entity_id=str(wa.pk)).exists()


def test_quiet_hours_defer_phone_channels(seeded, people):
    """Preferences: quiet hours defer SMS and WhatsApp; the job sends them later. Safety still goes."""
    kofi = people["client2"]
    now = timezone.now()
    start = (now - timedelta(hours=1)).time().replace(microsecond=0)
    end = (now + timedelta(hours=1)).time().replace(microsecond=0)
    services.set_preferences(kofi, [{"channel": "sms", "enabled": True, "quiet_start": start, "quiet_end": end,
                                     "timezone": "UTC", "address": "+15550001"}])
    m = services.notify(kofi, "case_status_changed", channels=("sms",),
                        context={"case_ref": "R1", "status_label": "done"})[0]
    assert m.status == "deferred" and m.scheduled_for > now
    s = services.notify(kofi, "security_alert", channels=("sms",), context={"summary": "x"})[0]
    assert s.status == "sent"
    # Demo messages seeded during someone else's quiet hours are due too; count them in.
    due = Message.objects.filter(status="deferred", scheduled_for__lte=now + timedelta(hours=2)).count()
    assert due >= 1
    assert services.send_due(now + timedelta(hours=2)) == due
    m.refresh_from_db()
    assert m.status == "sent"


# --- Templates (FR-NTF-002) ---------------------------------------------------------

def test_edited_template_new_version_used_for_next_message(seeded, api, people):
    """FR-NTF-002, TC-NTF-002-01."""
    c = api(people["admin"])
    r = c.put("/v1/admin/notification-templates", {"code": "task_assigned", "channel": "email", "language": "en",
                                                    "subject": "Task: {{ task_title }}",
                                                    "body": "Hi {{ first_name }}, please do {{ task_title }}."},
              format="json")
    assert r.status_code == 200 and r.json()["version"] == 1
    c.put("/v1/admin/notification-templates", {"code": "task_assigned", "channel": "email",
                                                "subject": "Task: {{ task_title }}",
                                                "body": "Hello {{ first_name }}. New task: {{ task_title }}."},
          format="json")
    m = services.notify(people["runner"], "task_assigned", channels=("email",), context={"task_title": "Site visit"})[0]
    assert m.body == "Hello Efua. New task: Site visit." and m.template_version.version == 2
    assert Template.objects.filter(code="task_assigned", status="retired").count() == 1


def test_broken_or_leaking_templates_refused(seeded, api, people):
    """FR-NTF-002 and FR-NTF-004, TC-NTF-002-02, TC-NTF-004-02, US-NTF-002 criterion 2."""
    c = api(people["admin"])
    cases = [
        ({"code": "task_assigned", "channel": "email", "body": "Hi {{ nickname }}"}, "template-invalid"),
        ({"code": "task_assigned", "channel": "email", "body": "Hi {{ first_name }}"}, "template-invalid"),
        ({"code": "report_released", "channel": "sms", "body": "Verdict {{ verdict }} for {{ case_ref }}"},
         "template-blocked-field"),
        ({"code": "case_status_changed", "channel": "sms", "body": "Code {{ otp_code }}"}, "template-invalid"),
        ({"code": "case_status_changed", "channel": "whatsapp", "body": "{{ case_ref }} {{ status_label }}"},
         "template-invalid"),
    ]
    for payload, code in cases:
        r = c.put("/v1/admin/notification-templates", payload, format="json")
        assert r.status_code == 422 and r.json()["code"] == code, (payload, r.json())
    assert api(people["cm"]).put("/v1/admin/notification-templates", {}, format="json").status_code == 403


def test_preview_and_catalogue(seeded, api, people):
    c = api(people["admin"])
    cat = {e["code"]: e for e in c.get("/v1/admin/notification-templates/catalogue").json()}
    assert "verdict" not in cat["report_released"]["phone_allowed"]
    r = c.post("/v1/admin/notification-templates/preview", {
        "code": "case_status_changed", "channel": "sms", "context": {"case_ref": "R9", "status_label": "ready"}},
        format="json")
    assert r.json()["body"] == "Tenmina: case R9 is now ready. Open the app."


# --- Content policy (FR-NTF-004) ------------------------------------------------------

def test_phone_messages_carry_no_sensitive_content(seeded, people, gh):
    """FR-NTF-004, TC-NTF-004-01: no verdict, account number, evidence link, code or large amount by SMS."""
    kofi = people["client2"]
    m = services.notify(kofi, "report_released", channels=("sms", "email"), to_address="+15550002",
                        context={"case_ref": "R2", "verdict": "Red"})
    sms, email = m
    assert "Red" not in sms.body and "R2" in sms.body
    assert "Red" in email.body
    big = services.notify(kofi, "money_update", channels=("sms",), to_address="+15550002",
                          context={"subject_label": "Payment sent", "amount": {"amount": "25000.00",
                                                                                 "currency": "GHS"}})[0]
    assert policy.HIDDEN_AMOUNT in big.body and "25,000" not in big.body
    small = services.notify(kofi, "money_update", channels=("sms",), to_address="+15550002",
                            context={"subject_label": "Payment sent", "amount": {"amount": "120.00",
                                                                                   "currency": "GHS"}})[0]
    assert "GHS 120.00" in small.body
    free = policy.sanitize("Paid USD 9,000 to account 0123456789012, code 482913, see "
                           "https://files.example/evidence/abc?signature=x", channel="sms", country=gh)
    assert "0123456789012" not in free and "482913" not in free and "evidence" not in free
    assert "9,000" not in free


def test_push_text_is_generic(seeded, people):
    """FR-APP-002, TC-APP-002-02: lock-screen text reveals nothing."""
    ama = people["client"]
    services.notify(ama, "approval_needed", channels=("push",), needs_action=True,
                    context={"subject_label": "Fees for Kwame", "amount": {"amount": "9000", "currency": "GHS"}})
    assert ConsolePush.sent[-1]["body"] in ("You have something to approve. Open Tenmina to see it.",
                                            "Tenmina: you have a request to review. Open the app to see it.")
    assert "Kwame" not in ConsolePush.sent[-1]["body"]


# --- Push devices (FR-APP-002) ---------------------------------------------------------

def test_push_device_register_revoke_and_invalid_token(seeded, api, people):
    """FR-APP-002, TC-APP-002-03: registration per install; removed or invalid tokens are revoked."""
    kofi = people["client2"]
    c = api(kofi)
    r = c.post("/v1/me/push-devices", {"app": "client", "platform": "android", "token": "fcm-token-kofi-123",
                                       "install_id": "kofi-phone", "app_version": "1.2.0"}, format="json")
    assert r.status_code == 201 and r.json()["provider"] == "fcm" and "token" not in r.json()
    dev_id = r.json()["id"]
    services.notify(kofi, "generic", body="hi", channels=("push",))
    assert ConsolePush.sent
    bad = services.register_device(kofi, app="client", platform="ios", token="invalid-token-xyz")
    m = services.notify(kofi, "generic", body="hi", channels=("push",))[0]
    bad.refresh_from_db()
    assert bad.revoked_at is not None and m.status == "sent"
    assert c.delete(f"/v1/me/push-devices/{dev_id}").status_code == 204
    m = services.notify(kofi, "generic", body="hi", channels=("push",))[0]
    assert m.status == "failed" and m.error == "no registered device"


def test_account_deletion_revokes_push_tokens(seeded, people):
    """FR-APP-004: tokens are revoked at once when deletion is requested."""
    ama = people["client"]
    assert PushDevice.objects.filter(person=ama, revoked_at__isnull=True).exists()
    publish("account.deletion_requested", ama.pk, {"person_id": ama.pk})
    assert not PushDevice.objects.filter(person=ama, revoked_at__isnull=True).exists()


# --- Inbox (apps) ---------------------------------------------------------------------

def test_inbox_needs_action_unread_and_read(seeded, api, people):
    """The apps' messages screen: needs-action filter, unread count, mark read, resolve."""
    ama = people["client"]
    c = api(ama)
    counts = c.get("/v1/me/notifications/unread-count").json()
    # Other modules' seeds give Ama more open actions; the two from this module's seed must be among them.
    assert counts["needs_action"] >= 2 and counts["unread"] >= 3
    items = c.get("/v1/me/notifications", {"needs_action": "true", "limit": 100}).json()["items"]
    assert {"fee_invoice", "case_document_request"} <= {i["subject_type"] for i in items}
    first = items[0]["id"]
    assert c.post(f"/v1/me/notifications/{first}/read").json()["unread"] is False
    services.resolve_action(subject_type="fee_invoice", subject_id="demo-1")
    assert c.get("/v1/me/notifications/unread-count").json()["needs_action"] == counts["needs_action"] - 1
    assert c.post("/v1/me/notifications/read-all").json()["marked"] >= 1
    assert c.get("/v1/me/notifications/unread-count").json()["unread"] == 0
    other = Message.objects.filter(person=people["client2"], channel="in_app").first()
    assert c.post(f"/v1/me/notifications/{other.pk}/read").status_code == 404


def test_preferences_api(seeded, api, people):
    c = api(people["client2"])
    r = c.put("/v1/me/notification-preferences", {"items": [
        {"channel": "whatsapp", "enabled": True, "quiet_start": "22:00", "quiet_end": "06:00",
         "timezone": "America/New_York"}]}, format="json")
    wa = next(p for p in r.json() if p["channel"] == "whatsapp")
    assert wa["enabled"] and wa["quiet_start"] == "22:00:00"
    r = c.put("/v1/me/notification-preferences", {"items": [{"channel": "in_app", "enabled": False}]},
              format="json")
    assert r.status_code == 422


# --- Delivery log and webhooks (FR-NTF-005) ---------------------------------------------

def _hook(c, url, payload, signed=True):
    raw = json.dumps(payload).encode()
    headers = {"HTTP_X_TENMINA_SIGNATURE": sign(raw) if signed else "bad"}
    return c.post(url, data=raw, content_type="application/json", **headers)


def test_delivery_status_stored_once_and_failure_falls_back(seeded, api, people):
    """FR-NTF-005, US-NTF-005: sent, delivered or failed stored from the provider; duplicates ignored."""
    ama = people["client"]
    services.set_preferences(ama, [{"channel": "whatsapp", "enabled": True, "address": "+447700900001"},
                                   {"channel": "sms", "enabled": True, "address": "+447700900001"}])
    m = services.notify(ama, "case_status_changed", channels=("whatsapp",), category="safety",
                        context={"case_ref": "R3", "status_label": "x"})[0]
    assert m.status == "sent"
    c = api()
    assert _hook(c, "/v1/hooks/messaging", {"provider": "console", "event_id": "e1", "provider_ref": m.provider_ref,
                                            "status": "delivered"}, signed=False).status_code == 403
    r = _hook(c, "/v1/hooks/messaging", {"provider": "console", "event_id": "e1", "provider_ref": m.provider_ref,
                                         "status": "delivered"})
    assert r.status_code == 200 and r.json()["duplicate"] is False
    assert _hook(c, "/v1/hooks/messaging", {"provider": "console", "event_id": "e1",
                                            "provider_ref": m.provider_ref, "status": "delivered"}).json()["duplicate"]
    m.refresh_from_db()
    assert m.status == "delivered" and m.delivery_events.count() == 1
    m2 = services.notify(ama, "case_status_changed", channels=("whatsapp",), category="safety",
                         context={"case_ref": "R4", "status_label": "x"})[0]
    _hook(c, "/v1/hooks/messaging", {"provider": "console", "event_id": "e2", "provider_ref": m2.provider_ref,
                                     "status": "undelivered"})
    m2.refresh_from_db()
    assert m2.status == "failed" and Message.objects.filter(fallback_of=m2, channel="sms").exists()
    log = api(people["admin"]).get("/v1/admin/messages", {"subject_type": "", "channel": "whatsapp"}).json()
    assert any(i["id"] == str(m.pk) and i["delivery_events"] for i in log["items"])
    assert api(people["client"]).get("/v1/admin/messages").status_code == 403


# --- Reminders (FR-NTF-003) ------------------------------------------------------------

def test_reminder_two_working_days_before_and_overdue_once(seeded, people, gh):
    """FR-NTF-003, TC-NTF-003-01 and 02: due Tuesday, run Friday: reminded; overdue: one alert on two runs."""
    friday = date(2026, 11, 13)
    due = reminders.DueItem("case_task", "t-1", "Collect site plan", date(2026, 11, 17), owner=people["runner"],
                            manager=people["cm"], country=gh, case_ref="TMR-GH-2026-00042")
    later = reminders.DueItem("case_task", "t-2", "Survey", date(2026, 11, 20), owner=people["runner"],
                              manager=people["cm"], country=gh)
    late = reminders.DueItem("case_task", "t-3", "Legal review", date(2026, 11, 10), owner=people["lawyer"],
                             manager=people["cm"], country=gh, case_ref="TMR-GH-2026-00041")
    assert reminders.run(friday, [due, later, late]) == {"due_soon": 1, "overdue": 1}
    assert reminders.run(friday, [due, later, late]) == {"due_soon": 0, "overdue": 0}
    alert = Message.objects.filter(person=people["cm"], template="task_overdue", channel="email").get()
    assert "Legal review" in alert.body and "Nana Lawyer" in alert.body
    assert Message.objects.filter(person=people["runner"], template="task_due_soon", subject_id="t-1").exists()


def test_task_assigned_event_emails_the_assignee(seeded, people):
    """US-NTF-001a criterion 2: a task assignment emails the assignee."""
    before = set(Message.objects.filter(person=people["surveyor"], template="task_assigned").values_list("pk", flat=True))
    publish("task.assigned", None, {"assignee_id": people["surveyor"].pk, "title": "Check the boundary",
                                    "case_ref": "TMR-GH-2026-00042", "due_date": "20 November 2026"})
    new = Message.objects.filter(person=people["surveyor"], template="task_assigned").exclude(pk__in=before)
    m = new.get(channel="email")
    assert "Check the boundary" in m.body


def test_producer_that_already_notified_is_not_repeated(seeded, people):
    """A producer that told the person itself sets "notified"; NTF sends nothing more."""
    before = Message.objects.filter(person=people["surveyor"], template="task_assigned").count()
    publish("task.assigned", None, {"assignee_id": people["surveyor"].pk, "title": "Walk the plot",
                                    "case_ref": "TMR-GH-2026-00043", "notified": True})
    assert Message.objects.filter(person=people["surveyor"], template="task_assigned").count() == before


# --- Family confirmation codes (ADR-20) ----------------------------------------------------

def test_code_sent_out_of_band_and_confirmed_by_link(seeded, api, people, gh):
    """ADR-20: the code goes to the confirmer, never back to the caller; GET never confirms, POST does."""
    conf = services.send_confirmation_code(subject_type="care_visit", subject_id="v-100", country=gh,
                                           to_address="+233244000999", recipient_name="Auntie Ama",
                                           summary="Afia's visit at 10:00", created_by=people["cm"])
    assert not hasattr(conf, "code")
    code, token = _code_from_outbox("+233244000999")
    c = api()
    assert c.get(f"/v1/family-confirmations/{token}").json()["status"] == "pending"
    conf.refresh_from_db()
    assert conf.status == "pending"
    r = c.post(f"/v1/family-confirmations/{token}", {"decision": "confirm"}, format="json")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert OutboxEvent.objects.filter(topic="family_confirmation.confirmed", payload__subject_id="v-100").exists()


def test_wrong_codes_counted_through_refused_requests_and_locked_at_five(seeded, api, people, gh):
    """ADR-20, 10.10: 422 confirmation-code-invalid; tries survive the refusal; alert at 3; lock at 5."""
    fam = people["family"]
    services.send_confirmation_code(subject_type="care_visit", subject_id="v-200", country=gh, channel="in_app",
                                    recipient_person=fam, summary="Visit", created_by=people["cm"])
    c = api(fam)
    for n in range(1, 6):
        r = c.post("/v1/family-confirmations/codes", {"subject_type": "care_visit", "subject_id": "v-200",
                                                      "code": "000000" if n % 2 else "111111"}, format="json")
        assert r.status_code == 422 and r.json()["code"] == "confirmation-code-invalid"
        assert r.json()["attempts_left"] == 5 - n
    conf = ConfirmationCode.objects.get(subject_id="v-200")
    assert conf.attempts == 5 and conf.status == "locked"
    assert SecurityAlert.objects.filter(kind="confirmation_code.failed", entity_id="v-200").count() == 1
    assert SecurityAlert.objects.filter(kind="confirmation_code.locked").exists()
    assert api(people["client2"]).post("/v1/family-confirmations/codes", {
        "subject_type": "care_visit", "subject_id": "v-200", "code": "1"}, format="json").status_code == 404


def test_right_code_in_app_and_by_sms_reply(seeded, api, people, gh):
    fam = people["family"]
    services.send_confirmation_code(subject_type="care_visit", subject_id="v-300", country=gh, channel="in_app",
                                    recipient_person=fam, summary="Visit", created_by=people["cm"])
    msg = Message.objects.filter(person=fam, template="family_confirmation_code").last()
    code = re.search(r"\b(\d{6})\b", msg.body).group(1)
    r = api(fam).post("/v1/family-confirmations/codes", {"subject_type": "care_visit", "subject_id": "v-300",
                                                         "code": code}, format="json")
    assert r.status_code == 200 and r.json()["ok"]
    services.send_confirmation_code(subject_type="event_delivery", subject_id="d-1", country=gh,
                                    to_address="+233200000555", channel="whatsapp", purpose="event_delivery",
                                    summary="Chairs delivered")
    code, _ = _code_from_outbox("+233200000555")
    r = _hook(api(), "/v1/hooks/messaging/replies", {"provider": "console", "event_id": "r1", "channel": "whatsapp",
                                                     "sender": "+233200000555", "text": f"Yes {code}"})
    assert r.status_code == 200
    assert services.confirmation_status("event_delivery", "d-1").confirmed_via == "reply"


def test_staff_call_needs_a_second_staff_member(seeded, api, people, gh):
    """ADR-20: a call confirmation is recorded by one staff member and checked by another."""
    conf = services.send_confirmation_code(subject_type="care_visit", subject_id="v-400", country=gh,
                                           to_address="+233244000123", summary="Visit")
    cm, rv = api(people["cm"]), api(people["reviewer"])
    r = cm.post(f"/v1/admin/confirmation-codes/{conf.pk}/call-records",
                {"outcome": "confirm", "note": "Spoke to the daughter; visit happened."}, format="json")
    assert r.json()["status"] == "pending_check"
    r = cm.post(f"/v1/admin/confirmation-codes/{conf.pk}/call-checks", {}, format="json")
    assert r.status_code == 409 and r.json()["code"] == "same-approver"
    r = rv.post(f"/v1/admin/confirmation-codes/{conf.pk}/call-checks", {}, format="json")
    assert r.json()["status"] == "confirmed" and r.json()["confirmed_via"] == "staff_call"


def test_expired_code_cannot_confirm(seeded, people, gh):
    conf = services.send_confirmation_code(subject_type="care_visit", subject_id="v-500", country=gh,
                                           to_address="+233244000124", summary="Visit")
    code, _ = _code_from_outbox("+233244000124")
    ConfirmationCode.objects.filter(pk=conf.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    res = services.attempt_code(subject_type="care_visit", subject_id="v-500", code=code)
    assert res["ok"] is False and res["status"] == "expired"


def test_staff_send_endpoint(seeded, api, people):
    r = api(people["cm"]).post("/v1/admin/confirmation-codes", {
        "subject_type": "care_visit", "subject_id": "v-600", "country": "GH", "to_address": "+233244000777",
        "summary": "Visit"}, format="json")
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert api(people["carer"]).post("/v1/admin/confirmation-codes", {}, format="json").status_code == 403
