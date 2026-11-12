from django.apps import AppConfig


class DataprotectionConfig(AppConfig):
    name = "dataprotection"
    verbose_name = "DPR Data protection"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
