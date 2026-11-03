import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import TimeStampedModel
from apps.core.text import plural_form

FRESH_FOR = timedelta(minutes=30)


class PromotionTariff(models.Model):
    code = models.SlugField("код", max_length=30, unique=True)
    title = models.CharField("название", max_length=60)
    description = models.CharField("описание", max_length=200)
    price = models.PositiveIntegerField("цена, ₽")
    bump = models.BooleanField("поднять в ленте", default=False)
    highlight_days = models.PositiveSmallIntegerField("выделение, дней", default=0)
    pin_days = models.PositiveSmallIntegerField("закрепление, дней", default=0)
    is_active = models.BooleanField("доступен", default=True)
    sort_order = models.PositiveSmallIntegerField("порядок", default=0)

    class Meta:
        verbose_name = "тариф продвижения"
        verbose_name_plural = "тарифы продвижения"
        ordering = ("sort_order", "price")
        constraints = [
            models.CheckConstraint(condition=Q(price__gt=0), name="tariff_price_positive"),
            models.CheckConstraint(
                condition=Q(bump=True) | Q(highlight_days__gt=0) | Q(pin_days__gt=0),
                name="tariff_not_empty",
            ),
        ]

    def __str__(self):
        return f"{self.title} — {self.price} ₽"

    @property
    def perks(self) -> list[str]:
        items = []
        if self.pin_days:
            items.append(f"Первые места в выдаче на {self.pin_days} {_days(self.pin_days)}")
        if self.highlight_days:
            items.append(f"Яркая карточка на {self.highlight_days} {_days(self.highlight_days)}")
        if self.bump:
            items.append("Поднятие в начало ленты")
        return items


def _days(count: int) -> str:
    return plural_form(count, ("день", "дня", "дней"))


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Ожидает оплаты"
    SUCCEEDED = "succeeded", "Оплачен"
    CANCELED = "canceled", "Отменён"


class Payment(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="плательщик",
        on_delete=models.PROTECT,
        related_name="payments",
    )
    ad = models.ForeignKey(
        "ads.Ad",
        verbose_name="объявление",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    tariff = models.ForeignKey(
        PromotionTariff, verbose_name="тариф", on_delete=models.PROTECT, related_name="payments"
    )
    amount = models.PositiveIntegerField("сумма, ₽")
    description = models.CharField("назначение", max_length=128)
    status = models.CharField(
        "статус", max_length=10, choices=PaymentStatus, default=PaymentStatus.PENDING
    )
    idempotence_key = models.UUIDField("ключ идемпотентности", default=uuid.uuid4, unique=True)
    provider_payment_id = models.CharField(
        "платёж в ЮKassa", max_length=64, unique=True, null=True, blank=True
    )
    confirmation_url = models.URLField("страница оплаты", max_length=500, blank=True)
    is_test = models.BooleanField("тестовый", default=False)
    paid_at = models.DateTimeField("оплачен", null=True, blank=True)
    applied_at = models.DateTimeField("продвижение применено", null=True, blank=True)
    cancellation_reason = models.CharField("причина отмены", max_length=200, blank=True)
    last_checked_at = models.DateTimeField("сверен с ЮKassa", null=True, blank=True)
    last_event = models.JSONField("последний ответ ЮKassa", default=dict, blank=True)

    class Meta:
        verbose_name = "платёж"
        verbose_name_plural = "платежи"
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=["user", "-created_at"], name="payment_user_idx"),
            models.Index(
                fields=["created_at"], condition=Q(status="pending"), name="payment_pending_idx"
            ),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"Платёж № {self.pk}: {self.description}"

    @property
    def is_pending(self) -> bool:
        return self.status == PaymentStatus.PENDING

    @property
    def is_fresh(self) -> bool:
        return timezone.now() - self.created_at < FRESH_FOR
