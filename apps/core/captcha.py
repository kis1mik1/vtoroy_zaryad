import json
import logging
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger(__name__)

VALIDATE_URL = "https://smartcaptcha.yandexcloud.net/validate"
SCRIPT_URL = "https://smartcaptcha.yandexcloud.net/captcha.js"
TOKEN_FIELD = "smart-token"
TEST_TOKEN = "test-mode-passed"
TIMEOUT = 3


def is_test_mode() -> bool:
    return not (settings.SMARTCAPTCHA_CLIENT_KEY and settings.SMARTCAPTCHA_SERVER_KEY)


def verify(token: str, ip: str) -> bool:
    if not token:
        return False
    if is_test_mode():
        return token == TEST_TOKEN

    payload = urlencode({"secret": settings.SMARTCAPTCHA_SERVER_KEY, "token": token, "ip": ip})
    request = Request(VALIDATE_URL, data=payload.encode(), method="POST")
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            body = response.read().decode()
    except (URLError, TimeoutError, OSError) as exc:
        logger.warning("SmartCaptcha недоступна, проверка пропущена: %s", exc)
        return True
    try:
        return json.loads(body).get("status") == "ok"
    except ValueError:
        logger.warning("SmartCaptcha вернула некорректный ответ: %s", body[:200])
        return True
