"""Shared pytest fixtures for every module.

Use `api(person)` to get an authenticated APIClient, `mfa(client)` to pass a
step-up, and `people` for the seeded cast (see accounts/seed.py).
"""
import pyotp
import pytest
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _fast(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.MEDIA_ROOT = tmp_path


@pytest.fixture
def seeded(db):
    """Runs every module's seed (countries, people, flags, ...). Returns ctx."""
    import importlib
    from django.conf import settings

    ctx = {"people": {}}
    for name in settings.TENMINA_MODULES:
        try:
            mod = importlib.import_module(f"{name}.seed")
        except ModuleNotFoundError as exc:
            if exc.name == f"{name}.seed":
                continue
            raise
        mod.run(ctx)
    return ctx


@pytest.fixture
def gh(seeded):
    return seeded["gh"]


@pytest.fixture
def people(seeded):
    return seeded["people"]


@pytest.fixture
def api():
    def make(person=None):
        c = APIClient()
        if person is not None:
            c.force_authenticate(person)
        return c

    return make


@pytest.fixture
def mfa():
    """mfa(client, person) passes a step-up so approvals are allowed."""

    def step_up(client, person):
        from accounts.seed import DEV_MFA_SECRET

        if not person.mfa_enabled:
            person.mfa_secret, person.mfa_enabled = DEV_MFA_SECRET, True
            person.save(update_fields=["mfa_secret", "mfa_enabled"])
        r = client.post("/v1/auth/mfa/step-up", {"code": pyotp.TOTP(person.mfa_secret).now()}, format="json")
        assert r.status_code == 200, r.content
        return r

    return step_up
