"""REC API (02 7.4: /v1/records/...). Staff see their countries; an authority
representative (AR) sees and confirms only their own authority's records
(US-REC-004 AC2: another authority's record is refused as not found); a lawyer
sees matches for cases they are assigned to."""
from django.db.models import Q
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from administration import flags
from core.errors import Forbidden, Invalid, NotFound
from core.idempotency import idempotent
from core.permissions import has_role

from . import services
from .models import Allocation, AllocationOverlap, Authority, Match, RevenueShare
from .serializers import (RecAllocationIn, RecAllocationSerializer, RecAuthorityIn, RecAuthoritySerializer,
                          RecMatchRunIn, RecMatchSerializer, RecNoteIn, RecOverlapSerializer, RecPaidIn, RecReasonIn,
                          RecRepresentativeIn, RecRepresentativeSerializer, RecShareComputeIn, RecShareSerializer)

STAFF = ("CM", "RV", "AD")


def _valid(cls, request):
    s = cls(data=request.data)
    s.is_valid(raise_exception=True)
    return s.validated_data


def _flag():
    flags.require(services.FLAG)


def _get(model, pk):
    obj = model.objects.filter(pk=pk).first() if pk else None
    if obj is None:
        raise NotFound()
    return obj


def _country(code):
    from countries.models import Country

    c = Country.objects.filter(code=str(code or "").upper()).first()
    if c is None:
        raise Invalid("Unknown country.", code="validation-error")
    return c


def _staff_scope(qs, user, field="country"):
    from accounts.selectors import scope_to_staff_countries

    if not has_role(user, *STAFF):
        return qs.none()
    return scope_to_staff_countries(qs, user, field=field, roles=STAFF)


class AuthorityViewSet(viewsets.GenericViewSet):
    serializer_class = RecAuthoritySerializer
    queryset = Authority.objects.none()

    def get_queryset(self):
        _flag()
        u = self.request.user
        own = Authority.objects.filter(pk__in=services.authority_ids_of(u)) if has_role(u, "AR") else \
            Authority.objects.none()
        return (_staff_scope(Authority.objects.all(), u) | own).distinct().select_related("country")

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(RecAuthoritySerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(RecAuthoritySerializer(self.get_object()).data)

    @extend_schema(request=RecAuthorityIn, responses={201: RecAuthoritySerializer})
    @idempotent
    def create(self, request):
        d = _valid(RecAuthorityIn, request)
        from evidence.models import Evidence

        ev = Evidence.objects.filter(pk=d.get("agreement_evidence_id")).first() if d.get("agreement_evidence_id") \
            else None
        a = services.create_authority(request.user, country=_country(d["country"]), name=d["name"], kind=d["kind"],
                                      region=d["region"], district=d["district"], share_per_case=d["share_per_case"],
                                      agreement_evidence=ev)
        return Response(RecAuthoritySerializer(a).data, status=201)

    @extend_schema(request=RecRepresentativeIn, responses={201: RecRepresentativeSerializer})
    @action(detail=True, methods=["post"])
    def representatives(self, request, pk=None):
        from accounts.models import Person
        from evidence.models import Evidence

        d = _valid(RecRepresentativeIn, request)
        r = services.add_representative(request.user, authority=self.get_object(),
                                        person=_get(Person, d["person_id"]), title=d["title"],
                                        authorisation_evidence=_get(Evidence, d["authorisation_evidence_id"]))
        return Response(RecRepresentativeSerializer(r).data, status=201)


class AllocationViewSet(viewsets.GenericViewSet):
    serializer_class = RecAllocationSerializer
    queryset = Allocation.objects.none()

    def get_queryset(self):
        _flag()
        u = self.request.user
        qs = _staff_scope(Allocation.objects.all(), u)
        if has_role(u, "AR"):
            qs = qs | Allocation.objects.filter(authority_id__in=services.authority_ids_of(u))
        qs = qs.distinct().select_related("authority", "allottee", "country", "document_evidence")
        p = self.request.query_params
        if p.get("authority"):
            qs = qs.filter(authority_id=p["authority"])
        if p.get("status"):
            qs = qs.filter(status=p["status"])
        if p.get("q"):
            qs = qs.filter(Q(reference__icontains=p["q"]) | Q(allottee__name__icontains=p["q"])
                           | Q(locality__icontains=p["q"]) | Q(plot_number__icontains=p["q"]))
        return qs

    @extend_schema(parameters=[OpenApiParameter("authority", str), OpenApiParameter("status", str),
                               OpenApiParameter("q", str)])
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(RecAllocationSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(RecAllocationSerializer(self.get_object()).data)

    @extend_schema(request=RecAllocationIn, responses={201: RecAllocationSerializer})
    @idempotent
    def create(self, request):
        from evidence.models import Evidence

        _flag()
        d = _valid(RecAllocationIn, request)
        authority = _get(Authority, d["authority_id"])
        if not services.can_view_authority(request.user, authority):
            raise NotFound()
        a = services.capture_allocation(
            request.user, authority=authority, reference=d["reference"], allottee_name=d["allottee_name"],
            allottee_kind=d["allottee_kind"], allottee_phone=d["allottee_phone"], allocated_on=d["allocated_on"],
            document_evidence=_get(Evidence, d["document_evidence_id"]), points=d.get("points"),
            geojson=d.get("geojson"), locality=d["locality"], plot_number=d["plot_number"],
            previous=_get(Allocation, d["previous_id"]) if d.get("previous_id") else None,
            extra_documents=[_get(Evidence, e) for e in d.get("extra_evidence_ids") or []])
        return Response(RecAllocationSerializer(a).data, status=201)

    @extend_schema(request=None, responses=RecAllocationSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def confirm(self, request, pk=None):
        """The authority's representative confirms the record (US-REC-004)."""
        return Response(RecAllocationSerializer(services.confirm_allocation(self.get_object(), request.user)).data)

    @extend_schema(request=RecReasonIn, responses=RecAllocationSerializer)
    @action(detail=True, methods=["post"])
    def dispute(self, request, pk=None):
        d = _valid(RecReasonIn, request)
        return Response(RecAllocationSerializer(services.dispute_allocation(self.get_object(), request.user,
                                                                            d["reason"])).data)

    @extend_schema(request=RecNoteIn, responses=RecAllocationSerializer)
    @action(detail=True, methods=["post"])
    def corrections(self, request, pk=None):
        d = _valid(RecNoteIn, request)
        return Response(RecAllocationSerializer(services.correct_allocation(self.get_object(), request.user,
                                                                            note=d["note"])).data)


class OverlapViewSet(viewsets.GenericViewSet):
    serializer_class = RecOverlapSerializer
    queryset = AllocationOverlap.objects.none()

    def get_queryset(self):
        _flag()
        return _staff_scope(AllocationOverlap.objects.all(), self.request.user, field="allocation__country")

    @extend_schema(request=RecNoteIn, responses=RecOverlapSerializer)
    @action(detail=True, methods=["post"])
    def resolutions(self, request, pk=None):
        d = _valid(RecNoteIn, request)
        return Response(RecOverlapSerializer(services.resolve_overlap(self.get_object(), request.user,
                                                                      note=d["note"])).data)


class MatchViewSet(viewsets.GenericViewSet):
    serializer_class = RecMatchSerializer
    queryset = Match.objects.none()

    def get_queryset(self):
        from cases.models import Task

        _flag()
        u = self.request.user
        qs = _staff_scope(Match.objects.all(), u)
        if has_role(u, "LW"):
            cases = Task.objects.filter(owner_role="LW").filter(Q(assignee=u) | Q(second_assignee=u)).values("case_id")
            qs = qs | Match.objects.filter(case_id__in=cases)
        qs = qs.distinct().select_related("case", "allocation__authority")
        if self.request.query_params.get("asset_id"):
            qs = qs.filter(asset_id=self.request.query_params["asset_id"])
        if self.request.query_params.get("case_id"):
            qs = qs.filter(case_id=self.request.query_params["case_id"])
        return qs

    @extend_schema(parameters=[OpenApiParameter("asset_id", str), OpenApiParameter("case_id", str)])
    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(RecMatchSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(RecMatchSerializer(self.get_object()).data)

    @extend_schema(request=RecMatchRunIn, responses=RecMatchSerializer(many=True))
    @action(detail=False, methods=["post"])
    def run(self, request):
        """Check a case against the records now (it also runs when a boundary is saved)."""
        from cases.models import Case

        _flag()
        case = _get(Case, _valid(RecMatchRunIn, request)["case_id"])
        if not has_role(request.user, "CM", "RV", country=case.country):
            raise Forbidden()
        return Response(RecMatchSerializer(services.match_case(case), many=True).data)

    @extend_schema(request=RecNoteIn, responses=RecMatchSerializer)
    @action(detail=True, methods=["post"])
    @idempotent
    def confirm(self, request, pk=None):
        d = _valid(RecNoteIn, request)
        return Response(RecMatchSerializer(services.confirm_match(self.get_object(), request.user,
                                                                  note=d["note"])).data)

    @extend_schema(request=RecNoteIn, responses=RecMatchSerializer)
    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        d = _valid(RecNoteIn, request)
        return Response(RecMatchSerializer(services.reject_match(self.get_object(), request.user,
                                                                 note=d["note"])).data)


class RevenueShareViewSet(viewsets.GenericViewSet):
    serializer_class = RecShareSerializer
    queryset = RevenueShare.objects.none()

    def get_queryset(self):
        from accounts.selectors import scope_to_staff_countries

        _flag()
        u = self.request.user
        qs = scope_to_staff_countries(RevenueShare.objects.all(), u, roles=("AD",)) if has_role(u, "AD") \
            else RevenueShare.objects.none()
        if has_role(u, "AR"):
            qs = qs | RevenueShare.objects.filter(authority_id__in=services.authority_ids_of(u))
        return qs.distinct().select_related("authority")

    def list(self, request):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(RecShareSerializer(page, many=True).data)

    def retrieve(self, request, pk=None):
        return Response(RecShareSerializer(self.get_object()).data)

    @extend_schema(request=RecShareComputeIn, responses={201: RecShareSerializer(many=True)})
    @action(detail=False, methods=["post"])
    def compute(self, request):
        d = _valid(RecShareComputeIn, request)
        auth = _get(Authority, d["authority_id"]) if d.get("authority_id") else None
        out = services.compute_revenue_shares(request.user, country=_country(d["country"]),
                                              period_start=d["period_start"], period_end=d["period_end"],
                                              authority=auth)
        return Response(RecShareSerializer(out, many=True).data, status=201)

    @extend_schema(request=None, responses=RecShareSerializer)
    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(RecShareSerializer(services.approve_share(self.get_object(), request.user)).data)

    @extend_schema(request=RecPaidIn, responses=RecShareSerializer)
    @action(detail=True, methods=["post"])
    def paid(self, request, pk=None):
        d = _valid(RecPaidIn, request)
        return Response(RecShareSerializer(services.mark_share_paid(self.get_object(), request.user,
                                                                    reference=d["reference"])).data)
