import pytest


@pytest.fixture
def b(seeded):
    from .helpers import Builder

    return Builder(seeded)


@pytest.fixture
def codes():
    def get(exc):
        return {r.get("code") for r in (getattr(exc, "blocking_reasons", None) or [])}

    return get
