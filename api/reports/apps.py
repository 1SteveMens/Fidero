from django.apps import AppConfig


class ReportsConfig(AppConfig):
    name = "reports"
    verbose_name = "RPT Reports"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
