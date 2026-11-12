from django.apps import AppConfig


class EscrowConfig(AppConfig):
    name = "escrow"
    verbose_name = "ESC Escrow and held funds"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
