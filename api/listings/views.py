"""LST API (02 section 7.4). Search, the map, listing pages and the report link are public or for any
signed-in buyer (RUL-14); sellers see their organisation's listings; staff are scoped to their countries."""
import html
import json

from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import mixins, permissions, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound as DrfNotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from core.errors import Invalid, NotFound
from core.idempotency import idempotent

from . import selectors, services
from .models import Enquiry, Listing, ListingMedia, Reservation, SellerScreening
from .serializers import (AnswerIn, EnquiryIn, EnquirySerializer, FeatureCollectionSerializer, ListingFreshSearchIn,
                          GeneralEnquiryIn, ListingCreateSerializer, ListingDetailSerializer, ListingSerializer,
                          ListingUpdateSerializer, MediaIn, MediaSerializer, NoteIn, ReasonIn, RemovalIn,
                          RemovalSerializer, ReportViewSerializer, ReservationSerializer, ScreeningCheckIn,
                          ScreeningDecisionIn, ScreeningIn, ScreeningSerializer, SubmitIn, SuspensionSerializer)

SEARCH_PARAMS = [OpenApiParameter(n, str, required=False) for n in (
    "country", "region", "district", "locality", "kind", "min_price", "max_price", "currency", "min_size",
    "max_size", "verified_since", "q", "organisation_id", "bbox", "sort", "mine", "status")]


def _valid(cls, request):
    s = cls(data=request.data, context={"request": request})
    s.is_valid(raise_exception=True)
    return s.validated_data


def _country(code):
    from countries.models import Country

    c = Country.objects.filter(code=str(code or "").upper()).first()
    if c is None:
        raise Invalid("Unknown country.")
    return c


def _evidence(pk):
    from evidence.models import Evidence

    ev = Evidence.objects.filter(pk=pk).first()
    if ev is None:
        raise Invalid("Evidence not found.")
    return ev


def _money(d):
    return {"amount": str(d["amount"]), "currency": d.get("currency", "")} if d else None


class SearchPagination(PageNumberPagination):
    page_size = 24
    page_size_query_param = "limit"
    max_page_size = 100

    def get_paginated_response(self, data):
        return Response({"items": data, "total": self.page.paginator.count,
                         "next_page": self.page.next_page_number() if self.page.has_next() else None})

    def get_paginated_response_schema(self, schema):
        return {"type": "object", "properties": {"items": schema, "total": {"type": "integer"},
                                                 "next_page": {"type": "integer", "nullable": True}}}


class ListingViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Search, map and listing pages (Pub); submit (SE, DV, AR); remove (RV)."""

    queryset = Listing.objects.none()
    pagination_class = SearchPagination
    serializer_class = ListingSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_permissions(self):
        if self.action in ("list", "retrieve", "map", "page", "photo"):
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        p = self.request.query_params
        if self.action == "list" and (p.get("mine") or p.get("status")) and user.is_authenticated:
            qs = selectors.visible_listings(user)
            if p.get("mine"):
                from django.db.models import Q

                qs = qs.filter(Q(submitted_by=user) | Q(organisation__memberships__person=user,
                                                        organisation__memberships__status="active")).distinct()
            if p.get("status"):
                qs = qs.filter(status__in=p["status"].split(","))
            return selectors.search({k: v for k, v in p.items() if k not in ("status", "mine")}, qs=qs)
        if self.action == "list":
            return selectors.search(p)
        return selectors.visible_listings(user if user.is_authenticated else None).select_related(
            "asset", "organisation", "country", "report", "submitted_by")

    def get_object(self):
        obj = self.get_queryset().filter(pk=self.kwargs["pk"]).first()
        if obj is None:
            raise NotFound("Listing not found.")
        return obj

    @extend_schema(parameters=SEARCH_PARAMS, responses=ListingSerializer(many=True),
                   summary="Search live listings (FR-LST-004). Expired and suspended listings never show.")
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(responses=ListingDetailSerializer)
    def retrieve(self, request, *args, **kwargs):
        x = self.get_object()
        if x.status in ("live", "reserved"):
            services.count_view(x)
        return Response(ListingDetailSerializer(x, context={"request": request}).data)

    @extend_schema(request=ListingCreateSerializer, responses={201: ListingDetailSerializer})
    @idempotent
    def create(self, request):
        d = _valid(ListingCreateSerializer, request)
        data = dict(d)
        data["price"] = _money(d["price"])
        data["asset"] = dict(d["asset"]) if d.get("asset") else None
        for k in ("organisation_id", "asset_id", "report_id"):
            if d.get(k):
                data[k] = str(d[k])
        x = services.create_listing(actor=request.user, country=_country(d["country"]), data=data)
        return Response(ListingDetailSerializer(x, context={"request": request}).data, status=201)

    @extend_schema(request=ListingUpdateSerializer, responses=ListingDetailSerializer,
                   summary="Seller edits title, description and price. Badge, report and status are system-set.")
    def partial_update(self, request, pk=None):
        x = Listing.objects.filter(pk=pk).first()
        if x is None:
            raise NotFound()
        data = dict(request.data)
        if "price" in data and isinstance(data["price"], dict):
            data["price"] = {"amount": data["price"].get("amount"), "currency": data["price"].get("currency", "")}
        x = services.update_listing(x, request.user, data)
        return Response(ListingDetailSerializer(x, context={"request": request}).data)

    def _mine(self, pk):
        x = selectors.visible_listings(self.request.user).filter(pk=pk).first()
        if x is None:
            raise NotFound("Listing not found.")
        return x

    @extend_schema(request=MediaIn, responses={201: MediaSerializer})
    @action(detail=True, methods=["post"])
    def media(self, request, pk=None):
        x = self._mine(pk)
        d = _valid(MediaIn, request)
        f = d.get("file")
        m = services.add_media(x, request.user, kind=d["kind"], caption=d.get("caption", ""),
                               evidence=_evidence(d["evidence_id"]) if d.get("evidence_id") else None,
                               data=f.read() if f else None, content_type=getattr(f, "content_type", ""),
                               name=getattr(f, "name", ""))
        return Response(MediaSerializer(m).data, status=201)

    @extend_schema(request=SubmitIn, responses=ListingDetailSerializer,
                   summary="Submit for verification; PAY invoices the listing fee (FR-LST-001)")
    @action(detail=True, methods=["post"])
    @idempotent
    def submissions(self, request, pk=None):
        d = _valid(SubmitIn, request)
        x = services.submit(self._mine(pk), request.user, terms_version=d.get("terms_version", ""),
                            scope_version=d.get("scope_version", ""))
        return Response(ListingDetailSerializer(x, context={"request": request}).data)

    @extend_schema(request=SubmitIn, responses=ListingDetailSerializer, summary="Order re-verification (Expired)")
    @action(detail=True, methods=["post"])
    @idempotent
    def reverifications(self, request, pk=None):
        d = _valid(SubmitIn, request)
        x = services.reverify(self._mine(pk), request.user, terms_version=d.get("terms_version", ""),
                              scope_version=d.get("scope_version", ""))
        return Response(ListingDetailSerializer(x, context={"request": request}).data)

    @extend_schema(request=ReasonIn, responses=ListingDetailSerializer)
    @action(detail=True, methods=["post"])
    def withdrawals(self, request, pk=None):
        x = services.withdraw(self._mine(pk), request.user, request.data.get("reason", ""))
        return Response(ListingDetailSerializer(x, context={"request": request}).data)

    @extend_schema(request=ReasonIn, responses={201: SuspensionSerializer}, summary="Suspend (CM, RV)")
    @action(detail=True, methods=["post"])
    def suspensions(self, request, pk=None):
        d = _valid(ReasonIn, request)
        s = services.staff_suspend(self._mine(pk), request.user, d["reason"])
        return Response(SuspensionSerializer(s).data, status=201)

    @extend_schema(request=NoteIn, responses=ListingDetailSerializer, summary="Lift every suspension (RV only)")
    @action(detail=True, methods=["post"])
    def reinstatements(self, request, pk=None):
        d = _valid(NoteIn, request)
        x = services.reinstate(self._mine(pk), request.user, d["note"])
        return Response(ListingDetailSerializer(x, context={"request": request}).data)

    @extend_schema(request=RemovalIn, responses={201: RemovalSerializer},
                   summary="Remove a listing, or its seller and all their listings, for misconduct (RV)")
    @action(detail=True, methods=["post"])
    @idempotent
    def removals(self, request, pk=None):
        d = _valid(RemovalIn, request)
        r = services.remove(self._mine(pk), request.user, d["reason"], scope=d["scope"])
        return Response(RemovalSerializer(r).data, status=201)

    @extend_schema(request=EnquiryIn, responses={201: EnquirySerializer})
    @action(detail=True, methods=["post"])
    @idempotent
    def enquiries(self, request, pk=None):
        d = _valid(EnquiryIn, request)
        e = services.enquire(request.user, message=d["message"], listing=self._mine(pk))
        return Response(EnquirySerializer(e, context={"request": request}).data, status=201)

    @extend_schema(request=None, responses={201: ReservationSerializer},
                   summary="Reserve: a fresh search starts and a purchase escrow is proposed (FR-LST-005)")
    @action(detail=True, methods=["post"])
    @idempotent
    def reservations(self, request, pk=None):
        r = services.reserve(self._mine(pk), request.user)
        return Response(ReservationSerializer(r, context={"request": request}).data, status=201)

    @extend_schema(responses=ReportViewSerializer,
                   summary="The full released report behind the badge, for any signed-in buyer (RUL-14)")
    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        x = self._mine(pk)
        allowed = services.badge_valid(x) or services.is_seller(request.user, x) or \
            services.is_staff(request.user, x.country) or x.reservations.filter(buyer=request.user).exists()
        if not allowed or x.report is None:
            raise NotFound("There is no report to show for this listing.")
        r = x.report
        from evidence.services import issue_link

        pdf = issue_link(r.pdf_evidence, request.user, variant="original", request=request) if r.pdf_evidence_id \
            else None
        sections = [{"number": s.number, "label": getattr(s, "label", str(s.number)), "title": s.title,
                     "verdict": s.verdict, "findings": (s.findings or {}).get("text", "")}
                    for s in r.sections.order_by("position")]
        return Response({"listing_id": x.pk, "report_id": r.pk, "reference": r.reference, "version": r.version,
                         "verdict": r.overall_verdict, "released_at": r.released_at, "pdf_sha256": r.pdf_sha256,
                         "pdf": pdf, "sections": sections})

    @extend_schema(parameters=SEARCH_PARAMS, responses=FeatureCollectionSerializer,
                   summary="Search results as GeoJSON points for the map (FR-LST-004)")
    @action(detail=False, methods=["get"])
    def map(self, request):
        features = []
        for x in selectors.search(request.query_params).select_related("asset__current_boundary")[:1000]:
            p = selectors.point_of(x)
            if p is None:
                continue  # the list view still shows it (US-LST-004b AC2)
            features.append({"type": "Feature", "id": str(x.pk), "geometry": {"type": "Point", "coordinates": list(p)},
                             "properties": {"reference": x.reference, "title": x.title, "kind": x.kind,
                                            "price": {"amount": f"{x.price_amount:.2f}", "currency": x.price_currency},
                                            "locality": x.locality, "checks_date": x.checks_date,
                                            "link": f"/listings/{x.pk}"}})
        return Response({"type": "FeatureCollection", "features": features})

    @extend_schema(responses={(200, "text/html"): OpenApiTypes.STR, 404: OpenApiResponse(description="Not live")},
                   summary="Server-rendered listing page for search engines and slow phones (FR-LST-010)")
    @action(detail=True, methods=["get"])
    def page(self, request, pk=None):
        x = Listing.objects.filter(pk=pk).select_related("asset", "organisation", "country", "report").first()
        if x is None or not services.badge_valid(x):
            resp = HttpResponse("<!doctype html><title>Not found</title><meta name=robots content=noindex>",
                                status=404, content_type="text/html; charset=utf-8")
            resp["X-Robots-Tag"] = "noindex"
            return resp
        return HttpResponse(_render_page(x), content_type="text/html; charset=utf-8")

    @extend_schema(responses={(200, "image/*"): OpenApiTypes.BINARY}, summary="A public photo of a live listing",
                   parameters=[OpenApiParameter("media_id", str, OpenApiParameter.PATH)])
    @action(detail=True, methods=["get"], url_path=r"photos/(?P<media_id>[^/.]+)")
    def photo(self, request, pk=None, media_id=None):
        m = ListingMedia.objects.filter(pk=media_id, listing_id=pk, public=True, kind="photo").select_related(
            "listing", "evidence").first()
        if m is None or not services.badge_valid(m.listing):
            raise DrfNotFound()
        ev = m.evidence
        if ev.deleted_at or ev.scan_status != "clean":
            raise DrfNotFound()
        from core.adapters import get_adapter

        resp = HttpResponse(get_adapter("evidence_store").get(ev.storage_key), content_type=ev.content_type)
        resp["Cache-Control"] = "public, max-age=3600"
        resp["ETag"] = f'"{ev.sha256}"'
        return resp


def _render_page(x) -> str:
    """Small, fast HTML: title, description, canonical link, JSON-LD and the badge. No scripts."""
    e = html.escape
    price = f"{x.price_currency} {x.price_amount:,.2f}"
    desc = (x.description or f"{x.title} in {x.locality}")[:155]
    ld = {"@context": "https://schema.org", "@type": "Offer", "name": x.title, "description": desc,
          "price": f"{x.price_amount:.2f}", "priceCurrency": x.price_currency,
          "availability": "https://schema.org/InStock" if x.status == "live" else "https://schema.org/LimitedAvailability",
          "areaServed": x.locality}
    photos = "".join(f'<img src="/v1/listings/{x.pk}/photos/{m.pk}" alt="{e(m.caption or x.title)}" loading="lazy" '
                     f'width="320">' for m in x.media.filter(public=True, kind="photo")[:6])
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{e(x.title)}, {e(x.locality)} | Tenmina Verified</title>"
        f"<meta name=description content=\"{e(desc)}\">"
        f"<link rel=canonical href=\"/listings/{x.pk}/{e(x.slug)}\">"
        f"<script type=application/ld+json>{json.dumps(ld, default=str)}</script>"
        "<style>body{font:16px/1.5 system-ui,sans-serif;margin:0 auto;max-width:720px;padding:16px}"
        ".badge{background:#c6f432;padding:4px 8px;border-radius:4px;font-weight:600}"
        "img{max-width:100%;height:auto}</style></head><body>"
        f"<h1>{e(x.title)}</h1><p><span class=badge>Tenmina Verified</span> Checks dated "
        f"{x.checks_date:%d %B %Y}. Badge valid until {timezone.localtime(x.badge_expires_at):%d %B %Y}.</p>"
        f"<p><strong>{e(price)}</strong> &middot; {e(x.locality)}{', ' + e(x.region) if x.region else ''}</p>"
        f"<p>{e(x.description)}</p>{photos}"
        f"<p><a href=\"/listings/{x.pk}/report\">Read the full report {e(x.report.reference)}</a></p>"
        f"<p><small>{e(services.disclosure(x.country)) if x.seller_paid_check else ''}</small></p>"
        "</body></html>")


class ReservationViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ReservationSerializer
    queryset = Reservation.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Reservation.objects.none()
        return selectors.reservations_for(self.request.user).select_related("listing", "escrow", "buyer", "country")

    @extend_schema(request=ReasonIn, responses=ReservationSerializer,
                   summary="The buyer withdraws, after the fresh search result (TC-STM-LST-12, -13)")
    @action(detail=True, methods=["post"])
    def withdrawals(self, request, pk=None):
        r = services.withdraw_reservation(self.get_object(), request.user, request.data.get("reason", ""))
        return Response(ReservationSerializer(r, context={"request": request}).data)

    @extend_schema(request=ListingFreshSearchIn, responses=ReservationSerializer,
                   summary="Record a failed fresh search (CM, RV): reservation ends, listing suspended")
    @action(detail=True, methods=["post"], url_path="fresh-search-results")
    def fresh_search_results(self, request, pk=None):
        d = _valid(ListingFreshSearchIn, request)
        r = services.record_fresh_search_failure(self.get_object(), request.user, d["note"])
        return Response(ReservationSerializer(r, context={"request": request}).data)


class EnquiryViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = EnquirySerializer
    queryset = Enquiry.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Enquiry.objects.none()
        qs = selectors.enquiries_for(self.request.user).select_related("listing", "buyer", "country")
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    @extend_schema(request=GeneralEnquiryIn, responses={201: EnquirySerializer},
                   summary="Ask about a listing, or tell Tenmina what land you are looking for")
    @idempotent
    def create(self, request):
        d = _valid(GeneralEnquiryIn, request)
        listing = None
        if d.get("listing_id"):
            listing = selectors.visible_listings(request.user).filter(pk=d["listing_id"]).first()
            if listing is None:
                raise NotFound("Listing not found.")
        e = services.enquire(request.user, message=d["message"], listing=listing, country=_country(d["country"]),
                             wanted_region=d.get("wanted_region", ""), wanted_locality=d.get("wanted_locality", ""),
                             budget=_money(d.get("budget")))
        return Response(EnquirySerializer(e, context={"request": request}).data, status=201)

    @extend_schema(request=AnswerIn, responses=EnquirySerializer)
    @action(detail=True, methods=["post"])
    def replies(self, request, pk=None):
        d = _valid(AnswerIn, request)
        e = services.answer_enquiry(self.get_object(), request.user, d["answer"])
        return Response(EnquirySerializer(e, context={"request": request}).data)

    @extend_schema(request=None, responses=EnquirySerializer)
    @action(detail=True, methods=["post"])
    def closures(self, request, pk=None):
        e = services.close_enquiry(self.get_object(), request.user)
        return Response(EnquirySerializer(e, context={"request": request}).data)


class SellerScreeningViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    """Established seller screening (CM runs the checks, a different RV decides)."""

    serializer_class = ScreeningSerializer
    queryset = SellerScreening.objects.none()

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return SellerScreening.objects.none()
        from accounts.selectors import scope_to_staff_countries

        if not services.is_staff(self.request.user, None):
            return SellerScreening.objects.none()
        return scope_to_staff_countries(SellerScreening.objects.select_related("organisation"), self.request.user)

    @extend_schema(request=ScreeningIn, responses={201: ScreeningSerializer})
    def create(self, request):
        from accounts.models import Organisation

        d = _valid(ScreeningIn, request)
        org = Organisation.objects.filter(pk=d["organisation_id"]).first()
        if org is None:
            raise NotFound("Organisation not found.")
        s = services.open_screening(request.user, org)
        return Response(ScreeningSerializer(s).data, status=201)

    @extend_schema(request=ScreeningCheckIn, responses=ScreeningSerializer)
    @action(detail=True, methods=["post"])
    def checks(self, request, pk=None):
        d = _valid(ScreeningCheckIn, request)
        s = services.record_screening_check(self.get_object(), request.user, key=d["key"], status=d["status"],
                                            note=d.get("note", ""),
                                            evidence=_evidence(d["evidence_id"]) if d.get("evidence_id") else None)
        return Response(ScreeningSerializer(s).data)

    @extend_schema(request=ScreeningDecisionIn, responses=ScreeningSerializer)
    @action(detail=True, methods=["post"])
    def decisions(self, request, pk=None):
        d = _valid(ScreeningDecisionIn, request)
        s = services.decide_screening(self.get_object(), request.user, outcome=d["outcome"], note=d.get("note", ""))
        return Response(ScreeningSerializer(s).data)
