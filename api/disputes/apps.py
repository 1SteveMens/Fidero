from django.apps import AppConfig


class DisputesConfig(AppConfig):
    name = "disputes"
    verbose_name = "DSP Disputes"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
