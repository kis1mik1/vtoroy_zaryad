from datetime import timedelta

from django.db import transaction
from django.db.models import Aggregate, Count, FloatField
from django.utils import timezone

from .models import Ad, AdStatus, PriceStat
from .selectors import MARKET_MIN_SAMPLE

WINDOW = timedelta(days=180)


class PercentileCont(Aggregate):
    function = "PERCENTILE_CONT"
    template = "%(function)s(%(percentile)s) WITHIN GROUP (ORDER BY %(expressions)s)"
    output_field = FloatField()

    def __init__(self, expression, percentile: float, **extra):
        if not 0 <= percentile <= 1:
            raise ValueError("Перцентиль должен быть от 0 до 1")
        super().__init__(expression, percentile=float(percentile), **extra)


@transaction.atomic
def recalculate_price_stats() -> int:
    rows = (
        Ad.objects.filter(
            is_deleted=False,
            device_model__isnull=False,
            status__in=(AdStatus.ACTIVE, AdStatus.SOLD),
            updated_at__gte=timezone.now() - WINDOW,
        )
        .values("device_model_id", "condition", "price_key")
        .annotate(
            p25=PercentileCont("price", 0.25),
            median=PercentileCont("price", 0.5),
            p75=PercentileCont("price", 0.75),
            sample_size=Count("pk"),
        )
    )
    kept = []
    for row in rows:
        stat, _ = PriceStat.objects.update_or_create(
            device_model_id=row["device_model_id"],
            condition=row["condition"],
            price_key=row["price_key"],
            defaults={
                "key_option_id": row["price_key"] or None,
                "p25": round(row["p25"]),
                "median": round(row["median"]),
                "p75": round(row["p75"]),
                "sample_size": row["sample_size"],
            },
        )
        kept.append(stat.pk)
    PriceStat.objects.exclude(pk__in=kept).delete()
    return len(kept)


def price_hint(device_model, condition: str, price_key: int) -> PriceStat | None:
    if device_model is None or not condition:
        return None
    return (
        PriceStat.objects.filter(
            device_model=device_model,
            condition=condition,
            price_key=price_key or 0,
            sample_size__gte=MARKET_MIN_SAMPLE,
        )
        .select_related("key_option")
        .first()
    )
