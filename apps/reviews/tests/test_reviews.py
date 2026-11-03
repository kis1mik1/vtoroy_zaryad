from decimal import Decimal

import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.ads.tests.factories import AdFactory
from apps.chat import services as chat
from apps.moderation.permissions import ensure_moderators_group
from apps.notifications.models import Notification, NotificationKind
from apps.reviews import services
from apps.reviews.models import AuthorRole, Review

pytestmark = pytest.mark.django_db


def deal(*, seller=None, buyer=None, answered=True):
    ad = AdFactory(**({"seller": seller} if seller else {}))
    conversation = chat.start_conversation(ad, buyer or UserFactory())
    chat.send_text(conversation, conversation.buyer, "Здравствуйте, ещё продаёте?")
    if answered:
        chat.send_text(conversation, conversation.seller, "Да, приезжайте вечером.")
    return conversation


def leave(client, conversation, author=None, rating=5, text="Всё как в описании, рекомендую."):
    client.force_login(author or conversation.buyer)
    return client.post(
        reverse("reviews:create", args=[conversation.pk]), {"rating": rating, "text": text}
    )


@pytest.fixture
def moderator():
    user = UserFactory()
    user.groups.add(ensure_moderators_group())
    return user


def test_review_needs_messages_from_both(client):
    conversation = deal(answered=False)
    client.force_login(conversation.buyer)
    url = reverse("reviews:create", args=[conversation.pk])

    response = client.get(url)
    assert response.url == reverse("chat:conversation", args=[conversation.pk])
    leave(client, conversation)
    assert not Review.objects.exists()

    chat.send_text(conversation, conversation.seller, "Добрый день, да.")
    assert client.get(url).status_code == 200
    leave(client, conversation)
    assert Review.objects.count() == 1


def test_outsider_cannot_review(client):
    conversation = deal()
    client.force_login(UserFactory())

    assert client.get(reverse("reviews:create", args=[conversation.pk])).status_code == 404


def test_review_updates_rating_and_notifies(client):
    seller = UserFactory()
    first, second = deal(seller=seller), deal(seller=seller)

    response = leave(client, first, rating=4)
    leave(client, second, rating=5)

    review = Review.objects.get(author=first.buyer)
    assert response.url == f"{reverse('reviews:list', args=[seller.pk])}#review-{review.pk}"
    assert (review.target, review.author_role, review.ad) == (seller, AuthorRole.BUYER, first.ad)
    seller.refresh_from_db()
    assert (seller.rating_avg, seller.rating_count) == (Decimal("4.50"), 2)
    assert Notification.objects.filter(user=seller, kind=NotificationKind.REVIEW).count() == 2


def test_one_review_per_deal(client):
    conversation = deal()
    leave(client, conversation)
    leave(client, conversation, rating=1)

    assert Review.objects.get().rating == 5
    with pytest.raises(services.ReviewError):
        services.create_review(conversation.buyer, conversation, rating=1, text="Повторный отзыв")


def test_seller_reviews_buyer(client):
    conversation = deal()

    leave(client, conversation, author=conversation.seller, text="Пришёл вовремя, вежливый.")

    review = Review.objects.get()
    assert (review.target, review.author_role) == (conversation.buyer, AuthorRole.SELLER)


def test_form_validation(client):
    conversation = deal()

    response = leave(client, conversation, rating="", text="Ок")

    assert response.status_code == 400
    page = response.content.decode()
    assert "Поставьте оценку." in page
    assert "Напишите хотя бы пару предложений." in page
    assert not Review.objects.exists()


def test_conversation_shows_review_action(client):
    conversation = deal()
    url = reverse("chat:conversation", args=[conversation.pk])
    client.force_login(conversation.buyer)

    assert reverse("reviews:create", args=[conversation.pk]) in client.get(url).content.decode()
    leave(client, conversation)
    page = client.get(url).content.decode()
    assert "Ваш отзыв" in page
    assert reverse("reviews:create", args=[conversation.pk]) not in page


def test_target_replies_once(client):
    conversation = deal()
    leave(client, conversation)
    review = Review.objects.get()
    url = reverse("reviews:reply", args=[review.pk])

    assert client.post(url, {"text": "Это я отвечаю себе"}).status_code == 404

    client.force_login(conversation.seller)
    client.post(url, {"text": "Спасибо за покупку!"})
    client.post(url, {"text": "Второй ответ"})

    review.refresh_from_db()
    assert review.reply_text == "Спасибо за покупку!"
    assert Notification.objects.filter(user=conversation.buyer, title="Ответ на ваш отзыв").exists()
    page = client.get(reverse("reviews:list", args=[conversation.seller.pk])).content.decode()
    assert "Спасибо за покупку!" in page


def test_author_edits_until_reply(client):
    conversation = deal()
    leave(client, conversation, rating=2)
    review = Review.objects.get()
    edit_url = reverse("reviews:edit", args=[review.pk])

    client.post(edit_url, {"rating": 4, "text": "Разобрались, продавец всё исправил."})
    review.refresh_from_db()
    conversation.seller.refresh_from_db()
    assert review.rating == 4
    assert conversation.seller.rating_avg == Decimal("4.00")

    services.reply(review, conversation.seller, "Спасибо!")
    client.post(edit_url, {"rating": 1, "text": "Передумал, всё плохо было."})
    review.refresh_from_db()
    assert review.rating == 4


def test_report_and_hide_by_moderator(client, moderator):
    conversation = deal()
    leave(client, conversation, rating=1, text="Обманщик и грубиян, не связывайтесь.")
    review = Review.objects.get()
    seller = conversation.seller

    client.force_login(seller)
    client.post(reverse("reviews:report", args=[review.pk]), {"reason": "Сделки не было."})
    review.refresh_from_db()
    assert review.reported_at is not None

    client.force_login(moderator)
    queue = client.get(reverse("reviews:moderation")).content.decode()
    assert "Сделки не было." in queue
    client.post(
        reverse("reviews:moderate", args=[review.pk, "hide"]), {"reason": "Оскорбления в тексте"}
    )

    review.refresh_from_db()
    seller.refresh_from_db()
    assert review.is_hidden
    assert review.moderated_by == moderator
    assert (seller.rating_avg, seller.rating_count) == (Decimal("0.00"), 0)
    assert Notification.objects.filter(
        user=conversation.buyer, title="Отзыв скрыт модератором"
    ).exists()
    client.force_login(UserFactory())
    public = client.get(reverse("reviews:list", args=[seller.pk])).content.decode()
    assert "Обманщик" not in public

    client.force_login(moderator)
    client.post(reverse("reviews:moderate", args=[review.pk, "restore"]))
    seller.refresh_from_db()
    assert seller.rating_count == 1


def test_moderator_keeps_review(client, moderator):
    conversation = deal()
    leave(client, conversation, rating=3)
    review = services.report(Review.objects.get(), conversation.seller, "Не согласен")

    client.force_login(moderator)
    client.post(reverse("reviews:moderate", args=[review.pk, "keep"]))

    review.refresh_from_db()
    assert review.reported_at is None
    assert not review.is_hidden
    assert not review.can_be_reported


def test_moderation_needs_permission(client):
    conversation = deal()
    leave(client, conversation)
    review = Review.objects.get()
    client.force_login(UserFactory())

    assert client.get(reverse("reviews:moderation")).status_code == 403
    response = client.post(reverse("reviews:moderate", args=[review.pk, "hide"]), {"reason": "x"})
    assert response.status_code == 403
    assert not Review.objects.get().is_hidden


def test_profile_shows_rating_distribution(client):
    seller = UserFactory()
    for rating in (5, 5, 4):
        leave(client, deal(seller=seller), rating=rating, text=f"Оценка {rating}, всё хорошо.")

    page = client.get(reverse("ads:profile", args=[seller.pk])).content.decode()

    assert "4,7" in page
    assert "3\u00a0отзыва" in page
    assert 'style="width: 67%"' in page
    assert reverse("reviews:list", args=[seller.pk]) in page


def test_list_filters_by_role(client):
    conversation = deal()
    leave(client, conversation, author=conversation.seller, text="Покупатель пунктуальный.")
    url = reverse("reviews:list", args=[conversation.buyer.pk])

    assert "Покупатель пунктуальный." in client.get(url, {"role": "seller"}).content.decode()
    assert "Покупатель пунктуальный." not in client.get(url, {"role": "buyer"}).content.decode()
