from django.apps import AppConfig


class AdsConfig(AppConfig):
    name = "apps.ads"
    verbose_name = "Объявления"

    def ready(self):
        from . import signals  # noqa: F401
