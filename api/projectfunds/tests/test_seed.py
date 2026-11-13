"""The project fund demo journeys load through the real services."""


def test_seed_journeys(seeded):
    """FR-PRJ-001 to FR-PRJ-003: an active borehole with an invoice waiting for the client; a shop being set up."""
    from construction.models import Payment, Project
    from projectfunds.models import Invoice

    refs = seeded["projectfunds"]
    b = Project.objects.get(pk=refs["borehole"].pk)
    assert b.status == "active", b.status
    inv = Invoice.objects.get(project=b)
    assert inv.status == "accepted"
    assert Payment.objects.get(subject_id=inv.pk).status == "awaiting_client"
    shop = Project.objects.get(pk=refs["shop"].pk)
    assert shop.status == "setup"
    assert shop.suppliers.filter(status="incomplete").count() == 1
