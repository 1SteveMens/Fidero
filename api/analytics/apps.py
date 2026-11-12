from django.apps import AppConfig


class AnalyticsConfig(AppConfig):
    name = "analytics"
    verbose_name = "ANL Analytics"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
