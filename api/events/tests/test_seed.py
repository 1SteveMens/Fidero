from events.models import Event, Vendor, VendorPayment


def test_seed_builds_every_state(seeded):
    """FR-EVT-001 to FR-EVT-003: demo events in several states."""
    e = Event.objects.get(name="Funeral of Opanyin Kwame Mensah")
    assert e.status == "in_progress"
    assert set(Vendor.objects.filter(event=e).values_list("status", flat=True)) == {"verified", "verifying"}
    assert set(VendorPayment.objects.filter(event=e).values_list("status", flat=True)) == {"paid", "evidenced"}
    assert Event.objects.get(name="Naming ceremony for baby Adwoa").status == "planning"
