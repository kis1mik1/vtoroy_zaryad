from celery import shared_task

from . import services
from .gateway import GatewayError
from .models import Payment


@shared_task(autoretry_for=(GatewayError,), retry_backoff=30, max_retries=5)
def sync_payment(payment_id: int) -> str:
    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None:
        return "missing"
    return services.sync_payment(payment).status


@shared_task
def sync_pending_payments() -> int:
    return services.sync_pending()


@shared_task
def expire_promotions() -> int:
    return services.expire_promotions()
