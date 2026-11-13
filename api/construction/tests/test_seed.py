"""The demo journeys load through the real services."""


def test_seed_journeys(seeded):
    """FR-BLD-001 to FR-BLD-009: the seeded projects reach the states the demo shows."""
    from construction.models import Milestone, PanelMember, Payment, Project

    refs = seeded["construction"]
    assert PanelMember.objects.get(pk=refs["panel"]["kobby"].pk).status == "active"
    assert PanelMember.objects.get(pk=refs["panel"]["adom"].pk).status == "pending"
    a = Project.objects.get(pk=refs["house"].pk)
    assert a.status == "active" and a.payment_route == "client_direct"
    assert Payment.objects.get(milestone__project=a, milestone__seq=0, part="main").status == "paid"
    assert Milestone.objects.get(project=a, key="foundation").status == "inspection_scheduled"
    b = Project.objects.get(pk=refs["quarters"].pk)
    assert b.status == "active" and b.payment_route == "escrow"
    assert Payment.objects.get(milestone__project=b, milestone__seq=0, part="main").status == "paid"
    f = Milestone.objects.get(project=b, key="foundation")
    assert f.status == "inspected"
    pay = Payment.objects.get(milestone=f, part="main", status="awaiting_client")
    assert pay.holdback_amount == 1200
