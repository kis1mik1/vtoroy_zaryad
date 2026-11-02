from datetime import timedelta

from django import forms
from django.core.paginator import Paginator
from django.utils import timezone

from .selectors import get_cities


class DemoForm(forms.Form):
    name = forms.CharField(label="Имя", max_length=50, help_text="Так вас увидят покупатели")
    email = forms.EmailField(label="Электронная почта")
    city = forms.ChoiceField(label="Город")
    condition = forms.ChoiceField(
        label="Состояние",
        choices=[("new", "Новое"), ("used", "Б/у")],
        widget=forms.RadioSelect,
    )
    description = forms.CharField(label="Описание", widget=forms.Textarea(attrs={"rows": 4}))
    agree = forms.BooleanField(label="Согласен с правилами размещения")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["city"].choices = [("", "Выберите город")] + [
            (city.slug, city.name) for city in get_cities()
        ]


def demo_page(request):
    return Paginator(range(240), 12).get_page(request.GET.get("page"))


def sample_dates():
    now = timezone.now()
    return [now, now - timedelta(days=1), now - timedelta(days=40), now - timedelta(days=400)]
