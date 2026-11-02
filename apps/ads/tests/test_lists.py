from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.ads import favorites, services
from apps.ads.models import Ad, Favorite, SavedSearch
from apps.ads.saved_searches import check_saved_searches
from apps.notifications.models import Notification, NotificationKind

from .helpers import publish

pytestmark = pytest.mark.django_db


def test_favorite_toggle(auth_client, user, phones):
    ad = publish(phones)

    added = auth_client.post(reverse("ads:favorite", args=[ad.pk]), headers={"HX-Request": "true"})
    ad.refresh_from_db()
    assert Favorite.objects.filter(user=user, ad=ad).exists()
    assert ad.favorites_count == 1
    assert 'aria-pressed="true"' in added.content.decode()

    auth_client.post(reverse("ads:favorite", args=[ad.pk]), headers={"HX-Request": "true"})
    ad.refresh_from_db()
    assert not Favorite.objects.exists()
    assert ad.favorites_count == 0


def test_favorite_anonymous_redirect(client, phones):
    ad = publish(phones)

    response = client.post(reverse("ads:favorite", args=[ad.pk]), headers={"HX-Request": "true"})

    assert "/account/login/" in response["HX-Redirect"]


def test_my_favorites_page(auth_client, user, phones):
    ad = publish(phones)
    favorites.toggle(user, ad)
    services.mark_sold(ad)

    html = auth_client.get(reverse("ads:favorites")).content.decode()

    assert ad.title in html
    assert "Продано" in html


def test_price_drop_notifies_favoriters(phones, run_on_commit):
    ad = publish(phones, price=50_000)
    fan = UserFactory()
    favorites.toggle(fan, ad)
    photos = list(ad.photos.all())
    from .test_services import draft

    with run_on_commit():
        services.update_ad(
            ad,
            draft(
                ad.seller,
                phones,
                price=45_000,
                photos=photos,
                description=ad.description,
                title=ad.title,
            ),
        )

    notification = Notification.objects.get(user=fan, kind=NotificationKind.PRICE_DROP)
    assert "45 000" in notification.body
    assert not Notification.objects.filter(
        user=ad.seller, kind=NotificationKind.PRICE_DROP
    ).exists()


def test_compare_limit_and_page(client, phones):
    ads = [publish(phones, price=40_000 + i * 1000) for i in range(4)]
    for ad in ads[:3]:
        client.post(reverse("ads:compare_toggle", args=[ad.pk]))

    response = client.post(
        reverse("ads:compare_toggle", args=[ads[3].pk]), headers={"HX-Request": "true"}
    )
    assert "до 3" in response["HX-Trigger"].encode().decode("unicode_escape")

    page = client.get(reverse("ads:compare"))
    assert [a.pk for a in page.context["ads"]] == [a.pk for a in ads[:3]]
    rows = {name: (cells, diff) for name, cells, diff in page.context["rows"]}
    assert rows["Память"] == (["128 ГБ"] * 3, False)

    client.post(reverse("ads:compare_clear"))
    assert client.get(reverse("ads:compare")).context["ads"] == []


def test_compare_drops_unavailable_ads(client, phones):
    ad = publish(phones)
    client.post(reverse("ads:compare_toggle", args=[ad.pk]))
    services.mark_sold(ad)

    assert client.get(reverse("ads:compare")).context["ads"] == []
    assert client.session["compare_ads"] == []


def test_save_search_and_manage(auth_client, user):
    response = auth_client.post(
        reverse("ads:saved_search_create"),
        {"url": "/search/?q=iphone&price_max=50000"},
        headers={"HX-Request": "true"},
    )

    search = SavedSearch.objects.get(user=user)
    assert search.query_string == "/search/?city=vladivostok&price_max=50000&q=iphone"
    assert "«iphone»" in search.name
    assert "Поиск сохранён" in response.content.decode()
    assert auth_client.get("/search/?q=iphone&price_max=50000").context["saved"]

    auth_client.post(reverse("ads:saved_search_update", args=[search.pk, "notify"]))
    search.refresh_from_db()
    assert not search.notify
    auth_client.post(reverse("ads:saved_search_update", args=[search.pk, "delete"]))
    assert not SavedSearch.objects.exists()


def test_save_search_rejects_foreign_urls(auth_client):
    response = auth_client.post(
        reverse("ads:saved_search_create"), {"url": "https://evil.example/search/"}
    )

    assert response.status_code == 400
    assert not SavedSearch.objects.exists()


def test_saved_search_notifies_about_new_ads_only(phones):
    owner = UserFactory()
    old = publish(phones)
    search = SavedSearch.objects.create(
        user=owner, name="iPhone", query_string="/search/?city=all&q=iphone"
    )
    Ad.objects.filter(pk=old.pk).update(published_at=timezone.now() - timedelta(hours=2))
    SavedSearch.objects.filter(pk=search.pk).update(
        last_checked_at=timezone.now() - timedelta(hours=1)
    )

    assert check_saved_searches() == 0

    publish(phones, price=30_000)
    SavedSearch.objects.filter(pk=search.pk).update(
        last_checked_at=timezone.now() - timedelta(minutes=5)
    )
    assert check_saved_searches() == 1
    notification = Notification.objects.get(user=owner)
    assert notification.kind == NotificationKind.SAVED_SEARCH
    assert notification.url == "/search/?city=all&q=iphone"
