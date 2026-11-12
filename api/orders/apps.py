from django.apps import AppConfig


class OrdersConfig(AppConfig):
    name = "orders"
    verbose_name = "ORD Orders"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
