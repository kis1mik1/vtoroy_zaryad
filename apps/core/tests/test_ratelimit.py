import json

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from apps.core.ratelimit import Rate, RateLimited, client_ip, hit, is_limited, reset


def test_hit_raises_after_limit():
    rate = Rate(limit=2, period=60)
    hit("test", "a", rate)
    hit("test", "a", rate)

    with pytest.raises(RateLimited) as exc:
        hit("test", "a", rate)

    assert 0 < exc.value.retry_after <= 61
    assert "минут" in exc.value.message


def test_limits_are_per_identity_and_scope():
    rate = Rate(limit=1, period=60)
    hit("test", "a", rate)
    hit("test", "b", rate)
    hit("other", "a", rate)

    assert is_limited("test", "a", rate)
    reset("test", "a", rate)
    assert not is_limited("test", "a", rate)


def test_client_ip_header(settings):
    request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_REAL_IP="203.0.113.5")

    assert client_ip(request) == "10.0.0.1"
    settings.CLIENT_IP_HEADER = "HTTP_X_REAL_IP"
    assert client_ip(request) == "203.0.113.5"


def test_rate_limit_middleware_htmx_response(rf):
    from django_htmx.middleware import HtmxDetails

    from apps.core.middleware import RateLimitMiddleware

    request = rf.post("/", headers={"HX-Request": "true"})
    request.htmx = HtmxDetails(request)
    middleware = RateLimitMiddleware(lambda r: HttpResponse())

    response = middleware.process_exception(request, RateLimited(90))

    assert response.status_code == 429
    assert response["Retry-After"] == "90"
    assert "2 минуты" in json.loads(response["HX-Trigger"])["toast"]["text"]
