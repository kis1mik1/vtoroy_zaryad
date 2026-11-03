from django.apps import AppConfig


class ChatConfig(AppConfig):
    name = "apps.chat"
    verbose_name = "Сообщения"

    def ready(self):
        from . import receivers  # noqa: F401
