import ipaddress
import logging
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from yookassa import Configuration
from yookassa import Payment as YooPayment
from yookassa.domain.common import SecurityHelper

logger = logging.getLogger(__name__)

CURRENCY = "RUB"


class GatewayError(Exception):
    pass


@dataclass(frozen=True)
class RemotePayment:
    id: str
    status: str
    paid: bool
    amount: Decimal
    currency: str
    confirmation_url: str = ""
    cancellation_reason: str = ""
    test: bool = False
    metadata: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def is_configured() -> bool:
    return bool(settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY)


def is_test_shop() -> bool:
    return settings.YOOKASSA_SECRET_KEY.startswith("test_")


def is_trusted_ip(ip: str) -> bool:
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(
        address in ipaddress.ip_network(network) for network in SecurityHelper.YOOKASSA_NETWORKS
    )


def _configure() -> None:
    if not is_configured():
        raise GatewayError("ЮKassa не настроена: нет YOOKASSA_SHOP_ID или YOOKASSA_SECRET_KEY.")
    Configuration.configure(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)


def _parse(response) -> RemotePayment:
    confirmation = getattr(response, "confirmation", None)
    cancellation = getattr(response, "cancellation_details", None)
    return RemotePayment(
        id=response.id,
        status=response.status,
        paid=bool(response.paid),
        amount=Decimal(str(response.amount.value)),
        currency=response.amount.currency,
        confirmation_url=getattr(confirmation, "confirmation_url", "") or "",
        cancellation_reason=getattr(cancellation, "reason", "") or "",
        test=bool(getattr(response, "test", False)),
        metadata=dict(response.metadata or {}),
        raw=dict(response),
    )


def create_payment(
    *, amount: int, description: str, return_url: str, idempotence_key: str, metadata: dict
) -> RemotePayment:
    _configure()
    params = {
        "amount": {"value": f"{amount}.00", "currency": CURRENCY},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description[:128],
        "metadata": metadata,
    }
    try:
        response = YooPayment.create(params, idempotence_key)
    except Exception as exc:
        logger.warning("ЮKassa: не удалось создать платёж %s: %r", idempotence_key, exc)
        raise GatewayError("Платёжная система не ответила. Попробуйте ещё раз.") from exc
    return _parse(response)


def fetch_payment(payment_id: str) -> RemotePayment:
    _configure()
    try:
        response = YooPayment.find_one(payment_id)
    except Exception as exc:
        logger.warning("ЮKassa: не удалось получить платёж %s: %r", payment_id, exc)
        raise GatewayError("Не удалось узнать статус платежа.") from exc
    return _parse(response)
