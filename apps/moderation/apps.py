from django.apps import AppConfig


class ModerationConfig(AppConfig):
    name = "apps.moderation"
    verbose_name = "Модерация"

    def ready(self):
        from . import receivers  # noqa: F401
