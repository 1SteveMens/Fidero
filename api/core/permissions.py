"""Role checks (document 02, 7.4 and 10.4).

Role codes: CL client, SE seller, DV developer, CM case manager, RV reviewer,
LW lawyer, SV surveyor, RN runner, CT contractor, IN inspector, PT partner,
AD administrator, QS quantity surveyor, AR authority representative,
FM family member, IC institution contact, CE carer or errand agent,
TN tenant, IS insurer partner. Rights: RR release rights, PY payment rights.
"""
from rest_framework.permissions import BasePermission

STAFF_ROLES = {"CM", "RV", "AD"}
PROFESSIONAL_ROLES = {"LW", "SV", "RN", "IN", "QS", "CE"}
ALL_ROLES = ["CL", "SE", "DV", "CM", "RV", "LW", "SV", "RN", "CT", "IN", "PT", "AD", "QS", "AR", "FM", "IC", "CE",
             "TN", "IS", "RR", "PY", "AN", "DPO", "SUP"]


def has_role(user, *roles, country=None) -> bool:
    if not user or not user.is_authenticated:
        return False
    return user.has_tenmina_role(*roles, country=country)


def is_staff(user) -> bool:
    return has_role(user, *STAFF_ROLES)


class HasRole(BasePermission):
    roles: tuple = ()

    def has_permission(self, request, view):
        return has_role(request.user, *self.roles)


def roles(*codes):
    """permission_classes = [roles("CM", "RV")]"""
    return type(f"HasRole_{'_'.join(codes)}", (HasRole,), {"roles": codes})


IsStaff = roles(*STAFF_ROLES)
IsAdmin = roles("AD")
