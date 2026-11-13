"""PRJ Project funds (document 02: 4.2, 6.8; document 01 C4.11): a family business, a borehole, a church
building or a shop, on the shared project and milestone engine of BLD (`bld_project` of type `funds`,
`bld_milestone` as its stages). PRJ adds named suppliers with background checks, invoices accepted against a
stage, the enhanced anti-money-laundering review above the country threshold and the project agreement with
its no-advice statement. Tenmina does not judge the business, only the evidence."""
from django.conf import settings
from django.db import models
from django.db.models import Q

from core import state
from core.models import CountryScopedModel
from core.money import amount_field, currency_field

NO_ADVICE_STATEMENT = (
    "Tenmina gives no investment advice and guarantees no returns. Tenmina does not judge the business or "
    "project, only the evidence: it checks the person running it and each supplier, and pays checked suppliers "
    "directly against invoices once each stage is confirmed.")


class Supplier(CountryScopedModel):
    """A named supplier the client wants paid. Money goes only to checked suppliers against invoices (RUL-21)."""

    STATUSES = ["incomplete", "pending_check", "checking", "passed", "failed", "removed"]
    project = models.ForeignKey("construction.Project", on_delete=models.PROTECT, related_name="suppliers")
    name = models.TextField()
    what_they_supply = models.TextField(blank=True, default="")
    contact_name = models.TextField(blank=True, default="")
    contact_phone = models.TextField(blank=True, default="")
    contact_email = models.TextField(blank=True, default="")
    registration_number = models.TextField(blank=True, default="")
    bank_name = models.TextField(blank=True, default="")  # as the client gave it; staff check it with the bank
    account_number = models.TextField(blank=True, default="")
    account_name = models.TextField(blank=True, default="")
    status = models.TextField(default="incomplete", choices=[(s, s) for s in STATUSES])
    missing = models.JSONField(default=list, blank=True)  # what makes it incomplete (US-PRJ-001 AC2)
    check_case_id = models.UUIDField(null=True, blank=True)  # cases: supplier_check
    payee = models.ForeignKey("escrow.Payee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    status_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "prj_supplier"
        indexes = [models.Index(fields=["project", "status"])]


SUPPLIER = state.register("prj_supplier", "prj_supplier", {
    "incomplete": {"pending_check", "removed"},
    "pending_check": {"incomplete", "checking", "removed"},
    "checking": {"passed", "failed", "removed"},
    "passed": {"removed", "failed"},
    "failed": {"removed", "pending_check"},
})


class BackgroundCheck(CountryScopedModel):
    """FR-PRJ-002: identity and background checks on the person running the project and on each supplier
    before money is accepted at the bank. `enhanced` above the anti-money-laundering threshold (FR-PRJ-004)."""

    SUBJECTS = ["runner", "supplier"]
    STATUSES = ["pending", "passed", "failed"]
    project = models.ForeignKey("construction.Project", on_delete=models.PROTECT, related_name="background_checks")
    subject_kind = models.TextField(choices=[(s, s) for s in SUBJECTS])
    supplier = models.ForeignKey(Supplier, null=True, blank=True, on_delete=models.PROTECT, related_name="checks")
    person = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                               related_name="+")
    subject_name = models.TextField()
    national_id_check = models.ForeignKey("accounts.NationalIdCheck", null=True, blank=True,
                                          on_delete=models.PROTECT, related_name="+")
    case_id = models.UUIDField(null=True, blank=True)
    level = models.TextField(default="standard", choices=[("standard", "standard"), ("enhanced", "enhanced")])
    status = models.TextField(default="pending", choices=[(s, s) for s in STATUSES])
    note = models.TextField(blank=True, default="")
    evidence = models.ForeignKey("evidence.Evidence", null=True, blank=True, on_delete=models.PROTECT,
                                 related_name="+")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "prj_background_check"
        constraints = [
            models.CheckConstraint(condition=~Q(subject_kind="supplier") | Q(supplier__isnull=False),
                                   name="prj_check_supplier"),
            models.CheckConstraint(condition=Q(status="pending") | Q(decided_at__isnull=False),
                                   name="prj_check_decided"),
        ]


BACKGROUND_CHECK = state.register("prj_background_check", "prj_background_check", {
    "pending": {"passed", "failed"},
})


class Invoice(CountryScopedModel):
    """A supplier's invoice against a stage. The release names the invoice's own supplier (RUL-21)."""

    STATUSES = ["submitted", "accepted", "rejected", "paid", "cancelled"]
    project = models.ForeignKey("construction.Project", on_delete=models.PROTECT, related_name="fund_invoices")
    milestone = models.ForeignKey("construction.Milestone", on_delete=models.PROTECT, related_name="fund_invoices")
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="invoices")
    number = models.TextField()
    amount = amount_field()
    currency = currency_field()
    description = models.TextField(blank=True, default="")
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT, related_name="+")
    status = models.TextField(default="submitted", choices=[(s, s) for s in STATUSES])
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "prj_invoice"
        constraints = [
            models.UniqueConstraint(fields=["supplier", "number"], condition=~Q(status__in=["rejected", "cancelled"]),
                                    name="prj_invoice_once"),
            models.CheckConstraint(condition=Q(amount__gt=0), name="prj_invoice_amount"),
            models.CheckConstraint(condition=~Q(status__in=["accepted", "paid"]) | Q(accepted_by__isnull=False),
                                   name="prj_invoice_accepted_by"),
        ]


INVOICE = state.register("prj_invoice", "prj_invoice", {
    "submitted": {"accepted", "rejected", "cancelled"},
    "accepted": {"paid", "cancelled", "submitted"},
})


class AmlReview(CountryScopedModel):
    """FR-PRJ-004: enhanced anti-money-laundering checks above the country threshold, completed and approved by
    a reviewer before funding."""

    STATUSES = ["required", "submitted", "approved", "rejected"]
    project = models.OneToOneField("construction.Project", on_delete=models.PROTECT, related_name="aml_review")
    threshold_amount = amount_field()
    threshold_currency = currency_field()
    budget_in_threshold_currency = amount_field()
    status = models.TextField(default="required", choices=[(s, s) for s in STATUSES])
    source_of_funds = models.TextField(blank=True, default="")
    purpose = models.TextField(blank=True, default="")
    evidence_ids = models.JSONField(default=list, blank=True)
    prepared_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                   related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "prj_aml_review"
        constraints = [models.CheckConstraint(condition=~Q(status__in=["approved", "rejected"]) | (
            Q(decided_by__isnull=False) & ~Q(decided_by=models.F("prepared_by"))), name="prj_aml_two_people")]


AML = state.register("prj_aml_review", "prj_aml_review", {
    "required": {"submitted"},
    "submitted": {"approved", "rejected", "required"},
    "rejected": {"submitted"},
})


class Agreement(CountryScopedModel):
    """FR-PRJ-005: every project agreement carries the no-advice statement (checked again by the database)."""

    project = models.ForeignKey("construction.Project", on_delete=models.PROTECT, related_name="fund_agreements")
    version = models.PositiveIntegerField()
    text = models.TextField()
    text_sha256 = models.CharField(max_length=64)
    terms_version = models.ForeignKey("administration.LockedTextVersion", null=True, blank=True,
                                      on_delete=models.PROTECT, related_name="+")
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="+")
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "prj_agreement"
        constraints = [models.UniqueConstraint(fields=["project", "version"], name="prj_agreement_version")]
