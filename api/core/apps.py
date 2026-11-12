from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "core"
    verbose_name = "Shared kernel"

    def ready(self):
        from django.db.models.signals import post_migrate

        from . import dbsql

        post_migrate.connect(dbsql.install_after_migrate, dispatch_uid="core.install_sql")
