"""EVT Events: read-only queries other modules may use."""
from .models import Event, Vendor, VendorPayment


def event(pk):
    return Event.objects.filter(pk=pk).first()


def events_of(client):
    return Event.objects.filter(client=client)


def vendor(pk):
    return Vendor.objects.filter(pk=pk).first()


def payment(pk):
    return VendorPayment.objects.filter(pk=pk).first()
