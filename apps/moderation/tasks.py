from celery import shared_task

from . import services


@shared_task(soft_time_limit=180, time_limit=240)
def check_ad(ad_id: int) -> str | None:
    check = services.run_auto_check(ad_id)
    return check.verdict if check else None
