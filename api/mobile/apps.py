from django.apps import AppConfig


class MobileConfig(AppConfig):
    name = "mobile"
    verbose_name = "MOB Field app server"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
