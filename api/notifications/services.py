from core.adapters import get_adapter

from .models import Message


def notify(person=None, template: str = "", *, body: str, subject: str = "", channels=("in_app",), link="",
           subject_obj=None, needs_action=False, to_address="") -> list[Message]:
    """Send a message. Every module calls this; never a provider directly.

    Content policy (FR-NTF-004): never put amounts with account numbers,
    codes or evidence links in SMS or WhatsApp; link to the app instead.
    """
    out = []
    for ch in channels:
        m = Message.objects.create(
            person=person, to_address=to_address, channel=ch, template=template, subject=subject, body=body,
            link=link, needs_action=needs_action,
            subject_type=type(subject_obj).__name__.lower() if subject_obj is not None else "",
            subject_id=str(getattr(subject_obj, "pk", "")) if subject_obj is not None else "",
        )
        if ch != "in_app":
            adapter = get_adapter("push" if ch == "push" else "messaging")
            ok = adapter.send(m)
            m.status = "sent" if ok else "failed"
            m.save(update_fields=["status"])
        else:
            m.status = "delivered"
            m.save(update_fields=["status"])
        out.append(m)
    return out
