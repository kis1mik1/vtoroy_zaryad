import pytest

from apps.catalog.models import (
    Attribute,
    AttributeKind,
    AttributeOption,
    Brand,
    DeviceModel,
    DeviceModelOption,
    DeviceModelSpec,
)
from apps.catalog.tests.factories import CategoryFactory


@pytest.fixture
def phones():
    parent = CategoryFactory(name="Телефоны", slug="phones-test")
    category = CategoryFactory(name="Смартфоны", slug="smartphones-test", parent=parent)
    storage = Attribute.objects.create(
        category=category,
        code="storage",
        name="Память",
        kind=AttributeKind.CHOICE,
        is_variant=True,
        is_required=True,
        in_title=True,
        sort_order=10,
    )
    ram = Attribute.objects.create(
        category=category,
        code="ram",
        name="Оперативная память",
        kind=AttributeKind.CHOICE,
        is_variant=True,
        sort_order=20,
    )
    color = Attribute.objects.create(
        category=category,
        code="color",
        name="Цвет",
        kind=AttributeKind.CHOICE,
        is_variant=True,
        in_title=True,
        sort_order=30,
    )
    screen = Attribute.objects.create(
        category=category,
        code="screen",
        name="Экран",
        kind=AttributeKind.NUMBER,
        unit="″",
        sort_order=40,
    )
    nfc = Attribute.objects.create(
        category=category,
        code="nfc",
        name="NFC",
        kind=AttributeKind.BOOLEAN,
        sort_order=50,
    )
    options = {
        value: AttributeOption.objects.create(attribute=storage, value=value, sort_order=i)
        for i, value in enumerate(["64 ГБ", "128 ГБ", "256 ГБ", "512 ГБ"])
    }
    ram4 = AttributeOption.objects.create(attribute=ram, value="4 ГБ")
    AttributeOption.objects.create(attribute=ram, value="6 ГБ")
    blue = AttributeOption.objects.create(attribute=color, value="синий")
    AttributeOption.objects.create(attribute=color, value="чёрный")

    apple = Brand.objects.create(name="Apple", slug="apple-test")
    apple.categories.add(category)
    other = Brand.objects.create(name="Nokia", slug="nokia-test")
    iphone = DeviceModel.objects.create(
        brand=apple, category=category, name="iPhone 13", slug="apple-iphone-13-test"
    )
    DeviceModelSpec.objects.create(device_model=iphone, attribute=screen, value_number="6.1")
    DeviceModelSpec.objects.create(device_model=iphone, attribute=nfc, value_bool=True)
    for value in ("128 ГБ", "256 ГБ"):
        DeviceModelOption.objects.create(device_model=iphone, option=options[value])
    DeviceModelOption.objects.create(device_model=iphone, option=ram4)
    return {
        "category": category,
        "apple": apple,
        "other_brand": other,
        "iphone": iphone,
        "storage": options,
        "blue": blue,
        "attributes": {
            "storage": storage,
            "ram": ram,
            "color": color,
            "screen": screen,
            "nfc": nfc,
        },
    }
