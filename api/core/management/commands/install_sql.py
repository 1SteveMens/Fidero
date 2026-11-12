from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Reinstall database triggers and allowed transitions"

    def handle(self, *args, **opts):
        from core.dbsql import install

        install()
        self.stdout.write("installed")
