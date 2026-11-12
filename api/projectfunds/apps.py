from django.apps import AppConfig


class ProjectfundsConfig(AppConfig):
    name = "projectfunds"
    verbose_name = "PRJ Project funds"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
