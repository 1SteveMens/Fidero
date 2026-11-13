"""INS Insurer partner lines: read-only queries other modules may use.

Clients see their own applications, policies, premiums and claims. An insurer's users (role IS, members of
the insurer's organisation) see only applications and policies for their own insurer (TC-INS-002-03). Staff see
their countries."""
from django.db.models import Q

from accounts.selectors import staff_country_codes

from .models import Application, Claim, Policy, Premium


def _staff_q(user, field="country"):
    codes = staff_country_codes(user)
    if codes is None:
        return Q(pk__isnull=False)
    if codes:
        return Q(**{f"{field}__code__in": codes})
    return None


def _insurer_ids(user):
    from .services import insurer_ids_for

    return insurer_ids_for(user)


def applications_visible(user):
    q = Q(client=user) | (Q(insurer_id__in=_insurer_ids(user)) & ~Q(status="draft"))
    sq = _staff_q(user)
    return Application.objects.filter(q | sq if sq is not None else q).distinct()


def policies_visible(user):
    q = Q(client=user) | Q(insurer_id__in=_insurer_ids(user))
    sq = _staff_q(user)
    return Policy.objects.filter(q | sq if sq is not None else q).distinct()


def premiums_visible(user):
    q = Q(policy__client=user) | Q(policy__insurer_id__in=_insurer_ids(user))
    sq = _staff_q(user)
    return Premium.objects.filter(q | sq if sq is not None else q).distinct()


def claims_visible(user):
    q = Q(policy__client=user) | Q(policy__insurer_id__in=_insurer_ids(user))
    sq = _staff_q(user)
    return Claim.objects.filter(q | sq if sq is not None else q).distinct()


def active_policies_of(person):
    return Policy.objects.filter(client=person, status="active")
