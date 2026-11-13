"""AUD read-only queries (FR-AUD-003)."""
from django.db.models import Q

from .models import AuditEvent

SEARCH_ROLES = ("RV", "AD", "DPO")


def search(params: dict, viewer=None):
    """Filter the log. A viewer whose grants are limited to some countries sees
    those countries' entries and platform entries (no country) only."""
    qs = AuditEvent.objects.all().order_by("-seq")
    if viewer is not None:
        from countries.selectors import staff_country_codes

        codes = staff_country_codes(viewer, *SEARCH_ROLES)
        if codes is not None:
            qs = qs.filter(Q(country_code__in=codes) | Q(country_code=""))
    for f in ("entity", "entity_id", "actor_id"):
        v = params.get(f)
        if v:
            qs = qs.filter(**{f: str(v)})
    action = params.get("action")
    if action:
        if action.endswith("*") or action.endswith("."):
            qs = qs.filter(action__startswith=action.rstrip("*"))
        else:
            qs = qs.filter(action=action)
    case_id = params.get("case_id")
    if case_id:
        qs = qs.filter(Q(entity="case", entity_id=str(case_id)) | Q(data__case_id=str(case_id)))
    country = params.get("country")
    if country:
        qs = qs.filter(country_code=country.upper())
    if params.get("occurred_from"):
        qs = qs.filter(occurred_at__gte=params["occurred_from"])
    if params.get("occurred_to"):
        qs = qs.filter(occurred_at__lte=params["occurred_to"])
    if params.get("before_seq"):
        qs = qs.filter(seq__lt=int(params["before_seq"]))
    return qs


def last_check():
    from .models import ChainCheck

    return ChainCheck.objects.order_by("-ran_at").first()
