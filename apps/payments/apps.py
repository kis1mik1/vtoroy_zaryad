from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "apps.payments"
    verbose_name = "Платежи"

    def ready(self):
        from . import checks  # noqa: F401
