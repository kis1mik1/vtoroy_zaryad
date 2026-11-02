import json
import re
from decimal import Decimal
from pathlib import Path

from django.db import transaction

from apps.core.text import slugify_ru

from .models import (
    Attribute,
    AttributeKind,
    AttributeOption,
    Brand,
    Category,
    DeviceModel,
    DeviceModelOption,
    DeviceModelSpec,
)

WORD_ALIASES = {
    "iphone": ["айфон"],
    "ipad": ["айпад"],
    "macbook": ["макбук"],
    "imac": ["аймак"],
    "airpods": ["аирподс", "эйрподс"],
    "galaxy": ["галакси"],
    "redmi": ["редми"],
    "poco": ["поко"],
    "note": ["ноут"],
    "pro": ["про"],
    "max": ["макс"],
    "plus": ["плюс"],
    "mini": ["мини"],
    "ultra": ["ультра"],
    "air": ["эйр"],
    "lite": ["лайт"],
    "playstation": ["плейстейшн", "пс"],
    "xbox": ["иксбокс"],
    "switch": ["свитч"],
    "pixel": ["пиксель"],
    "watch": ["вотч"],
    "band": ["бэнд"],
    "buds": ["бадс"],
    "steam": ["стим"],
    "deck": ["дек"],
    "geforce": ["джифорс"],
    "rtx": ["ртх"],
    "gtx": ["гтх"],
    "radeon": ["радеон"],
    "ryzen": ["райзен"],
    "dualsense": ["дуалсенс"],
    "kindle": ["киндл"],
}


class CatalogError(Exception):
    pass


def generate_aliases(full_name: str) -> list[str]:
    tokens = re.findall(r"[\w+]+", full_name.lower())
    variants = [[]]
    for token in tokens:
        token = "плюс" if token == "+" else token
        choices = WORD_ALIASES.get(token, [token])
        variants = [[*v, c] for v in variants for c in choices][:8]
    aliases = []
    for words in variants:
        text = " ".join(words)
        if text != " ".join(tokens) and re.search("[а-я]", text):
            aliases.append(text)
            if "пс" in words:
                aliases.append(text.replace("пс ", "пс"))
    return list(dict.fromkeys(aliases))


class CatalogLoader:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.stats = {"categories": 0, "attributes": 0, "brands": 0, "models": 0}
        self.categories: dict[str, Category] = {}
        self.attributes: dict[tuple[int, str], Attribute] = {}

    @transaction.atomic
    def run(self) -> dict:
        self.load_categories(json.loads((self.root / "categories.json").read_text()))
        brands = self.load_brands(json.loads((self.root / "brands.json").read_text()))
        for path in sorted((self.root / "models").glob("*.json")):
            self.load_models(json.loads(path.read_text()), brands, path.name)
        return self.stats

    def load_categories(self, tree):
        for order, node in enumerate(tree, start=1):
            parent = self._category(node, None, order)
            for child_order, child in enumerate(node.get("children", []), start=1):
                self._category(child, parent, child_order)

    def _category(self, node, parent, order):
        category, _ = Category.objects.update_or_create(
            slug=node["slug"],
            defaults={
                "parent": parent,
                "name": node["name"],
                "icon": node.get("icon", ""),
                "seo_description": node.get("seo", ""),
                "sort_order": order * 10,
                "is_active": True,
                "has_battery": node.get("battery", False),
                "has_screen": node.get("screen", False),
            },
        )
        self.categories[category.slug] = category
        self.stats["categories"] += 1
        for attr_order, data in enumerate(node.get("attributes", []), start=1):
            self._attribute(category, data, attr_order)
        return category

    def _attribute(self, category, data, order):
        attribute, _ = Attribute.objects.update_or_create(
            category=category,
            code=data["code"],
            defaults={
                "name": data["name"],
                "kind": data["kind"],
                "unit": data.get("unit", ""),
                "is_required": data.get("required", False),
                "is_variant": data.get("variant", False),
                "is_filterable": data.get("filter", False),
                "is_price_key": data.get("price_key", False),
                "in_title": data.get("in_title", False),
                "filter_widget": data["widget"],
                "sort_order": order * 10,
            },
        )
        for option_order, value in enumerate(data.get("options", []), start=1):
            AttributeOption.objects.update_or_create(
                attribute=attribute, value=value, defaults={"sort_order": option_order * 10}
            )
        self.attributes[(category.pk, attribute.code)] = attribute
        self.stats["attributes"] += 1

    def load_brands(self, data) -> dict[str, Brand]:
        brands = {}
        for name, info in data.items():
            brand, _ = Brand.objects.update_or_create(
                name=name,
                defaults={
                    "slug": slugify_ru(name) or name.lower(),
                    "aliases": info.get("aliases", []),
                },
            )
            brand.categories.add(*[self._get_category(slug) for slug in info.get("categories", [])])
            brands[name] = brand
            self.stats["brands"] += 1
        return brands

    def _get_category(self, slug) -> Category:
        if slug not in self.categories:
            raise CatalogError(f"Неизвестная категория «{slug}»")
        return self.categories[slug]

    def load_models(self, data, brands, source):
        category = self._get_category(data["category"])
        for brand_name, models in data["brands"].items():
            if brand_name not in brands:
                raise CatalogError(f"{source}: бренд «{brand_name}» не описан в brands.json")
            brand = brands[brand_name]
            brand.categories.add(category)
            for item in models:
                self._device_model(category, brand, item, source)

    def _device_model(self, category, brand, item, source):
        model = DeviceModel(brand=brand, category=category, name=item["name"])
        slug = slugify_ru(model.full_name.replace("+", " plus"), max_length=180)
        if (
            DeviceModel.objects.filter(slug=slug)
            .exclude(brand=brand, category=category, name=item["name"])
            .exists()
        ):
            slug = f"{slug}-{category.slug}"
        model, _ = DeviceModel.objects.update_or_create(
            brand=brand,
            category=category,
            name=item["name"],
            defaults={
                "slug": slug,
                "release_year": item.get("year"),
                "aliases": list(
                    dict.fromkeys(item.get("aliases", []) + generate_aliases(item["name"]))
                ),
                "is_active": True,
            },
        )
        self._specs(model, category, item.get("specs", {}), source)
        self._options(model, category, item.get("options", {}), source)
        self.stats["models"] += 1

    def _attr(self, category, code, source) -> Attribute:
        key = (category.pk, code)
        if key not in self.attributes:
            raise CatalogError(
                f"{source}: у категории «{category.name}» нет характеристики «{code}»"
            )
        return self.attributes[key]

    def _option(self, attribute, value, source) -> AttributeOption:
        option = AttributeOption.objects.filter(attribute=attribute, value=value).first()
        if option is None:
            raise CatalogError(
                f"{source}: нет варианта «{value}» у характеристики «{attribute.name}»"
            )
        return option

    def _specs(self, model, category, specs, source):
        kept = []
        for code, value in specs.items():
            attribute = self._attr(category, code, source)
            defaults = {"option": None, "value_number": None, "value_bool": None}
            if attribute.kind == AttributeKind.CHOICE:
                defaults["option"] = self._option(attribute, value, source)
            elif attribute.kind == AttributeKind.NUMBER:
                defaults["value_number"] = Decimal(str(value))
            else:
                defaults["value_bool"] = bool(value)
            DeviceModelSpec.objects.update_or_create(
                device_model=model, attribute=attribute, defaults=defaults
            )
            kept.append(attribute.pk)
        DeviceModelSpec.objects.filter(device_model=model).exclude(attribute_id__in=kept).delete()

    def _options(self, model, category, options, source):
        kept = []
        for code, values in options.items():
            attribute = self._attr(category, code, source)
            if not attribute.is_variant:
                raise CatalogError(f"{source}: «{attribute.name}» не выбирается продавцом")
            for value in values:
                option = self._option(attribute, value, source)
                DeviceModelOption.objects.get_or_create(device_model=model, option=option)
                kept.append(option.pk)
        DeviceModelOption.objects.filter(device_model=model).exclude(option_id__in=kept).delete()
