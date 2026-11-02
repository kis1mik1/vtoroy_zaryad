import pytest
from django.urls import reverse

from apps.accounts.services import ban_user
from apps.accounts.tests.factories import UserFactory
from apps.ads import services
from apps.ads.models import Ad, AdStatus

from .helpers import publish

pytestmark = pytest.mark.django_db


def url(ad):
    return reverse("ads:detail", args=[ad.pk, ad.slug])


def test_detail_page(client, phones):
    ad = publish(phones)

    response = client.get(url(ad))

    html = response.content.decode()
    assert response.status_code == 200
    assert ad.title in html
    assert "Характеристики" in html
    assert 'property="og:title"' in html
    assert '"@type": "Product"' in html


def test_wrong_slug_redirects(client, phones):
    ad = publish(phones)

    response = client.get(reverse("ads:detail", args=[ad.pk, "old-title"]))

    assert response.status_code == 301
    assert response.url == url(ad)


def test_pending_ad_visible_only_to_owner_and_staff(client, phones):
    ad = publish(phones)
    services.withdraw(ad)
    Ad.objects.filter(pk=ad.pk).update(status=AdStatus.PENDING)

    assert client.get(url(ad)).status_code == 404
    client.force_login(ad.seller)
    assert "Объявление на проверке" in client.get(url(ad)).content.decode()
    client.force_login(UserFactory(is_staff=True))
    assert client.get(url(ad)).status_code == 200


def test_sold_ad_visible_with_note(client, phones):
    ad = publish(phones)
    services.mark_sold(ad)

    html = client.get(url(ad)).content.decode()

    assert "Товар продан" in html
    assert "Показать телефон" not in html


def test_banned_seller_ads_hidden(client, phones):
    ad = publish(phones)
    ban_user(ad.seller, reason="Спам", until=None)

    assert client.get(url(ad)).status_code == 404


def test_views_counted_once_per_viewer_and_not_for_owner(client, phones):
    ad = publish(phones)

    client.get(url(ad))
    client.get(url(ad))
    ad.refresh_from_db()
    assert ad.views_count == 1

    client.force_login(ad.seller)
    client.get(url(ad))
    ad.refresh_from_db()
    assert ad.views_count == 1


def test_recently_viewed_in_session(client, phones):
    first = publish(phones)
    second = publish(phones, price=35_000)

    client.get(url(first))
    response = client.get(url(second))

    assert [a.pk for a in response.context["recent"]] == [first.pk]


def test_similar_ads_same_model_price_range(client, phones):
    ad = publish(phones, price=40_000)
    close = publish(phones, price=45_000)
    publish(phones, price=90_000)

    response = client.get(url(ad))

    assert [a.pk for a in response.context["similar"]] == [close.pk]


def test_phone_requires_login(client, phones):
    ad = publish(phones)

    response = client.post(reverse("ads:phone", args=[ad.pk]))

    assert response.status_code == 302
    assert "/account/login/" in response.url


def test_phone_reveal(auth_client, phones):
    seller = UserFactory(phone="+79141234567", contact_mode="phone_and_messages")
    ad = publish(phones, seller=seller)

    response = auth_client.post(reverse("ads:phone", args=[ad.pk]), headers={"HX-Request": "true"})

    assert "+7 914 123-45-67" in response.content.decode()
    ad.refresh_from_db()
    assert ad.contacts_shown_count == 1


def test_phone_hidden_for_messages_only(auth_client, phones):
    seller = UserFactory(phone="+79141234567", contact_mode="messages_only")
    ad = publish(phones, seller=seller)

    page = auth_client.get(url(ad)).content.decode()
    reveal = auth_client.post(reverse("ads:phone", args=[ad.pk])).content.decode()

    assert "предпочитает переписку" in page
    assert "+7 914" not in reveal


def test_public_profile(client, phones):
    ad = publish(phones)
    seller = ad.seller

    response = client.get(reverse("ads:profile", args=[seller.pk]))

    html = response.content.decode()
    assert seller.first_name in html
    assert ad.title in html


def test_profile_of_deleted_or_banned_user_404(client, phones):
    from apps.accounts.services import delete_account

    deleted = UserFactory()
    delete_account(deleted)
    banned = UserFactory()
    ban_user(banned, reason="Спам", until=None)

    assert client.get(reverse("ads:profile", args=[deleted.pk])).status_code == 404
    assert client.get(reverse("ads:profile", args=[banned.pk])).status_code == 404


def test_home_shows_fresh_ads_of_current_city(client, phones):
    here = publish(phones, city="vladivostok")
    there = publish(phones, city="khabarovsk", price=30_000)

    fresh = client.get(reverse("ads:home")).context["fresh"]

    assert [a.pk for a in fresh] == [here.pk]
    assert there.pk not in [a.pk for a in fresh]


def test_sitemap_lists_active_ads(client, phones):
    ad = publish(phones)

    body = client.get("/sitemap.xml").content.decode()

    assert url(ad) in body
    assert reverse("ads:category", args=[phones["category"].slug]) in body
