import smtplib
from dataclasses import dataclass
from urllib.parse import urlsplit

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from apps.core import captcha
from apps.moderation.ml import images
from apps.payments import gateway

OK, WARN, FAIL = "ok", "warn", "fail"
MARKS = {OK: "✓", WARN: "!", FAIL: "✗"}
TEST_EMAIL_BACKENDS = ("console", "locmem", "filebased", "dummy")


@dataclass(frozen=True)
class Result:
    status: str
    title: str
    detail: str


def check_database() -> Result:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            version = cursor.fetchone()[0].split(",")[0]
    except Exception as exc:
        return Result(FAIL, "PostgreSQL", str(exc).strip())
    return Result(OK, "PostgreSQL", version)


def check_redis() -> Result:
    try:
        cache.set("check_services", "1", 10)
        cached = cache.get("check_services") == "1"
        layer = get_channel_layer()
        channel = async_to_sync(layer.new_channel)()
        async_to_sync(layer.send)(channel, {"type": "check"})
        delivered = async_to_sync(layer.receive)(channel)["type"] == "check"
    except Exception as exc:
        return Result(FAIL, "Redis", f"кеш или channel layer недоступны: {exc}")
    if not (cached and delivered):
        return Result(FAIL, "Redis", "кеш или channel layer вернули не то, что записали")
    return Result(OK, "Redis", "кеш и channel layer для WebSocket работают")


def check_email(recipient: str) -> Result:
    backend = settings.EMAIL_BACKEND.rsplit(".", 2)[-2]
    if backend in TEST_EMAIL_BACKENDS:
        detail = f"письма не уходят наружу (бэкенд {backend}), задайте EMAIL_URL"
        return Result(WARN, "Почта", detail)
    if not recipient:
        return Result(WARN, "Почта", "укажите адрес: check_services --email you@example.com")
    try:
        send_mail(
            f"Проверка почты — {settings.SITE_NAME}",
            "Если вы читаете это письмо, отправка с сайта настроена правильно.",
            settings.DEFAULT_FROM_EMAIL,
            [recipient],
        )
    except smtplib.SMTPAuthenticationError:
        return Result(FAIL, "Почта", "сервер не принял логин или пароль приложения")
    except smtplib.SMTPSenderRefused:
        sender = settings.DEFAULT_FROM_EMAIL
        detail = f"сервер отклонил отправителя {sender}: он должен совпадать с ящиком"
        return Result(FAIL, "Почта", detail)
    except (smtplib.SMTPException, OSError) as exc:
        return Result(FAIL, "Почта", f"нет связи с SMTP-сервером ({exc.__class__.__name__}: {exc})")
    return Result(OK, "Почта", f"письмо отправлено на {recipient} от {settings.DEFAULT_FROM_EMAIL}")


def check_yookassa() -> Result:
    if not gateway.is_configured():
        return Result(WARN, "ЮKassa", "не настроена: YOOKASSA_SHOP_ID и YOOKASSA_SECRET_KEY")
    try:
        shop = gateway.shop_info()
    except gateway.GatewayError as exc:
        return Result(FAIL, "ЮKassa", str(exc))
    kind = "тестовый" if shop.test else "боевой"
    return Result(OK, "ЮKassa", f"магазин {shop.account_id}, {kind}, статус {shop.status}")


def check_captcha() -> Result:
    if captcha.is_test_mode():
        return Result(WARN, "SmartCaptcha", "тестовый режим: нет ключей SMARTCAPTCHA_*")
    accepted, detail = captcha.check_server_key()
    return Result(OK if accepted else FAIL, "SmartCaptcha", detail)


def check_photos() -> Result:
    ready, note = images.availability()
    return Result(OK if ready else WARN, "Проверка фото", note)


def check_addresses() -> Result:
    host = urlsplit(settings.SITE_URL).hostname or ""
    allowed = settings.ALLOWED_HOSTS
    detail = f"SITE_URL={settings.SITE_URL}, ALLOWED_HOSTS={','.join(allowed)}"
    if "*" not in allowed and host not in allowed:
        return Result(WARN, "Адреса", f"{detail}: хоста {host} нет в ALLOWED_HOSTS")
    return Result(OK, "Адреса", detail)


class Command(BaseCommand):
    help = "Проверяет подключение к базе, Redis, почте, ЮKassa, SmartCaptcha и модели фото."

    def add_arguments(self, parser):
        parser.add_argument("--email", default="", help="Куда отправить тестовое письмо")

    def handle(self, *args, email, **options):
        results = [
            check_database(),
            check_redis(),
            check_email(email),
            check_yookassa(),
            check_captcha(),
            check_photos(),
            check_addresses(),
        ]
        styles = {OK: self.style.SUCCESS, WARN: self.style.WARNING, FAIL: self.style.ERROR}
        for result in results:
            line = f"{MARKS[result.status]} {result.title:<14} {result.detail}"
            self.stdout.write(styles[result.status](line))
        failed = sum(result.status == FAIL for result in results)
        if failed:
            raise CommandError(f"Есть ошибки: {failed}")
        self.stdout.write("Критичных ошибок нет.")
