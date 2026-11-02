from datetime import UTC, datetime

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

from .managers import UserManager

PERMANENT_BAN_UNTIL = datetime(9999, 12, 31, tzinfo=UTC)


class ContactMode(models.TextChoices):
    PHONE_AND_MESSAGES = "phone_and_messages", "Звонки и сообщения"
    MESSAGES_ONLY = "messages_only", "Только сообщения"


def avatar_upload_to(instance, filename):
    return f"avatars/{instance.pk}/{filename}"


class User(AbstractUser):
    username = None
    email = models.EmailField(
        "электронная почта",
        unique=True,
        error_messages={"unique": "Пользователь с такой почтой уже зарегистрирован."},
    )
    first_name = models.CharField("имя", max_length=60)
    phone = models.CharField("телефон", max_length=12, blank=True)
    contact_mode = models.CharField(
        "способ связи",
        max_length=20,
        choices=ContactMode,
        default=ContactMode.MESSAGES_ONLY,
    )
    city = models.ForeignKey(
        "core.City",
        verbose_name="город",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
    )
    avatar = models.ImageField("фото", upload_to=avatar_upload_to, blank=True)
    about = models.TextField("о себе", max_length=1000, blank=True)

    email_verified_at = models.DateTimeField("почта подтверждена", null=True, blank=True)
    last_seen_at = models.DateTimeField("последний визит", null=True, blank=True)
    banned_until = models.DateTimeField("заблокирован до", null=True, blank=True)
    ban_reason = models.CharField("причина блокировки", max_length=500, blank=True)
    deleted_at = models.DateTimeField("аккаунт удалён", null=True, blank=True)

    rating_avg = models.DecimalField("средняя оценка", max_digits=3, decimal_places=2, default=0)
    rating_count = models.PositiveIntegerField("число отзывов", default=0)

    email_on_messages = models.BooleanField("письма о новых сообщениях", default=True)
    email_on_price_drop = models.BooleanField("письма о снижении цены в избранном", default=True)
    email_on_saved_search = models.BooleanField(
        "письма о новых объявлениях по сохранённым поискам", default=True
    )
    email_on_moderation = models.BooleanField("письма о решениях модерации", default=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = ["first_name"]

    objects = UserManager()

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
        ordering = ("-date_joined",)
        indexes = [models.Index(fields=["banned_until"], name="user_banned_until_idx")]

    def __str__(self):
        return self.email

    def clean(self):
        super().clean()
        self.email = type(self).objects.normalize_email(self.email)

    def get_full_name(self):
        return self.first_name

    def get_short_name(self):
        return self.first_name

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_banned(self) -> bool:
        return self.banned_until is not None and self.banned_until > timezone.now()

    @property
    def is_banned_forever(self) -> bool:
        return self.is_banned and self.banned_until >= PERMANENT_BAN_UNTIL

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    @property
    def shows_phone(self) -> bool:
        return bool(self.phone) and self.contact_mode == ContactMode.PHONE_AND_MESSAGES

    @property
    def initials(self) -> str:
        return (self.first_name[:1] or self.email[:1]).upper()


class BanRecord(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        on_delete=models.CASCADE,
        related_name="ban_records",
    )
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="модератор",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reason = models.CharField("причина", max_length=500)
    until = models.DateTimeField("до", null=True, blank=True, help_text="Пусто — навсегда")
    created_at = models.DateTimeField("создано", auto_now_add=True)
    lifted_at = models.DateTimeField("снята", null=True, blank=True)
    lifted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто снял",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        verbose_name = "блокировка"
        verbose_name_plural = "блокировки"
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.user} — {self.reason}"

    @property
    def is_permanent(self) -> bool:
        return self.until is None
