"""REC API serializers. Boundaries come back as GeoJSON."""
import json

from rest_framework import serializers

from .models import Allocation, AllocationOverlap, Authority, Match, Representative, RevenueShare


class RecAuthoritySerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    share_per_case = serializers.SerializerMethodField()

    class Meta:
        model = Authority
        fields = ["id", "country", "name", "kind", "region", "district", "share_per_case", "status",
                  "agreement_evidence", "created_at"]
        read_only_fields = fields

    def get_share_per_case(self, a) -> dict:
        return {"amount": f"{a.share_per_case:.2f}", "currency": a.share_currency}


class RecAuthorityIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    name = serializers.CharField()
    kind = serializers.ChoiceField(choices=Authority.KINDS)
    region = serializers.CharField(required=False, allow_blank=True, default="")
    district = serializers.CharField(required=False, allow_blank=True, default="")
    share_per_case = serializers.DecimalField(max_digits=18, decimal_places=2, min_value=0, default=0)
    agreement_evidence_id = serializers.UUIDField(required=False, allow_null=True)


class RecRepresentativeSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="person.full_name", read_only=True)

    class Meta:
        model = Representative
        fields = ["id", "authority", "person", "name", "title", "active", "granted_by", "revoked_at", "created_at"]
        read_only_fields = fields


class RecRepresentativeIn(serializers.Serializer):
    person_id = serializers.UUIDField()
    title = serializers.CharField(required=False, allow_blank=True, default="")
    authorisation_evidence_id = serializers.UUIDField()


class RecOverlapSerializer(serializers.ModelSerializer):
    other_reference = serializers.CharField(source="other.reference", read_only=True)
    other_authority = serializers.CharField(source="other.authority.name", read_only=True)

    class Meta:
        model = AllocationOverlap
        fields = ["id", "other", "other_reference", "other_authority", "share", "status", "resolution_note",
                  "resolved_by"]
        read_only_fields = fields


class RecAllocationSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    authority_name = serializers.CharField(source="authority.name", read_only=True)
    allottee_name = serializers.CharField(source="allottee.name", read_only=True)
    boundary = serializers.SerializerMethodField()
    overlaps = RecOverlapSerializer(many=True, read_only=True)
    document_sha256 = serializers.CharField(source="document_evidence.sha256", read_only=True)

    class Meta:
        model = Allocation
        fields = ["id", "country", "authority", "authority_name", "reference", "allottee", "allottee_name",
                  "allocated_on", "previous", "boundary", "area_sqm", "locality", "plot_number", "document_evidence",
                  "document_sha256", "status", "status_note", "captured_by", "confirmed_by", "confirmed_name",
                  "confirmed_at", "overlaps", "created_at"]
        read_only_fields = fields

    def get_boundary(self, a) -> dict:
        return json.loads(a.geom.geojson)


class RecAllocationIn(serializers.Serializer):
    authority_id = serializers.UUIDField()
    reference = serializers.CharField()
    allottee_name = serializers.CharField()
    allottee_kind = serializers.ChoiceField(choices=["person", "family", "company", "other"], default="person")
    allottee_phone = serializers.CharField(required=False, allow_blank=True, default="")
    allocated_on = serializers.DateField()
    document_evidence_id = serializers.UUIDField()
    extra_evidence_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)
    points = serializers.ListField(child=serializers.ListField(child=serializers.FloatField(), min_length=2,
                                                               max_length=2), required=False)
    geojson = serializers.JSONField(required=False)
    locality = serializers.CharField(required=False, allow_blank=True, default="")
    plot_number = serializers.CharField(required=False, allow_blank=True, default="")
    previous_id = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        if bool(attrs.get("points")) == bool(attrs.get("geojson")):
            raise serializers.ValidationError("Send the boundary as points or as geojson.")
        return attrs


class RecNoteIn(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="")


class RecReasonIn(serializers.Serializer):
    reason = serializers.CharField()


class RecMatchSerializer(serializers.ModelSerializer):
    case_reference = serializers.CharField(source="case.reference", read_only=True)
    authority_name = serializers.CharField(source="allocation.authority.name", read_only=True)
    allocation_reference = serializers.CharField(source="allocation.reference", read_only=True)

    class Meta:
        model = Match
        fields = ["id", "case", "case_reference", "asset", "boundary", "allocation", "allocation_reference",
                  "authority_name", "kind", "share_of_plot", "share_of_record", "prefill", "status", "decided_by",
                  "decided_at", "note", "applied_to_report_id", "created_at"]
        read_only_fields = fields


class RecMatchRunIn(serializers.Serializer):
    case_id = serializers.UUIDField()


class RecShareSerializer(serializers.ModelSerializer):
    authority_name = serializers.CharField(source="authority.name", read_only=True)
    amount = serializers.SerializerMethodField()
    cases = serializers.SerializerMethodField()

    class Meta:
        model = RevenueShare
        fields = ["id", "authority", "authority_name", "period_start", "period_end", "case_count", "amount", "status",
                  "computed_by", "approved_by", "paid_reference", "cases", "created_at"]
        read_only_fields = fields

    def get_amount(self, s) -> dict:
        return {"amount": f"{s.amount:.2f}", "currency": s.currency}

    def get_cases(self, s) -> list[dict]:
        return [{"case_id": str(i.case_id), "case_reference": i.case.reference, "amount": f"{i.amount:.2f}"}
                for i in s.items.select_related("case")]


class RecShareComputeIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    period_start = serializers.DateField()
    period_end = serializers.DateField()
    authority_id = serializers.UUIDField(required=False, allow_null=True)


class RecPaidIn(serializers.Serializer):
    reference = serializers.CharField()
