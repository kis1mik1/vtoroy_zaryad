import json
from datetime import timedelta

import pytest
from django.core import mail
from django.core.checks import run_checks
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.ads.models import Ad, AdStatus
from apps.ads.tests.factories import AdFactory
from apps.notifications.models import Notification, NotificationKind
from apps.payments import services, tasks
from apps.payments.models import Payment, PaymentStatus, PromotionTariff

pytestmark = pytest.mark.django_db
YOOKASSA_IP = "185.71.76.10"


@pytest.fixture
def ad():
    return AdFactory()


def tariff(code):
    return PromotionTariff.objects.get(code=code)


def pay(client, ad, code="turbo"):
    client.force_login(ad.seller)
    return client.post(reverse("payments:promote", args=[ad.pk]), {"tariff": code})


def webhook(client, provider_id, event="payment.succeeded", ip=YOOKASSA_IP):
    body = {"type": "notification", "event": event, "object": {"id": provider_id, "status": "x"}}
    return client.post(
        reverse("payments:webhook"),
        json.dumps(body),
        content_type="application/json",
        REMOTE_ADDR=ip,
    )


def test_tariffs_come_from_migration():
    prices = dict(PromotionTariff.objects.values_list("code", "price"))
    assert prices == {"bump": 99, "highlight": 149, "pin": 249, "turbo": 399}
    turbo = tariff("turbo")
    assert (turbo.bump, turbo.highlight_days, turbo.pin_days) == (True, 7, 3)


def test_promote_page_only_for_owner(client, ad):
    url = reverse("payments:promote", args=[ad.pk])
    assert client.get(url).status_code == 302

    client.force_login(UserFactory())
    assert client.get(url).status_code == 404

    client.force_login(ad.seller)
    response = client.get(url)
    assert response.status_code == 200
    for title in ("Поднять", "Выделить", "Закрепить", "Турбо"):
        assert title in response.content.decode()


def test_choosing_tariff_creates_payment_with_idempotence_key(client, ad, yookassa):
    response = pay(client, ad, "pin")

    payment = Payment.objects.get()
    assert response.status_code == 302
    assert response.url == payment.confirmation_url
    assert (payment.status, payment.amount, payment.user, payment.ad) == (
        PaymentStatus.PENDING,
        249,
        ad.seller,
        ad,
    )
    params, key = yookassa.created[0]
    assert key == str(payment.idempotence_key)
    assert params["amount"] == {"value": "249.00", "currency": "RUB"}
    assert params["capture"] is True
    assert params["confirmation"]["return_url"] == (
        f"http://testserver{reverse('payments:return', args=[payment.pk])}"
    )
    assert params["metadata"]["payment_id"] == str(payment.pk)
    assert payment.provider_payment_id in yookassa.payments
    assert payment.is_test


def test_second_click_reuses_pending_payment(client, ad, yookassa):
    first, second = pay(client, ad), pay(client, ad)

    assert Payment.objects.count() == 1
    assert len(yookassa.created) == 1
    assert first.url == second.url


def test_failed_request_is_retried_with_same_key(client, ad, yookassa):
    yookassa.fail = True
    response = pay(client, ad)

    payment = Payment.objects.get()
    assert response.url == reverse("payments:promote", args=[ad.pk])
    assert payment.provider_payment_id is None

    yookassa.fail = False
    response = pay(client, ad)

    payment.refresh_from_db()
    assert Payment.objects.count() == 1
    assert yookassa.created[-1][1] == str(payment.idempotence_key)
    assert response.url == payment.confirmation_url


def test_only_active_ad_can_be_promoted(client, yookassa):
    ad = AdFactory(status=AdStatus.ARCHIVED)

    response = pay(client, ad)

    assert response.status_code == 302
    assert not Payment.objects.exists()
    assert not yookassa.created
    page = client.get(reverse("payments:promote", args=[ad.pk])).content.decode()
    assert "только опубликованное объявление" in page


@override_settings(YOOKASSA_SHOP_ID="", YOOKASSA_SECRET_KEY="")
def test_without_keys_payment_is_unavailable(client, ad, yookassa):
    client.force_login(ad.seller)
    page = client.get(reverse("payments:promote", args=[ad.pk])).content.decode()
    assert "Оплата временно недоступна" in page

    pay(client, ad)
    assert not yookassa.created
    assert not Payment.objects.exists()


def test_return_page_checks_status_without_webhook(client, ad, yookassa, run_on_commit):
    pay(client, ad)
    payment = Payment.objects.get()
    yookassa.succeed(payment.provider_payment_id)

    with run_on_commit():
        response = client.get(reverse("payments:return", args=[payment.pk]))

    payment.refresh_from_db()
    ad.refresh_from_db()
    now = timezone.now()
    assert "Оплата прошла" in response.content.decode()
    assert payment.status == PaymentStatus.SUCCEEDED
    assert payment.paid_at
    assert payment.applied_at
    assert ad.pinned_until - now > timedelta(days=2, hours=23)
    assert ad.highlighted_until - now > timedelta(days=6, hours=23)
    assert now - ad.bumped_at < timedelta(minutes=1)
    notification = Notification.objects.get(user=ad.seller, kind=NotificationKind.PAYMENT)
    assert "Турбо" in notification.title
    assert [message.to for message in mail.outbox] == [[ad.seller.email]]


def test_promotion_applied_once_for_repeated_events(client, ad, yookassa):
    pay(client, ad, "pin")
    payment = Payment.objects.get()
    yookassa.succeed(payment.provider_payment_id)

    webhook(client, payment.provider_payment_id)
    ad.refresh_from_db()
    pinned_until = ad.pinned_until
    webhook(client, payment.provider_payment_id)
    client.get(reverse("payments:return", args=[payment.pk]))
    services.apply_remote(payment.pk, services.gateway.fetch_payment(payment.provider_payment_id))

    ad.refresh_from_db()
    assert ad.pinned_until == pinned_until
    assert Notification.objects.filter(kind=NotificationKind.PAYMENT).count() == 1


def test_active_promotion_is_extended(client, yookassa):
    ad = AdFactory(pinned_until=timezone.now() + timedelta(days=1))
    pay(client, ad, "pin")
    payment = Payment.objects.get()
    yookassa.succeed(payment.provider_payment_id)

    webhook(client, payment.provider_payment_id)

    ad.refresh_from_db()
    assert ad.pinned_until - timezone.now() > timedelta(days=3, hours=23)


def test_webhook_trusts_api_not_body(client, ad, yookassa):
    pay(client, ad)
    payment = Payment.objects.get()

    response = webhook(client, payment.provider_payment_id, event="payment.succeeded")

    payment.refresh_from_db()
    assert response.status_code == 200
    assert payment.status == PaymentStatus.PENDING
    assert payment.last_checked_at is not None
    assert Ad.objects.get(pk=ad.pk).pinned_until is None


def test_webhook_from_foreign_address_is_rejected(client, ad, yookassa):
    pay(client, ad)
    payment = Payment.objects.get()
    yookassa.succeed(payment.provider_payment_id)

    response = webhook(client, payment.provider_payment_id, ip="203.0.113.5")

    payment.refresh_from_db()
    assert response.status_code == 403
    assert payment.status == PaymentStatus.PENDING


def test_webhook_ignores_unknown_payment_and_rejects_garbage(client, yookassa):
    assert webhook(client, "unknown-id").status_code == 200
    response = client.post(
        reverse("payments:webhook"), "{", content_type="application/json", REMOTE_ADDR=YOOKASSA_IP
    )
    assert response.status_code == 400
    assert client.get(reverse("payments:webhook")).status_code == 405


def test_amount_mismatch_is_not_applied(client, ad, yookassa):
    pay(client, ad, "bump")
    payment = Payment.objects.get()
    yookassa.succeed(payment.provider_payment_id)
    yookassa.payments[payment.provider_payment_id]["amount"]["value"] = "1.00"

    webhook(client, payment.provider_payment_id)

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.PENDING
    assert payment.applied_at is None


def test_canceled_payment_shows_reason(client, ad, yookassa):
    pay(client, ad)
    payment = Payment.objects.get()
    yookassa.cancel(payment.provider_payment_id, "insufficient_funds")

    webhook(client, payment.provider_payment_id, event="payment.canceled")
    page = client.get(reverse("payments:return", args=[payment.pk])).content.decode()

    payment.refresh_from_db()
    assert payment.status == PaymentStatus.CANCELED
    assert payment.cancellation_reason == "Недостаточно денег на карте."
    assert "Платёж не прошёл" in page
    assert "Недостаточно денег на карте" in page
    assert Ad.objects.get(pk=ad.pk).pinned_until is None


def test_status_is_polled_while_pending(client, ad, yookassa):
    pay(client, ad)
    payment = Payment.objects.get()
    url = reverse("payments:status", args=[payment.pk])

    assert 'hx-trigger="every 3s"' in client.get(url).content.decode()

    yookassa.succeed(payment.provider_payment_id)
    page = client.get(url).content.decode()
    assert "hx-trigger" not in page
    assert "Оплата прошла" in page


def test_status_page_survives_gateway_outage(client, ad, yookassa):
    pay(client, ad)
    payment = Payment.objects.get()
    yookassa.fail = True

    response = client.get(reverse("payments:return", args=[payment.pk]))

    assert response.status_code == 200
    assert "Платёжная система не ответила" in response.content.decode()


def test_payments_are_private(client, ad, yookassa):
    pay(client, ad)
    payment = Payment.objects.get()
    client.force_login(UserFactory())

    assert client.get(reverse("payments:return", args=[payment.pk])).status_code == 404
    assert client.get(reverse("payments:status", args=[payment.pk])).status_code == 404
    assert "Платежей пока нет" in client.get(reverse("payments:history")).content.decode()


def test_history_lists_own_payments(client, ad, yookassa):
    pay(client, ad, "bump")
    payment = Payment.objects.get()
    yookassa.succeed(payment.provider_payment_id)
    webhook(client, payment.provider_payment_id)

    page = client.get(reverse("payments:history")).content.decode()

    assert "«Поднять»" in page
    assert ad.title in page
    assert "Оплачен" in page


def test_expired_promotions_are_cleared_with_notice():
    past, future = timezone.now() - timedelta(minutes=1), timezone.now() + timedelta(days=2)
    ad = AdFactory(pinned_until=past, highlighted_until=future)

    assert tasks.expire_promotions() == 1
    assert tasks.expire_promotions() == 0

    ad.refresh_from_db()
    assert ad.pinned_until is None
    assert ad.highlighted_until == future
    notification = Notification.objects.get(user=ad.seller)
    assert notification.title == f"Закончилось закрепление: {ad.title}"
    assert notification.url == reverse("payments:promote", args=[ad.pk])


def test_pending_payments_are_synced_in_background(client, ad, yookassa):
    pay(client, ad, "highlight")
    payment = Payment.objects.get()
    old = timezone.now() - timedelta(minutes=5)
    Payment.objects.filter(pk=payment.pk).update(created_at=old, last_checked_at=old)
    unsent = Payment.objects.create(
        user=ad.seller, ad=ad, tariff=tariff("bump"), amount=99, description="Поднять"
    )
    Payment.objects.filter(pk=unsent.pk).update(created_at=timezone.now() - timedelta(days=2))
    yookassa.succeed(payment.provider_payment_id)

    assert tasks.sync_pending_payments() == 1

    payment.refresh_from_db()
    unsent.refresh_from_db()
    assert payment.status == PaymentStatus.SUCCEEDED
    assert unsent.status == PaymentStatus.CANCELED


def test_owner_sees_promote_button_and_state(client, ad):
    Ad.objects.filter(pk=ad.pk).update(pinned_until=timezone.now() + timedelta(days=1))
    client.force_login(ad.seller)

    detail = client.get(reverse("ads:detail", args=[ad.pk, ad.slug])).content.decode()
    my_ads = client.get(reverse("ads:my_ads")).content.decode()

    for page in (detail, my_ads):
        assert reverse("payments:promote", args=[ad.pk]) in page
        assert "Закреплено до" in page


@override_settings(DEBUG=False, YOOKASSA_SHOP_ID="", YOOKASSA_SECRET_KEY="")
def test_deploy_check_warns_without_keys():
    ids = [message.id for message in run_checks(include_deployment_checks=True)]
    assert "payments.W001" in ids
