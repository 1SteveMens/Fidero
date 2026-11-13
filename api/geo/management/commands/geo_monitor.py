"""Run the satellite monitoring comparison now: `python manage.py geo_monitor [--country GH]`."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compare new satellite imagery of watched plots and raise alerts (FR-GEO-007)"

    def add_arguments(self, parser):
        parser.add_argument("--country", default=None)

    def handle(self, *args, country=None, **opts):
        from geo.tasks import monitor_changes

        self.stdout.write(str(monitor_changes(country)))
