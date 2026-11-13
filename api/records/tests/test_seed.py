"""REC demo data loads with records in several states."""


def test_seed_states(seeded):
    from records.models import Allocation, Authority, Match, RevenueShare

    assert Authority.objects.count() >= 2
    statuses = set(Allocation.objects.values_list("status", flat=True))
    assert "confirmed" in statuses and "flagged" in statuses
    assert Match.objects.filter(kind="exact").exists()
    assert RevenueShare.objects.exists()
