from django.apps import AppConfig


class ErrandsConfig(AppConfig):
    name = "errands"
    verbose_name = "TSK Paperwork and errands"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
