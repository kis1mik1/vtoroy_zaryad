import io
import json
from unittest import mock
from urllib.error import URLError

import pytest
from django.core.checks import run_checks
from django.template import Context, Template

from apps.core import captcha


@pytest.fixture
def keys(settings):
    settings.SMARTCAPTCHA_CLIENT_KEY = "client-key"
    settings.SMARTCAPTCHA_SERVER_KEY = "server-key"


def fake_response(payload):
    response = mock.MagicMock()
    response.__enter__.return_value = io.BytesIO(json.dumps(payload).encode())
    return response


def test_test_mode_accepts_only_test_token():
    assert captcha.is_test_mode()
    assert captcha.verify(captcha.TEST_TOKEN, "1.2.3.4")
    assert not captcha.verify("something-else", "1.2.3.4")
    assert not captcha.verify("", "1.2.3.4")


@pytest.mark.usefixtures("keys")
def test_verify_sends_secret_token_and_ip():
    with mock.patch.object(
        captcha, "urlopen", return_value=fake_response({"status": "ok"})
    ) as call:
        assert captcha.verify("user-token", "203.0.113.7")

    request = call.call_args.args[0]
    assert request.full_url == captcha.VALIDATE_URL
    assert request.data == b"secret=server-key&token=user-token&ip=203.0.113.7"


@pytest.mark.usefixtures("keys")
def test_verify_rejects_failed_status():
    response = fake_response({"status": "failed", "message": "Token invalid"})
    with mock.patch.object(captcha, "urlopen", return_value=response):
        assert not captcha.verify("user-token", "203.0.113.7")


@pytest.mark.usefixtures("keys")
def test_verify_lets_user_through_when_service_unavailable():
    with mock.patch.object(captcha, "urlopen", side_effect=URLError("timeout")):
        assert captcha.verify("user-token", "203.0.113.7")


@pytest.mark.usefixtures("keys")
def test_widget_renders_yandex_container():
    html = Template("{% captcha %}").render(Context())

    assert 'class="smart-captcha" data-sitekey="client-key"' in html
    assert captcha.SCRIPT_URL in html


def test_widget_in_test_mode():
    html = Template("{% captcha %}").render(Context())

    assert f'name="smart-token" value="{captcha.TEST_TOKEN}"' in html
    assert "тестовый режим" in html


def test_deploy_check_warns_without_keys(settings):
    settings.DEBUG = False

    messages = run_checks(include_deployment_checks=True)

    assert "core.W001" in {message.id for message in messages}


@pytest.mark.usefixtures("keys")
def test_deploy_check_silent_with_keys(settings):
    settings.DEBUG = False

    messages = run_checks(include_deployment_checks=True)

    assert "core.W001" not in {message.id for message in messages}
