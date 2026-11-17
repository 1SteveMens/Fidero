"""PRO demo data loads and shows journeys in several states."""


def test_seed_states(seeded):
    """FR-PRO-001 to FR-PRO-009: the seed has agreements, payables, claims and runs in several states."""
    from profpay.models import Agreement, ExpenseClaim, Payable, PaymentRun

    assert Agreement.objects.filter(status="active").count() >= 3
    assert Agreement.objects.filter(status="draft").exists()
    statuses = set(Payable.objects.values_list("status", flat=True))
    assert {"paid", "in_run"} <= statuses
    assert set(PaymentRun.objects.values_list("status", flat=True)) & {"partly_confirmed", "confirmed"}
    assert PaymentRun.objects.filter(status="pending_approval").exists()
    assert ExpenseClaim.objects.filter(status="submitted", approved_by__isnull=False).exists()


def test_seed_gives_the_field_errand_agent_pay(seeded):
    """FR-PRO-002, FR-PRO-004, FR-PRO-005, US-PRO-007: the errand agent in Tenmina Field has a paid payable for his
    finished errand, an approved expense claim, a confirmed payment line with its remittance advice and a yearly
    statement, so every My pay screen has data."""
    from profpay.models import Agreement, Document, ExpenseClaim, Payable, PaymentLine

    person = seeded["errands"]["agent"].person
    a = Agreement.objects.get(professional=person, role="errand_agent")
    assert a.status == "active"
    assert Payable.objects.filter(agreement=a, work_kind="errand", status="paid").exists()
    assert ExpenseClaim.objects.filter(claimant=person).exclude(status__in=["submitted", "rejected"]).exists()
    assert PaymentLine.objects.filter(agreement=a, outcome="confirmed").exists()
    kinds = set(Document.objects.filter(agreement=a).values_list("kind", flat=True))
    assert {"remittance_advice", "yearly_statement"} <= kinds
