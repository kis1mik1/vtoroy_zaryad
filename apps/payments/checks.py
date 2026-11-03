from django.conf import settings
from django.core.checks import Tags, Warning, register

from . import gateway


@register(Tags.security, deploy=True)
def yookassa_keys(app_configs, **kwargs):
    if settings.DEBUG or gateway.is_configured():
        return []
    return [
        Warning(
            "Оплата продвижения не настроена.",
            hint="Укажите YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY в .env.",
            id="payments.W001",
        )
    ]
