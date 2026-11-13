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
def django_db_createdb():
    """Always start from an empty test database. Seeds are committed once per run
    (see `_seed_once`), so a database kept from an earlier run would hold that
    run's seed rows and evidence rows whose files lived in its media folder."""
    return True


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


@pytest.fixture
def publish_config(people):
    """publish_config(country, **changes) publishes a new configuration version
    with `changes` merged in, the way the countries module intends: a draft
    copy of the current version, prepared by one administrator and approved by
    a second. A published configuration itself never changes (cty_config_rules)."""

    def publish(country, **changes):
        from django.utils import timezone

        from countries import services as cty

        draft = cty.create_config(country, by=people["admin"])
        cty.update_config(draft, by=people["admin"], data={**draft.data, **changes})
        cty.submit_config(draft, by=people["admin"])
        draft.refresh_from_db()
        cty.decide_config(draft, people["admin2"], mfa_at=timezone.now())
        draft.refresh_from_db()
        assert draft.status == "published", draft.status
        return draft

    return publish

