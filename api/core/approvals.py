"""One approval component for every two-person rule (ADR-12, RUL-03, RUL-05).

Rules enforced here and again by database triggers (dbsql.py):
- the preparer never approves their own request;
- one person gives at most one approval per request;
- every approval needs a fresh MFA step-up (settings.TENMINA["MFA_FRESHNESS"]);
- the request closes as approved when `required` different people approve,
  and as rejected on the first rejection.

When a request closes, the event `approval.approved` or `approval.rejected`
is published with subject_type and subject_id. The owning module subscribes
and moves its own object on.
"""
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .errors import DomainError, MfaRequired, SameApprover, StateConflict
from .events import publish
from .models import Approval, ApprovalRequest


# Subject types decided only through their owning module's endpoint, which
# adds its own checks (release rights, the signing lawyer, the client first).
# The generic /v1/approvals/{id}/decisions endpoint refuses them.
DEDICATED = {"report_release", "escrow_release", "escrow_cancel", "payee_change", "payee_verification", "refund",
             "offline_fee_payment", "programme_account", "programme_rate", "pro_payment_run", "pro_expense_exception",
             "pro_rate_card_change", "fee_payment", "care_payment", "errand_payment", "repair_release",
             "event_payment", "insurance_premium", "milestone_release", "project_release", "dispute_decision"}


def request_approval(subject_type, subject_id, prepared_by, *, required=2, summary="", country=None):
    if subject_type not in ApprovalRequest.SUBJECT_TYPES:
        raise ValueError(f"Unknown approval subject type '{subject_type}'. Add it to ApprovalRequest.SUBJECT_TYPES.")
    if required < 2 and subject_type not in ApprovalRequest.ONE_APPROVER_TYPES:
        raise DomainError("Two people must approve this.", code="two-person-rule")
    existing = ApprovalRequest.objects.filter(subject_type=subject_type, subject_id=subject_id, status="open").first()
    if existing:
        return existing
    req = ApprovalRequest.objects.create(subject_type=subject_type, subject_id=subject_id, prepared_by=prepared_by,
                                         required=required, summary=summary, country=country)
    from audit.services import record

    record(actor=prepared_by, action="approval.requested", entity="approval_request", entity_id=req.pk,
           data={"subject_type": subject_type, "subject_id": str(subject_id), "required": required})
    publish("approval.requested", req.pk, {"subject_type": subject_type, "subject_id": subject_id})
    return req


def open_request(subject_type, subject_id):
    return ApprovalRequest.objects.filter(subject_type=subject_type, subject_id=subject_id, status="open").first()


def decide(req: ApprovalRequest, approver, *, decision="approve", mfa_at=None, slot=None, note="",
           allowed=None):
    """Record one approval or rejection.

    `allowed(approver) -> bool` lets the owning module apply extra checks
    (release rights, payment rights, assigned reviewer).
    """
    from audit.services import record

    with transaction.atomic():
        req = ApprovalRequest.objects.select_for_update().get(pk=req.pk)
        if req.status != "open":
            raise StateConflict("This approval is already closed.")
        if approver.pk == req.prepared_by_id:
            raise SameApprover("The person who prepared this cannot approve it.")
        if req.approvals.filter(approver=approver).exists():
            raise SameApprover("You have already approved this. A different person must give the next approval.")
        if allowed is not None and not allowed(approver):
            from .errors import Forbidden

            raise Forbidden("You do not hold the rights needed to approve this.")
        now = timezone.now()
        if mfa_at is None or now - mfa_at > settings.TENMINA["MFA_FRESHNESS"]:
            raise MfaRequired()
        n = req.approvals.count()
        Approval.objects.create(request=req, slot=slot or f"approver_{n + 1}", approver=approver,
                                decision=decision, mfa_at=mfa_at, note=note)
        record(actor=approver, action=f"approval.{decision}", entity="approval_request", entity_id=req.pk,
               data={"subject_type": req.subject_type, "subject_id": str(req.subject_id), "note": note})
        if decision == "reject":
            req.status = "rejected"
        elif req.approvals.filter(decision="approve").values("approver").distinct().count() >= req.required:
            req.status = "approved"
        if req.status != "open":
            req.closed_at = now
            req.save(update_fields=["status", "closed_at"])
            publish(f"approval.{req.status}", req.pk,
                    {"subject_type": req.subject_type, "subject_id": req.subject_id, "request_id": req.pk})
        return req


def withdraw(req: ApprovalRequest, actor):
    if req.status == "open":
        req.status = "withdrawn"
        req.closed_at = timezone.now()
        req.save(update_fields=["status", "closed_at"])
        publish("approval.withdrawn", req.pk, {"subject_type": req.subject_type, "subject_id": req.subject_id})
    return req
