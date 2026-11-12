from rest_framework import serializers

from .models import Organisation, Person, RoleGrant


class PersonSerializer(serializers.ModelSerializer):
    roles = serializers.SerializerMethodField()
    home_country = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = Person
        fields = ["id", "email", "phone", "full_name", "preferred_language", "residence_country", "home_country",
                  "mfa_enabled", "roles", "created_at"]
        read_only_fields = ["id", "email", "mfa_enabled", "roles", "created_at"]

    def get_roles(self, obj):
        return sorted(obj.roles())


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(min_length=10, write_only=True)
    full_name = serializers.CharField()
    phone = serializers.CharField(required=False, allow_blank=True)
    residence_country = serializers.CharField(required=False, allow_blank=True, max_length=2)
    home_country = serializers.CharField(required=False, default="GH", max_length=2)
    preferred_language = serializers.CharField(required=False, default="en")


class OrganisationSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", queryset=__import__("countries.models", fromlist=["Country"]).Country.objects.all())

    class Meta:
        model = Organisation
        fields = ["id", "name", "kind", "country", "registration_number", "status", "contact_email",
                  "contact_phone", "address", "created_at"]


class RoleGrantSerializer(serializers.ModelSerializer):
    country = serializers.SlugRelatedField(slug_field="code", read_only=True)

    class Meta:
        model = RoleGrant
        fields = ["id", "person", "role", "country", "organisation", "granted_by", "revoked_at", "created_at"]
