from django.conf import settings
from django.db import models
from django.db.models import Q


class Verdict(models.TextChoices):
    APPROVED = "approved", "Одобрено"
    MANUAL = "manual", "Передано модератору"
    REJECTED = "rejected", "Отклонено"


class RejectionReason(models.TextChoices):
    NOT_ELECTRONICS = "not_electronics", "Товар не относится к электронике"
    PHOTOS = "photos", "Фотографии не соответствуют товару или взяты из интернета"
    CONTACTS = "contacts", "В описании есть контакты или ссылки"
    CATEGORY = "category", "Неверно выбрана категория или модель"
    PRICE = "price", "Цена не соответствует товару"
    MULTIPLE = "multiple", "Несколько товаров в одном объявлении"
    FORBIDDEN = "forbidden", "Запрещённый товар"
    SERVICES = "services", "Услуги размещать нельзя"
    DUPLICATE = "duplicate", "Такое объявление у вас уже есть"
    FRAUD = "fraud", "Подозрение на мошенничество"
    OTHER = "other", "Другая причина"


class ModerationCheck(models.Model):
    ad = models.ForeignKey(
        "ads.Ad", verbose_name="объявление", on_delete=models.CASCADE, related_name="checks"
    )
    verdict = models.CharField("решение", max_length=10, choices=Verdict)
    rule_flags = models.JSONField("сработавшие правила", default=list, blank=True)
    text_label = models.CharField("класс по тексту", max_length=30, blank=True)
    text_confidence = models.FloatField("уверенность по тексту", null=True, blank=True)
    electronics_score = models.FloatField("электроника по тексту", null=True, blank=True)
    predicted_category = models.ForeignKey(
        "catalog.Category",
        verbose_name="категория по тексту",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    image_scores = models.JSONField("оценки фото", default=list, blank=True)
    reasons = models.JSONField("что вызвало сомнение", default=list, blank=True)
    rejection_reason = models.TextField("причина для продавца", blank=True)
    duration_ms = models.PositiveIntegerField("длительность, мс", default=0)
    created_at = models.DateTimeField("проверено", auto_now_add=True)

    class Meta:
        verbose_name = "автопроверка"
        verbose_name_plural = "автопроверки"
        ordering = ("-created_at", "-pk")
        indexes = [models.Index(fields=["ad", "-created_at"], name="check_ad_created_idx")]

    def __str__(self):
        return f"{self.ad} — {self.get_verdict_display()}"

    @property
    def flagged_photo_ids(self) -> set[int]:
        return {item["photo"] for item in self.image_scores if item.get("flagged")}


class ActionKind(models.TextChoices):
    APPROVE = "approve", "Одобрено"
    REJECT = "reject", "Отклонено"
    TAKE_DOWN = "take_down", "Снято с публикации"
    RESTORE = "restore", "Возвращено в публикацию"
    REVIEW = "review", "Отправлено на проверку"


class ModerationAction(models.Model):
    ad = models.ForeignKey(
        "ads.Ad",
        verbose_name="объявление",
        on_delete=models.CASCADE,
        related_name="moderation_actions",
    )
    moderator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="модератор",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Пусто — действие выполнено автоматически",
    )
    action = models.CharField("действие", max_length=10, choices=ActionKind)
    reason_code = models.CharField("причина", max_length=20, choices=RejectionReason, blank=True)
    comment = models.TextField("комментарий", blank=True)
    created_at = models.DateTimeField("когда", auto_now_add=True)

    class Meta:
        verbose_name = "решение модератора"
        verbose_name_plural = "решения модераторов"
        ordering = ("-created_at", "-pk")
        permissions = [
            ("review_ad", "Может проверять объявления"),
            ("handle_complaint", "Может разбирать жалобы"),
            ("ban_user", "Может блокировать пользователей"),
        ]

    def __str__(self):
        return f"{self.get_action_display()}: {self.ad}"


class ComplaintReason(models.TextChoices):
    NOT_ELECTRONICS = "not_electronics", "Это не электроника"
    FRAUD = "fraud", "Мошенничество"
    WRONG_PRICE = "wrong_price", "Неверная цена"
    SOLD = "sold", "Уже продано"
    SPAM = "spam", "Спам или повтор"
    INSULT = "insult", "Оскорбления"
    OTHER = "other", "Другое"


AD_COMPLAINT_REASONS = (
    ComplaintReason.NOT_ELECTRONICS,
    ComplaintReason.FRAUD,
    ComplaintReason.WRONG_PRICE,
    ComplaintReason.SOLD,
    ComplaintReason.SPAM,
    ComplaintReason.OTHER,
)
USER_COMPLAINT_REASONS = (
    ComplaintReason.FRAUD,
    ComplaintReason.INSULT,
    ComplaintReason.SPAM,
    ComplaintReason.OTHER,
)


class ComplaintStatus(models.TextChoices):
    NEW = "new", "Новая"
    ACCEPTED = "accepted", "Подтверждена"
    DISMISSED = "dismissed", "Отклонена"


class Complaint(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="автор",
        on_delete=models.CASCADE,
        related_name="complaints_sent",
    )
    ad = models.ForeignKey(
        "ads.Ad",
        verbose_name="объявление",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="complaints",
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="complaints_received",
    )
    reason = models.CharField("причина", max_length=20, choices=ComplaintReason)
    comment = models.TextField("комментарий", max_length=1000, blank=True)
    status = models.CharField(
        "статус", max_length=10, choices=ComplaintStatus, default=ComplaintStatus.NEW
    )
    handled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="кто разобрал",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    handled_at = models.DateTimeField("разобрана", null=True, blank=True)
    created_at = models.DateTimeField("отправлена", auto_now_add=True)

    class Meta:
        verbose_name = "жалоба"
        verbose_name_plural = "жалобы"
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(
                condition=(Q(ad__isnull=False) & Q(target_user__isnull=True))
                | (Q(ad__isnull=True) & Q(target_user__isnull=False)),
                name="complaint_single_target",
            ),
            models.UniqueConstraint(
                fields=("author", "ad"),
                condition=Q(ad__isnull=False),
                name="complaint_unique_ad",
            ),
            models.UniqueConstraint(
                fields=("author", "target_user"),
                condition=Q(target_user__isnull=False, status="new"),
                name="complaint_unique_open_user",
            ),
        ]
        indexes = [models.Index(fields=["status", "-created_at"], name="complaint_status_idx")]

    def __str__(self):
        return f"{self.get_reason_display()}: {self.target}"

    @property
    def target(self):
        return self.ad if self.ad_id else self.target_user
