import hashlib
import math
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from .text import plural_form


@dataclass(frozen=True)
class Rate:
    limit: int
    period: int


class RateLimited(Exception):
    def __init__(self, retry_after: int):
        super().__init__(retry_after)
        self.retry_after = retry_after

    @property
    def message(self) -> str:
        minutes = max(1, math.ceil(self.retry_after / 60))
        word = plural_form(minutes, ("минуту", "минуты", "минут"))
        return f"Слишком много попыток. Повторите через {minutes} {word}."


def client_ip(request) -> str:
    header = getattr(settings, "CLIENT_IP_HEADER", "")
    if header and request.META.get(header):
        return request.META[header].split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def _key(scope: str, ident: str, window: int) -> str:
    digest = hashlib.sha256(str(ident).encode()).hexdigest()[:32]
    return f"rl:{scope}:{digest}:{window}"


def hit(scope: str, ident: str, rate: Rate) -> None:
    now = time.time()
    window = int(now // rate.period)
    key = _key(scope, ident, window)
    if cache.add(key, 1, rate.period):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, rate.period)
            count = 1
    if count > rate.limit:
        raise RateLimited(int((window + 1) * rate.period - now) + 1)


def is_limited(scope: str, ident: str, rate: Rate) -> bool:
    window = int(time.time() // rate.period)
    return (cache.get(_key(scope, ident, window)) or 0) >= rate.limit


def reset(scope: str, ident: str, rate: Rate) -> None:
    window = int(time.time() // rate.period)
    cache.delete(_key(scope, ident, window))
