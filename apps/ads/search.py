import re

from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramWordSimilarity,
)
from django.db.models import F, FloatField, Value
from django.db.models.functions import Coalesce

from .models import Ad

CONFIG = "russian"
MIN_SIMILARITY = 0.5
MAX_FUZZY_TOKENS = 5


def _join(*parts) -> str:
    return " ".join(str(part) for part in parts if part)


def index_ad(ad: Ad) -> None:
    ad = (
        Ad.objects.select_related("category__parent", "brand", "device_model__brand")
        .prefetch_related("attribute_values__option", "attribute_values__attribute")
        .get(pk=ad.pk)
    )
    model = ad.device_model
    brand = model.brand if model else ad.brand
    names = _join(
        ad.title,
        model.full_name if model else ad.custom_model_name,
        " ".join(model.aliases) if model else "",
        brand.name if brand else "",
        " ".join(brand.aliases) if brand else "",
    )
    values = sorted(ad.attribute_values.all(), key=lambda v: v.attribute.sort_order)
    details = _join(
        ad.category.name,
        ad.category.parent.name if ad.category.parent_id else "",
        " ".join(value.display for value in values),
    )
    price_key = next((v.option_id for v in values if v.attribute.is_price_key and v.option_id), 0)
    vector = (
        SearchVector(Value(names), weight="A", config=CONFIG)
        + SearchVector(Value(details), weight="B", config=CONFIG)
        + SearchVector(Value(ad.description), weight="C", config=CONFIG)
    )
    Ad.objects.filter(pk=ad.pk).update(
        search_vector=vector,
        search_text=normalize(_join(names, details)),
        price_key=price_key,
    )


def normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[^\w+]+", " ", text)).strip()


def apply_query(queryset, raw: str):
    text = normalize(raw)
    if not text:
        return queryset
    query = SearchQuery(text, search_type="websearch", config=CONFIG)
    exact = queryset.filter(search_vector=query).annotate(
        relevance=Coalesce(
            SearchRank(F("search_vector"), query), Value(0.0), output_field=FloatField()
        )
    )
    if exact.exists():
        return exact
    tokens = text.split()[:MAX_FUZZY_TOKENS]
    fuzzy = queryset
    for index, token in enumerate(tokens):
        name = f"similarity_{index}"
        fuzzy = fuzzy.annotate(**{name: TrigramWordSimilarity(token, "search_text")}).filter(
            **{f"{name}__gte": MIN_SIMILARITY}
        )
    similarities = [F(f"similarity_{index}") for index in range(len(tokens))]
    return fuzzy.annotate(relevance=sum(similarities[1:], similarities[0]) / len(tokens))
