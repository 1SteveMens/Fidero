"""The ESC seed builds escrows in every state through the real services."""


def test_seed_states(seeded):
    """FR-ESC-001 to 024: the demo data covers every state a screen shows."""
    from escrow.models import Escrow, ReleaseInstruction

    states = set(Escrow.objects.values_list("status", flat=True))
    assert {"proposed", "funded", "ready_to_release", "released", "frozen", "partly_released"} <= states, states
    assert ReleaseInstruction.objects.filter(status="confirmed").count() >= 3
    assert ReleaseInstruction.objects.filter(status="awaiting_client").exists()
