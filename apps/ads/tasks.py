from celery import shared_task

from . import photos, services


@shared_task
def archive_stale_ads() -> int:
    return services.archive_stale()


@shared_task
def remove_orphan_photos() -> int:
    return photos.remove_orphans()
