from django.apps import AppConfig


class CareConfig(AppConfig):
    name = "care"
    verbose_name = "CARE Care visits"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
