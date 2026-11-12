from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "payments"
    verbose_name = "PAY Tenmina fee payments"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
