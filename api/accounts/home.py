"""The client's home dashboard (FR-ACC-012, `GET /v1/home`).

A registry: each module that has something running at home registers a
provider once, usually in its handlers.py or AppConfig.ready():

    from accounts import home

    @home.register
    def my_items(person):
        return [home.item(kind="fee_payment", id=p.pk, title="School fees for Kofi", status=p.status,
                          status_text="Waiting for your approval", next_date=p.due_on, needs_action=True,
                          link=f"/fees/payments/{p.pk}", family_member_id=p.family_member_id, line="fee")]

`needs_action` is what the apps show in orange: only things that need the
client. A provider that fails is logged and skipped, so one module never
breaks the dashboard.
"""
import logging

log = logging.getLogger(__name__)
_providers: list = []


def register(fn):
    if fn not in _providers:
        _providers.append(fn)
    return fn


def unregister(fn):
    if fn in _providers:
        _providers.remove(fn)


def item(*, kind, id, title, status="", status_text="", next_date=None, needs_action=False, link="",
         family_member_id=None, line="", amount=None):
    return {"kind": kind, "id": str(id), "title": title, "status": status, "status_text": status_text,
            "next_date": next_date.isoformat() if hasattr(next_date, "isoformat") else next_date,
            "needs_action": bool(needs_action), "link": link,
            "family_member_id": str(family_member_id) if family_member_id else None, "line": line, "amount": amount}


def _own_items(person):
    from .models import BankAccount, IdentityCheck, RepresentativeGrant

    out = []
    if person.id_check_status in ("none", "failed"):
        out.append(item(kind="identity_check", id=person.pk, title="Confirm your identity",
                        status=person.id_check_status, needs_action=True, link="/account/identity",
                        status_text="We need to confirm who you are before your first report or escrow."))
    else:
        chk = IdentityCheck.objects.filter(person=person, status="manual_review").first()
        if chk:
            out.append(item(kind="identity_check", id=chk.pk, title="Identity check", status=chk.status,
                            status_text="A case manager is checking your document by hand.",
                            link="/account/identity"))
    if not person.phone_verified_at and person.phone:
        out.append(item(kind="contact_check", id=person.pk, title="Confirm your mobile number", status="pending",
                        needs_action=True, link="/account/profile",
                        status_text="Enter the code we sent to your phone."))
    for acct in BankAccount.objects.filter(holder=person).exclude(verification_status="verified"):
        text = {"unverified": "Send a letter from your bank so we can verify it.",
                "pending": "Tenmina is checking this account.",
                "rejected": "We could not verify this account. Send a new bank letter.",
                "suspended": "This account is suspended. Contact your case manager."}[acct.verification_status]
        out.append(item(kind="bank_account", id=acct.pk, title=f"{acct.bank_name} account ending {acct.last4}",
                        status=acct.verification_status, status_text=text,
                        needs_action=acct.verification_status in ("unverified", "rejected"),
                        link=f"/account/bank-accounts/{acct.pk}"))
    for g in RepresentativeGrant.objects.filter(client=person, status="pending"):
        out.append(item(kind="representative", id=g.pk, title=f"Representative {g.invited_name or g.invited_email}",
                        status="pending", status_text="Waiting for them to sign up.",
                        link="/account/representatives"))
    return out


def items_for(person) -> list[dict]:
    out = _own_items(person)
    for fn in list(_providers):
        try:
            out.extend(fn(person) or [])
        except Exception:  # noqa: BLE001
            log.exception("home provider %s failed", getattr(fn, "__name__", fn))
    out.sort(key=lambda i: (not i["needs_action"], i["next_date"] or "9999", i["title"]))
    return out
