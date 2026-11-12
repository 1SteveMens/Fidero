from django.apps import AppConfig


class ProfpayConfig(AppConfig):
    name = "profpay"
    verbose_name = "PRO Professional payments"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
