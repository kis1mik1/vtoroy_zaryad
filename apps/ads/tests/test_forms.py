from decimal import Decimal

import pytest

from apps.ads.forms import AdForm, AttributesForm, ConditionForm
from apps.core.models import City

pytestmark = pytest.mark.django_db


def test_model_specs_are_fixed_and_variants_restricted(phones):
    form = AttributesForm(phones["category"], phones["iphone"])

    fixed = {value.attribute.code: value.display for value in form.fixed}
    assert fixed == {"screen": "6,1″", "nfc": "есть", "ram": "4 ГБ"}
    storage_choices = [label for _, label in form.fields["attr_storage"].choices]
    assert storage_choices == ["Не выбрано", "128 ГБ", "256 ГБ"]
    assert "attr_screen" not in form.fields


def test_option_outside_model_variants_rejected(phones):
    form = AttributesForm(
        phones["category"], phones["iphone"], {"attr_storage": phones["storage"]["512 ГБ"].pk}
    )

    assert not form.is_valid()
    assert "attr_storage" in form.errors


def test_custom_model_fills_all_attributes(phones):
    data = {
        "attr_storage": phones["storage"]["64 ГБ"].pk,
        "attr_screen": "6,5",
        "attr_nfc": "no",
    }
    form = AttributesForm(phones["category"], None, data)

    assert form.is_valid(), form.errors
    values = {value.attribute.code: value for value in form.values()}
    assert values["storage"].option == phones["storage"]["64 ГБ"]
    assert values["screen"].number == Decimal("6.5")
    assert values["nfc"].flag is False


def ad_data(phones, **overrides):
    return {
        "category": phones["category"].pk,
        "brand": phones["apple"].pk,
        "device_model": phones["iphone"].pk,
        "description": "Пользовался аккуратно, всё работает исправно.",
        "price": "38 500 ₽",
        "condition": "used",
        "city": City.objects.get(slug="vladivostok").pk,
        **overrides,
    }


def test_ad_form_parses_price_and_model(phones):
    form = AdForm(ad_data(phones))

    assert form.is_valid(), form.errors
    assert form.cleaned_data["price"] == 38_500
    assert form.cleaned_data["device_model"] == phones["iphone"]


def test_ad_form_requires_model_or_name(phones):
    form = AdForm(ad_data(phones, device_model="other"))

    assert "custom_model_name" in form.errors


def test_ad_form_rejects_brand_from_other_category(phones):
    form = AdForm(ad_data(phones, brand=phones["other_brand"].pk, device_model="other"))

    assert "brand" in form.errors


@pytest.mark.parametrize("price", ["0", "10000001", "дорого"])
def test_ad_form_price_limits(phones, price):
    assert "price" in AdForm(ad_data(phones, price=price)).errors


def test_short_description_rejected(phones):
    assert "description" in AdForm(ad_data(phones, description="Норм")).errors


def test_condition_form_requires_used_details(phones):
    form = ConditionForm(
        {"everything_works": "", "was_repaired": "on"},
        condition="used",
        category=phones["category"],
    )

    assert not form.is_valid()
    assert set(form.errors) == {"screen_state", "body_state", "issues", "repair_note"}


def test_condition_form_new_item_ignores_used_fields(phones):
    form = ConditionForm(
        {"is_sealed": "on", "body_state": "damaged", "battery_health": "50"},
        condition="new",
        category=phones["category"],
    )

    assert form.is_valid(), form.errors
    report = form.report_data()
    assert report["is_sealed"] is True
    assert report["body_state"] == ""
    assert report["battery_health"] is None
