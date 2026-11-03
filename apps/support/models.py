from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class FAQSection(models.Model):
    title = models.CharField("название", max_length=100)
    slug = models.SlugField("адрес в ссылке", max_length=100, unique=True)
    sort_order = models.PositiveSmallIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликован", default=True)

    class Meta:
        verbose_name = "раздел помощи"
        verbose_name_plural = "разделы помощи"
        ordering = ("sort_order", "title")

    def __str__(self):
        return self.title


class FAQItem(models.Model):
    section = models.ForeignKey(
        FAQSection, verbose_name="раздел", on_delete=models.CASCADE, related_name="items"
    )
    question = models.CharField("вопрос", max_length=200)
    answer = models.TextField("ответ", help_text="Абзацы разделяйте пустой строкой.")
    sort_order = models.PositiveSmallIntegerField("порядок", default=0)
    is_published = models.BooleanField("опубликован", default=True)

    class Meta:
        verbose_name = "вопрос и ответ"
        verbose_name_plural = "вопросы и ответы"
        ordering = ("section__sort_order", "sort_order", "pk")

    def __str__(self):
        return self.question


class TicketTopic(models.TextChoices):
    ACCOUNT = "account", "Аккаунт и вход"
    ADS = "ads", "Объявления и модерация"
    PAYMENT = "payment", "Оплата продвижения"
    FRAUD = "fraud", "Мошенничество"
    BUG = "bug", "Ошибка на сайте"
    OTHER = "other", "Другое"


class TicketStatus(models.TextChoices):
    NEW = "new", "Новое"
    ANSWERED = "answered", "Есть ответ"
    CLOSED = "closed", "Закрыто"


class SupportTicket(TimeStampedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="пользователь",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="support_tickets",
    )
    name = models.CharField("имя", max_length=100)
    email = models.EmailField("почта для ответа")
    topic = models.CharField("тема", max_length=20, choices=TicketTopic)
    subject = models.CharField("заголовок", max_length=150)
    message = models.TextField("сообщение", max_length=5000)
    status = models.CharField(
        "статус", max_length=10, choices=TicketStatus, default=TicketStatus.NEW
    )

    class Meta:
        verbose_name = "обращение"
        verbose_name_plural = "обращения"
        ordering = ("-created_at", "-pk")
        indexes = [
            models.Index(fields=["status", "-created_at"], name="ticket_status_idx"),
            models.Index(fields=["user", "-created_at"], name="ticket_user_idx"),
        ]

    def __str__(self):
        return f"№ {self.pk}: {self.subject}"


class TicketReply(models.Model):
    ticket = models.ForeignKey(
        SupportTicket, verbose_name="обращение", on_delete=models.CASCADE, related_name="replies"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="сотрудник",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    message = models.TextField("ответ", max_length=5000)
    created_at = models.DateTimeField("отправлен", auto_now_add=True)

    class Meta:
        verbose_name = "ответ поддержки"
        verbose_name_plural = "ответы поддержки"
        ordering = ("created_at", "pk")

    def __str__(self):
        return f"Ответ на обращение № {self.ticket_id}"
