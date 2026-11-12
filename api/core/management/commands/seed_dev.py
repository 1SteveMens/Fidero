"""Load development and demo data: `python manage.py seed_dev`.

Calls `<module>.seed.run(ctx)` for every module that has a seed.py, in
settings.TENMINA_MODULES order. ctx is a dict modules use to share objects
(for example ctx["gh"] is the Ghana country, ctx["people"]["client"]).
"""
import importlib

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Seed development data for every module"

    def handle(self, *args, **opts):
        ctx = {"people": {}}
        with transaction.atomic():
            for name in settings.TENMINA_MODULES:
                try:
                    mod = importlib.import_module(f"{name}.seed")
                except ModuleNotFoundError as exc:
                    if exc.name == f"{name}.seed":
                        continue
                    raise
                mod.run(ctx)
                self.stdout.write(f"seeded {name}")
        self.stdout.write(self.style.SUCCESS("Done. Sign in as any seeded person with password 'tenmina-dev-123'."))
