from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter(trailing_slash=False)
router.include_root_view = False
router.register("organisations", views.OrganisationViewSet, basename="organisation")
router.register("admin/people", views.AdminPeopleViewSet, basename="admin-person")
router.register("admin/role-grants", views.RoleGrantViewSet, basename="admin-role-grant")
router.register("admin/users/invitations", views.InvitationViewSet, basename="invitation")
router.register("admin/rights-requests", views.RightsRequestViewSet, basename="rights-request")
router.register("licences", views.LicenceViewSet, basename="licence")
router.register("admin/licences", views.AdminLicenceViewSet, basename="admin-licence")
router.register("identity-checks", views.IdentityCheckViewSet, basename="identity-check")
router.register("national-id-checks", views.NationalIdCheckViewSet, basename="national-id-check")
router.register("me/representatives", views.MyRepresentativeViewSet, basename="my-representative")
router.register("family-members", views.FamilyMemberViewSet, basename="family-member")
router.register("bank-accounts", views.BankAccountViewSet, basename="bank-account")
router.register("vettings", views.VettingViewSet, basename="vetting")

urlpatterns = [
    path("auth/csrf", views.csrf),
    path("auth/signup", views.signup),
    path("auth/register", views.register_legacy),  # deprecated: older clients
    path("auth/otp/send", views.otp_send),
    path("auth/otp/verify", views.otp_verify),
    path("auth/login", views.session_login),
    path("auth/logout", views.session_logout),
    path("auth/token", views.token),
    path("auth/refresh", views.refresh),
    path("auth/token/refresh", views.refresh, name="auth-token-refresh"),
    path("auth/password-reset", views.password_reset),
    path("auth/password-reset/confirm", views.password_reset_confirm),
    path("auth/password", views.password_change),
    path("auth/invitations/accept", views.accept_invitation),
    path("auth/mfa/setup", views.mfa_setup),
    path("auth/mfa/confirm", views.mfa_confirm),
    path("auth/mfa/step-up", views.mfa_step_up),
    path("auth/mfa/disable", views.mfa_disable),
    path("me", views.me),
    path("me/identity-checks", views.my_identity_checks),
    path("me/represented", views.represented),
    path("home", views.home),
    *router.urls,
]
