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


def _increment(key: str, timeout: int) -> int:
    if cache.add(key, 1, timeout):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout)
        return 1


def hit(scope: str, ident: str, rate: Rate) -> None:
    now = time.time()
    window = int(now // rate.period)
    if _increment(_key(scope, ident, window), rate.period) > rate.limit:
        raise RateLimited(int((window + 1) * rate.period - now) + 1)


class FailureCounter:
    def __init__(self, scope: str, ttl: int):
        self.scope = scope
        self.ttl = ttl

    def _key(self, ident: str) -> str:
        return _key(self.scope, ident, 0)

    def count(self, ident: str) -> int:
        return cache.get(self._key(ident)) or 0

    def add(self, ident: str) -> int:
        return _increment(self._key(ident), self.ttl)

    def clear(self, ident: str) -> None:
        cache.delete(self._key(ident))
