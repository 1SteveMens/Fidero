from django.apps import AppConfig


class FeesConfig(AppConfig):
    name = "fees"
    verbose_name = "FEE Payments to institutions"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
