from django.apps import AppConfig


class ListingsConfig(AppConfig):
    name = "listings"
    verbose_name = "LST Verified listings"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
