from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel

RATING_LABELS = {5: "Отлично", 4: "Хорошо", 3: "Нормально", 2: "Плохо", 1: "Ужасно"}


class AuthorRole(models.TextChoices):
    BUYER = "buyer", "Покупатель"
    SELLER = "seller", "Продавец"


class ReviewQuerySet(models.QuerySet):
    def visible(self):
        return self.filter(is_hidden=False)

    def reported(self):
        return self.filter(reported_at__isnull=False, is_hidden=False)


class Review(TimeStampedModel):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="автор",
        on_delete=models.CASCADE,
        related_name="reviews_written",
    )
    target = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="о ком",
        on_delete=models.CASCADE,
        related_name="reviews_received",
    )
    ad = models.ForeignKey(
        "ads.Ad",
        verbose_name="объявление",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews",
    )
    author_role = models.CharField("автор в сделке", max_length=10, choices=AuthorRole)
    rating = models.PositiveSmallIntegerField("оценка")
    text = models.TextField("отзыв", max_length=2000)
    reply_text = models.TextField("ответ", max_length=1000, blank=True)
    reply_at = models.DateTimeField("ответ дан", null=True, blank=True)
    reported_at = models.DateTimeField("жалоба получена", null=True, blank=True)
    report_reason = models.TextField("жалоба", max_length=500, blank=True)
    is_hidden = models.BooleanField("скрыт", default=False)
    hidden_reason = models.CharField("причина скрытия", max_length=300, blank=True)
    moderated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="модератор",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    moderated_at = models.DateTimeField("проверен модератором", null=True, blank=True)

    objects = ReviewQuerySet.as_manager()

    class Meta:
        verbose_name = "отзыв"
        verbose_name_plural = "отзывы"
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=Q(rating__gte=1) & Q(rating__lte=5), name="review_rating_range"
            ),
            models.CheckConstraint(condition=~Q(author=F("target")), name="review_not_self"),
            models.UniqueConstraint(
                fields=("author", "ad"), condition=Q(ad__isnull=False), name="review_unique_deal"
            ),
        ]
        indexes = [
            models.Index(fields=["target", "is_hidden", "-created_at"], name="review_target_idx"),
            models.Index(
                fields=["reported_at"],
                condition=Q(reported_at__isnull=False, is_hidden=False),
                name="review_reported_idx",
            ),
        ]
        permissions = [("moderate_review", "Может скрывать отзывы")]

    def __str__(self):
        return f"{self.author} → {self.target}: {self.rating}"

    @property
    def rating_label(self) -> str:
        return RATING_LABELS.get(self.rating, "")

    @property
    def reply_title(self) -> str:
        return "Ответ продавца" if self.author_role == AuthorRole.BUYER else "Ответ покупателя"

    @property
    def is_editable(self) -> bool:
        return not self.is_hidden and not self.reply_text

    @property
    def can_be_reported(self) -> bool:
        return not self.is_hidden and self.reported_at is None and self.moderated_at is None
