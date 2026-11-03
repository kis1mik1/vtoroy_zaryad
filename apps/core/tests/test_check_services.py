import json
import smtplib
from io import BytesIO
from urllib.error import HTTPError

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from yookassa.domain.exceptions import UnauthorizedError

from apps.core import captcha
from apps.core.management.commands import check_services
from apps.payments import gateway

pytestmark = pytest.mark.django_db
SMTP = "django.core.mail.backends.smtp.EmailBackend"


class FakeShop:
    account_id = "123456"
    test = True
    status = "enabled"


class FakeSettings:
    error = None

    @classmethod
    def get_account_settings(cls):
        if cls.error:
            raise cls.error
        return FakeShop()


@pytest.fixture
def shop(monkeypatch):
    FakeSettings.error = None
    monkeypatch.setattr(gateway, "YooSettings", FakeSettings)
    return FakeSettings


def captcha_answer(monkeypatch, body=None, status=200):
    def fake_urlopen(request, timeout):
        if status != 200:
            raise HTTPError(request.full_url, status, "Forbidden", {}, BytesIO())
        return BytesIO(json.dumps(body).encode())

    monkeypatch.setattr(captcha, "urlopen", fake_urlopen)


def test_report_without_failures(shop, capsys):
    call_command("check_services")

    output = capsys.readouterr().out
    assert "✓ PostgreSQL" in output
    assert "✓ Redis" in output
    assert "✓ ЮKassa" in output
    assert "магазин 123456, тестовый" in output
    assert "! SmartCaptcha" in output
    assert "Критичных ошибок нет." in output


def test_wrong_yookassa_keys_fail(shop):
    shop.error = UnauthorizedError({"code": "invalid_credentials"})

    result = check_services.check_yookassa()

    assert result.status == check_services.FAIL
    assert "не приняла shopId" in result.detail
    with pytest.raises(CommandError, match="Есть ошибки: 1"):
        call_command("check_services")


def test_test_email_is_sent(settings, monkeypatch):
    settings.EMAIL_BACKEND = SMTP
    sent = []
    monkeypatch.setattr(check_services, "send_mail", lambda *args: sent.append(args))

    result = check_services.check_email("me@example.com")

    assert result.status == check_services.OK
    assert sent[0][3] == ["me@example.com"]


@pytest.mark.parametrize(
    ("error", "text"),
    [
        (smtplib.SMTPAuthenticationError(535, b"auth"), "пароль приложения"),
        (smtplib.SMTPSenderRefused(553, b"from", "x@example.com"), "должен совпадать с ящиком"),
        (OSError("unreachable"), "нет связи с SMTP-сервером"),
    ],
)
def test_email_errors_are_explained(settings, monkeypatch, error, text):
    settings.EMAIL_BACKEND = SMTP

    def fail(*args):
        raise error

    monkeypatch.setattr(check_services, "send_mail", fail)

    result = check_services.check_email("me@example.com")
    assert result.status == check_services.FAIL
    assert text in result.detail


def test_console_email_is_a_warning():
    assert check_services.check_email("me@example.com").status == check_services.WARN


def test_captcha_server_key_accepted(settings, monkeypatch):
    settings.SMARTCAPTCHA_CLIENT_KEY = "client"
    settings.SMARTCAPTCHA_SERVER_KEY = "server"
    captcha_answer(monkeypatch, {"status": "failed", "message": "Token invalid or expired."})

    assert check_services.check_captcha().status == check_services.OK


def test_captcha_server_key_rejected(settings, monkeypatch):
    settings.SMARTCAPTCHA_CLIENT_KEY = "client"
    settings.SMARTCAPTCHA_SERVER_KEY = "wrong"
    captcha_answer(monkeypatch, status=403)

    result = check_services.check_captcha()
    assert result.status == check_services.FAIL
    assert "HTTP 403" in result.detail


def test_site_url_outside_allowed_hosts_is_reported(settings):
    settings.SITE_URL = "https://192.168.1.20:8443"
    settings.ALLOWED_HOSTS = ["localhost"]

    result = check_services.check_addresses()
    assert result.status == check_services.WARN
    assert "192.168.1.20" in result.detail
