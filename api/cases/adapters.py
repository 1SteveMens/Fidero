"""CASE ports (ADR-10).

registry_search (IF-09, RUL-30, 02 9.5): official searches through the registry's own
channel. The manual adapter is the R1 path: a named case manager or reviewer lodges the
search on the registry's portal (or at its office) from Tenmina's own account and records
it in Tenmina; nothing is sent automatically, and a runner never holds the account.
"""
from core.adapters import get_adapter


class ManualRegistrySearch:
    name = "manual-registry-search"

    def has_remote_channel(self, partner) -> bool:
        """True when the registry can be searched remotely (its online portal)."""
        channels = (partner.details or {}).get("channels") or []
        return any(c in ("online", "online_portal", "portal") for c in channels)

    def submit(self, *, partner, account_ref, search_on):
        """Manual: staff lodge it themselves and record the registry's reference. Returns None."""
        return None

    def fetch_result(self, *, partner, registry_reference):
        """Manual: staff download the result from the portal and attach it. Returns None."""
        return None


def registry_adapter():
    return get_adapter("registry_search", default="cases.adapters.ManualRegistrySearch")
