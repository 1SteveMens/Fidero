"""RAT API (02 section 7.4): POST /v1/ratings (CL), /v1/ratings/{id}/hide (RV), GET /v1/track-records (Pub)."""
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from core.errors import Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role

from . import selectors, services
from .models import Rating, RatingOpportunity, TrackRecord
from .serializers import (HideIn, OpportunitySerializer, RateIn, RatingSerializer, SummarySerializer,
                          TrackRecordSerializer)


def _valid(cls, request):
    s = cls(data=request.data, context={"request": request})
    s.is_valid(raise_exception=True)
    return s.validated_data


class RatingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Clients see their own ratings; reviewers see the moderation queue (?comment_status=pending)."""

    serializer_class = RatingSerializer
    queryset = Rating.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Rating.objects.none()
        u = self.request.user
        qs = Rating.objects.select_related("opportunity")
        if has_role(u, "RV", "AD"):
            from accounts.selectors import staff_country_codes

            codes = staff_country_codes(u, ("RV", "AD"))
            if codes is not None:
                qs = qs.filter(Q(country__code__in=list(codes)) | Q(country__isnull=True) | Q(rater=u))
        else:
            qs = qs.filter(rater=u)
        st = self.request.query_params.get("comment_status")
        return qs.filter(comment_status=st) if st else qs

    @extend_schema(parameters=[OpenApiParameter("comment_status", str, required=False)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(request=RateIn, responses={201: RatingSerializer},
                   summary="Rate a completed case, deal, milestone or dispute, once (FR-RAT-002)")
    @idempotent
    def create(self, request):
        d = _valid(RateIn, request)
        opp = None
        if d.get("opportunity_id"):
            opp = RatingOpportunity.objects.filter(pk=d["opportunity_id"], rater=request.user).first()
            if opp is None:
                raise NotFound("Nothing to rate here.")
        r = services.rate(request.user, score=d["score"], comment=d.get("comment", ""), opportunity=opp,
                          context_type=d.get("context_type"), context_id=d.get("context_id"),
                          subject_type=d.get("subject_type"), subject_id=d.get("subject_id"))
        return Response(RatingSerializer(r, context={"request": request}).data, status=201)

    @extend_schema(request=HideIn, responses=RatingSerializer,
                   summary="Hide an abusive comment with a reason; the score stays (FR-RAT-004)")
    @action(detail=True, methods=["post"])
    def hide(self, request, pk=None):
        d = _valid(HideIn, request)
        r = services.hide_comment(self.get_object(), request.user, d["reason"])
        return Response(RatingSerializer(r, context={"request": request}).data)

    @extend_schema(request=None, responses=RatingSerializer, summary="Publish a moderated comment (RV)")
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        r = services.publish_comment(self.get_object(), request.user)
        return Response(RatingSerializer(r, context={"request": request}).data)


class OpportunityViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """What the client can rate now."""

    serializer_class = OpportunitySerializer
    queryset = RatingOpportunity.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return RatingOpportunity.objects.none()
        qs = RatingOpportunity.objects.filter(rater=self.request.user)
        if self.request.query_params.get("open"):
            qs = qs.filter(rating__isnull=True)
        return qs

    @extend_schema(parameters=[OpenApiParameter("open", bool, required=False)])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class TrackRecordViewSet(viewsets.GenericViewSet):
    """Public track records (FR-RAT-001, FR-RAT-003)."""

    permission_classes = [permissions.AllowAny]
    serializer_class = TrackRecordSerializer
    queryset = TrackRecord.objects.all()

    @extend_schema(parameters=[OpenApiParameter("subject_type", str, required=False)],
                   responses=TrackRecordSerializer)
    def retrieve(self, request, pk=None):
        st = request.query_params.get("subject_type")
        qs = TrackRecord.objects.filter(subject_id=pk)
        if st:
            qs = qs.filter(subject_type=st)
        tr = qs.first()
        if tr is None:
            from accounts.models import Organisation, Person

            kind = st or ("organisation" if Organisation.objects.filter(pk=pk).exists() else "person")
            if not (Organisation if kind == "organisation" else Person).objects.filter(pk=pk).exists():
                raise NotFound("No such seller, contractor or professional.")
            tr = TrackRecord(subject_type=kind, subject_id=pk, display_name=services.subject_name(kind, pk))
        return Response(TrackRecordSerializer(tr).data)

    @extend_schema(parameters=[OpenApiParameter("subject_ids", str, required=True,
                                                description="Comma-separated ids to compare"),
                               OpenApiParameter("subject_type", str, required=False)],
                   responses=SummarySerializer(many=True),
                   summary="Compare track records, e.g. when a client chooses a contractor (FR-RAT-003)")
    def list(self, request):
        ids = [i for i in (request.query_params.get("subject_ids") or "").split(",") if i.strip()]
        if not ids or len(ids) > 50:
            raise Invalid("Give between 1 and 50 subject ids.")
        st = request.query_params.get("subject_type") or "organisation"
        try:
            data = selectors.summaries(st, ids)
        except Exception:  # noqa: BLE001 - a malformed id
            raise Invalid("The subject ids are not valid.") from None
        return Response(list(data.values()))

    @extend_schema(request=None, responses={200: SummarySerializer}, summary="Recompute now (RV, AD)")
    @action(detail=False, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def recompute(self, request):
        from core.errors import Forbidden

        if not has_role(request.user, "RV", "AD"):
            raise Forbidden()
        return Response({"recomputed": services.recompute_all()})
