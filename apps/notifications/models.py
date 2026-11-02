from django.conf import settings
from django.db import models


class NotificationKind(models.TextChoices):
    MESSAGE = "message", "Сообщение"
    MODERATION = "moderation", "Модерация"
    PRICE_DROP = "price_drop", "Снижение цены"
    SAVED_SEARCH = "saved_search", "Сохранённый поиск"
    REVIEW = "review", "Отзыв"
    PAYMENT = "payment", "Оплата"
    ACCOUNT = "account", "Аккаунт"


class Notification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="получатель",
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    kind = models.CharField("тип", max_length=20, choices=NotificationKind)
    title = models.CharField("заголовок", max_length=200)
    body = models.TextField("текст", blank=True)
    url = models.CharField("ссылка", max_length=500, blank=True)
    is_read = models.BooleanField("прочитано", default=False)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(
                fields=["user", "is_read", "-created_at"], name="notification_user_read_idx"
            )
        ]

    def __str__(self):
        return self.title
