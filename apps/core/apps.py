from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Общее"

    def ready(self):
        from . import signals  # noqa: F401
