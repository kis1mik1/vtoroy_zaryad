import logging
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from apps.ads.models import Ad, AdStatus
from apps.core.ratelimit import Rate, hit
from apps.core.text import format_day
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify

from . import gateway
from .models import Payment, PaymentStatus, PromotionTariff

logger = logging.getLogger(__name__)

PAYMENT_RATE = Rate(limit=10, period=60 * 60)
REUSE_WINDOW = timedelta(hours=1)
SYNC_AFTER = timedelta(minutes=2)
FORGET_UNSENT_AFTER = timedelta(days=1)
REMOTE_STATUSES = {
    "pending": PaymentStatus.PENDING,
    "waiting_for_capture": PaymentStatus.PENDING,
    "succeeded": PaymentStatus.SUCCEEDED,
    "canceled": PaymentStatus.CANCELED,
}
CANCELLATION_REASONS = {
    "3d_secure_failed": "Не пройдена проверка 3-D Secure.",
    "call_issuer": "Банк отклонил оплату. Уточните причину в банке.",
    "canceled_by_merchant": "Платёж отменён.",
    "card_expired": "Истёк срок действия карты.",
    "country_forbidden": "Оплата картой этой страны недоступна.",
    "expired_on_confirmation": "Время на оплату истекло.",
    "fraud_suspected": "Платёж заблокирован из-за подозрения в мошенничестве.",
    "general_decline": "Банк отклонил платёж.",
    "identification_required": "Кошелёк ЮMoney не идентифицирован.",
    "insufficient_funds": "Недостаточно денег на карте.",
    "internal_timeout": "Технический сбой в платёжной системе. Попробуйте ещё раз.",
    "invalid_card_number": "Неверный номер карты.",
    "invalid_csc": "Неверный код CVC.",
    "issuer_unavailable": "Банк не отвечает. Попробуйте позже.",
    "payment_method_limit_exceeded": "Превышен лимит платежей.",
    "payment_method_restricted": "Этот способ оплаты недоступен.",
}
DEFAULT_CANCELLATION = "Платёж не прошёл."
UNSENT_CANCELLATION = "Платёж не был создан в платёжной системе."


class PaymentError(Exception):
    pass


def _ad_url(ad: Ad) -> str:
    return reverse("ads:detail", args=[ad.pk, ad.slug])


def _description(tariff: PromotionTariff, ad: Ad) -> str:
    return f"«{tariff.title}» для объявления № {ad.pk}: {ad.title}"[:128]


def ensure_can_promote(ad: Ad, user) -> None:
    if ad.seller_id != user.pk:
        raise PaymentError("Продвигать можно только свои объявления.")
    if ad.is_deleted or ad.status != AdStatus.ACTIVE:
        raise PaymentError("Продвинуть можно только опубликованное объявление.")


def _reusable_payment(ad: Ad, user, tariff: PromotionTariff) -> Payment | None:
    candidate = (
        Payment.objects.filter(
            user=user,
            ad=ad,
            tariff=tariff,
            amount=tariff.price,
            status=PaymentStatus.PENDING,
            created_at__gte=timezone.now() - REUSE_WINDOW,
        )
        .order_by("-created_at")
        .first()
    )
    if candidate is None or not candidate.provider_payment_id:
        return candidate
    candidate = sync_payment(candidate)
    return candidate if candidate.is_pending and candidate.confirmation_url else None


def start_payment(ad: Ad, user, tariff: PromotionTariff, *, site_url: str) -> Payment:
    ensure_can_promote(ad, user)
    if not gateway.is_configured():
        raise PaymentError("Оплата временно недоступна. Попробуйте позже.")
    if not tariff.is_active:
        raise PaymentError("Этот тариф больше недоступен.")
    payment = _reusable_payment(ad, user, tariff)
    if payment is None:
        hit("payment-create", f"user:{user.pk}", PAYMENT_RATE)
        payment = Payment.objects.create(
            user=user,
            ad=ad,
            tariff=tariff,
            amount=tariff.price,
            description=_description(tariff, ad),
        )
    if payment.provider_payment_id:
        return payment

    remote = gateway.create_payment(
        amount=payment.amount,
        description=payment.description,
        return_url=f"{site_url}{reverse('payments:return', args=[payment.pk])}",
        idempotence_key=str(payment.idempotence_key),
        metadata={"payment_id": str(payment.pk), "ad_id": str(ad.pk)},
    )
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        payment.provider_payment_id = remote.id
        payment.confirmation_url = remote.confirmation_url
        payment.is_test = remote.test
        payment.save(
            update_fields=["provider_payment_id", "confirmation_url", "is_test", "updated_at"]
        )
    return apply_remote(payment.pk, remote)


def sync_payment(payment: Payment) -> Payment:
    if not payment.is_pending or not payment.provider_payment_id:
        return payment
    return apply_remote(payment.pk, gateway.fetch_payment(payment.provider_payment_id))


def _matches(payment: Payment, remote: gateway.RemotePayment) -> bool:
    return (
        remote.id == payment.provider_payment_id
        and remote.amount == Decimal(payment.amount)
        and remote.currency == gateway.CURRENCY
        and remote.metadata.get("payment_id") == str(payment.pk)
    )


@transaction.atomic
def apply_remote(payment_id: int, remote: gateway.RemotePayment) -> Payment:
    payment = (
        Payment.objects.select_for_update(of=("self",))
        .select_related("tariff", "user")
        .get(pk=payment_id)
    )
    payment.last_event = remote.raw
    payment.last_checked_at = timezone.now()
    fields = ["last_event", "last_checked_at", "updated_at"]
    status = REMOTE_STATUSES.get(remote.status, PaymentStatus.PENDING)

    if payment.is_pending and status != PaymentStatus.PENDING:
        if not _matches(payment, remote):
            logger.error("ЮKassa: данные платежа %s не совпадают с ответом API", payment.pk)
            payment.save(update_fields=fields)
            return payment
        payment.status = status
        fields.append("status")
        if status == PaymentStatus.SUCCEEDED:
            payment.paid_at = timezone.now()
            fields += ["paid_at", "applied_at"]
            _promote(payment)
        else:
            payment.cancellation_reason = CANCELLATION_REASONS.get(
                remote.cancellation_reason, DEFAULT_CANCELLATION
            )
            fields.append("cancellation_reason")
    payment.save(update_fields=fields)
    return payment


def _extend(current, now, days: int):
    return max(current or now, now) + timedelta(days=days)


def _promote(payment: Payment) -> None:
    ad = Ad.objects.select_for_update().filter(pk=payment.ad_id).first()
    if ad is None:
        return
    now = timezone.now()
    tariff = payment.tariff
    fields = ["updated_at"]
    done = []
    if tariff.pin_days:
        ad.pinned_until = _extend(ad.pinned_until, now, tariff.pin_days)
        fields.append("pinned_until")
        done.append(f"закреплено до {_moment(ad.pinned_until)}")
    if tariff.highlight_days:
        ad.highlighted_until = _extend(ad.highlighted_until, now, tariff.highlight_days)
        fields.append("highlighted_until")
        done.append(f"выделено до {_moment(ad.highlighted_until)}")
    if tariff.bump:
        ad.bumped_at = now
        fields.append("bumped_at")
        done.append("поднято наверх ленты")
    ad.save(update_fields=fields)
    payment.applied_at = now
    notify(
        payment.user,
        NotificationKind.PAYMENT,
        f"Оплата прошла: «{tariff.title}» — {payment.amount} ₽",
        f"Объявление «{ad.title}»: {', '.join(done)}.",
        url=_ad_url(ad),
    )


def _moment(value) -> str:
    local = timezone.localtime(value)
    return f"{format_day(local.date())}, {local:%H:%M}"


def sync_pending() -> int:
    now = timezone.now()
    Payment.objects.filter(
        status=PaymentStatus.PENDING,
        provider_payment_id__isnull=True,
        created_at__lt=now - FORGET_UNSENT_AFTER,
    ).update(status=PaymentStatus.CANCELED, cancellation_reason=UNSENT_CANCELLATION, updated_at=now)

    synced = 0
    pending = Payment.objects.filter(
        Q(last_checked_at__isnull=True) | Q(last_checked_at__lt=now - SYNC_AFTER),
        status=PaymentStatus.PENDING,
        provider_payment_id__isnull=False,
        created_at__lt=now - SYNC_AFTER,
    )
    for payment in pending.iterator():
        try:
            sync_payment(payment)
        except gateway.GatewayError:
            continue
        synced += 1
    return synced


def expire_promotions() -> int:
    now = timezone.now()
    ads = Ad.objects.filter(Q(pinned_until__lte=now) | Q(highlighted_until__lte=now))
    expired = 0
    for ad in ads.select_related("seller"):
        ended = []
        if Ad.objects.filter(pk=ad.pk, pinned_until__lte=now).update(pinned_until=None):
            ended.append("закрепление")
        if Ad.objects.filter(pk=ad.pk, highlighted_until__lte=now).update(highlighted_until=None):
            ended.append("выделение")
        if not ended:
            continue
        expired += 1
        if ad.status == AdStatus.ACTIVE and not ad.is_deleted:
            notify(
                ad.seller,
                NotificationKind.PAYMENT,
                f"Закончилось {' и '.join(ended)}: {ad.title}",
                "Продлите продвижение, чтобы объявление оставалось заметным.",
                url=reverse("payments:promote", args=[ad.pk]),
                email=False,
            )
    return expired
