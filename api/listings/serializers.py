from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.money import MoneyField

from . import selectors, services
from .models import Enquiry, Listing, ListingMedia, Removal, Reservation, SellerScreening, Suspension


@extend_schema_field({"type": "object", "properties": {"amount": {"type": "string"}, "currency": {"type": "string"}}})
class Money(MoneyField):
    """{"amount": "250.00", "currency": "GHS"} with a typed schema."""


class ListingMoneyIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(max_length=3, required=False)


class AssetIn(serializers.Serializer):
    locality = serializers.CharField()
    region = serializers.CharField(required=False, allow_blank=True)
    district = serializers.CharField(required=False, allow_blank=True)
    plot_number = serializers.CharField(required=False, allow_blank=True)
    site_plan_ref = serializers.CharField(required=False, allow_blank=True)
    ghana_post_gps = serializers.CharField(required=False, allow_blank=True)
    name = serializers.CharField(required=False, allow_blank=True)
    location = serializers.DictField(required=False, help_text='{"lng": -0.15, "lat": 5.63}, only when confirmed')


class ListingCreateSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    organisation_id = serializers.UUIDField(required=False)
    origin = serializers.ChoiceField(choices=Listing.ORIGINS, required=False)
    kind = serializers.ChoiceField(choices=Listing.KINDS, default="plot")
    title = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    estate_name = serializers.CharField(required=False, allow_blank=True)
    records_reference = serializers.CharField(required=False, allow_blank=True)
    price = ListingMoneyIn()
    size_sqm = serializers.DecimalField(max_digits=14, decimal_places=2, required=False)
    asset_id = serializers.UUIDField(required=False)
    asset = AssetIn(required=False)
    report_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if not attrs.get("asset_id") and not attrs.get("asset"):
            raise serializers.ValidationError({"asset": "Give the plot (asset_id) or its details (asset)."})
        return attrs


class ListingUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    estate_name = serializers.CharField(required=False, allow_blank=True)
    kind = serializers.ChoiceField(choices=Listing.KINDS, required=False)
    price = ListingMoneyIn(required=False)
    size_sqm = serializers.DecimalField(max_digits=14, decimal_places=2, required=False, allow_null=True)


class SubmitIn(serializers.Serializer):
    terms_version = serializers.CharField(required=False, allow_blank=True)
    scope_version = serializers.CharField(required=False, allow_blank=True)


class ReasonIn(serializers.Serializer):
    reason = serializers.CharField()


class RemovalIn(serializers.Serializer):
    reason = serializers.CharField()
    scope = serializers.ChoiceField(choices=Removal.SCOPES, default="listing")


class NoteIn(serializers.Serializer):
    note = serializers.CharField()


class MediaIn(serializers.Serializer):
    kind = serializers.ChoiceField(choices=ListingMedia.KINDS, default="photo")
    caption = serializers.CharField(required=False, allow_blank=True)
    evidence_id = serializers.UUIDField(required=False)
    file = serializers.FileField(required=False)


class EnquiryIn(serializers.Serializer):
    message = serializers.CharField()


class GeneralEnquiryIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    message = serializers.CharField()
    listing_id = serializers.UUIDField(required=False)
    wanted_region = serializers.CharField(required=False, allow_blank=True)
    wanted_locality = serializers.CharField(required=False, allow_blank=True)
    budget = ListingMoneyIn(required=False)


class AnswerIn(serializers.Serializer):
    answer = serializers.CharField()


class ListingFreshSearchIn(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["failed"])
    note = serializers.CharField()


class ScreeningIn(serializers.Serializer):
    organisation_id = serializers.UUIDField()


class ScreeningCheckIn(serializers.Serializer):
    key = serializers.ChoiceField(choices=SellerScreening.CHECKS)
    status = serializers.ChoiceField(choices=["passed", "failed", "not_applicable"])
    note = serializers.CharField(required=False, allow_blank=True)
    evidence_id = serializers.UUIDField(required=False)


class ScreeningDecisionIn(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=["established", "not_established"])
    note = serializers.CharField(required=False, allow_blank=True)


class MediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()
    sha256 = serializers.CharField(source="evidence.sha256", read_only=True)

    class Meta:
        model = ListingMedia
        fields = ["id", "kind", "caption", "position", "public", "evidence_id", "sha256", "url"]

    def get_url(self, m) -> str | None:
        return f"/v1/listings/{m.listing_id}/photos/{m.pk}" if m.public and m.kind == "photo" else None


class BadgeSerializer(serializers.Serializer):
    label = serializers.CharField()
    checks_date = serializers.DateField()
    expires_at = serializers.DateTimeField()
    report_link = serializers.CharField()
    report_reference = serializers.CharField()


class TrackRecordSummary(serializers.Serializer):
    subject_type = serializers.CharField()
    subject_id = serializers.UUIDField()
    enough_history = serializers.BooleanField()
    summary = serializers.CharField()
    deals_completed = serializers.IntegerField()
    disputes_lost = serializers.IntegerField()
    average_score = serializers.DecimalField(max_digits=3, decimal_places=2, allow_null=True)
    ratings_count = serializers.IntegerField()


def _track_record(org_id):
    if not org_id:
        return None
    try:
        from ratings.selectors import summary
    except ImportError:  # pragma: no cover
        return None
    return summary("organisation", org_id)


class ListingSerializer(serializers.ModelSerializer):
    """FR-LST-003: badge, check date and the full report link on every live listing; none when not live."""

    price = Money(prefix="price")
    badge = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    disclosure = serializers.SerializerMethodField()
    location = serializers.SerializerMethodField()
    media = serializers.SerializerMethodField()
    reserved = serializers.SerializerMethodField()
    can_reserve = serializers.SerializerMethodField()
    seller_track_record = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = ["id", "reference", "slug", "status", "origin", "kind", "title", "description", "estate_name",
                  "price", "size_sqm", "region", "district", "locality", "asset_id", "organisation_id", "badge",
                  "checks_date", "seller", "disclosure", "location", "media", "reserved", "can_reserve",
                  "seller_track_record", "live_at", "sold_at"]

    @extend_schema_field(BadgeSerializer(allow_null=True))
    def get_badge(self, x):
        if not services.badge_valid(x):
            return None
        return {"label": "Tenmina Verified", "checks_date": x.checks_date, "expires_at": x.badge_expires_at,
                "report_link": f"/v1/listings/{x.pk}/report", "report_reference": x.report.reference}

    @extend_schema_field(serializers.DictField())
    def get_seller(self, x):
        org = x.organisation
        return {"name": org.name if org else x.submitted_by.full_name, "kind": org.kind if org else x.origin,
                "established": services.is_established(x.organisation_id)}

    def get_disclosure(self, x) -> str:
        return services.disclosure(x.country) if x.seller_paid_check else ""

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_location(self, x):
        p = selectors.point_of(x)
        return {"lng": p[0], "lat": p[1]} if p else None

    @extend_schema_field(MediaSerializer(many=True))
    def get_media(self, x):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        qs = x.media.select_related("evidence")
        if not (user and (services.is_seller(user, x) or services.is_staff(user, x.country))):
            qs = qs.filter(public=True)
        return MediaSerializer(qs, many=True).data

    def get_reserved(self, x) -> bool:
        return x.status == "reserved"

    def get_can_reserve(self, x) -> bool:
        return x.status == "live" and services.badge_valid(x)

    @extend_schema_field(TrackRecordSummary(allow_null=True))
    def get_seller_track_record(self, x):
        return _track_record(x.organisation_id)


class SuspensionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Suspension
        fields = ["id", "kind", "source_id", "reason", "prior_status", "created_at", "lifted_at", "lift_note"]


class ListingDetailSerializer(ListingSerializer):
    """Adds what the seller and staff see: why it is in this state, the order, the fee and suspensions."""

    boundary = serializers.SerializerMethodField()
    owner_view = serializers.SerializerMethodField()

    class Meta(ListingSerializer.Meta):
        fields = ListingSerializer.Meta.fields + ["boundary", "owner_view"]

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_boundary(self, x):
        return selectors.boundary_geojson(x)

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_owner_view(self, x):
        req = self.context.get("request")
        user = getattr(req, "user", None)
        if not (user and user.is_authenticated and (services.is_seller(user, x) or services.is_staff(user, x.country))):
            return None
        return {"status_reason": x.status_reason, "submitted_at": x.submitted_at, "fee_invoice_id": x.fee_invoice_id,
                "fee_paid_at": x.fee_paid_at, "verification_order_id": x.verification_order_id,
                "verification_case_id": getattr(x.verification_order, "case_id", None),
                "report_id": x.report_id, "badge_expires_at": x.badge_expires_at, "view_count": x.view_count,
                "enquiries": x.enquiries.count(),
                "suspensions": SuspensionSerializer(x.suspensions.order_by("-created_at"), many=True).data}


class ReportViewSerializer(serializers.Serializer):
    listing_id = serializers.UUIDField()
    report_id = serializers.UUIDField()
    reference = serializers.CharField()
    version = serializers.IntegerField()
    verdict = serializers.CharField()
    released_at = serializers.DateTimeField()
    pdf_sha256 = serializers.CharField()
    pdf = serializers.DictField(help_text="A short-lived link to the released PDF")
    sections = serializers.ListField(child=serializers.DictField())


class ReservationSerializer(serializers.ModelSerializer):
    listing = serializers.SerializerMethodField()
    buyer_name = serializers.SerializerMethodField()
    escrow = serializers.SerializerMethodField()

    class Meta:
        model = Reservation
        fields = ["id", "reference", "status", "listing", "buyer_name", "expires_at", "fresh_search_status",
                  "fresh_search_date", "fresh_search_case_id", "fresh_search_note", "escrow", "ended_at",
                  "end_reason", "created_at"]

    @extend_schema_field(serializers.DictField())
    def get_listing(self, r):
        return {"id": r.listing_id, "reference": r.listing.reference, "title": r.listing.title,
                "status": r.listing.status}

    def get_buyer_name(self, r) -> str | None:
        """The seller never sees the buyer's personal data beyond what the deal needs (01 B5)."""
        user = getattr(self.context.get("request"), "user", None)
        if user and (user.pk == r.buyer_id or services.is_staff(user, r.country)):
            return r.buyer.full_name
        return None

    @extend_schema_field(serializers.DictField(allow_null=True))
    def get_escrow(self, r):
        e = r.escrow
        return {"id": e.pk, "reference": e.reference, "status": e.status} if e else None


class EnquirySerializer(serializers.ModelSerializer):
    budget = Money(prefix="budget", required=False)
    buyer_name = serializers.SerializerMethodField()

    class Meta:
        model = Enquiry
        fields = ["id", "reference", "listing_id", "status", "message", "wanted_region", "wanted_locality",
                  "budget", "answer", "answered_at", "seller_note", "buyer_name", "created_at", "closed_at"]

    def get_buyer_name(self, e) -> str | None:
        user = getattr(self.context.get("request"), "user", None)
        if user and (user.pk == e.buyer_id or services.is_staff(user, e.country)):
            return e.buyer.full_name
        return None


class ScreeningSerializer(serializers.ModelSerializer):
    organisation_name = serializers.CharField(source="organisation.name", read_only=True)

    class Meta:
        model = SellerScreening
        fields = ["id", "organisation_id", "organisation_name", "status", "checks", "opened_by", "decided_by",
                  "decided_at", "decision_note", "created_at"]


class RemovalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Removal
        fields = ["id", "scope", "listing_id", "organisation_id", "reason", "removed_by", "listings_removed",
                  "created_at"]


class FeatureCollectionSerializer(serializers.Serializer):
    type = serializers.CharField(default="FeatureCollection")
    features = serializers.ListField(child=serializers.DictField())


def page_now():
    return timezone.now()
