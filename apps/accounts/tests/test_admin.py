from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import BanRecord

from .factories import UserFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client):
    admin = UserFactory(is_staff=True, is_superuser=True)
    client.force_login(admin)
    return client


def test_user_changelist_with_filters(admin_client):
    UserFactory(unverified=True)

    response = admin_client.get(reverse("admin:accounts_user_changelist"), {"verified": "no"})

    assert response.status_code == 200
    assert response.context["cl"].result_count == 1


def test_ban_user_from_admin(admin_client):
    target = UserFactory()
    until = timezone.localtime() + timedelta(days=3)

    response = admin_client.post(
        reverse("admin:accounts_banrecord_add"),
        {
            "user": target.pk,
            "reason": "Оскорбления в переписке",
            "until_0": until.strftime("%d.%m.%Y"),
            "until_1": until.strftime("%H:%M:%S"),
        },
    )

    assert response.status_code == 302
    target.refresh_from_db()
    assert target.is_banned
    assert target.ban_reason == "Оскорбления в переписке"
    assert BanRecord.objects.get(user=target).moderator.is_superuser


def test_ban_in_past_rejected(admin_client):
    target = UserFactory()

    response = admin_client.post(
        reverse("admin:accounts_banrecord_add"),
        {"user": target.pk, "reason": "Спам", "until_0": "01.01.2020", "until_1": "10:00:00"},
    )

    assert response.status_code == 200
    target.refresh_from_db()
    assert not target.is_banned


def test_lift_ban_admin_action(admin_client):
    from apps.accounts.services import ban_user

    target = UserFactory()
    ban_user(target, reason="Спам", until=None)

    admin_client.post(
        reverse("admin:accounts_user_changelist"),
        {"action": "lift_bans", "_selected_action": [target.pk]},
    )

    target.refresh_from_db()
    assert not target.is_banned
