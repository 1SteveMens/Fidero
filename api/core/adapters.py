"""Ports and adapters (ADR-10). get_adapter("payments") returns the adapter
configured in settings.TENMINA["ADAPTERS"]. Every port ships a fake or manual
adapter so the full workflow runs before any integration exists."""
from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string


@lru_cache(maxsize=None)
def _cls(path):
    return import_string(path)


def get_adapter(port: str, default: str | None = None):
    """`default` is the dotted path used when settings do not name the port,
    so a module can add a port without editing settings."""
    path = settings.TENMINA["ADAPTERS"].get(port, default)
    if path is None:
        raise KeyError(f"No adapter configured for port '{port}'")
    return _cls(path)()
