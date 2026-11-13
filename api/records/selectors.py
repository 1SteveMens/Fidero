"""REC Records programme: read-only queries other modules may use.

- confirmed_chain(case_id)    the chain of ownership a lawyer confirmed from the records, for section 9 (RPT)
- matches_for_asset(asset_id)
"""
from .models import Match


def confirmed_chain(case_id) -> list[dict]:
    m = Match.objects.filter(case_id=case_id, status="confirmed", kind="exact").order_by("-decided_at").first()
    return list(m.prefill) if m else []


def matches_for_asset(asset_id):
    return Match.objects.filter(asset_id=asset_id).select_related("allocation__authority")
