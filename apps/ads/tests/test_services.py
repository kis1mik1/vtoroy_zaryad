from datetime import timedelta

import pytest
from django.utils import timezone

from apps.accounts.services import ban_user, delete_account
from apps.accounts.tests.factories import UserFactory
from apps.ads import services
from apps.ads.models import Ad, AdPhoto, AdStatus, PriceChange
from apps.ads.photos import remove_orphans
from apps.ads.services import AdDraft, AttributeValue, TransitionError, build_title
from apps.core.models import City
from apps.notifications.models import Notification

from .factories import AdFactory, make_photo

pytestmark = pytest.mark.django_db


def draft(seller, phones, **fields):
    photos = fields.pop("photos", None) or [make_photo(seller)]
    base = {
        "category": phones["category"],
        "brand": phones["apple"],
        "device_model": phones["iphone"],
        "custom_model_name": "",
        "title": "",
        "description": "Пользовался аккуратно, всё работает, батарея 88 процентов.",
        "price": 38_500,
        "is_negotiable": True,
        "condition": "used",
        "city": City.objects.get(slug="artem"),
    }
    base.update(fields)
    attributes = [
        AttributeValue(phones["attributes"]["storage"], option=phones["storage"]["256 ГБ"]),
        AttributeValue(phones["attributes"]["color"], option=phones["blue"]),
    ]
    return AdDraft(
        fields=base,
        attributes=attributes,
        condition={"body_state": "minor", "battery_health": 88, "package": ["box"]},
        photos=photos,
    )


def test_create_ad(phones):
    seller = UserFactory()
    photos = [make_photo(seller), make_photo(seller)]

    ad = services.create_ad(seller, draft(seller, phones, photos=list(reversed(photos))))

    assert ad.status == AdStatus.PENDING
    assert ad.title == "Apple iPhone 13, 256 ГБ, синий"
    assert ad.slug == "apple-iphone-13-256-gb-siniy"
    assert [p.pk for p in ad.photos.all()] == [photos[1].pk, photos[0].pk]
    assert ad.attribute_values.count() == 2
    assert ad.condition_report.battery_health == 88
    assert ad.condition_report.package_display == ["Коробка"]


def test_custom_title_kept(phones):
    seller = UserFactory()

    ad = services.create_ad(seller, draft(seller, phones, title="Айфон в идеале"))

    assert ad.title == "Айфон в идеале"


def test_build_title_skips_values_already_in_model_name(phones):
    cpu = phones["attributes"]["storage"]
    model = phones["iphone"]
    model.name = "iPhone 13 256 ГБ"

    title = build_title(
        device_model=model, attributes=[AttributeValue(cpu, option=phones["storage"]["256 ГБ"])]
    )

    assert title == "Apple iPhone 13 256 ГБ"


def test_build_title_for_custom_model(phones):
    title = build_title(brand=phones["other_brand"], custom_name=" 3310 ", attributes=[])

    assert title == "Nokia 3310"


@pytest.fixture
def active_ad(phones):
    seller = UserFactory()
    ad = services.create_ad(seller, draft(seller, phones))
    services.approve(ad)
    ad.refresh_from_db()
    return ad


def test_approve_publishes_and_notifies(active_ad):
    assert active_ad.status == AdStatus.ACTIVE
    assert active_ad.published_at is not None
    assert active_ad.bumped_at == active_ad.published_at
    notification = Notification.objects.get(user=active_ad.seller)
    assert notification.title.startswith("Объявление опубликовано")
    assert "status=active" in notification.url


def test_reject_with_reason(phones):
    seller = UserFactory()
    ad = services.create_ad(seller, draft(seller, phones))

    services.reject(ad, "В описании есть контакты или ссылки")

    ad.refresh_from_db()
    assert ad.status == AdStatus.REJECTED
    assert ad.rejection_reason == "В описании есть контакты или ссылки"
    assert "Причина: В описании" in Notification.objects.get(user=seller).body


def test_price_change_keeps_ad_active_and_logs_history(active_ad, phones):
    photos = list(active_ad.photos.all())

    sent = services.update_ad(
        active_ad, draft(active_ad.seller, phones, price=35_000, photos=photos)
    )

    active_ad.refresh_from_db()
    assert not sent
    assert active_ad.status == AdStatus.ACTIVE
    change = PriceChange.objects.get(ad=active_ad)
    assert (change.old_price, change.new_price) == (38_500, 35_000)


def test_reordering_photos_does_not_trigger_review(active_ad, phones):
    extra = make_photo(active_ad.seller)
    services.update_ad(
        active_ad, draft(active_ad.seller, phones, photos=[*active_ad.photos.all(), extra])
    )
    services.approve(active_ad)
    photos = list(active_ad.photos.all())

    sent = services.update_ad(active_ad, draft(active_ad.seller, phones, photos=photos[::-1]))

    assert not sent
    assert [p.pk for p in active_ad.photos.all()] == [p.pk for p in photos[::-1]]


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "Совсем другое описание товара, чтобы проверить модерацию."},
        {"device_model": None, "custom_model_name": "iPhone 13 (восстановленный)"},
        {"title": "Новое название"},
    ],
)
def test_moderated_changes_send_to_review(active_ad, phones, changes):
    photos = list(active_ad.photos.all())

    sent = services.update_ad(active_ad, draft(active_ad.seller, phones, photos=photos, **changes))

    active_ad.refresh_from_db()
    assert sent
    assert active_ad.status == AdStatus.PENDING


def test_removing_photo_sends_to_review_and_deletes_it(active_ad, phones):
    old = active_ad.photos.get()
    new = make_photo(active_ad.seller)

    assert services.update_ad(active_ad, draft(active_ad.seller, phones, photos=[new]))

    assert not AdPhoto.objects.filter(pk=old.pk).exists()


def test_rejected_ad_resubmitted_on_edit(phones):
    seller = UserFactory()
    ad = services.create_ad(seller, draft(seller, phones))
    services.reject(ad, "Неверная категория")

    services.update_ad(ad, draft(seller, phones, photos=list(ad.photos.all()), price=30_000))

    ad.refresh_from_db()
    assert ad.status == AdStatus.PENDING
    assert ad.rejection_reason == ""


def test_owner_transitions(active_ad):
    services.withdraw(active_ad)
    assert active_ad.status == AdStatus.ARCHIVED

    services.restore(active_ad)
    assert active_ad.status == AdStatus.ACTIVE

    services.mark_sold(active_ad)
    assert active_ad.status == AdStatus.SOLD
    with pytest.raises(TransitionError):
        services.restore(active_ad)

    services.delete(active_ad)
    assert active_ad.is_deleted


def test_cannot_delete_active_or_edit_sold(active_ad, phones):
    with pytest.raises(TransitionError):
        services.delete(active_ad)
    services.mark_sold(active_ad)
    with pytest.raises(TransitionError):
        services.update_ad(active_ad, draft(active_ad.seller, phones))


def test_restore_never_published_goes_to_review(phones):
    seller = UserFactory()
    ad = services.create_ad(seller, draft(seller, phones))
    services.withdraw(ad)

    services.restore(ad)

    assert ad.status == AdStatus.PENDING


def test_archive_stale_ads():
    fresh = AdFactory()
    stale = AdFactory(bumped_at=timezone.now() - timedelta(days=31))

    assert services.archive_stale() == 1

    stale.refresh_from_db()
    fresh.refresh_from_db()
    assert stale.status == AdStatus.ARCHIVED
    assert fresh.status == AdStatus.ACTIVE


def test_visible_hides_banned_deleted_and_inactive():
    visible = AdFactory()
    AdFactory(status=AdStatus.PENDING)
    AdFactory(is_deleted=True)
    banned = AdFactory()
    ban_user(banned.seller, reason="Спам", until=None)

    assert list(Ad.objects.visible()) == [visible]


def test_deleted_account_archives_ads():
    ad = AdFactory()

    delete_account(ad.seller)

    ad.refresh_from_db()
    assert ad.status == AdStatus.ARCHIVED


def test_orphan_photos_removed_after_a_day():
    owner = UserFactory()
    old = make_photo(owner)
    fresh = make_photo(owner)
    AdPhoto.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=2))

    assert remove_orphans() == 1

    assert not AdPhoto.objects.filter(pk=old.pk).exists()
    assert AdPhoto.objects.filter(pk=fresh.pk).exists()
