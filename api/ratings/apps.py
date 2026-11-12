from django.apps import AppConfig


class RatingsConfig(AppConfig):
    name = "ratings"
    verbose_name = "RAT Ratings"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
