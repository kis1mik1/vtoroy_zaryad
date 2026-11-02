import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.core.email import send_templated_email

from .images import make_avatar
from .models import PERMANENT_BAN_UNTIL, BanRecord, User
from .signals import account_deleted
from .tokens import (
    make_email_change_token,
    make_verification_token,
    read_email_change_token,
    read_verification_token,
)

LAST_SEEN_INTERVAL = timedelta(minutes=5)


class EmailTaken(Exception):
    pass


def _absolute(path: str) -> str:
    return f"{settings.SITE_URL}{path}"


def send_verification_email(user: User) -> None:
    token = make_verification_token(user)
    send_templated_email(
        user.email,
        "verify_email",
        {"user": user, "url": _absolute(reverse("accounts:verify_email", args=[token]))},
    )


@transaction.atomic
def register_user(*, email: str, password: str, first_name: str, city) -> User:
    user = User.objects.create_user(email, password, first_name=first_name, city=city)
    send_verification_email(user)
    return user


@transaction.atomic
def verify_email(token: str) -> tuple[User, bool]:
    user = read_verification_token(token)
    user = User.objects.select_for_update().get(pk=user.pk)
    if user.is_email_verified:
        return user, False
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email_verified_at"])
    return user, True


def request_email_change(user: User, new_email: str) -> None:
    token = make_email_change_token(user, new_email)
    send_templated_email(
        new_email,
        "change_email",
        {
            "user": user,
            "new_email": new_email,
            "url": _absolute(reverse("accounts:confirm_email_change", args=[token])),
        },
    )


@transaction.atomic
def confirm_email_change(token: str) -> User:
    user, new_email = read_email_change_token(token)
    if User.objects.filter(email=new_email).exclude(pk=user.pk).exists():
        raise EmailTaken
    old_email = user.email
    user.email = new_email
    user.email_verified_at = timezone.now()
    user.save(update_fields=["email", "email_verified_at"])
    send_templated_email(old_email, "email_changed", {"user": user, "new_email": new_email})
    return user


def notify_password_changed(user: User) -> None:
    send_templated_email(
        user.email,
        "password_changed",
        {"user": user, "reset_url": _absolute(reverse("accounts:password_reset"))},
    )


def set_avatar(user: User, uploaded) -> None:
    content = make_avatar(uploaded)
    old_name = user.avatar.name
    user.avatar.save(f"{secrets.token_hex(8)}.webp", content, save=False)
    user.save(update_fields=["avatar"])
    if old_name and old_name != user.avatar.name:
        user.avatar.storage.delete(old_name)


def remove_avatar(user: User) -> None:
    if user.avatar:
        user.avatar.delete(save=False)
        user.save(update_fields=["avatar"])


def touch_last_seen(user: User) -> None:
    now = timezone.now()
    if user.last_seen_at and now - user.last_seen_at < LAST_SEEN_INTERVAL:
        return
    User.objects.filter(pk=user.pk).update(last_seen_at=now)
    user.last_seen_at = now


@transaction.atomic
def ban_user(user: User, *, reason: str, until: datetime | None, moderator=None) -> BanRecord:
    record = BanRecord.objects.create(user=user, moderator=moderator, reason=reason, until=until)
    user.banned_until = until or PERMANENT_BAN_UNTIL
    user.ban_reason = reason
    user.save(update_fields=["banned_until", "ban_reason"])
    return record


@transaction.atomic
def lift_ban(user: User, *, moderator=None) -> None:
    now = timezone.now()
    BanRecord.objects.filter(user=user, lifted_at__isnull=True).update(
        lifted_at=now, lifted_by=moderator
    )
    user.banned_until = None
    user.ban_reason = ""
    user.save(update_fields=["banned_until", "ban_reason"])


@transaction.atomic
def delete_account(user: User) -> None:
    account_deleted.send(sender=User, user=user)
    if user.avatar:
        user.avatar.delete(save=False)
    user.email = f"deleted-{user.pk}-{secrets.token_hex(4)}@deleted.invalid"
    user.first_name = "Пользователь удалён"
    user.last_name = ""
    user.phone = ""
    user.about = ""
    user.is_active = False
    user.is_staff = False
    user.is_superuser = False
    user.deleted_at = timezone.now()
    user.email_on_messages = False
    user.email_on_price_drop = False
    user.email_on_saved_search = False
    user.email_on_moderation = False
    user.set_unusable_password()
    user.save()
    user.groups.clear()
    user.user_permissions.clear()
    user.notifications.all().delete()
