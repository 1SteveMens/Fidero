"""NTF read-only queries other modules may use."""
from .models import ConfirmationCode, Message, PushDevice


def messages_for(subject_type: str, subject_id) -> list[Message]:
    """Proof that someone was told (FR-NTF-005)."""
    return list(Message.objects.filter(subject_type=subject_type, subject_id=str(subject_id)).order_by("created_at"))


def latest_confirmation(subject_type: str, subject_id) -> ConfirmationCode | None:
    return ConfirmationCode.objects.filter(subject_type=subject_type, subject_id=str(subject_id)).exclude(
        status="superseded").order_by("-created_at").first()


def is_confirmed(subject_type: str, subject_id) -> bool:
    c = latest_confirmation(subject_type, subject_id)
    return bool(c and c.status == "confirmed")


def active_devices(person):
    return PushDevice.objects.filter(person=person, revoked_at__isnull=True)
