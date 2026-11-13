"""INS API shapes (02 7.4 /v1/insurance/*)."""
from rest_framework import serializers

from .models import (PERIODS, PREMIUM_ROUTES, Application, Claim, ClaimUpdate, Insurer, IntermediaryLicence, Policy,
                     Premium, Product)


def _money(amount, currency):
    return None if amount is None else {"amount": f"{amount:.2f}", "currency": currency}


class InsMoneyIn(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=18, decimal_places=2)
    currency = serializers.CharField(max_length=3)


class InsDocumentFields(serializers.Serializer):
    evidence_id = serializers.UUIDField(required=False, allow_null=True)
    document_base64 = serializers.CharField(required=False, allow_blank=True)
    content_type = serializers.CharField(required=False, default="application/pdf")
    file_name = serializers.CharField(required=False, allow_blank=True, default="")


class InsInsurerSerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    country = serializers.CharField(source="country.code", read_only=True)
    payee = serializers.SerializerMethodField()

    class Meta:
        model = Insurer
        fields = ["id", "country", "name", "partner", "organisation", "licence_body", "licence_number",
                  "licence_valid_until", "claim_contact", "routes", "status", "payee", "created_at"]

    def get_payee(self, obj) -> dict | None:
        p = obj.payee
        return None if p is None else {"id": str(p.pk), "account_name": p.account_name, "account_last4": p.last4,
                                       "verification_status": p.verification_status}


class InsInsurerIn(serializers.Serializer):
    country = serializers.CharField(max_length=2)
    partner_id = serializers.UUIDField()
    organisation_id = serializers.UUIDField(required=False, allow_null=True)
    licence_body = serializers.CharField(required=False, allow_blank=True, default="")
    licence_number = serializers.CharField(required=False, allow_blank=True, default="")
    licence_valid_until = serializers.DateField(required=False, allow_null=True)
    licence_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    claim_contact = serializers.CharField(required=False, allow_blank=True, default="")
    routes = serializers.ListField(child=serializers.ChoiceField(choices=PREMIUM_ROUTES), required=False)
    payee_id = serializers.UUIDField(required=False, allow_null=True)


class InsInsurerPatch(serializers.Serializer):
    licence_body = serializers.CharField(required=False, allow_blank=True)
    licence_number = serializers.CharField(required=False, allow_blank=True)
    licence_valid_until = serializers.DateField(required=False, allow_null=True)
    licence_evidence_id = serializers.UUIDField(required=False, allow_null=True)
    claim_contact = serializers.CharField(required=False, allow_blank=True)
    routes = serializers.ListField(child=serializers.ChoiceField(choices=PREMIUM_ROUTES), required=False)
    status = serializers.ChoiceField(choices=["active", "suspended"], required=False)
    payee_id = serializers.UUIDField(required=False, allow_null=True)


class InsLicenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntermediaryLicence
        fields = ["id", "body", "reference", "valid_until", "evidence", "status", "created_at"]


class InsLicenceIn(InsDocumentFields):
    country = serializers.CharField(max_length=2)
    body = serializers.CharField()
    reference = serializers.CharField()
    valid_until = serializers.DateField()


class InsProductSerializer(serializers.ModelSerializer):
    country = serializers.CharField(source="country.code", read_only=True)
    insurer_name = serializers.CharField(source="insurer.name", read_only=True)
    premium = serializers.SerializerMethodField()
    statement = serializers.SerializerMethodField()
    premium_routes = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "country", "insurer", "insurer_name", "kind", "name", "summary", "terms_evidence", "premium",
                  "premium_period", "premium_routes", "application_questions", "statement", "status",
                  "published_at"]

    def get_premium(self, obj) -> dict:
        return _money(obj.premium_amount, obj.premium_currency)

    def get_statement(self, obj) -> str:
        from .services import statement_for

        return statement_for(obj)

    def get_premium_routes(self, obj) -> list:
        return list(obj.insurer.routes)


class InsProductIn(InsDocumentFields):
    insurer_id = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=Product.KINDS)
    name = serializers.CharField()
    summary = serializers.CharField(required=False, allow_blank=True, default="")
    premium = InsMoneyIn()
    premium_period = serializers.ChoiceField(choices=PERIODS, default="month")
    application_questions = serializers.ListField(child=serializers.DictField(), required=False, default=list)


class InsApplicationSerializer(serializers.ModelSerializer):
    product_name = serializers.CharField(source="product.name", read_only=True)
    insurer_name = serializers.CharField(source="insurer.name", read_only=True)
    status_text = serializers.SerializerMethodField()
    policy = serializers.SerializerMethodField()

    class Meta:
        model = Application
        fields = ["id", "product", "product_name", "insurer", "insurer_name", "insured_family_member", "answers",
                  "premium_route", "submitted_to_insurer_at", "insurer_reference", "insurer_note", "decided_at",
                  "status", "status_text", "policy", "created_at"]

    def get_status_text(self, obj) -> str:
        return {"draft": "Not sent yet.", "submitted": "Sent to insurer.", "accepted": "Accepted by the insurer.",
                "declined": "Declined by the insurer.", "withdrawn": "Withdrawn."}[obj.status]

    def get_policy(self, obj) -> str | None:
        pol = getattr(obj, "policy", None) if obj.status == "accepted" else None
        return str(pol.pk) if pol else None


class InsApplicationIn(serializers.Serializer):
    product_id = serializers.UUIDField()
    family_member_id = serializers.UUIDField()
    answers = serializers.DictField(required=False, default=dict)
    premium_route = serializers.ChoiceField(choices=PREMIUM_ROUTES, default="client_direct_to_insurer")
    submit = serializers.BooleanField(default=False, help_text="Send to the insurer at once (with consent).")
    consent = serializers.BooleanField(default=False)


class InsConsentIn(serializers.Serializer):
    consent = serializers.BooleanField()


class InsOutcomeIn(InsDocumentFields):
    outcome = serializers.ChoiceField(choices=["accepted", "declined"])
    policy_number = serializers.CharField(required=False, allow_blank=True, default="")
    starts_on = serializers.DateField(required=False, allow_null=True)
    renews_on = serializers.DateField(required=False, allow_null=True)
    claim_contact = serializers.CharField(required=False, allow_blank=True, default="")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class InsPolicySerializer(serializers.ModelSerializer):
    insurer_name = serializers.CharField(source="insurer.name", read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)
    premium = serializers.SerializerMethodField()
    statement = serializers.SerializerMethodField()

    class Meta:
        model = Policy
        fields = ["id", "application", "insurer", "insurer_name", "product", "product_name", "insured_family_member",
                  "policy_number", "document_evidence", "starts_on", "renews_on", "claim_contact", "premium",
                  "premium_period", "premium_route", "status", "status_note", "statement", "created_at"]

    def get_premium(self, obj) -> dict:
        return _money(obj.premium_amount, obj.premium_currency)

    def get_statement(self, obj) -> str:
        from .services import statement_for

        return statement_for(obj.product)


class InsRenewalIn(InsDocumentFields):
    renews_on = serializers.DateField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class InsPremiumSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    policy_number = serializers.CharField(source="policy.policy_number", read_only=True)
    insurer_name = serializers.CharField(source="policy.insurer.name", read_only=True)
    pay_to = serializers.SerializerMethodField()

    class Meta:
        model = Premium
        fields = ["id", "policy", "policy_number", "insurer_name", "due_on", "amount", "route",
                  "release_instruction", "client_reported_at", "client_transfer_reference", "paid_at",
                  "insurer_receipt_evidence", "status", "pay_to"]

    def get_amount(self, obj) -> dict:
        return _money(obj.amount, obj.currency)

    def get_pay_to(self, obj) -> dict | None:
        req = self.context.get("request")
        if obj.route != "client_direct_to_insurer" or obj.status not in ("due", "overdue", "client_reported") \
                or req is None or req.user.pk != obj.policy.client_id:
            return None
        from core.errors import DomainError

        from .services import pay_to

        try:
            return pay_to(obj)
        except DomainError:
            return None


class InsPremiumPaidIn(InsDocumentFields):
    reference = serializers.CharField(required=False, allow_blank=True, default="")


class InsPremiumConfirmIn(InsDocumentFields):
    received = serializers.BooleanField(default=True)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class InsClaimUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClaimUpdate
        fields = ["id", "insurer_status", "note", "evidence", "source", "created_at"]


class InsClaimSerializer(serializers.ModelSerializer):
    updates = InsClaimUpdateSerializer(many=True, read_only=True)
    status_text = serializers.SerializerMethodField()

    class Meta:
        model = Claim
        fields = ["id", "policy", "description", "event_date", "submitted_to_insurer_at", "insurer_reference",
                  "insurer_status", "insurer_status_at", "outcome_evidence", "status_text", "updates", "created_at"]

    def get_status_text(self, obj) -> str:
        if not obj.insurer_status:
            return "Sent to the insurer."
        return f"The insurer says: {obj.insurer_status.replace('_', ' ')}."


class InsClaimIn(serializers.Serializer):
    description = serializers.CharField()
    event_date = serializers.DateField(required=False, allow_null=True)
    document_ids = serializers.ListField(child=serializers.UUIDField(), required=False, default=list)


class InsClaimUpdateIn(InsDocumentFields):
    insurer_status = serializers.ChoiceField(choices=Claim.INSURER_STATUSES)
    note = serializers.CharField(required=False, allow_blank=True, default="")


class InsLineStatusOut(serializers.Serializer):
    open = serializers.BooleanField()
    reasons = serializers.ListField(child=serializers.DictField())
