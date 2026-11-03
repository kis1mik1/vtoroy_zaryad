from django import forms

from apps.core.forms import CaptchaMixin

from .models import TicketTopic


class ContactForm(CaptchaMixin, forms.Form):
    name = forms.CharField(label="Имя", max_length=100)
    email = forms.EmailField(
        label="Почта для ответа", widget=forms.EmailInput(attrs={"autocomplete": "email"})
    )
    topic = forms.ChoiceField(label="Тема", choices=TicketTopic.choices)
    subject = forms.CharField(
        label="Коротко о проблеме",
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "Например, не пришло письмо после оплаты"}),
    )
    message = forms.CharField(
        label="Подробности",
        min_length=20,
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Номер объявления или платежа и что вы уже пробовали — так ответим быстрее.",
        error_messages={"min_length": "Опишите проблему чуть подробнее."},
    )

    def __init__(self, *args, user=None, ip="", **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.ip = ip
        if user is not None and user.is_authenticated:
            del self.fields["name"]
            del self.fields["email"]

    def clean(self):
        cleaned = super().clean()
        self.validate_captcha(self.ip)
        if self.user is not None and self.user.is_authenticated:
            cleaned["name"] = self.user.first_name
            cleaned["email"] = self.user.email
        return cleaned
