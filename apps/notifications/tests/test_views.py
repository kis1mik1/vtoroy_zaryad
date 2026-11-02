import json

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.notifications.models import Notification, NotificationKind

pytestmark = pytest.mark.django_db


def make(user, title="Событие", url="", is_read=False):
    return Notification.objects.create(
        user=user, kind=NotificationKind.ACCOUNT, title=title, url=url, is_read=is_read
    )


def test_list_requires_login(client):
    assert client.get(reverse("notifications:list")).status_code == 302


def test_list_shows_only_own_notifications(auth_client, user):
    make(user, "Моё")
    make(UserFactory(), "Чужое")

    html = auth_client.get(reverse("notifications:list")).content.decode()

    assert "Моё" in html
    assert "Чужое" not in html


def test_unread_filter(auth_client, user):
    make(user, "Прочитанное", is_read=True)
    make(user, "Новое")

    response = auth_client.get(reverse("notifications:list"), {"filter": "unread"})

    titles = [n.title for n in response.context["page_obj"]]
    assert titles == ["Новое"]


def test_list_paginated(auth_client, user):
    for index in range(25):
        make(user, f"Событие {index}")

    response = auth_client.get(reverse("notifications:list"), {"page": 2})

    assert len(response.context["page_obj"]) == 5


def test_header_counter(auth_client, user):
    make(user)
    make(user)

    response = auth_client.get("/")

    assert response.context["unread_notifications"] == 2
    assert "data-notifications-count>2<" in response.content.decode()


def test_dropdown_partial(auth_client, user):
    make(user, "Свежее")

    response = auth_client.get(reverse("notifications:dropdown"), headers={"HX-Request": "true"})

    html = response.content.decode()
    assert "<html" not in html
    assert "Свежее" in html


def test_open_marks_read_and_redirects(auth_client, user):
    notification = make(user, url="/rules/")

    response = auth_client.get(reverse("notifications:open", args=[notification.pk]))

    assert response.url == "/rules/"
    notification.refresh_from_db()
    assert notification.is_read


def test_open_ignores_external_url(auth_client, user):
    notification = make(user, url="https://evil.example/")

    response = auth_client.get(reverse("notifications:open", args=[notification.pk]))

    assert response.url == reverse("notifications:list")


def test_cannot_open_foreign_notification(auth_client):
    notification = make(UserFactory())

    response = auth_client.get(reverse("notifications:open", args=[notification.pk]))

    assert response.status_code == 404
    notification.refresh_from_db()
    assert not notification.is_read


def test_read_all_form(auth_client, user):
    make(user)

    response = auth_client.post(reverse("notifications:read_all"), {"next": "/notifications/"})

    assert response.url == "/notifications/"
    assert not Notification.objects.filter(is_read=False).exists()


def test_read_all_htmx(auth_client, user):
    make(user)

    response = auth_client.post(reverse("notifications:read_all"), headers={"HX-Request": "true"})

    assert json.loads(response["HX-Trigger"]) == {"notifications-count": 0}
    assert "Прочитать все" not in response.content.decode()


def test_read_all_rejects_get(auth_client):
    assert auth_client.get(reverse("notifications:read_all")).status_code == 405
