"""The INS demo data covers the states the screens show."""


def test_seeded_insurance(seeded):
    """FR-INS-001 to FR-INS-004: products published, policies on both premium routes, a claim from the insurer."""
    from insurance.models import Application, Claim, Policy, Premium, Product

    assert Product.objects.filter(status="published").count() >= 2
    assert Application.objects.filter(status="submitted").exists()
    assert set(Policy.objects.values_list("premium_route", flat=True)) == {"client_direct_to_insurer",
                                                                           "held_funds_to_insurer"}
    assert Premium.objects.filter(status="instructed").exists()
    assert Claim.objects.filter(insurer_status="assessing").exists()
