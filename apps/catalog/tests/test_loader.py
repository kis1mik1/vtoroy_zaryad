import json
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.catalog.loader import generate_aliases
from apps.catalog.models import Attribute, Brand, Category, DeviceModel
from apps.catalog.selectors import get_category_tree, leaf_categories

pytestmark = pytest.mark.django_db

CATEGORIES = [
    {
        "name": "Телефоны",
        "slug": "phones",
        "icon": "smartphone",
        "children": [
            {
                "name": "Смартфоны",
                "slug": "smartphones",
                "battery": True,
                "screen": True,
                "attributes": [
                    {"code": "storage", "name": "Память", "kind": "choice",
                     "options": ["128 ГБ", "256 ГБ", "512 ГБ"], "variant": True, "required": True,
                     "in_title": True, "widget": "checkboxes"},
                    {"code": "screen", "name": "Экран", "kind": "number", "unit": "″",
                     "widget": "range"},
                    {"code": "nfc", "name": "NFC", "kind": "boolean", "widget": "toggle"},
                ],
            }
        ],
    }
]  # fmt: skip


def write_seed(root, models, brands=None):
    (root / "models").mkdir()
    (root / "categories.json").write_text(json.dumps(CATEGORIES, ensure_ascii=False))
    brands = brands or {"Apple": {"aliases": ["эпл"], "categories": []}}
    (root / "brands.json").write_text(json.dumps(brands, ensure_ascii=False))
    (root / "models" / "smartphones.json").write_text(
        json.dumps({"category": "smartphones", "brands": models}, ensure_ascii=False)
    )


IPHONE = {
    "name": "iPhone 13",
    "year": 2021,
    "specs": {"screen": 6.1, "nfc": True},
    "options": {"storage": ["128 ГБ", "256 ГБ"]},
}


def test_loads_tree_attributes_and_models(tmp_path):
    write_seed(tmp_path, {"Apple": [IPHONE]})

    call_command("load_catalog", path=str(tmp_path))

    smartphones = Category.objects.get(slug="smartphones")
    assert smartphones.parent.slug == "phones"
    assert smartphones.has_battery
    assert Attribute.objects.get(category=smartphones, code="storage").options.count() == 3

    model = DeviceModel.objects.get(name="iPhone 13")
    assert model.full_name == "Apple iPhone 13"
    assert model.slug == "apple-iphone-13"
    assert "айфон 13" in model.aliases
    specs = {spec.attribute.code: spec for spec in model.specs.all()}
    assert specs["screen"].value_number == Decimal("6.1")
    assert specs["nfc"].value_bool is True
    assert sorted(o.option.value for o in model.allowed_options.all()) == ["128 ГБ", "256 ГБ"]
    assert list(Brand.objects.get(name="Apple").categories.all()) == [smartphones]


def test_reload_is_idempotent_and_updates(tmp_path):
    write_seed(tmp_path, {"Apple": [IPHONE]})
    call_command("load_catalog", path=str(tmp_path))
    changed = {**IPHONE, "options": {"storage": ["512 ГБ"]}, "specs": {"screen": 6.1}}
    (tmp_path / "models" / "smartphones.json").write_text(
        json.dumps({"category": "smartphones", "brands": {"Apple": [changed]}}, ensure_ascii=False)
    )

    call_command("load_catalog", path=str(tmp_path))

    model = DeviceModel.objects.get(name="iPhone 13")
    assert DeviceModel.objects.count() == 1
    assert [o.option.value for o in model.allowed_options.all()] == ["512 ГБ"]
    assert [s.attribute.code for s in model.specs.all()] == ["screen"]


@pytest.mark.parametrize(
    ("models", "message"),
    [
        ({"Apple": [{**IPHONE, "options": {"storage": ["2 ТБ"]}}]}, "нет варианта «2 ТБ»"),
        ({"Apple": [{**IPHONE, "specs": {"weight": 170}}]}, "нет характеристики «weight»"),
        ({"Apple": [{**IPHONE, "options": {"nfc": ["да"]}}]}, "не выбирается продавцом"),
        ({"Nokia": [IPHONE]}, "бренд «Nokia» не описан"),
    ],
)
def test_invalid_seed_reports_clear_error(tmp_path, models, message):
    write_seed(tmp_path, models)

    with pytest.raises(CommandError, match=message):
        call_command("load_catalog", path=str(tmp_path))

    assert not DeviceModel.objects.exists()


def test_real_seed_loads():
    call_command("load_catalog")

    assert DeviceModel.objects.count() >= 300
    assert Category.objects.filter(parent__isnull=True).count() == 11
    leaves = leaf_categories()
    assert len(leaves) == 29
    assert all(not leaf.children.exists() for leaf in leaves)
    tree = get_category_tree()
    assert tree[0].category.name == "Телефоны"
    assert [c.name for c in tree[0].children] == ["Смартфоны", "Кнопочные телефоны"]


def test_generate_aliases():
    assert generate_aliases("iPhone 15 Pro Max") == ["айфон 15 про макс"]
    assert "пс5" in generate_aliases("PlayStation 5")
    assert generate_aliases("Z6 II") == []


def test_category_tree_limited_to_two_levels():
    from django.core.exceptions import ValidationError

    from .factories import CategoryFactory

    child = CategoryFactory(parent=CategoryFactory())
    grandchild = CategoryFactory.build(parent=child)

    with pytest.raises(ValidationError):
        grandchild.clean()
