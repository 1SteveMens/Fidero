from django.apps import AppConfig


class InsuranceConfig(AppConfig):
    name = "insurance"
    verbose_name = "INS Insurer partner lines"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
