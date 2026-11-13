from propertymgmt.models import ManagedProperty, RentPeriod, Repair


def test_seed_builds_every_state(seeded):
    """FR-PMG-001 to FR-PMG-006: demo properties in several states."""
    props = {p.title: p for p in ManagedProperty.objects.all()}
    house = props["House at Tema Community 25"]
    assert house.status == "managed"
    assert props["Flat at East Legon"].status == "onboarding"
    statuses = set(RentPeriod.objects.filter(tenancy__property=house).values_list("status", flat=True))
    assert {"received", "late"} <= statuses
    assert set(Repair.objects.filter(property=house).values_list("status", flat=True)) == {"paid", "quotes_ready"}
