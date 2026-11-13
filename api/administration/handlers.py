"""ADM event handlers: apply two-person changes once their approval closes.
Idempotent: each change applies only while it is still pending."""
from django.db import transaction

from core.events import subscribe
from core.models import ApprovalRequest

from . import services
from .models import ChangeRequest, LockedTextVersion

CHANGE_TYPES = {"release_setting_change", "setting_change", "feature_flag_change", "partner_bank_change"}


def _approvers(req: ApprovalRequest):
    return [a.approver for a in req.approvals.filter(decision="approve").select_related("approver")]


@subscribe("approval.approved")
def on_approved(ev):
    st = ev.payload.get("subject_type")
    if st not in CHANGE_TYPES and st != "locked_text_change":
        return
    req = ApprovalRequest.objects.get(pk=ev.payload.get("request_id") or ev.aggregate_id)
    with transaction.atomic():
        if st == "locked_text_change":
            ltv = LockedTextVersion.objects.filter(pk=req.subject_id).first()
            if ltv:
                services._publish_locked_text(ltv, _approvers(req))
            return
        cr = ChangeRequest.objects.filter(pk=req.subject_id).first()
        if cr:
            services.apply_approved_change(cr, _approvers(req))


@subscribe("approval.rejected", "approval.withdrawn")
def on_rejected(ev):
    from core import state

    st = ev.payload.get("subject_type")
    sid = ev.payload.get("subject_id")
    if st == "locked_text_change":
        ltv = LockedTextVersion.objects.filter(pk=sid, status="pending_approval").first()
        if ltv:
            state.transition(ltv, "locked_text", "draft", reason="Approval was rejected or withdrawn")
    elif st in CHANGE_TYPES and ev.topic == "approval.rejected":
        cr = ChangeRequest.objects.filter(pk=sid, status="pending").first()
        if cr:
            state.transition(cr, "adm_change", "rejected", reason="A second administrator rejected it")
