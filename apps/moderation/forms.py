from datetime import timedelta

from django import forms
from django.utils import timezone

from .models import ComplaintReason, RejectionReason
from .services import rejection_message

BAN_TERMS = (
    ("1", "1 день"),
    ("3", "3 дня"),
    ("7", "Неделя"),
    ("30", "Месяц"),
    ("forever", "Навсегда"),
)
BAN_REASONS = (
    "Мошенничество",
    "Продажа запрещённых товаров",
    "Оскорбления и угрозы",
    "Спам и повторяющиеся объявления",
)
OTHER_REASON = "other"


class RejectForm(forms.Form):
    reason = forms.ChoiceField(
        label="Причина", choices=RejectionReason.choices, widget=forms.RadioSelect
    )
    comment = forms.CharField(
        label="Пояснение для продавца",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="Продавец увидит причину и пояснение в уведомлении и в «Моих объявлениях».",
    )

    def clean(self):
        cleaned = super().clean()
        comment = cleaned.get("comment", "").strip()
        if cleaned.get("reason") == RejectionReason.OTHER and not comment:
            self.add_error("comment", "Опишите причину, чтобы продавец понял, что исправить.")
        return cleaned

    @property
    def message(self) -> str:
        return rejection_message(self.cleaned_data["reason"], self.cleaned_data["comment"])


class ComplaintForm(forms.Form):
    reason = forms.ChoiceField(label="Что не так?", widget=forms.RadioSelect)
    comment = forms.CharField(
        label="Подробности",
        required=False,
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Что вас насторожило"}),
    )

    def __init__(self, *args, reasons=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reason"].choices = [(reason.value, reason.label) for reason in reasons]

    def clean(self):
        cleaned = super().clean()
        comment = cleaned.get("comment", "").strip()
        if cleaned.get("reason") == ComplaintReason.OTHER and not comment:
            self.add_error("comment", "Расскажите, что случилось.")
        return cleaned


class BanForm(forms.Form):
    reason = forms.ChoiceField(
        label="Причина",
        choices=[(reason, reason) for reason in BAN_REASONS] + [(OTHER_REASON, "Другая")],
        widget=forms.RadioSelect,
    )
    term = forms.ChoiceField(label="Срок", choices=BAN_TERMS, initial="7")
    comment = forms.CharField(
        label="Пояснение",
        required=False,
        max_length=300,
        help_text="Пользователь увидит причину на странице блокировки и в письме.",
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("reason") == OTHER_REASON and not cleaned.get("comment", "").strip():
            self.add_error("comment", "Опишите причину блокировки.")
        return cleaned

    @property
    def reason_text(self) -> str:
        reason, comment = self.cleaned_data["reason"], self.cleaned_data["comment"].strip()
        if reason == OTHER_REASON:
            return comment
        return f"{reason}. {comment}" if comment else reason

    @property
    def until(self):
        term = self.cleaned_data["term"]
        if term == "forever":
            return None
        return timezone.now() + timedelta(days=int(term))
