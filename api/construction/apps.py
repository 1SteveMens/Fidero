from django.apps import AppConfig


class ConstructionConfig(AppConfig):
    name = "construction"
    verbose_name = "BLD Construction"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
