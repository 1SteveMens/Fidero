from django.apps import AppConfig


class RecordsConfig(AppConfig):
    name = "records"
    verbose_name = "REC Records programme"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
