from django.conf import settings
from django.core.checks import Tags, Warning, register

from . import captcha


@register(Tags.security, deploy=True)
def smartcaptcha_keys(app_configs, **kwargs):
    if settings.DEBUG or not captcha.is_test_mode():
        return []
    return [
        Warning(
            "Яндекс SmartCaptcha работает в тестовом режиме.",
            hint="Укажите SMARTCAPTCHA_CLIENT_KEY и SMARTCAPTCHA_SERVER_KEY в .env.",
            id="core.W001",
        )
    ]
