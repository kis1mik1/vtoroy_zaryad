from dataclasses import dataclass, field

from django.core.cache import cache
from django.db.models import Prefetch

from .models import Attribute, AttributeOption, Brand, Category, DeviceModel

TREE_CACHE_KEY = "catalog:tree:v1"


@dataclass
class CategoryNode:
    category: Category
    children: list[Category] = field(default_factory=list)


def get_category_tree() -> list[CategoryNode]:
    tree = cache.get(TREE_CACHE_KEY)
    if tree is None:
        categories = list(Category.objects.filter(is_active=True))
        nodes = {c.pk: CategoryNode(c) for c in categories if c.parent_id is None}
        for category in categories:
            if category.parent_id in nodes:
                nodes[category.parent_id].children.append(category)
        tree = list(nodes.values())
        cache.set(TREE_CACHE_KEY, tree, 60 * 60)
    return tree


def leaf_categories() -> list[Category]:
    leaves = []
    for node in get_category_tree():
        leaves.extend(node.children or [node.category])
    return leaves


def get_leaf_category(pk) -> Category | None:
    return next((c for c in leaf_categories() if str(c.pk) == str(pk)), None)


def clear_catalog_cache() -> None:
    cache.delete(TREE_CACHE_KEY)


def brands_for(category: Category):
    return Brand.objects.filter(categories=category).order_by("name")


def models_for(category: Category, brand_id) -> list[DeviceModel]:
    return list(
        DeviceModel.objects.filter(category=category, brand_id=brand_id, is_active=True)
        .select_related("brand")
        .order_by("-release_year", "name")
    )


def attributes_for(category: Category) -> list[Attribute]:
    return list(
        Attribute.objects.filter(category=category).prefetch_related(
            Prefetch("options", queryset=AttributeOption.objects.order_by("sort_order", "pk"))
        )
    )


def model_with_specs(pk) -> DeviceModel | None:
    return (
        DeviceModel.objects.filter(pk=pk, is_active=True)
        .select_related("brand", "category")
        .prefetch_related("specs__option", "specs__attribute", "allowed_options__option")
        .first()
    )
