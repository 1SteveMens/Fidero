from django.apps import AppConfig


class AuditConfig(AppConfig):
    name = "audit"
    verbose_name = "AUD Audit"

    def ready(self):
        import importlib

        from django.core.signals import request_finished, request_started

        from . import context

        request_started.connect(context.on_request_started, dispatch_uid="audit.origin_started")
        request_finished.connect(context.on_request_finished, dispatch_uid="audit.origin_finished")
        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
