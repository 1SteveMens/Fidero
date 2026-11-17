"""ACC read-only queries other modules may use (FR-ACC-007 scoping, RUL-20,
RUL-22, RUL-24, RUL-31, FR-ACC-012)."""
from django.db.models import Q
from django.utils import timezone

from core.errors import Invalid, NotFound
from core.permissions import STAFF_ROLES

from .models import (BankAccount, FamilyMember, IdentityCheck, Membership, NationalIdCheck, Organisation, Person,
                     ProfessionalLicence, RepresentativeGrant, Vetting)
from .normalise import normalise_name, normalise_phone


def person(pk) -> Person:
    return Person.objects.get(pk=pk)


def staff_country_codes(p, roles=STAFF_ROLES):
    """Countries where `p` works as staff. None means every country; an
    empty set means none (FR-ACC-007, US-CTY-001b)."""
    grants = p.role_grants.filter(revoked_at__isnull=True, role__in=roles)
    codes = set()
    for country_code in grants.values_list("country__code", flat=True):
        if country_code is None:
            return None
        codes.add(country_code)
    return codes


def scope_to_staff_countries(qs, p, field="country", roles=STAFF_ROLES):
    codes = staff_country_codes(p, roles)
    if codes is None:
        return qs
    return qs.filter(**{f"{field}__code__in": codes})


def in_staff_scope(p, country, roles=STAFF_ROLES) -> bool:
    codes = staff_country_codes(p, roles)
    return codes is None or getattr(country, "code", country) in codes


def can_place_orders(p) -> bool:
    """A closing account (deletion waiting on open matters) takes no new orders."""
    return p.is_active and p.status == "active"


# ---- organisations (FR-ACC-011)

def organisations_of(p):
    return Organisation.objects.filter(memberships__person=p, memberships__status="active").distinct()


def is_member(p, organisation_id) -> bool:
    return Membership.objects.filter(person=p, organisation_id=organisation_id, status="active").exists()


def membership(p, organisation_id):
    return Membership.objects.filter(person=p, organisation_id=organisation_id, status="active").first()


# ---- representatives (FR-ACC-008)

def representative_subject_ids(p, subject_type):
    now = timezone.now()
    return list(RepresentativeGrant.objects.filter(representative=p, subject_type=subject_type, status="active")
                .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now)).values_list("subject_id", flat=True))


def is_representative(p, subject_type, subject_id) -> bool:
    return subject_id in representative_subject_ids(p, subject_type) or str(subject_id) in {
        str(x) for x in representative_subject_ids(p, subject_type)}


# ---- family members and RUL-22

def active_family_member(client, family_member_id) -> FamilyMember:
    """Raise unless the family member is the client's and still active
    (US-ACC-012 AC3: nothing new is linked to a removed member)."""
    fm = FamilyMember.objects.filter(pk=family_member_id, client=client).first()
    if fm is None:
        raise NotFound()
    if fm.status != "active":
        raise Invalid("This family member was removed. Nothing new can be linked to them.",
                      code="family-member-removed")
    return fm


def family_members_of(client, include_removed=False):
    qs = FamilyMember.objects.filter(client=client)
    return qs if include_removed else qs.filter(status="active")


def is_relative_or_representative(client, *, person=None, name="", phone="") -> bool:
    """RUL-22: a family member or a representative of the client is never a
    payee. Matches by account, normalised name or phone."""
    fms = FamilyMember.objects.filter(client=client).exclude(status="anonymised")
    reps = RepresentativeGrant.objects.filter(client=client, status__in=["pending", "active"])
    if person is not None:
        if fms.filter(person=person).exists() or reps.filter(representative=person).exists():
            return True
        name = name or person.full_name
        phone = phone or person.phone
    if name:
        n = normalise_name(name)
        if any(normalise_name(x) == n for x in fms.values_list("full_name", flat=True)):
            return True
        if any(normalise_name(x) == n for x in reps.values_list("invited_name", flat=True) if x):
            return True
    if phone:
        ph = normalise_phone(phone)
        if ph and fms.filter(phone=ph).exists():
            return True
    return False


# ---- bank accounts (RUL-24)

def verified_bank_account(holder, bank_account_id) -> BankAccount:
    acct = BankAccount.objects.filter(pk=bank_account_id, holder=holder).first()
    if acct is None or acct.verification_status != "verified":
        from core.errors import DomainError

        raise DomainError("The account must be the owner's own verified account.", code="rent-destination-invalid",
                          status=422)
    return acct


# ---- licences, identity, national identity, vetting

def valid_licence(p, role, on=None):
    on = on or timezone.localdate()
    return ProfessionalLicence.objects.filter(person=p, role=role, status="verified", expires_on__gte=on) \
        .order_by("-expires_on").first()


def licensed_people(role, country=None, on=None):
    on = on or timezone.localdate()
    qs = Person.objects.filter(licences__role=role, licences__status="verified", licences__expires_on__gte=on)
    if country is not None:
        qs = qs.filter(licences__country=country)
    return qs.distinct()


def client_identity_passed(p) -> bool:
    return p.id_check_status in ("passed", "manual_passed")


def latest_identity_check(p):
    return IdentityCheck.objects.filter(person=p).order_by("-created_at").first()


def national_id_check(pk) -> NationalIdCheck | None:
    return NationalIdCheck.objects.filter(pk=pk).first()


def national_id_passed(pk) -> bool:
    return NationalIdCheck.objects.filter(pk=pk, result="match").exists()


def latest_national_id_check(*, person=None, context_type=None, context_id=None, subject_role=None):
    qs = NationalIdCheck.objects.all()
    if person is not None:
        qs = qs.filter(person=person)
    if context_type:
        qs = qs.filter(context_type=context_type)
    if context_id:
        qs = qs.filter(context_id=context_id)
    if subject_role:
        qs = qs.filter(subject_role=subject_role)
    return qs.order_by("-requested_at").first()


def live_vetting(p, kind):
    return Vetting.objects.filter(person=p, kind=kind, status="vetted",
                                  valid_until__gte=timezone.localdate()).first()


def is_vetted(p, kind) -> bool:
    return live_vetting(p, kind) is not None


# ---- people pickers in the back office

PEOPLE_SEARCH_MIN = 2
PEOPLE_SEARCH_MAX = 50


def mask_email(email: str) -> str:
    """'ama.mensah@example.com' -> 'a***@example.com'. Enough to tell two people apart, not to write to them."""
    local, _, domain = (email or "").partition("@")
    if not local or not domain:
        return ""
    return f"{local[0]}***@{domain}"


def search_people(viewer, term: str, *, role: str = "", limit: int = 20) -> list[dict]:
    """People pickers for staff (CM, RV, AD): people with an active role grant in, or living in, one of the
    viewer's countries. Only id, name, roles and a masked email. At least PEOPLE_SEARCH_MIN characters."""
    from core.permissions import ALL_ROLES

    term = (term or "").strip()
    if len(term) < PEOPLE_SEARCH_MIN:
        raise Invalid(f"Type at least {PEOPLE_SEARCH_MIN} characters to search.", code="search-too-short",
                      extra={"errors": [{"pointer": "/search", "message": f"At least {PEOPLE_SEARCH_MIN}."}]})
    role = (role or "").strip().upper()
    if role and role not in ALL_ROLES:
        raise Invalid("Unknown role.", extra={"errors": [{"pointer": "/role", "message": "Unknown role."}]})
    codes = staff_country_codes(viewer)
    qs = Person.objects.filter(is_active=True, deleted_at__isnull=True, anonymised_at__isnull=True)
    if codes is not None:
        # A grant for every country alone does not put a person in scope: they must work or live here.
        qs = qs.filter(Q(home_country__code__in=codes)
                       | Q(role_grants__revoked_at__isnull=True, role_grants__country__code__in=codes))
    if role:
        qs = qs.filter(role_grants__role=role, role_grants__revoked_at__isnull=True)
    qs = qs.filter(Q(full_name__icontains=term) | Q(email__icontains=term)).distinct().order_by("full_name")
    limit = max(1, min(int(limit or 20), PEOPLE_SEARCH_MAX))
    people = list(qs[:limit])
    grants = {}
    from .models import RoleGrant

    for pid, r, cc in RoleGrant.objects.filter(person__in=people, revoked_at__isnull=True) \
            .values_list("person_id", "role", "country__code"):
        if codes is None or cc is None or cc in codes:
            grants.setdefault(pid, set()).add(r)
    return [{"id": p.pk, "name": p.full_name, "roles": sorted(grants.get(p.pk, set())),
             "email_masked": mask_email(p.email)} for p in people]
