import pytest
from django.contrib.messages import get_messages
from django.http import HttpResponse
from django.test import RequestFactory
from django.urls import reverse

from apps.core.middleware import HtmxMessagesMiddleware

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("name", "heading"),
    [
        ("ads:home", "Категории"),
        ("core:rules", "Правила размещения"),
        ("core:safety", "Признаки мошенничества"),
        ("core:terms", "Пользовательское соглашение"),
        ("core:privacy", "Политика конфиденциальности"),
        ("core:about", "Почему только электроника"),
    ],
)
def test_public_pages(client, name, heading):
    response = client.get(reverse(name))

    assert response.status_code == 200
    assert heading in response.content.decode()


def test_info_page_marks_current_section(client):
    html = client.get(reverse("core:safety")).content.decode()

    assert 'href="/safety/" aria-current="page"' in html
    assert '"@type": "BreadcrumbList"' in html


def test_theme_cookie_sets_html_attribute(client):
    client.cookies["theme"] = "dark"
    assert '<html lang="ru" data-theme="dark">' in client.get("/").content.decode()

    client.cookies["theme"] = "<script>"
    assert '<html lang="ru">' in client.get("/").content.decode()


def test_custom_404_page(client):
    response = client.get("/no-such-page/")

    assert response.status_code == 404
    assert "Такой страницы нет" in response.content.decode()


def test_csrf_failure_page():
    from django.test import Client

    csrf_client = Client(enforce_csrf_checks=True)
    response = csrf_client.post(reverse("core:city_select"), {"city": "artem"})

    assert response.status_code == 403
    assert "Страница устарела" in response.content.decode()


def test_server_error_page():
    from apps.core.views import server_error

    request = RequestFactory().get("/")
    response = server_error(request)

    assert response.status_code == 500
    assert "Что-то сломалось" in response.content.decode()


def test_robots_txt(client):
    response = client.get("/robots.txt")
    body = response.content.decode()

    assert response["Content-Type"].startswith("text/plain")
    assert "Disallow: /account/" in body
    assert "Sitemap: http://localhost:8000/sitemap.xml" in body


def test_sitemap_lists_static_pages(client):
    body = client.get("/sitemap.xml").content.decode()

    assert "<loc>http://testserver/rules/</loc>" in body
    assert "<loc>http://testserver/</loc>" in body


def test_health_ok(client):
    response = client.get("/health/")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "cache": "ok"}


def test_health_reports_cache_failure(client, monkeypatch):
    class BrokenCache:
        def set(self, *args, **kwargs):
            raise ConnectionError

    monkeypatch.setattr("apps.core.views.cache", BrokenCache())
    response = client.get("/health/")

    assert response.status_code == 503
    assert response.json()["cache"] == "error"


def test_styleguide_not_available_without_debug(client):
    assert client.get("/dev/ui/").status_code == 404


class TestHtmxMessagesMiddleware:
    def test_appends_messages_to_htmx_response(self, rf, client):
        from django.contrib import messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django_htmx.middleware import HtmxDetails

        request = rf.get("/", headers={"HX-Request": "true"})
        request.session = client.session
        request._messages = FallbackStorage(request)
        request.htmx = HtmxDetails(request)
        messages.success(request, "Сохранено")

        middleware = HtmxMessagesMiddleware(lambda r: HttpResponse("<p>ok</p>"))
        html = middleware(request).content.decode()

        assert html.startswith("<p>ok</p>")
        assert 'hx-swap-oob="beforeend"' in html
        assert "Сохранено" in html
        assert get_messages(request).used

    def test_skips_non_htmx_requests(self, rf, client):
        from django.contrib import messages
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django_htmx.middleware import HtmxDetails

        request = rf.get("/")
        request.session = client.session
        request._messages = FallbackStorage(request)
        request.htmx = HtmxDetails(request)
        messages.info(request, "Позже")

        middleware = HtmxMessagesMiddleware(lambda r: HttpResponse("<p>ok</p>"))

        assert middleware(request).content == b"<p>ok</p>"
