from django.conf import settings
from django.core.files.storage import storages
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.models import TimeStampedModel


def protected_storage():
    return storages["protected"]


def message_file_path(instance, filename):
    return f"chat/{timezone.now():%Y/%m}/{filename}"


class Conversation(TimeStampedModel):
    ad = models.ForeignKey(
        "ads.Ad", verbose_name="объявление", on_delete=models.CASCADE, related_name="conversations"
    )
    buyer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="покупатель",
        on_delete=models.CASCADE,
        related_name="buyer_conversations",
    )
    seller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="продавец",
        on_delete=models.CASCADE,
        related_name="seller_conversations",
    )
    last_message_at = models.DateTimeField("последнее сообщение", null=True, blank=True)
    buyer_hidden = models.BooleanField("скрыт у покупателя", default=False)
    seller_hidden = models.BooleanField("скрыт у продавца", default=False)

    class Meta:
        verbose_name = "диалог"
        verbose_name_plural = "диалоги"
        ordering = ("-last_message_at", "-pk")
        constraints = [
            models.UniqueConstraint(fields=("ad", "buyer"), name="conversation_unique_buyer"),
            models.CheckConstraint(condition=~Q(buyer=F("seller")), name="conversation_two_people"),
        ]
        indexes = [
            models.Index(fields=["buyer", "-last_message_at"], name="conversation_buyer_idx"),
            models.Index(fields=["seller", "-last_message_at"], name="conversation_seller_idx"),
        ]

    def __str__(self):
        return f"{self.ad} — {self.buyer}"

    def is_participant(self, user) -> bool:
        return user.is_authenticated and user.pk in (self.buyer_id, self.seller_id)

    def other(self, user):
        return self.seller if user.pk == self.buyer_id else self.buyer

    def hidden_field(self, user) -> str:
        return "buyer_hidden" if user.pk == self.buyer_id else "seller_hidden"


class MessageKind(models.TextChoices):
    TEXT = "text", "Текст"
    PHOTO = "photo", "Фото"
    VOICE = "voice", "Голосовое"
    SYSTEM = "system", "Системное"


class Message(models.Model):
    conversation = models.ForeignKey(
        Conversation, verbose_name="диалог", on_delete=models.CASCADE, related_name="messages"
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="отправитель",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    kind = models.CharField("тип", max_length=10, choices=MessageKind, default=MessageKind.TEXT)
    text = models.TextField("текст", max_length=2000, blank=True)
    file = models.FileField(
        "файл", storage=protected_storage, upload_to=message_file_path, blank=True
    )
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    duration = models.PositiveSmallIntegerField("длительность, с", null=True, blank=True)
    is_ready = models.BooleanField("готово", default=True)
    is_suspicious = models.BooleanField("похоже на мошенничество", default=False)
    read_at = models.DateTimeField("прочитано", null=True, blank=True)
    emailed = models.BooleanField("напомнили письмом", default=False)
    created_at = models.DateTimeField("отправлено", auto_now_add=True)

    class Meta:
        verbose_name = "сообщение"
        verbose_name_plural = "сообщения"
        ordering = ("created_at", "pk")
        indexes = [
            models.Index(fields=["conversation", "created_at"], name="message_conversation_idx"),
            models.Index(
                fields=["created_at"],
                condition=Q(read_at__isnull=True, emailed=False),
                name="message_unread_idx",
            ),
        ]

    def __str__(self):
        return self.preview

    @property
    def preview(self) -> str:
        if self.kind == MessageKind.PHOTO:
            return "Фото"
        if self.kind == MessageKind.VOICE:
            return "Голосовое сообщение"
        return self.text[:100]


class UserBlock(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто заблокировал",
        on_delete=models.CASCADE,
        related_name="blocks",
    )
    blocked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кого",
        on_delete=models.CASCADE,
        related_name="+",
    )
    created_at = models.DateTimeField("когда", auto_now_add=True)

    class Meta:
        verbose_name = "блокировка собеседника"
        verbose_name_plural = "блокировки собеседников"
        constraints = [
            models.UniqueConstraint(fields=("user", "blocked_user"), name="user_block_unique")
        ]

    def __str__(self):
        return f"{self.user} → {self.blocked_user}"
