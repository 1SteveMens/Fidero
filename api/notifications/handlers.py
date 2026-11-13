"""NTF consumes "most events" (02 4.2). A topic below is turned into a
notification when its payload names the person to tell. Producers include
these keys in their payload; anything else is ignored. Idempotent through
core.events (one delivery per consumer and event).

A producer that has already told the person in its own words (CASE status
messages, RPT report release, CASE task assignment) sets `"notified": true`
in the payload, and this handler sends nothing, so nobody hears it twice.

| topic | template | person key in payload | other keys used |
|---|---|---|---|
| case.status_changed | case_status_changed | client_id | case_ref, status_label (or to) |
| task.assigned | task_assigned | assignee_id | task_title (or title), case_ref, due_date |
| report.released | report_released | client_id | case_ref |
| invoice.submitted, milestone.status_changed, repair.reported | approval_needed | client_id | subject_label, amount |
| release.confirmed | money_update | client_id | subject_label, amount |
"""
from core.events import subscribe

EVENT_NOTIFICATIONS = {
    "case.status_changed": ("case_status_changed", "client_id", "preferred", False),
    "task.assigned": ("task_assigned", "assignee_id", ("in_app", "email"), False),
    "report.released": ("report_released", "client_id", "preferred", False),
    "invoice.submitted": ("approval_needed", "client_id", "preferred", True),
    "release.confirmed": ("money_update", "client_id", "preferred", False),
}


def _person(pk):
    from accounts.models import Person

    if not pk:
        return None
    return Person.objects.filter(pk=pk, is_active=True).first()


@subscribe(*EVENT_NOTIFICATIONS)
def on_event(ev):
    from .services import notify

    code, key, channels, needs_action = EVENT_NOTIFICATIONS[ev.topic]
    p = ev.payload or {}
    if p.get("notified"):
        return
    person = _person(p.get(key))
    if person is None:
        return
    ctx = {k: v for k, v in p.items() if isinstance(v, (str, int, float, dict))}
    ctx.setdefault("status_label", str(p.get("to", "")).replace("_", " "))
    ctx.setdefault("task_title", p.get("title", ""))
    ctx.setdefault("subject_label", p.get("label", ev.topic.replace(".", " ").replace("_", " ")))
    notify(person, code, channels=channels, context=ctx, link=p.get("link", ""), needs_action=needs_action,
           subject_type=p.get("subject_type") or p.get("entity") or ev.topic.split(".")[0],
           subject_id=str(p.get("id") or ev.aggregate_id or ""))


@subscribe("approval.requested")
def on_approval_requested(ev):
    """Tell the other administrators that an ADM or CTY change waits for them."""
    from accounts.models import Person
    from core.models import ApprovalRequest

    from .services import notify

    admin_types = {"locked_text_change", "release_setting_change", "setting_change", "feature_flag_change",
                   "partner_bank_change", "country_config_publish", "country_activation"}
    if ev.payload.get("subject_type") not in admin_types:
        return
    req = ApprovalRequest.objects.filter(pk=ev.aggregate_id).first()
    if req is None:
        return
    for p in Person.objects.filter(role_grants__role="AD", role_grants__revoked_at__isnull=True,
                                   is_active=True).exclude(pk=req.prepared_by_id).distinct():
        notify(p, "approval_needed", channels=("in_app",), category="approval", needs_action=True,
               context={"subject_label": req.summary or req.subject_type.replace("_", " "),
                        "link": f"/back-office/approvals/{req.pk}"},
               link=f"/back-office/approvals/{req.pk}", subject_type="approval_request", subject_id=str(req.pk))


@subscribe("approval.approved", "approval.rejected", "approval.withdrawn")
def on_approval_closed(ev):
    from .services import resolve_action

    resolve_action(subject_type="approval_request", subject_id=str(ev.aggregate_id))


@subscribe("account.deletion_requested")
def on_deletion(ev):
    """FR-APP-004: push tokens are revoked at once."""
    from accounts.models import Person

    from .services import revoke_all_devices

    person = Person.objects.filter(pk=ev.payload.get("person_id") or ev.aggregate_id).first()
    if person is not None:
        revoke_all_devices(person, reason="account deletion requested")
