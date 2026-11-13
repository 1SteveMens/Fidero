"""PTR Partner API: read-only queries other modules may use.

- active_clients(country)          partner API clients a client may consent to (DPR consent screens)
- client(pk)                       an API client by id (dpr_consent.partner_client_id)
"""
from .models import ApiClient


def active_clients(country=None):
    qs = ApiClient.objects.filter(status="active")
    return qs.filter(country=country) if country is not None else qs


def client(pk) -> ApiClient | None:
    return ApiClient.objects.filter(pk=pk).first()
