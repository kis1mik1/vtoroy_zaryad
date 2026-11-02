from django.apps import AppConfig


class AdsConfig(AppConfig):
    name = "apps.ads"
    verbose_name = "Объявления"

    def ready(self):
        from . import receivers  # noqa: F401
