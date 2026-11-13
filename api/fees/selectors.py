"""FEE Payments to institutions: read-only queries other modules may use.

Clients see only their own bills, payments, schedules and the institutions
they added or use. An institution contact sees only its own institution's
bills (TC-FEE-002-02). Staff see their countries (FR-ACC-007). A runner sees
only the tasks assigned to them."""
from django.db.models import Q

from accounts.selectors import staff_country_codes

from .models import ClientInstitution, Institution, InstitutionContact, Invoice, Payment, RunnerTask, Schedule


def _staff_q(user, field="country"):
    codes = staff_country_codes(user)
    if codes is None:
        return Q()
    if codes:
        return Q(**{f"{field}__code__in": codes})
    return None


def contact_institution_ids(user):
    return list(InstitutionContact.objects.filter(person=user, status="active").values_list("institution_id",
                                                                                            flat=True))


def institutions_visible(user):
    q = Q(pk__in=ClientInstitution.objects.filter(client=user).values("institution")) \
        | Q(pk__in=contact_institution_ids(user)) \
        | Q(pk__in=RunnerTask.objects.filter(runner=user).values("institution"))
    sq = _staff_q(user)
    if sq is not None:
        q |= sq if sq else Q(pk__isnull=False)
    return Institution.objects.filter(q).distinct()


def invoices_visible(user):
    q = Q(client=user) | (Q(institution_id__in=contact_institution_ids(user)) & ~Q(status="draft")) \
        | Q(pk__in=RunnerTask.objects.filter(runner=user, invoice__isnull=False).values("invoice"))
    sq = _staff_q(user)
    if sq is not None:
        q |= sq if sq else Q(pk__isnull=False)
    return Invoice.objects.filter(q).distinct()


def payments_visible(user):
    q = Q(invoice__client=user) | Q(invoice__institution_id__in=contact_institution_ids(user))
    sq = _staff_q(user)
    if sq is not None:
        q |= sq if sq else Q(pk__isnull=False)
    return Payment.objects.filter(q).distinct()


def schedules_visible(user):
    q = Q(client=user)
    sq = _staff_q(user)
    if sq is not None:
        q |= sq if sq else Q(pk__isnull=False)
    return Schedule.objects.filter(q).distinct()


def runner_tasks_visible(user):
    q = Q(runner=user)
    sq = _staff_q(user)
    if sq is not None:
        q |= sq if sq else Q(pk__isnull=False)
    return RunnerTask.objects.filter(q).distinct()


def invoices_for_family_member(client, family_member_id):
    return Invoice.objects.filter(client=client, family_member_id=family_member_id)


def open_payments_of(person):
    return Payment.objects.filter(invoice__client=person, status__in=["awaiting_client_payment", "client_reported",
                                                                     "instructed"])


def institution(pk) -> Institution | None:
    return Institution.objects.filter(pk=pk).first()
