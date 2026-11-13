from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .approvals import decide
from .models import ApprovalRequest
from .permissions import is_staff
from .views import require_mfa


class ApprovalRequestSerializer(serializers.ModelSerializer):
    approvals = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = ["id", "subject_type", "subject_id", "prepared_by", "required", "status", "summary",
                  "created_at", "closed_at", "approvals"]

    def get_approvals(self, obj):
        return [{"approver": str(a.approver_id), "approver_name": a.approver.full_name, "decision": a.decision,
                 "slot": a.slot, "at": a.approved_at} for a in obj.approvals.select_related("approver")]


@extend_schema(responses=ApprovalRequestSerializer(many=True))
@api_view(["GET"])
def approval_queue(request):
    """Open approvals the caller could give (staff only)."""
    if not is_staff(request.user):
        return Response({"items": [], "next_cursor": None})
    qs = ApprovalRequest.objects.filter(status=request.query_params.get("status", "open")).exclude(
        prepared_by=request.user).order_by("created_at")
    st = request.query_params.get("subject_type")
    if st:
        qs = qs.filter(subject_type=st)
    return Response({"items": ApprovalRequestSerializer(qs[:100], many=True).data, "next_cursor": None})


@extend_schema(request=dict, responses=ApprovalRequestSerializer)
@api_view(["POST"])
def approval_decide(request, pk):
    """Generic approve/reject. Owning modules may add their own endpoints with
    extra checks; this one is for approvals with no extra rule."""
    from .approvals import DEDICATED
    from .errors import DomainError

    req = ApprovalRequest.objects.get(pk=pk)
    if req.subject_type in DEDICATED:
        raise DomainError("Approve this from its own screen, where its extra checks run.",
                          code="use-dedicated-endpoint", extra={"subject_type": req.subject_type})
    at = require_mfa(request)
    req = decide(req, request.user, decision=request.data.get("decision", "approve"), mfa_at=at,
                 note=request.data.get("note", ""))
    return Response(ApprovalRequestSerializer(req).data)


urlpatterns = [
    path("approvals", approval_queue),
    path("approvals/<uuid:pk>/decisions", approval_decide),
]
