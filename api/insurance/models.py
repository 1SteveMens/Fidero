"""INS Insurer partner lines (document 02 section 6.12, FR-INS-001 to FR-INS-004, RUL-25).

Insurance is sold only as a licensed insurer's product. Tenmina passes the
application to the insurer, keeps the policy document, schedules premiums with
instructions only to the insurer's verified payee record, reminds the client
before renewal and tracks claims. Tenmina collects no premium into its own
account and decides no claim: there is no decision column anywhere here.
"""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import BaseModel, CountryScopedModel
from core.money import amount_field, currency_field

PREMIUM_ROUTES = ["client_direct_to_insurer", "held_funds_to_insurer"]
PERIODS = ["month", "quarter", "year"]


class Insurer(CountryScopedModel):
    """A licensed insurer partner in one country (AS-11, Q-17). Its users hold role IS in its organisation; its
    premiums go only to its verified payee record (kind insurer)."""

    partner = models.ForeignKey("administration.Partner", on_delete=models.PROTECT, related_name="+")
    organisation = models.ForeignKey("accounts.Organisation", null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    licence_body = models.TextField(blank=True, default="")
    licence_number = models.TextField(blank=True, default="")
    licence_valid_until = models.DateField(null=True, blank=True)
    licence_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    claim_contact = models.TextField(blank=True, default="")
    routes = models.JSONField(default=list)  # premium routes this insurer accepts (FR-INS-002)
    adapter_path = models.TextField(blank=True, default="")  # IF-11; empty means the FakeInsurer adapter
    status = models.TextField(default="active", choices=[("active", "active"), ("suspended", "suspended")])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "ins_insurer"
        constraints = [models.UniqueConstraint(fields=["country", "partner"], name="ins_insurer_partner_uq")]

    @property
    def name(self):
        return self.partner.name


class IntermediaryLicence(CountryScopedModel):
    """C-11: the licence Tenmina needs, if any, to present insurers' products in a country."""

    body = models.TextField()
    reference = models.TextField()
    valid_until = models.DateField()
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="active", choices=[("active", "active"), ("withdrawn", "withdrawn")])

    class Meta:
        db_table = "ins_intermediary_licence"


class Product(CountryScopedModel):
    """FR-INS-001: health or funeral cover, shown with the insurer's name, its terms and the statement that the
    policy is the insurer's, not Tenmina's."""

    KINDS = ["health", "funeral"]
    STATUSES = ["draft", "published", "withdrawn"]
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="products")
    kind = models.TextField(choices=[(k, k) for k in KINDS])
    name = models.TextField()
    summary = models.TextField(blank=True, default="")
    terms_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    premium_amount = amount_field()
    premium_currency = currency_field()
    premium_period = models.TextField(choices=[(p, p) for p in PERIODS])
    application_questions = models.JSONField(default=list, blank=True)  # [{"key", "label", "required"}]
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    published_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        db_table = "ins_product"
        constraints = [models.CheckConstraint(condition=Q(premium_amount__gt=0), name="ins_product_premium_positive")]


PRODUCT = state.register("ins_product", "ins_product", {
    "draft": {"published", "withdrawn"},
    "published": {"withdrawn"},
})


class Application(CountryScopedModel):
    """FR-INS-002: collected by Tenmina, passed to the insurer, decided by the insurer."""

    STATUSES = ["draft", "submitted", "accepted", "declined", "withdrawn"]
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    insured_family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="applications")
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="applications")
    answers = models.JSONField(default=dict)  # class insurance; encrypt at field level in production (10.6)
    premium_route = models.TextField(choices=[(r, r) for r in PREMIUM_ROUTES])
    consent_at = models.DateTimeField(null=True, blank=True)
    submitted_to_insurer_at = models.DateTimeField(null=True, blank=True)
    sent_via = models.TextField(blank=True, default="")
    insurer_reference = models.TextField(blank=True, default="")
    insurer_note = models.TextField(blank=True, default="")
    decided_at = models.DateTimeField(null=True, blank=True)  # when the insurer answered
    status = models.TextField(default="draft", choices=[(s, s) for s in STATUSES])
    data_class = models.TextField(default="insurance")

    class Meta:
        db_table = "ins_application"
        constraints = [models.CheckConstraint(condition=Q(status__in=["draft", "withdrawn"])
                                              | Q(submitted_to_insurer_at__isnull=False, consent_at__isnull=False),
                                              name="ins_application_sent_needs_consent")]


APPLICATION = state.register("ins_application", "ins_application", {
    "draft": {"submitted", "withdrawn"},
    "submitted": {"accepted", "declined", "withdrawn"},
})


class Policy(CountryScopedModel):
    """FR-INS-003. The insurer's policy; Tenmina keeps the document, the renewal date and the insurer's claim
    contact. `insurer_payee` is the insurer's verified payee record (RUL-25)."""

    STATUSES = ["active", "lapsed", "cancelled", "renewed"]
    application = models.OneToOneField(Application, on_delete=models.PROTECT, related_name="policy")
    client = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    insured_family_member = models.ForeignKey("accounts.FamilyMember", on_delete=models.PROTECT, related_name="+")
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name="policies")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="policies")
    policy_number = models.TextField()
    document_evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    insurer_payee = models.ForeignKey("escrow.Payee", on_delete=models.PROTECT, related_name="+")
    starts_on = models.DateField()
    renews_on = models.DateField()
    claim_contact = models.TextField()
    premium_amount = amount_field()
    premium_currency = currency_field()
    premium_period = models.TextField(choices=[(p, p) for p in PERIODS])
    premium_route = models.TextField(choices=[(r, r) for r in PREMIUM_ROUTES])
    renewal_reminded_for = models.DateField(null=True, blank=True)
    status = models.TextField(default="active", choices=[(s, s) for s in STATUSES])
    status_note = models.TextField(blank=True, default="")
    data_class = models.TextField(default="insurance")

    class Meta:
        db_table = "ins_policy"
        constraints = [models.CheckConstraint(condition=Q(renews_on__gt=models.F("starts_on")),
                                              name="ins_policy_renews_after_start")]


POLICY = state.register("ins_policy", "ins_policy", {
    "active": {"lapsed", "cancelled", "renewed"},
    "lapsed": {"active", "cancelled"},
    "renewed": {"active"},
})


class Premium(CountryScopedModel):
    """FR-INS-002: due premiums, paid only to the insurer's account by one of two routes. A client-direct premium
    never has an instruction; a held-funds premium is paid by the bank on an instruction to the insurer's payee."""

    STATUSES = ["due", "client_reported", "instructed", "paid", "overdue", "waived"]
    policy = models.ForeignKey(Policy, on_delete=models.PROTECT, related_name="premiums")
    due_on = models.DateField()
    amount = amount_field()
    currency = currency_field()
    route = models.TextField(choices=[(r, r) for r in PREMIUM_ROUTES])
    release_instruction = models.ForeignKey("escrow.ReleaseInstruction", null=True, blank=True,
                                            on_delete=models.PROTECT, related_name="+")
    client_reported_at = models.DateTimeField(null=True, blank=True)
    client_transfer_reference = models.TextField(blank=True, default="")
    client_transfer_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    insurer_receipt_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True,
                                                 on_delete=models.PROTECT, related_name="+")
    paid_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                     related_name="+")
    reminded_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(default="due", choices=[(s, s) for s in STATUSES])

    class Meta:
        db_table = "ins_premium"
        constraints = [
            models.UniqueConstraint(fields=["policy", "due_on"], name="ins_premium_policy_due_uq"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="ins_premium_amount_positive"),
            models.CheckConstraint(condition=~Q(route="held_funds_to_insurer") | Q(status__in=["due", "overdue",
                                                                                               "waived"])
                                   | Q(release_instruction__isnull=False), name="ins_premium_held_funds_instruction"),
            models.CheckConstraint(condition=~Q(route="client_direct_to_insurer") | Q(release_instruction__isnull=True),
                                   name="ins_premium_client_direct_no_instruction"),
            models.CheckConstraint(condition=~Q(status="paid") | Q(paid_at__isnull=False), name="ins_premium_paid_at"),
        ]


PREMIUM = state.register("ins_premium", "ins_premium", {
    "due": {"client_reported", "instructed", "paid", "overdue", "waived"},
    "overdue": {"client_reported", "instructed", "paid", "waived"},
    "client_reported": {"paid", "due", "overdue"},
    "instructed": {"paid", "due", "overdue"},
})


class Claim(CountryScopedModel):
    """FR-INS-004: the client starts a claim; Tenmina passes it to the insurer and shows the insurer's responses.
    `insurer_status` is only ever set from the insurer (RUL-25). There is no Tenmina decision column."""

    INSURER_STATUSES = ["received", "assessing", "more_information", "paid", "declined"]
    policy = models.ForeignKey(Policy, on_delete=models.PROTECT, related_name="claims")
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    description = models.TextField()
    event_date = models.DateField(null=True, blank=True)
    submitted_to_insurer_at = models.DateTimeField(null=True, blank=True)
    sent_via = models.TextField(blank=True, default="")
    insurer_reference = models.TextField(blank=True, default="")
    insurer_status = models.TextField(blank=True, default="", choices=[("", "")] + [(s, s) for s in INSURER_STATUSES])
    insurer_status_at = models.DateTimeField(null=True, blank=True)
    outcome_evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                         related_name="+")
    data_class = models.TextField(default="insurance")

    class Meta:
        db_table = "ins_claim"


class ClaimUpdate(BaseModel):
    """Each response from the insurer, append-only."""

    claim = models.ForeignKey(Claim, on_delete=models.PROTECT, related_name="updates")
    insurer_status = models.TextField(choices=[(s, s) for s in Claim.INSURER_STATUSES])
    note = models.TextField(blank=True, default="")
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")  # an insurer user; null when the insurer's adapter sent it
    source = models.TextField(default="insurer_portal", choices=[("insurer_portal", "insurer_portal"),
                                                                 ("insurer_adapter", "insurer_adapter")])

    class Meta:
        db_table = "ins_claim_update"
