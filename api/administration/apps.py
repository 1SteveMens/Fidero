from django.apps import AppConfig


class AdministrationConfig(AppConfig):
    name = "administration"
    verbose_name = "ADM Administration"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
