from django.apps import AppConfig


class PartnersConfig(AppConfig):
    name = "partners"
    verbose_name = "PTR Partner API"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
