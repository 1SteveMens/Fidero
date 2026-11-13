"""The FEE demo data covers every state the screens show."""


def test_seeded_institutions_and_payments(seeded):
    """FR-FEE-001 to FR-FEE-007: the seed builds institutions and bills in several states on both routes."""
    from fees.models import Institution, Invoice, Payment, RunnerTask, Schedule

    gh = seeded["gh"]
    by_name = {i.legal_name: i for i in Institution.objects.filter(country=gh)}
    assert by_name["Accra Hills School (demo)"].status == "verified"
    assert by_name["Komfo Anokye Teaching Hospital (demo)"].status == "verified"
    assert by_name["Tema Community Clinic (demo)"].status == "pending"
    assert by_name["Mama Esi Chemist (demo)"].status == "not_eligible"
    assert by_name["Accra Hilis School (demo)"].look_alike_status == "open"
    statuses = set(Invoice.objects.values_list("status", flat=True))
    assert {"checked", "client_approved", "paid", "receipted", "instructed", "draft"} <= statuses
    pay_statuses = set(Payment.objects.values_list("status", flat=True))
    assert {"awaiting_client_payment", "client_reported", "receipt_overdue", "receipted", "instructed"} <= pay_statuses
    assert RunnerTask.objects.filter(status="open").exists()
    assert Schedule.objects.filter(status="active").exists()
