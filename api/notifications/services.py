"""NTF services (FR-NTF-001 to 005, FR-APP-002, ADR-20).

Every module calls notify(); never a provider directly. The signature is
backward compatible with the foundation version: `notify(person, "code",
body=..., channels=(...))` still sends one message per channel and returns
them, now with templates, preferences, the content policy, fallbacks and
the delivery log applied.
"""
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings as dj_settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from audit.services import record, security_event
from core import state
from core.adapters import get_adapter
from core.errors import DomainError, Forbidden, Invalid, NotFound, StateConflict
from core.events import publish

from . import catalogue, policy
from .models import ConfirmationCode, DeliveryEvent, Message, Preference, PushDevice, Template

FALLBACK = {"whatsapp": ["sms", "email"], "sms": ["whatsapp", "email"], "email": [], "push": [], "in_app": []}
DEFAULT_ON = {"in_app": True, "email": True, "sms": False, "whatsapp": False, "push": True}
PREFERRED = "preferred"


class ConfirmationCodeInvalid(DomainError):
    status = 422
    code = "confirmation-code-invalid"
    title = "The confirmation code is wrong, expired or used up"


# --- Preferences -------------------------------------------------------------------

def _prefs(person) -> dict:
    if person is None:
        return {}
    return {p.channel: p for p in Preference.objects.filter(person=person)}


def channel_allowed(person, channel, category, prefs=None) -> tuple[bool, str]:
    """Opt-outs and muted categories apply, except that money and safety
    messages always go in-app."""
    if person is None:
        return True, ""
    if channel == "in_app":
        if category in catalogue.MANDATORY_IN_APP:
            return True, ""
    prefs = _prefs(person) if prefs is None else prefs
    p = prefs.get(channel)
    if p is not None and not p.enabled:
        return False, "opted_out"
    if p is not None and category in (p.muted_categories or []):
        return False, f"muted:{category}"
    return True, ""


def preferred_channels(person, category="status") -> list[str]:
    """In-app always, then the person's chosen channels. WhatsApp is preferred
    to SMS when both are on; SMS is then the fallback."""
    prefs = _prefs(person)
    out = ["in_app"]
    for ch in ("email", "whatsapp", "sms", "push"):
        p = prefs.get(ch)
        on = p.enabled if p is not None else DEFAULT_ON[ch]
        if on and channel_allowed(person, ch, category, prefs)[0]:
            out.append(ch)
    if "whatsapp" in out and "sms" in out:
        out.remove("sms")
    return out


def get_preferences(person) -> list[dict]:
    prefs = _prefs(person)
    out = []
    for ch in catalogue.CHANNELS:
        p = prefs.get(ch)
        out.append({"channel": ch, "enabled": p.enabled if p else DEFAULT_ON[ch],
                    "quiet_start": p.quiet_start if p else None, "quiet_end": p.quiet_end if p else None,
                    "timezone": p.timezone if p else "", "muted_categories": p.muted_categories if p else [],
                    "address": p.address if p else ""})
    return out


@transaction.atomic
def set_preferences(person, items: list[dict]) -> list[dict]:
    for it in items:
        ch = it.get("channel")
        if ch not in catalogue.CHANNELS:
            raise Invalid(f"Unknown channel '{ch}'.")
        if ch == "in_app" and it.get("enabled") is False:
            raise Invalid("In-app messages cannot be turned off. Money and safety messages always go in-app.")
        muted = it.get("muted_categories") or []
        bad = [c for c in muted if c not in catalogue.CATEGORIES]
        if bad:
            raise Invalid(f"Unknown categories: {', '.join(bad)}.")
        if ch == "in_app" and set(muted) & catalogue.MANDATORY_IN_APP:
            raise Invalid("Money and safety messages always go in-app.")
        qs, qe = it.get("quiet_start"), it.get("quiet_end")
        if (qs is None) != (qe is None):
            raise Invalid("Give both ends of the quiet hours, or neither.")
        tz = it.get("timezone") or ""
        if tz:
            try:
                ZoneInfo(tz)
            except Exception:  # noqa: BLE001
                raise Invalid(f"Unknown time zone '{tz}'.") from None
        Preference.objects.update_or_create(person=person, channel=ch, defaults={
            "enabled": it.get("enabled", True), "quiet_start": qs, "quiet_end": qe, "timezone": tz,
            "muted_categories": muted, "address": it.get("address") or ""})
    record(actor=person, action="notification_preferences.changed", entity="person", entity_id=person.pk,
           data={"channels": [i.get("channel") for i in items]})
    return get_preferences(person)


def _quiet_until(pref: Preference | None, now) -> datetime | None:
    if pref is None or pref.quiet_start is None or pref.quiet_end is None:
        return None
    tz = ZoneInfo(pref.timezone) if pref.timezone else ZoneInfo("UTC")
    local = now.astimezone(tz)
    t, s, e = local.time(), pref.quiet_start, pref.quiet_end
    inside = (s <= t < e) if s < e else (t >= s or t < e)
    if not inside:
        return None
    end = local.replace(hour=e.hour, minute=e.minute, second=0, microsecond=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(ZoneInfo("UTC"))


# --- Templates (FR-NTF-002) -----------------------------------------------------------

def find_template(code, channel, language="en", country=None) -> Template | None:
    qs = Template.objects.filter(code=code, channel=channel, status="active")
    for lang in dict.fromkeys([language or "en", "en"]):
        if country is not None:
            t = qs.filter(language=lang, country=country).order_by("-version").first()
            if t:
                return t
        t = qs.filter(language=lang, country__isnull=True).order_by("-version").first()
        if t:
            return t
    return None


@transaction.atomic
def save_template(*, code, channel, language="en", country=None, subject="", body, by,
                  whatsapp_template_name="") -> Template:
    """A new version, used for the next message; the old one is kept as retired."""
    policy.validate_template(code, channel, subject, body)
    if channel == "whatsapp" and not whatsapp_template_name:
        raise Invalid("Name the WhatsApp template the provider approved for this text.", code="template-invalid")
    last = Template.objects.filter(code=code, channel=channel, language=language, country=country).aggregate(
        m=Max("version"))["m"] or 0
    Template.objects.filter(code=code, channel=channel, language=language, country=country,
                            status="active").update(status="retired")
    t = Template.objects.create(code=code, channel=channel, language=language, country=country, version=last + 1,
                                subject=subject, body=body, created_by=by,
                                whatsapp_template_name=whatsapp_template_name)
    record(actor=by, action="notification_template.saved", entity="notification_template", entity_id=t.pk,
           country=country, data={"code": code, "channel": channel, "language": language, "version": t.version})
    return t


def _context(person, context, body, link):
    ctx = {"app_name": "Tenmina", "link": link or ""}
    if person is not None:
        ctx["first_name"] = (person.full_name or "").split(" ")[0] or "there"
        ctx["recipient_name"] = ctx["first_name"]
    if body:
        ctx["body"] = body
    ctx.update(context or {})
    return ctx


def compose(code, channel, *, person=None, body="", subject="", context=None, link="", language="en", country=None,
            needs_action=False) -> tuple[str, str, Template | None]:
    """Subject and text for one channel, with the content policy applied."""
    e = catalogue.entry(code)
    allows_code = bool(e and e.get("allows_code"))
    ctx = _context(person, context, body, link)
    t = find_template(code, channel, language, country)
    phone = channel in catalogue.PHONE_CHANNELS
    if t is not None:
        missing = policy.placeholders(t.body) - {k for k, v in ctx.items() if v not in ("", None)}
        if missing and body and not phone:
            t = None
    if t is not None:
        subj = policy.render(t.subject, ctx, channel=channel, country=country, allows_code=allows_code)
        text = policy.render(t.body, ctx, channel=channel, country=country, allows_code=allows_code)
    elif channel == "push":
        subj = "Tenmina"
        text = catalogue.GENERIC_ACTION if needs_action else catalogue.GENERIC_PHONE
    elif phone:
        subj = ""
        text = policy.render(e["phone"], ctx, channel=channel, country=country, allows_code=allows_code) if e \
            else body
    elif body:
        subj = subject or (policy.render(e["defaults"]["subject"], ctx, channel=channel, country=country) if e else "")
        text = body
    elif e:
        subj = subject or policy.render(e["defaults"]["subject"], ctx, channel=channel, country=country)
        text = policy.render(e["defaults"]["body"], ctx, channel=channel, country=country, allows_code=allows_code)
    else:
        subj, text = subject, ""
    if phone:
        text = policy.sanitize(text, channel=channel, country=country, allows_code=allows_code)
        subj = policy.sanitize(subj, channel=channel, country=country)
    return subj, text, t


# --- notify() -----------------------------------------------------------------------

def _address(person, channel, to_address, prefs) -> str:
    if to_address:
        return to_address
    p = prefs.get(channel)
    if p is not None and p.address:
        return p.address
    if person is None:
        return ""
    return person.email if channel == "email" else person.phone if channel in ("sms", "whatsapp") else ""


def notify(person=None, template: str = "", *, body: str = "", subject: str = "", channels=("in_app",), link="",
           subject_obj=None, needs_action=False, to_address="", context=None, category=None, country=None,
           language=None, subject_type="", subject_id="") -> list[Message]:
    """Send a notification. Every module calls this; never a provider directly.

    channels: a tuple of channels, or "preferred" for the person's own choice.
    Opt-outs and muted categories suppress a channel (the message is logged as
    `suppressed`); money and safety messages always go in-app. On SMS,
    WhatsApp and push only template text goes out, with no report contents,
    account numbers, codes, evidence links or amounts above the threshold
    (FR-NTF-004). A failed WhatsApp or SMS falls back to the next allowed
    channel (US-NTF-001b). Returns one message per requested channel.
    """
    code = template or "generic"
    category = category or catalogue.category_of(code)
    if country is None and person is not None:
        country = getattr(person, "home_country", None)
    language = language or (getattr(person, "preferred_language", "") or "en")
    if subject_obj is not None:
        subject_type = subject_type or type(subject_obj).__name__.lower()
        subject_id = subject_id or str(getattr(subject_obj, "pk", ""))
    prefs = _prefs(person)
    chans = preferred_channels(person, category) if channels in (PREFERRED, None) else list(channels)
    if person is not None and category in catalogue.MANDATORY_IN_APP and "in_app" not in chans:
        chans.append("in_app")
    group = uuid.uuid4()
    used = set(chans)
    out = []
    with transaction.atomic():
        for ch in chans:
            out.append(_one(person, code, ch, body=body, subject=subject, link=link, needs_action=needs_action,
                            to_address=to_address, context=context, category=category, country=country,
                            language=language, subject_type=subject_type, subject_id=subject_id, prefs=prefs,
                            group=group, used=used))
    return out


def _one(person, code, ch, *, body, subject, link, needs_action, to_address, context, category, country, language,
         subject_type, subject_id, prefs, group, used, fallback_of=None) -> Message:
    phone = ch in catalogue.PHONE_CHANNELS
    subj, text, t = compose(code, ch, person=person, body=body, subject=subject, context=context, link=link,
                            language=language, country=country, needs_action=needs_action)
    m = Message.objects.create(
        person=person, to_address=_address(person, ch, to_address, prefs) if ch != "in_app" else "",
        channel=ch, template=code, template_version=t, category=category, language=language, country=country,
        subject=subj, body=text or body or "", link=policy.safe_link(link) if phone else link,
        subject_type=subject_type, subject_id=str(subject_id or ""), needs_action=needs_action,
        group_id=group, fallback_of=fallback_of)
    ok, reason = channel_allowed(person, ch, category, prefs)
    if not ok:
        m.status, m.error = "suppressed", reason
        m.save(update_fields=["status", "error"])
        return m
    if ch == "in_app":
        if person is None:
            m.status, m.error = "failed", "no account for in-app"
        else:
            m.status = "delivered"
            m.delivered_at = timezone.now()
        m.save(update_fields=["status", "error", "delivered_at"])
        return m
    if ch in ("email", "sms", "whatsapp") and not m.to_address:
        _fail(m, "no address for this channel")
        _fallback(m, used=used, context=context, body=body, subject=subject, prefs=prefs)
        return m
    if phone and category != "safety":
        until = _quiet_until(prefs.get(ch), timezone.now())
        if until is not None:
            m.status, m.scheduled_for = "deferred", until
            m.save(update_fields=["status", "scheduled_for"])
            return m
    _dispatch(m, used=used, context=context, body=body, subject=subject, prefs=prefs)
    return m


def _fail(m: Message, error: str):
    m.status, m.error, m.failed_at = "failed", error[:500], timezone.now()
    m.save(update_fields=["status", "error", "failed_at"])


def _dispatch(m: Message, *, used=None, context=None, body="", subject="", prefs=None):
    m.attempts += 1
    if m.channel == "push":
        adapter = get_adapter("push", default="notifications.adapters.ConsolePush")
        devices = list(PushDevice.objects.filter(person=m.person, revoked_at__isnull=True)) if m.person else []
        if not devices:
            m.save(update_fields=["attempts"])
            _fail(m, "no registered device")
            return m
        sent = False
        for d in devices:
            res = adapter.send_push(d, m.subject or "Tenmina", m.body, {"link": m.link, "message_id": str(m.pk)})
            if res == "invalid_token":
                revoke_device(d, reason="provider reported the token invalid")
            elif res == "ok":
                sent = True
        if sent:
            m.status, m.sent_at, m.provider = "sent", timezone.now(), getattr(adapter, "name", "")
            m.save(update_fields=["status", "sent_at", "provider", "attempts"])
        else:
            m.save(update_fields=["attempts"])
            _fail(m, "no device accepted the push")
        return m
    adapter = get_adapter("messaging", default="notifications.adapters.ConsoleMessaging")
    try:
        res = adapter.send(m)
    except Exception as exc:  # noqa: BLE001 - a provider error is a failed send, logged
        res = {"ok": False, "error": str(exc)}
    if isinstance(res, bool):
        res = {"ok": res}
    m.provider = getattr(adapter, "name", "") or type(adapter).__name__
    if res.get("ok"):
        m.status, m.sent_at, m.provider_ref = "sent", timezone.now(), res.get("provider_ref", "") or ""
        m.save(update_fields=["status", "sent_at", "provider_ref", "provider", "attempts"])
    else:
        m.save(update_fields=["provider", "attempts"])
        _fail(m, res.get("error") or "provider refused the message")
        _fallback(m, used=used, context=context, body=body, subject=subject, prefs=prefs)
    return m


def _fallback(m: Message, *, used=None, context=None, body="", subject="", prefs=None):
    """US-NTF-001b: retry on the next allowed channel and log it."""
    if m.fallback_of_id is None and m.fallbacks.exists():
        return None
    if used is None:
        used = set(Message.objects.filter(group_id=m.group_id).values_list("channel", flat=True)) if m.group_id \
            else {m.channel}
    prefs = _prefs(m.person) if prefs is None else prefs
    for ch in FALLBACK.get(m.channel, []):
        if ch in used:
            continue
        if not channel_allowed(m.person, ch, m.category, prefs)[0]:
            continue
        if not _address(m.person, ch, m.to_address if m.channel in ("sms", "whatsapp") and ch in ("sms", "whatsapp")
                        else "", prefs):
            continue
        used.add(ch)
        record(action="notification.fallback", entity="notification", entity_id=m.pk, country=m.country,
               data={"from": m.channel, "to": ch, "error": m.error})
        return _one(m.person, m.template, ch, body=body or m.body, subject=subject or m.subject, link=m.link,
                    needs_action=m.needs_action, to_address=m.to_address if ch in ("sms", "whatsapp") else "",
                    context=context, category=m.category, country=m.country, language=m.language,
                    subject_type=m.subject_type, subject_id=m.subject_id, prefs=prefs, group=m.group_id,
                    used=used, fallback_of=m)
    return None


def send_due(now=None) -> int:
    """Send messages deferred by quiet hours (job notifications.send_deferred)."""
    now = now or timezone.now()
    n = 0
    for m in Message.objects.filter(status="deferred", scheduled_for__lte=now).order_by("scheduled_for")[:500]:
        with transaction.atomic():
            m.status = "queued"
            _dispatch(m)
            n += 1
    return n


# --- Delivery reports (FR-NTF-005, 7.3) -----------------------------------------------

STATUS_MAP = {"queued": "sent", "accepted": "sent", "sent": "sent", "delivered": "delivered", "read": "delivered",
              "failed": "failed", "undelivered": "failed", "rejected": "failed", "expired": "failed"}
RANK = {"queued": 0, "deferred": 0, "sent": 1, "delivered": 2, "read": 3, "failed": 2}


def record_delivery(*, provider, event_id, provider_ref, status, raw: bytes, occurred_at=None,
                    payload=None) -> DeliveryEvent:
    """Store the provider's report once (deduplicated on its event id), take the
    authoritative status from the provider and update the message."""
    adapter = get_adapter("messaging", default="notifications.adapters.ConsoleMessaging")
    existing = DeliveryEvent.objects.filter(provider=provider, provider_event_id=event_id).first()
    if existing:
        return existing
    authoritative = adapter.fetch_status(provider_ref, status)
    mapped = STATUS_MAP.get((authoritative or "").lower(), "")
    m = Message.objects.filter(provider_ref=provider_ref).first() if provider_ref else None
    try:
        with transaction.atomic():
            ev = DeliveryEvent.objects.create(message=m, provider=provider, provider_event_id=event_id,
                                              provider_ref=provider_ref or "", status=authoritative or status,
                                              occurred_at=occurred_at, raw_sha256=hashlib.sha256(raw).hexdigest(),
                                              payload=payload or {})
    except IntegrityError:
        return DeliveryEvent.objects.get(provider=provider, provider_event_id=event_id)
    if m is not None and mapped:
        now = timezone.now()
        if mapped == "failed" and m.status != "failed":
            _fail(m, f"provider reported {authoritative}")
            _fallback(m)
        elif mapped != "failed" and RANK.get(mapped, 0) > RANK.get(m.status, 0) and m.status != "read":
            m.status = mapped
            if mapped == "delivered":
                m.delivered_at = now
            m.save(update_fields=["status", "delivered_at"])
    return ev


# --- Inbox (the apps' messages screen) ---------------------------------------------

def inbox(person, *, unread=None, needs_action=None):
    qs = Message.objects.filter(person=person, channel="in_app").exclude(status="suppressed")
    if unread:
        qs = qs.filter(read_at__isnull=True)
    if needs_action:
        qs = qs.filter(needs_action=True, action_done_at__isnull=True)
    return qs.order_by("-created_at")


def unread_count(person) -> dict:
    qs = inbox(person, unread=True)
    return {"unread": qs.count(), "needs_action": inbox(person, needs_action=True).count()}


def mark_read(person, message_id) -> Message:
    m = Message.objects.filter(pk=message_id, person=person, channel="in_app").first()
    if not m:
        raise NotFound()
    if m.read_at is None:
        m.read_at, m.status = timezone.now(), "read"
        m.save(update_fields=["read_at", "status"])
    return m


def mark_all_read(person) -> int:
    return inbox(person, unread=True).update(read_at=timezone.now(), status="read")


def resolve_action(subject_obj=None, *, subject_type="", subject_id="", person=None) -> int:
    """Other modules call this when the thing a message asked for is done, so
    it leaves the orange needs-action list."""
    if subject_obj is not None:
        subject_type = subject_type or type(subject_obj).__name__.lower()
        subject_id = subject_id or str(subject_obj.pk)
    qs = Message.objects.filter(subject_type=subject_type, subject_id=str(subject_id), needs_action=True,
                                action_done_at__isnull=True)
    if person is not None:
        qs = qs.filter(person=person)
    return qs.update(action_done_at=timezone.now())


# --- Push devices (FR-APP-002) ---------------------------------------------------------

@transaction.atomic
def register_device(person, *, app, platform, token, install_id="", app_version="", os_version="") -> PushDevice:
    if app not in PushDevice.APPS or platform not in PushDevice.PLATFORMS:
        raise Invalid("app must be client or field; platform must be ios or android.")
    if not token or len(token) < 8:
        raise Invalid("The push token is missing.")
    h = hashlib.sha256(token.encode()).hexdigest()
    now = timezone.now()
    for other in PushDevice.objects.filter(token_sha256=h, revoked_at__isnull=True).exclude(person=person):
        revoke_device(other, reason="token now registered by another account")
    d = PushDevice.objects.filter(person=person, token_sha256=h, revoked_at__isnull=True).first()
    if d is None and install_id:
        d = PushDevice.objects.filter(person=person, install_id=install_id, app=app, revoked_at__isnull=True).first()
    if d is None:
        d = PushDevice(person=person, app=app, platform=platform)
    d.token, d.token_sha256, d.install_id = token, h, install_id or d.install_id
    d.provider = "apns" if platform == "ios" else "fcm"
    d.app_version, d.os_version, d.last_seen_at = app_version, os_version, now
    d.save()
    record(actor=person, action="push_device.registered", entity="push_device", entity_id=d.pk,
           data={"app": app, "platform": platform, "app_version": app_version})
    return d


def revoke_device(d: PushDevice, *, reason="") -> PushDevice:
    if d.revoked_at is None:
        d.revoked_at, d.revoked_reason = timezone.now(), reason
        d.save(update_fields=["revoked_at", "revoked_reason"])
        record(action="push_device.revoked", entity="push_device", entity_id=d.pk, data={"reason": reason})
    return d


def revoke_all_devices(person, *, reason="") -> int:
    n = 0
    for d in PushDevice.objects.filter(person=person, revoked_at__isnull=True):
        revoke_device(d, reason=reason)
        n += 1
    return n


# --- Family confirmation codes (ADR-20) ------------------------------------------------

CODE_TTL = timedelta(hours=24)
MAX_ATTEMPTS = 5


def _hash(value: str, purpose: str) -> str:
    return hmac.new(dj_settings.SECRET_KEY.encode(), f"{purpose}:{value}".encode(), hashlib.sha256).hexdigest()


def _portal_link(token: str) -> str:
    base = getattr(dj_settings, "TENMINA_PORTAL_URL", "") or "https://tenmina.example/confirm"
    return f"{base.rstrip('/')}/{token}"


@transaction.atomic
def send_confirmation_code(*, subject_type, subject_id, country, purpose="care_visit", to_address="",
                           channel="sms", recipient_name="", recipient_person=None, summary="",
                           created_by=None) -> ConfirmationCode:
    """Send a one-time code and a one-tap link to the confirmer's registered
    channel. Returns the record only: the code is never returned to the
    caller, so it can never appear in a carer's or agent's app."""
    if channel not in ("sms", "whatsapp", "in_app"):
        raise Invalid("Codes go by SMS, WhatsApp or in-app.")
    if channel == "in_app" and recipient_person is None:
        raise Invalid("An in-app code needs a confirmer with an account.")
    if channel != "in_app" and not (to_address or getattr(recipient_person, "phone", "")):
        raise Invalid("The confirmer has no phone number on record.")
    to_address = to_address or getattr(recipient_person, "phone", "")
    for old in ConfirmationCode.objects.filter(subject_type=subject_type, subject_id=str(subject_id),
                                               status__in=("pending", "locked", "expired")):
        state.transition(old, "confirmation_code", "superseded", actor=created_by)
    code = f"{secrets.randbelow(10 ** 6):06d}"
    token = secrets.token_urlsafe(24)
    conf = ConfirmationCode.objects.create(
        country=country, subject_type=subject_type, subject_id=str(subject_id), purpose=purpose,
        recipient_person=recipient_person, recipient_name=recipient_name, to_address=to_address, channel=channel,
        summary=summary, code_hash=_hash(code, f"code:{subject_type}:{subject_id}"),
        link_token_hash=_hash(token, "link"), expires_at=timezone.now() + CODE_TTL, max_attempts=MAX_ATTEMPTS,
        created_by=created_by)
    msgs = notify(recipient_person, "family_confirmation_code", channels=(channel,), to_address=to_address,
                  context={"otp_code": code, "summary": summary or "a visit", "link": _portal_link(token),
                           "recipient_name": recipient_name or "there", "expires_in": "24 hours"},
                  link=_portal_link(token), category="safety", country=country, subject_type="confirmation_code",
                  subject_id=str(conf.pk))
    conf.message = msgs[0] if msgs else None
    conf.save(update_fields=["message"])
    record(actor=created_by, action="confirmation_code.sent", entity=subject_type, entity_id=subject_id,
           country=country, data={"confirmation_id": str(conf.pk), "channel": channel, "purpose": purpose})
    return conf


def _confirmed(conf: ConfirmationCode, via: str, actor=None, decision="confirm"):
    conf.confirmed_at, conf.confirmed_via = timezone.now(), via
    to = "confirmed" if decision == "confirm" else "disputed"
    state.transition(conf, "confirmation_code", to, actor=actor, event=f"family_confirmation.{to}",
                     payload={"subject_type": conf.subject_type, "subject_id": conf.subject_id,
                              "purpose": conf.purpose, "confirmation_id": str(conf.pk), "via": via},
                     extra_fields=["confirmed_at", "confirmed_via"])
    return conf


def _expire_if_due(conf):
    if conf.status == "pending" and conf.expires_at <= timezone.now():
        state.transition(conf, "confirmation_code", "expired")
    return conf


def _register_failure(conf: ConfirmationCode, attempts_now: int):
    """Count a wrong try so that it survives the rollback of the refused
    request, and lock at the limit. Security events at 3 and at 5 (10.10)."""
    from audit import context

    conf_id = conf.pk

    def apply():
        c = ConfirmationCode.objects.select_for_update().get(pk=conf_id)
        if c.attempts < attempts_now:
            c.attempts = attempts_now
            c.save(update_fields=["attempts"])
        if c.attempts >= c.max_attempts and c.status == "pending":
            state.transition(c, "confirmation_code", "locked", event="family_confirmation.locked",
                             payload={"subject_type": c.subject_type, "subject_id": c.subject_id,
                                      "purpose": c.purpose})
            security_event("confirmation_code.locked", entity=c.subject_type, entity_id=c.subject_id,
                           country=c.country, data={"confirmation_id": str(c.pk)},
                           summary=f"Confirmation code locked after {c.attempts} wrong tries")
        security_event("confirmation_code.failed", entity=c.subject_type, entity_id=c.subject_id,
                       country=c.country, data={"confirmation_id": str(c.pk), "attempts": c.attempts})

    conf.attempts = attempts_now
    conf.save(update_fields=["attempts"])
    context.defer(apply)


@transaction.atomic
def attempt_code(*, subject_type, subject_id, code, via="code", actor=None) -> dict:
    """Check a code without raising, so the attempt is counted even when the
    caller answers 422. Returns {"ok", "status", "attempts_left", "confirmation"}."""
    conf = ConfirmationCode.objects.select_for_update().filter(
        subject_type=subject_type, subject_id=str(subject_id)).exclude(status="superseded").order_by(
        "-created_at").first()
    if conf is None:
        return {"ok": False, "status": "none", "attempts_left": 0, "confirmation": None}
    return _attempt(conf, code, via=via, actor=actor)


def _attempt(conf, code, *, via, actor=None, decision="confirm"):
    _expire_if_due(conf)
    if conf.status != "pending":
        return {"ok": conf.status == "confirmed", "status": conf.status, "attempts_left": 0, "confirmation": conf}
    if conf.attempts >= conf.max_attempts:
        return {"ok": False, "status": "locked", "attempts_left": 0, "confirmation": conf}
    good = hmac.compare_digest(_hash(str(code or "").strip(), f"code:{conf.subject_type}:{conf.subject_id}"),
                               conf.code_hash)
    if not good:
        n = conf.attempts + 1
        _register_failure(conf, n)
        return {"ok": False, "status": "locked" if n >= conf.max_attempts else "wrong_code",
                "attempts_left": max(conf.max_attempts - n, 0), "confirmation": conf}
    _confirmed(conf, via, actor=actor, decision=decision)
    return {"ok": True, "status": conf.status, "attempts_left": conf.max_attempts - conf.attempts,
            "confirmation": conf}


def verify_code_or_raise(**kw) -> ConfirmationCode:
    """As attempt_code, raising 422 confirmation-code-invalid on failure. The
    failed attempt is still counted (it is written after the request)."""
    res = attempt_code(**kw)
    if not res["ok"]:
        raise ConfirmationCodeInvalid(_failure_text(res), extra={"attempts_left": res["attempts_left"],
                                                                 "reason": res["status"]})
    return res["confirmation"]


def _failure_text(res) -> str:
    return {"wrong_code": f"That code is not right. {res['attempts_left']} tries left.",
            "locked": "Too many wrong tries. Tenmina will call to confirm.",
            "expired": "This code has expired. Ask Tenmina for a new one.",
            "none": "There is nothing to confirm with this code."}.get(
        res["status"], "This confirmation is already closed.")


def my_confirmations(person, limit=50):
    """Confirmations sent to a family member who has an account (SCR-PTL-45 in the portal). Newest first;
    expired ones are marked so. The code itself is never returned: it is on the person's own phone."""
    rows = list(ConfirmationCode.objects.filter(recipient_person=person).exclude(status="superseded").order_by(
        "-created_at")[:limit])
    for c in rows:
        _expire_if_due(c)
    return rows


@transaction.atomic
def dispute_mine(conf_id, person) -> ConfirmationCode:
    """The named confirmer says the visit or delivery did not happen. A dispute never pays anyone, so it
    needs no code (as with a "No" reply to the message); confirming always needs the code."""
    conf = ConfirmationCode.objects.select_for_update().filter(pk=conf_id, recipient_person=person).first()
    if conf is None:
        raise NotFound("There is nothing to confirm here.")
    _expire_if_due(conf)
    if conf.status != "pending":
        raise StateConflict("This confirmation is already closed.")
    return _confirmed(conf, "app", actor=person, decision="dispute")


def by_link(token: str) -> ConfirmationCode:
    conf = ConfirmationCode.objects.filter(link_token_hash=_hash(token, "link")).first()
    if conf is None:
        raise NotFound("This link is not valid.")
    return conf


@transaction.atomic
def confirm_by_link(token: str, *, decision="confirm") -> dict:
    """The one-tap link: the token is the secret. Opening the link shows the
    summary; only this explicit POST confirms or disputes."""
    conf = by_link(token)
    _expire_if_due(conf)
    if conf.status != "pending":
        return {"ok": conf.status in ("confirmed", "disputed"), "status": conf.status, "attempts_left": 0,
                "confirmation": conf}
    if decision not in ("confirm", "dispute"):
        raise Invalid("decision must be confirm or dispute.")
    _confirmed(conf, "link", decision=decision)
    return {"ok": True, "status": conf.status, "attempts_left": conf.max_attempts - conf.attempts,
            "confirmation": conf}


@transaction.atomic
def confirm_by_reply(*, from_address: str, text: str) -> dict:
    """An SMS or WhatsApp reply carrying the code (inbound webhook)."""
    digits = "".join(ch for ch in (text or "") if ch.isdigit())
    conf = ConfirmationCode.objects.select_for_update().filter(to_address=from_address, status="pending").order_by(
        "-created_at").first()
    if conf is None:
        return {"ok": False, "status": "none", "attempts_left": 0, "confirmation": None}
    low = (text or "").strip().lower()
    if low.startswith(("no", "dispute")):
        _confirmed(conf, "reply", decision="dispute")
        return {"ok": True, "status": conf.status, "attempts_left": 0, "confirmation": conf}
    return _attempt(conf, digits[:6], via="reply")


@transaction.atomic
def record_call(conf: ConfirmationCode, *, by, outcome="confirm", note="") -> ConfirmationCode:
    """ADR-20: staff record a confirmation by phone; a second staff member
    checks it before it counts."""
    _expire_if_due(conf)
    if conf.status not in ("pending", "locked", "expired"):
        raise StateConflict("This confirmation is already closed.")
    if outcome not in ("confirm", "dispute"):
        raise Invalid("outcome must be confirm or dispute.")
    if not note:
        raise Invalid("Say who was called and what they said.")
    if conf.status != "pending":
        # a locked or expired code is replaced by a staff-call record on a fresh row
        conf = _call_row(conf, by)
    conf.call_recorded_by, conf.call_outcome, conf.call_note = by, outcome, note
    state.transition(conf, "confirmation_code", "pending_check", actor=by,
                     extra_fields=["call_recorded_by", "call_outcome", "call_note"])
    return conf


def _call_row(old: ConfirmationCode, by) -> ConfirmationCode:
    state.transition(old, "confirmation_code", "superseded", actor=by)
    return ConfirmationCode.objects.create(
        country=old.country, subject_type=old.subject_type, subject_id=old.subject_id, purpose=old.purpose,
        recipient_person=old.recipient_person, recipient_name=old.recipient_name, to_address=old.to_address,
        channel="staff_call", summary=old.summary, code_hash=secrets.token_hex(32),
        link_token_hash=_hash(secrets.token_urlsafe(24), "link"), expires_at=timezone.now() + CODE_TTL,
        created_by=by)


@transaction.atomic
def check_call(conf: ConfirmationCode, *, by, agree=True) -> ConfirmationCode:
    if conf.status != "pending_check":
        raise StateConflict("No staff call is waiting for a check.")
    if conf.call_recorded_by_id == by.pk:
        from core.errors import SameApprover

        raise SameApprover("A different staff member must check the call.")
    conf.call_checked_by = by
    conf.save(update_fields=["call_checked_by"])
    if not agree:
        state.transition(conf, "confirmation_code", "pending", actor=by, reason="Call check disagreed")
        return conf
    return _confirmed(conf, "staff_call", actor=by, decision=conf.call_outcome or "confirm")


def confirmation_status(subject_type, subject_id) -> ConfirmationCode | None:
    """For the owning module: the latest confirmation for a subject."""
    c = ConfirmationCode.objects.filter(subject_type=subject_type, subject_id=str(subject_id)).exclude(
        status="superseded").order_by("-created_at").first()
    return _expire_if_due(c) if c else None


def require_staff(person):
    from core.permissions import is_staff

    if not is_staff(person):
        raise Forbidden()
