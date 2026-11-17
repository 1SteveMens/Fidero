"""Runs every module's demo seed (`seed_dev` and the test fixtures).

Each module with a seed.py has `run(ctx)`, called in settings.TENMINA_MODULES
order. A module may also have `run_late(ctx)`, called once every `run` is done,
in the same order. Use it for demo rows that point at objects a later module
creates (a case, a project, a listing), so every id a seed writes belongs to a
real row. ctx is a dict the seeds use to share objects.
"""
import importlib

from django.conf import settings


def seed_modules():
    for name in settings.TENMINA_MODULES:
        try:
            yield name, importlib.import_module(f"{name}.seed")
        except ModuleNotFoundError as exc:
            if exc.name == f"{name}.seed":
                continue
            raise


def run_all(ctx=None, log=None) -> dict:
    ctx = {"people": {}} if ctx is None else ctx
    mods = list(seed_modules())
    for name, mod in mods:
        mod.run(ctx)
        if log:
            log(f"seeded {name}")
    for name, mod in mods:
        late = getattr(mod, "run_late", None)
        if late is not None:
            late(ctx)
            if log:
                log(f"seeded {name} (late)")
    return ctx
