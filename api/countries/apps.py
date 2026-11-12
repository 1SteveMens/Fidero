from django.apps import AppConfig


class CountriesConfig(AppConfig):
    name = "countries"
    verbose_name = "CTY Multi-country"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
