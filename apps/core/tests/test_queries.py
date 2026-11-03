from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.ads.models import AdPhoto, AdStatus, Favorite, PriceChange
from apps.ads.tests.factories import AdFactory, make_photo
from apps.chat import services as chat
from apps.moderation.permissions import ensure_moderators_group
from apps.moderation.services import file_complaint
from apps.notifications.models import NotificationKind
from apps.notifications.services import notify
from apps.payments.models import Payment, PromotionTariff
from apps.reviews.models import AuthorRole, Review
from apps.support import services as support

pytestmark = pytest.mark.django_db


def queries(client, url) -> int:
    with CaptureQueriesContext(connection) as context:
        response = client.get(url)
    assert response.status_code == 200, url
    return len(context)


def ad_with_photo(**fields):
    ad = AdFactory(**fields)
    AdPhoto.objects.filter(pk=make_photo(ad.seller).pk).update(ad=ad)
    PriceChange.objects.create(ad=ad, old_price=ad.price + 1000, new_price=ad.price)
    return ad


def assert_constant(client, url, grow, *, times=2):
    grow()
    queries(client, url)
    before = queries(client, url)
    for _ in range(times):
        grow()
    assert queries(client, url) == before, f"{url}: число запросов растёт с данными"


@pytest.fixture
def seller():
    return UserFactory()


@pytest.fixture
def viewer(client):
    user = UserFactory()
    client.force_login(user)
    return user


def test_public_lists(client, seller, viewer):
    category = AdFactory(seller=seller).category

    def grow():
        ad = ad_with_photo(
            seller=seller, category=category, pinned_until=timezone.now() + timedelta(days=1)
        )
        Favorite.objects.create(user=viewer, ad=ad)

    for url in (
        reverse("ads:home"),
        reverse("ads:search"),
        reverse("ads:category", args=[category.slug]),
        reverse("ads:profile", args=[seller.pk]),
        reverse("ads:favorites"),
    ):
        assert_constant(client, url, grow)


def test_ad_detail(client, seller, viewer):
    ad = ad_with_photo(seller=seller)

    def grow():
        AdPhoto.objects.filter(pk=make_photo(seller).pk).update(ad=ad)
        PriceChange.objects.create(ad=ad, old_price=ad.price, new_price=ad.price - 100)
        ad_with_photo(seller=seller, category=ad.category)

    assert_constant(client, reverse("ads:detail", args=[ad.pk, ad.slug]), grow)


def test_owner_pages(client, viewer):
    tariff = PromotionTariff.objects.get(code="bump")

    def grow():
        ad = ad_with_photo(seller=viewer)
        Payment.objects.create(
            user=viewer, ad=ad, tariff=tariff, amount=tariff.price, description="Поднять"
        )
        notify(viewer, NotificationKind.MODERATION, "Объявление опубликовано")
        support.create_ticket(
            user=viewer,
            name="Я",
            email=viewer.email,
            topic="ads",
            subject="Вопрос",
            message="x" * 30,
        )

    for url in (
        reverse("ads:my_ads"),
        reverse("payments:history"),
        reverse("notifications:list"),
        reverse("support:tickets"),
    ):
        assert_constant(client, url, grow)


def test_messages(client, viewer):
    def grow():
        conversation = chat.start_conversation(ad_with_photo(), viewer)
        chat.send_text(conversation, viewer, "Здравствуйте")
        chat.send_text(conversation, conversation.seller, "Добрый день")
        return conversation

    conversation = grow()
    assert_constant(client, reverse("chat:list"), grow)
    assert_constant(
        client,
        reverse("chat:conversation", args=[conversation.pk]),
        lambda: chat.send_text(conversation, viewer, "Ещё вопрос"),
    )


def test_reviews(client, seller, viewer):
    def grow():
        buyer = UserFactory()
        ad = ad_with_photo(seller=seller)
        Review.objects.create(
            author=buyer,
            target=seller,
            ad=ad,
            author_role=AuthorRole.BUYER,
            rating=5,
            text="Всё отлично, рекомендую.",
            reply_text="Спасибо!",
        )

    assert_constant(client, reverse("reviews:list", args=[seller.pk]), grow)
    assert_constant(client, reverse("ads:profile", args=[seller.pk]), grow)


def test_moderation_panel(client, seller):
    moderator = UserFactory()
    moderator.groups.add(ensure_moderators_group())
    client.force_login(moderator)

    def grow():
        ad = ad_with_photo(seller=seller, status=AdStatus.PENDING)
        ad.review_queued_at = timezone.now()
        ad.save(update_fields=["review_queued_at"])
        active = ad_with_photo(seller=seller)
        file_complaint(UserFactory(), ad=active, reason="fraud", comment="Просит предоплату")
        review = Review.objects.create(
            author=UserFactory(),
            target=seller,
            ad=active,
            author_role=AuthorRole.BUYER,
            rating=1,
            text="Плохая сделка, не советую.",
        )
        Review.objects.filter(pk=review.pk).update(reported_at=timezone.now(), report_reason="Ложь")

    for url in (
        reverse("moderation:queue"),
        reverse("moderation:complaints"),
        reverse("moderation:history"),
        reverse("reviews:moderation"),
        reverse("moderation:user", args=[seller.pk]),
    ):
        assert_constant(client, url, grow)
