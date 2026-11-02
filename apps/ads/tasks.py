from celery import shared_task

from . import favorites, market, photos, saved_searches, services
from .models import Ad


@shared_task
def archive_stale_ads() -> int:
    return services.archive_stale()


@shared_task
def remove_orphan_photos() -> int:
    return photos.remove_orphans()


@shared_task
def notify_price_drop_task(ad_id: int, old_price: int, new_price: int) -> int:
    ad = Ad.objects.filter(pk=ad_id).first()
    return favorites.notify_price_drop(ad, old_price, new_price) if ad else 0


@shared_task
def recalculate_price_stats() -> int:
    return market.recalculate_price_stats()


@shared_task
def check_saved_searches() -> int:
    return saved_searches.check_saved_searches()
