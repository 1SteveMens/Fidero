"""Shared pytest fixtures for every module.

Use `api(person)` to get an authenticated APIClient, `mfa(client)` to pass a
step-up, and `people` for the seeded cast (see accounts/seed.py).
"""
import pyotp
import pytest
from rest_framework.test import APIClient


@pytest.fixture(autouse=True)
def _fast(settings, _media_root):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.MEDIA_ROOT = _media_root


@pytest.fixture(scope="session")
def _media_root(tmp_path_factory):
    """One evidence store per test run: seeds and tests share it (keys are unique, files write-once)."""
    return tmp_path_factory.mktemp("media")


def _run_seeds():
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


@pytest.fixture(scope="session")
def _seed_once(django_db_setup, django_db_blocker, _media_root):
    """Seeds load once per test run and are committed; each test then runs in
    a transaction that is rolled back, so every test starts from the seeded state."""
    from django.test import override_settings

    with django_db_blocker.unblock(), override_settings(
        MEDIA_ROOT=_media_root,
        PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"],
    ):
        return _run_seeds()


@pytest.fixture
def seeded(db, _seed_once):
    """Every module's seed (countries, people, flags, ...). Returns a fresh copy of ctx."""
    import copy

    return copy.deepcopy(_seed_once)


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
