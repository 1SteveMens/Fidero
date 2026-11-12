from django.apps import AppConfig


class EventsConfig(AppConfig):
    name = "events"
    verbose_name = "EVT Events"

    def ready(self):
        import importlib

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
