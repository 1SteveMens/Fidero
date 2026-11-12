from django.urls import path
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.errors import Forbidden
from core.permissions import has_role

from .models import AuditEvent
from .services import verify_chain


def _row(e):
    return {"seq": e.seq, "occurred_at": e.occurred_at, "actor_id": e.actor_id, "actor": e.actor_label,
            "action": e.action, "entity": e.entity, "entity_id": e.entity_id, "country": e.country_code,
            "data": e.data, "hash": e.hash}


@extend_schema(responses=dict)
@api_view(["GET"])
def events(request):
    """FR-AUD-002: search the audit log (reviewers and administrators)."""
    if not has_role(request.user, "RV", "AD", "DPO"):
        raise Forbidden()
    qs = AuditEvent.objects.all().order_by("-seq")
    for f in ("entity", "entity_id", "action", "actor_id"):
        v = request.query_params.get(f)
        if v:
            qs = qs.filter(**{f: v})
    before = request.query_params.get("before_seq")
    if before:
        qs = qs.filter(seq__lt=int(before))
    rows = list(qs[: min(int(request.query_params.get("limit", 50)), 200)])
    return Response({"items": [_row(e) for e in rows], "next_cursor": str(rows[-1].seq) if rows else None})


@extend_schema(responses=dict)
@api_view(["POST"])
def verify(request):
    """FR-AUD-003: recompute the chain."""
    if not has_role(request.user, "AD"):
        raise Forbidden()
    return Response(verify_chain())


urlpatterns = [path("audit-events", events), path("audit-events/verify", verify)]
