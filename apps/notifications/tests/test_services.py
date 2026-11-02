from unittest import mock

import pytest
from django.core import mail

from apps.accounts.tests.factories import UserFactory
from apps.notifications.models import Notification, NotificationKind
from apps.notifications.services import mark_all_read, notify, user_group

pytestmark = pytest.mark.django_db


@pytest.fixture
def pushed():
    with mock.patch("apps.notifications.services.push_to_user") as push:
        yield push


def test_notify_saves_pushes_and_emails(user, pushed, run_on_commit):
    with run_on_commit():
        notification = notify(
            user, NotificationKind.MODERATION, "Объявление опубликовано", url="/rules/"
        )

    assert Notification.objects.get() == notification
    user_id, event = pushed.call_args.args
    assert user_id == user.pk
    assert event["type"] == "notification.created"
    assert event["unread"] == 1
    assert "Объявление опубликовано" in event["html"]
    assert len(mail.outbox) == 1
    assert mail.outbox[0].subject == "Объявление опубликовано"
    assert f"/notifications/{notification.pk}/open/" in mail.outbox[0].body


def test_notify_respects_email_preferences(pushed, run_on_commit):
    user = UserFactory(email_on_price_drop=False)

    with run_on_commit():
        notify(user, NotificationKind.PRICE_DROP, "Цена снизилась")
        notify(user, NotificationKind.REVIEW, "Новый отзыв")

    assert Notification.objects.count() == 2
    assert mail.outbox == []


def test_account_notifications_always_emailed(pushed, run_on_commit):
    user = UserFactory(
        email_on_messages=False,
        email_on_moderation=False,
        email_on_price_drop=False,
        email_on_saved_search=False,
    )

    with run_on_commit():
        notify(user, NotificationKind.PAYMENT, "Оплата прошла")

    assert len(mail.outbox) == 1


def test_no_email_for_unverified_address(pushed, run_on_commit):
    user = UserFactory(unverified=True)

    with run_on_commit():
        notify(user, NotificationKind.MODERATION, "Объявление отклонено")

    assert mail.outbox == []


def test_email_can_be_disabled_per_call(user, pushed, run_on_commit):
    with run_on_commit():
        notify(user, NotificationKind.MODERATION, "Тихое", email=False)

    assert mail.outbox == []


def test_mark_all_read(user, pushed, run_on_commit):
    notify(user, NotificationKind.ACCOUNT, "Один", email=False)
    notify(user, NotificationKind.ACCOUNT, "Два", email=False)

    with run_on_commit():
        assert mark_all_read(user) == 2

    assert not Notification.objects.filter(is_read=False).exists()
    assert pushed.call_args.args == (user.pk, {"type": "notification.read", "unread": 0})


def test_user_group_name():
    assert user_group(15) == "user_15"
