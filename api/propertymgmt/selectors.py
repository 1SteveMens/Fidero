"""PMG Property management: read-only queries other modules may use."""
from .models import ManagedProperty, RentPeriod, Repair, Tenancy


def managed_property(pk):
    return ManagedProperty.objects.filter(pk=pk).first()


def properties_of(owner):
    return ManagedProperty.objects.filter(owner=owner)


def active_tenancies_of(tenant):
    return Tenancy.objects.filter(tenant=tenant, status="active")


def repair(pk):
    return Repair.objects.filter(pk=pk).first()


def counts(country=None) -> dict:
    """For ANL (A9): properties under management, rent periods received, repairs completed."""
    props = ManagedProperty.objects.filter(status="managed")
    rent = RentPeriod.objects.filter(status__in=["received", "partial"])
    repairs = Repair.objects.filter(status="paid")
    if country is not None:
        props, rent = props.filter(country=country), rent.filter(tenancy__country=country)
        repairs = repairs.filter(country=country)
    return {"properties_managed": props.count(), "rent_periods_received": rent.count(),
            "repairs_completed": repairs.count()}
