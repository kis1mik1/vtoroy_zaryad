from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse

from apps.core.email import send_templated_email

from .models import Notification, NotificationKind
from .selectors import unread_count

EMAIL_PREFERENCES = {
    NotificationKind.MESSAGE: "email_on_messages",
    NotificationKind.MODERATION: "email_on_moderation",
    NotificationKind.PRICE_DROP: "email_on_price_drop",
    NotificationKind.SAVED_SEARCH: "email_on_saved_search",
}
ALWAYS_EMAILED = {NotificationKind.PAYMENT, NotificationKind.ACCOUNT}


def user_group(user_id: int) -> str:
    return f"user_{user_id}"


def wants_email(user, kind: str) -> bool:
    if not user.is_active or not user.is_email_verified:
        return False
    if kind in ALWAYS_EMAILED:
        return True
    field = EMAIL_PREFERENCES.get(kind)
    return bool(field and getattr(user, field))


def push_to_user(user_id: int, event: dict) -> None:
    layer = get_channel_layer()
    if layer is not None:
        async_to_sync(layer.group_send)(user_group(user_id), event)


def _absolute(url: str) -> str:
    return f"{settings.SITE_URL}{url}" if url.startswith("/") else url


def notify(user, kind: str, title: str, body: str = "", url: str = "", *, email: bool = True):
    notification = Notification.objects.create(
        user=user, kind=kind, title=title, body=body, url=url
    )

    def broadcast():
        push_to_user(
            user.pk,
            {
                "type": "notification.created",
                "unread": unread_count(user),
                "title": notification.title,
                "url": reverse("notifications:open", args=[notification.pk]),
                "html": render_to_string(
                    "notifications/partials/item.html", {"notification": notification}
                ),
            },
        )

    transaction.on_commit(broadcast)

    if email and wants_email(user, kind):
        send_templated_email(
            user.email,
            "notification",
            {
                "user": user,
                "notification": notification,
                "url": _absolute(reverse("notifications:open", args=[notification.pk]))
                if url
                else "",
                "settings_url": _absolute(reverse("accounts:settings_notifications")),
            },
        )
    return notification


def mark_all_read(user) -> int:
    updated = Notification.objects.filter(user=user, is_read=False).update(is_read=True)
    if updated:
        transaction.on_commit(
            lambda: push_to_user(user.pk, {"type": "notification.read", "unread": 0})
        )
    return updated


def mark_read(notification: Notification) -> None:
    if notification.is_read:
        return
    notification.is_read = True
    notification.save(update_fields=["is_read"])
    user = notification.user
    transaction.on_commit(
        lambda: push_to_user(user.pk, {"type": "notification.read", "unread": unread_count(user)})
    )
