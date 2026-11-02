import json
from datetime import timedelta

import pytest
from django.http import HttpResponse
from django.urls import reverse
from django.utils import timezone

from apps.accounts import services
from apps.accounts.decorators import verified_email_required
from apps.accounts.models import BanRecord, User

from .factories import UserFactory

pytestmark = pytest.mark.django_db


def test_last_seen_updated_not_more_often_than_every_five_minutes(auth_client, user):
    auth_client.get("/")
    user.refresh_from_db()
    first = user.last_seen_at
    assert first is not None

    auth_client.get("/")
    user.refresh_from_db()
    assert user.last_seen_at == first

    User.objects.filter(pk=user.pk).update(last_seen_at=first - timedelta(minutes=6))
    auth_client.get("/")
    user.refresh_from_db()
    assert user.last_seen_at > first


def test_banned_user_sees_ban_page(auth_client, user):
    services.ban_user(user, reason="Мошенничество", until=timezone.now() + timedelta(days=7))

    response = auth_client.get(reverse("accounts:settings"))

    assert response.status_code == 403
    html = response.content.decode()
    assert "Аккаунт заблокирован" in html
    assert "Мошенничество" in html
    assert "Доступ откроется" in html
    assert response.context["current_city"].slug == "vladivostok"


def test_banned_user_can_read_rules_and_logout(auth_client, user):
    services.ban_user(user, reason="Спам", until=None)

    assert auth_client.get(reverse("core:rules")).status_code == 200
    auth_client.post(reverse("accounts:logout"))
    assert auth_client.get("/").status_code == 200


def test_permanent_ban(auth_client, user):
    record = services.ban_user(user, reason="Спам", until=None)

    assert record.is_permanent
    user.refresh_from_db()
    assert user.is_banned_forever
    assert "Блокировка бессрочная" in auth_client.get("/").content.decode()


def test_expired_ban_does_not_block(auth_client, user):
    User.objects.filter(pk=user.pk).update(
        banned_until=timezone.now() - timedelta(minutes=1), ban_reason="Спам"
    )

    assert auth_client.get(reverse("accounts:settings")).status_code == 200


def test_lift_ban(auth_client, user):
    moderator = UserFactory(is_staff=True)
    services.ban_user(user, reason="Спам", until=None, moderator=moderator)

    services.lift_ban(user, moderator=moderator)

    assert auth_client.get(reverse("accounts:settings")).status_code == 200
    record = BanRecord.objects.get(user=user)
    assert record.lifted_at is not None
    assert record.lifted_by == moderator


@verified_email_required
def protected_view(request):
    return HttpResponse("ok")


def test_verified_email_required_allows_verified(rf, user):
    request = rf.get("/")
    request.user = user
    request.htmx = False

    assert protected_view(request).content == b"ok"


def test_verified_email_required_shows_banner_page(rf):
    request = rf.get("/")
    request.user = UserFactory(unverified=True)
    request.htmx = False

    response = protected_view(request)

    assert response.status_code == 403
    assert "Подтвердите почту" in response.content.decode()


def test_verified_email_required_htmx_toast(rf):
    from django_htmx.middleware import HtmxDetails

    request = rf.get("/", headers={"HX-Request": "true"})
    request.user = UserFactory(unverified=True)
    request.htmx = HtmxDetails(request)

    response = protected_view(request)

    assert response.status_code == 403
    assert json.loads(response["HX-Trigger"])["toast"]["level"] == "warning"


def test_verified_email_required_redirects_anonymous(rf):
    from django.contrib.auth.models import AnonymousUser

    request = rf.get("/secret/")
    request.user = AnonymousUser()

    response = protected_view(request)

    assert response.status_code == 302
    assert "/account/login/" in response.url
