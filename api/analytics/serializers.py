from rest_framework import serializers

from .metrics import LINES
from .models import ExportLog


class FiltersOut(serializers.Serializer):
    date_from = serializers.DateField()
    date_to = serializers.DateField()
    countries = serializers.ListField(child=serializers.CharField(), allow_null=True)
    line = serializers.CharField(allow_blank=True)
    tier = serializers.CharField(allow_blank=True)


class SuppressionOut(serializers.Serializer):
    applied = serializers.BooleanField()
    min_group_size = serializers.IntegerField()
    cells_blanked = serializers.IntegerField()


class TableOut(serializers.Serializer):
    name = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    source = serializers.CharField()
    columns = serializers.ListField(child=serializers.CharField())
    rows = serializers.ListField(child=serializers.DictField(), help_text="One object per row, keyed by column. "
                                 "Money is a string with two decimals; a blanked cell is null.")
    suppression = SuppressionOut()
    filters_ignored = serializers.ListField(child=serializers.CharField())


class TableWithFiltersOut(TableOut):
    filters = FiltersOut()


class DashboardOut(serializers.Serializer):
    filters = FiltersOut()
    generated_at = serializers.DateTimeField()
    tiles = TableOut(many=True)


class CatalogueOut(serializers.Serializer):
    name = serializers.CharField()
    title = serializers.CharField()
    description = serializers.CharField()
    source = serializers.CharField()
    columns = serializers.ListField(child=serializers.CharField())
    filters = serializers.ListField(child=serializers.CharField())
    personal_data = serializers.BooleanField()


class ExportIn(serializers.Serializer):
    metric = serializers.CharField()
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    country = serializers.CharField(required=False, allow_blank=True, help_text="One code, or several joined by commas")
    line = serializers.ChoiceField(choices=[("", "")] + [(x, x) for x in LINES], required=False, allow_blank=True)
    tier = serializers.CharField(required=False, allow_blank=True)
    purpose = serializers.CharField(required=False, allow_blank=True)
    fields = serializers.ListField(child=serializers.CharField(), required=False,
                                   help_text="Personal-data tables only: the fields to include")


class ExportLogSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)
    bulk_export_id = serializers.UUIDField(read_only=True, allow_null=True)
    bulk_export_status = serializers.SerializerMethodField()

    class Meta:
        model = ExportLog
        fields = ["id", "created_at", "requested_by", "country", "countries", "metric", "filters", "format", "status",
                  "row_count", "sha256", "suppressed_cells", "personal_data", "bulk_export_id", "bulk_export_status",
                  "purpose"]
        read_only_fields = fields

    def get_bulk_export_status(self, obj) -> str | None:
        return obj.bulk_export.status if obj.bulk_export_id else None
