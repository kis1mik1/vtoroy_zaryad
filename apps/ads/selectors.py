from dataclasses import dataclass

from django.db.models import (
    BooleanField,
    Case,
    ExpressionWrapper,
    F,
    FloatField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Value,
    When,
)
from django.utils import timezone

from .models import Ad, AdPhoto, AdStatus, PriceStat

MARKET_MIN_SAMPLE = 5
BELOW_MARKET = 0.9
ABOVE_MARKET = 1.1


@dataclass(frozen=True)
class MarketLabel:
    text: str
    tone: str


def _stat(field):
    return Subquery(
        PriceStat.objects.filter(
            device_model=OuterRef("device_model"),
            condition=OuterRef("condition"),
            price_key=OuterRef("price_key"),
            sample_size__gte=MARKET_MIN_SAMPLE,
        ).values(field)[:1]
    )


def with_market(queryset):
    return queryset.annotate(
        market_median=_stat("median"),
        market_p25=_stat("p25"),
        market_p75=_stat("p75"),
    ).annotate(
        market_ratio=ExpressionWrapper(
            F("price") * Value(1.0) / F("market_median"), output_field=FloatField()
        )
    )


def market_label(ad) -> MarketLabel | None:
    ratio = getattr(ad, "market_ratio", None)
    if ratio is None:
        return None
    if ratio < BELOW_MARKET:
        return MarketLabel("Ниже рынка", "success")
    if ratio > ABOVE_MARKET:
        return MarketLabel("Выше рынка", "warning")
    return MarketLabel("В рынке", "info")


def card_queryset(queryset=None):
    queryset = Ad.objects.visible() if queryset is None else queryset
    now = timezone.now()
    return with_market(
        queryset.select_related("city", "category", "device_model__brand")
        .prefetch_related(
            Prefetch(
                "photos",
                queryset=AdPhoto.objects.order_by("position", "pk"),
                to_attr="ordered_photos",
            )
        )
        .annotate(
            is_pinned=Case(
                When(pinned_until__gt=now, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
            is_highlighted=Case(
                When(highlighted_until__gt=now, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )
    )


SORTS = {
    "date": ("Сначала новые", ("-is_pinned", "-bumped_at", "-pk")),
    "price_asc": ("Дешевле", ("price", "-bumped_at")),
    "price_desc": ("Дороже", ("-price", "-bumped_at")),
    "market": ("Ниже рынка", (F("market_ratio").asc(nulls_last=True), "-bumped_at")),
}


def sort_queryset(queryset, sort: str, *, relevance: bool = False):
    if sort == "date" and relevance:
        return queryset.order_by("-is_pinned", "-relevance", "-bumped_at")
    return queryset.order_by(*SORTS.get(sort, SORTS["date"])[1])


def similar_ads(ad, limit: int = 8):
    low, high = int(ad.price * 0.7), int(ad.price * 1.3)
    queryset = Ad.objects.visible().exclude(pk=ad.pk).filter(price__range=(low, high))
    if ad.device_model_id:
        queryset = queryset.filter(
            Q(device_model_id=ad.device_model_id) | Q(category_id=ad.category_id)
        ).annotate(
            same_model=Case(
                When(device_model_id=ad.device_model_id, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
    else:
        queryset = queryset.filter(category_id=ad.category_id).annotate(
            same_model=Value(False, output_field=BooleanField())
        )
    queryset = queryset.annotate(
        same_city=Case(
            When(city_id=ad.city_id, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )
    )
    return list(card_queryset(queryset).order_by("-same_model", "-same_city", "-bumped_at")[:limit])


def can_view(ad, user) -> bool:
    if user.is_authenticated and user.is_staff:
        return True
    if ad.is_deleted:
        return False
    if user.is_authenticated and user.pk == ad.seller_id:
        return True
    seller_ok = ad.seller.is_active and not ad.seller.is_banned
    return seller_ok and ad.status in (AdStatus.ACTIVE, AdStatus.SOLD)
