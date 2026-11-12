from django.apps import AppConfig


class PropertymgmtConfig(AppConfig):
    name = "propertymgmt"
    verbose_name = "PMG Property management"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
