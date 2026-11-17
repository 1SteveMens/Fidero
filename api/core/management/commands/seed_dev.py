"""Load development and demo data: `python manage.py seed_dev`.

Calls `<module>.seed.run(ctx)` for every module that has a seed.py, in
settings.TENMINA_MODULES order, then `<module>.seed.run_late(ctx)` where a
module has one (core/seeding.py). ctx is a dict modules use to share objects
(for example ctx["gh"] is the Ghana country, ctx["people"]["client"]).
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.seeding import run_all


class Command(BaseCommand):
    help = "Seed development data for every module"

    def handle(self, *args, **opts):
        with transaction.atomic():
            run_all(log=self.stdout.write)
        self.stdout.write(self.style.SUCCESS("Done. Sign in as any seeded person with password 'tenmina-dev-123'."))
