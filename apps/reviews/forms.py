from django import forms

from .models import RATING_LABELS, AuthorRole


class ReviewForm(forms.Form):
    rating = forms.TypedChoiceField(
        label="Оценка",
        choices=[(stars, label) for stars, label in RATING_LABELS.items()],
        coerce=int,
        widget=forms.RadioSelect,
        error_messages={"required": "Поставьте оценку."},
    )
    text = forms.CharField(
        label="Отзыв",
        min_length=10,
        max_length=2000,
        widget=forms.Textarea(
            attrs={"rows": 5, "placeholder": "Как прошла сделка, соответствовал ли товар описанию"}
        ),
        error_messages={"min_length": "Напишите хотя бы пару предложений."},
    )


class ReplyForm(forms.Form):
    text = forms.CharField(
        label="Ответ",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Ваш ответ увидят все"}),
    )


class ReportForm(forms.Form):
    reason = forms.CharField(
        label="Что не так с отзывом?",
        max_length=500,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Например, сделки не было или в отзыве оскорбления"}
        ),
    )


class HideForm(forms.Form):
    reason = forms.CharField(
        label="Причина",
        max_length=300,
        help_text="Автор увидит причину в уведомлении.",
    )


ROLE_FILTERS = (
    ("", "Все"),
    (AuthorRole.BUYER, "От покупателей"),
    (AuthorRole.SELLER, "От продавцов"),
)
