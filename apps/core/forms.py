from django import forms
from django.forms.renderers import TemplatesSetting

from . import captcha
from .selectors import get_cities, get_cities_by_region


class FormRenderer(TemplatesSetting):
    form_template_name = "components/forms/form.html"
    field_template_name = "components/forms/field.html"


def _city_choices():
    return [
        ("", "Выберите город"),
        *[
            (region, [(city.pk, city.name) for city in cities])
            for region, cities in get_cities_by_region()
        ],
    ]


class CityChoiceField(forms.ChoiceField):
    def __init__(self, **kwargs):
        kwargs.setdefault("label", "Город")
        super().__init__(choices=_city_choices, **kwargs)

    def prepare_value(self, value):
        return getattr(value, "pk", value)

    def to_python(self, value):
        value = super().to_python(value)
        if value in self.empty_values:
            return None
        return next((city for city in get_cities() if str(city.pk) == value), value)

    def valid_value(self, value):
        return any(city.pk == getattr(value, "pk", None) for city in get_cities())


class CaptchaMixin:
    captcha_message = "Подтвердите, что вы не робот."

    def validate_captcha(self, ip: str) -> None:
        if not captcha.verify(self.data.get(captcha.TOKEN_FIELD, ""), ip):
            raise forms.ValidationError(self.captcha_message, code="captcha")
