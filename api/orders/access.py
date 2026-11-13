"""Object-level scoping for orders (FR-ACC-007, 02 section 10.4).

Clients see their own orders. Sellers and developers also see orders billed
to an organisation they belong to. Staff see the countries of their role
grants (a grant with no country covers every country)."""
from django.db.models import Q

from core.permissions import STAFF_ROLES, has_role


def staff_country_ids(user, roles=STAFF_ROLES):
    """None means every country; a list limits staff to those countries; [] means not staff."""
    if not user or not user.is_authenticated:
        return []
    grants = user.role_grants.filter(revoked_at__isnull=True, role__in=list(roles))
    if grants.filter(country__isnull=True).exists():
        return None
    return list(grants.values_list("country_id", flat=True))


def is_staff_for(user, country, roles=STAFF_ROLES) -> bool:
    ids = staff_country_ids(user, roles)
    if ids is None:
        return True
    return getattr(country, "pk", country) in ids


def organisation_ids(user):
    """Organisations the user acts for: an active ACC membership (FR-ACC-011, the source listings and the other
    lines use) or a role grant scoped to the organisation."""
    if not user or not user.is_authenticated:
        return []
    from accounts.selectors import organisations_of

    ids = list(user.role_grants.filter(revoked_at__isnull=True, organisation__isnull=False)
               .values_list("organisation_id", flat=True))
    ids += [pk for pk in organisations_of(user).values_list("pk", flat=True) if pk not in ids]
    return ids


def scope(qs, user, *, client_field="client", org_field="organisation", country_field="country"):
    """Filter a queryset of client-owned rows to what `user` may see."""
    if not user or not user.is_authenticated:
        return qs.none()
    ids = staff_country_ids(user)
    if ids is None:
        return qs
    cond = Q(**{client_field: user})
    if org_field:
        orgs = organisation_ids(user)
        if orgs and has_role(user, "SE", "DV"):
            cond |= Q(**{f"{org_field}__in": orgs})
    if ids:
        cond |= Q(**{f"{country_field}_id__in": ids})
    return qs.filter(cond)
