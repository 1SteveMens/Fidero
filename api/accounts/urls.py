from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf", views.csrf),
    path("auth/register", views.register),
    path("auth/login", views.session_login),
    path("auth/logout", views.session_logout),
    path("auth/token", views.token),
    path("auth/refresh", views.refresh),
    path("auth/mfa/setup", views.mfa_setup),
    path("auth/mfa/confirm", views.mfa_confirm),
    path("auth/mfa/step-up", views.mfa_step_up),
    path("me", views.me),
]
