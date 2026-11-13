"""Security events from other modules' events (02 section 10.10). The audit
entries themselves are written in-transaction by record(); these handlers
only add the security log and alerts for topics 10.10 names."""
from django.utils import timezone

from core.events import subscribe

from .services import security_event

# topic -> security event kind
TOPIC_KINDS = {
    "account.locked": "account.locked",
    "payee.verified": "payee.verified",
    "payee.suspended": "payee.suspended",
    "payee_change.requested": "payee_change.requested",
    "payee_change.applied": "payee_change.applied",
    "payee_change.stopped": "payee_change.stopped",
    "recheck.failed": "recheck.failed",
    "incident.opened": "incident.opened",
    "evidence.rejected": "evidence.rejected",
}


@subscribe(*TOPIC_KINDS)
def on_security_topic(ev):
    kind = TOPIC_KINDS[ev.topic]
    security_event(kind, entity=ev.topic.split(".")[0], entity_id=ev.aggregate_id or "", data=ev.payload)


@subscribe("national_id_check.completed")
def on_national_id(ev):
    if ev.payload.get("result") in ("no_match", "not_found"):
        security_event("national_id.no_match", entity="national_id_check", entity_id=ev.aggregate_id or "",
                       data={"result": ev.payload.get("result")})


# Working hours for the out-of-hours approval alert (assumption, 10.10):
# 07:00 to 19:00 UTC on weekdays. A country calendar can refine this later.
WORK_START, WORK_END = 7, 19


@subscribe("approval.approved")
def on_approval(ev):
    now = timezone.now()
    if now.weekday() >= 5 or not (WORK_START <= now.hour < WORK_END):
        security_event("approval.out_of_hours", entity="approval_request", entity_id=ev.aggregate_id or "",
                       data={"subject_type": ev.payload.get("subject_type")})
