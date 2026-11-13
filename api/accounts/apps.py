from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "ACC Accounts and identity"

    def ready(self):
        import importlib

        from . import schema  # noqa: F401  OpenAPI security schemes

        try:
            importlib.import_module(f"{self.name}.handlers")  # event subscribers
        except ModuleNotFoundError as exc:
            if exc.name != f"{self.name}.handlers":
                raise
