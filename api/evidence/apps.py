from django.apps import AppConfig


class EvidenceConfig(AppConfig):
    name = "evidence"
    verbose_name = "EVD Evidence store"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
