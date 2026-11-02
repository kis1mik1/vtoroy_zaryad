import pytest
from django.urls import reverse

from apps.accounts.tests.factories import UserFactory
from apps.ads.models import Ad, AdStatus
from apps.core.models import City
from apps.notifications.models import Notification

from .factories import AdFactory, image_upload

pytestmark = pytest.mark.django_db


def upload(client, **kwargs):
    return client.post(reverse("ads:photo_upload"), {"photo": image_upload(**kwargs)})


def photo_id(response):
    html = response.content.decode()
    return html.split('name="photos" value="')[1].split('"')[0]


def form_data(phones, photos, **overrides):
    return {
        "category": phones["category"].pk,
        "brand": phones["apple"].pk,
        "device_model": phones["iphone"].pk,
        "attr_storage": phones["storage"]["128 ГБ"].pk,
        "attr_color": phones["blue"].pk,
        "condition": "used",
        "screen_state": "perfect",
        "body_state": "minor",
        "battery_health": "91",
        "everything_works": "on",
        "package": ["box", "cable"],
        "photos": photos,
        "description": "Полтора года в чехле и со стеклом, работает идеально.",
        "price": "41 000",
        "city": City.objects.get(slug="nakhodka").pk,
        **overrides,
    }


def test_create_requires_verified_email(client):
    client.force_login(UserFactory(unverified=True))

    response = client.get(reverse("ads:create"))

    assert response.status_code == 403
    assert "Подтвердите почту" in response.content.decode()


def test_create_page_lists_categories(auth_client, phones):
    response = auth_client.get(reverse("ads:create"))

    html = response.content.decode()
    assert response.status_code == 200
    assert "Смартфоны" in html
    assert "Сначала выберите категорию" in html


def test_full_create_flow(auth_client, user, phones):
    first = photo_id(upload(auth_client))
    second = photo_id(upload(auth_client, color=(200, 20, 20)))

    response = auth_client.post(reverse("ads:create"), form_data(phones, [second, first]))

    assert response.status_code == 302
    assert response.url == f"{reverse('ads:my_ads')}?status=pending"
    ad = Ad.objects.get(seller=user)
    assert ad.title == "Apple iPhone 13, 128 ГБ, синий"
    assert ad.price == 41_000
    assert ad.city.slug == "nakhodka"
    assert [str(p.pk) for p in ad.photos.all()] == [second, first]
    assert ad.condition_report.package == ["box", "cable"]
    values = {v.attribute.code: v.display for v in ad.attribute_values.select_related("option")}
    assert values == {
        "storage": "128 ГБ",
        "color": "синий",
        "ram": "4 ГБ",
        "screen": "6,1″",
        "nfc": "есть",
    }


def test_create_without_photos_shows_errors_and_keeps_input(auth_client, phones):
    response = auth_client.post(reverse("ads:create"), form_data(phones, [], body_state=""))

    html = response.content.decode()
    assert response.status_code == 400
    assert "Добавьте хотя бы одно фото" in html
    assert "Опишите состояние корпуса" in html
    assert "41 000" in html or "41000" in html
    assert not Ad.objects.exists()


def test_cannot_use_foreign_photo(auth_client, phones):
    other = UserFactory()
    auth_client.force_login(other)
    foreign = photo_id(upload(auth_client))
    auth_client.force_login(UserFactory())

    response = auth_client.post(reverse("ads:create"), form_data(phones, [foreign]))

    assert response.status_code == 400
    assert "не найдены" in response.content.decode()


def test_photo_upload_rejects_non_image(auth_client):
    from django.core.files.uploadedfile import SimpleUploadedFile

    fake = SimpleUploadedFile("virus.jpg", b"MZ\x90\x00", content_type="image/jpeg")

    response = auth_client.post(reverse("ads:photo_upload"), {"photo": fake})

    assert response.status_code == 400
    assert "Не удалось прочитать изображение" in response.content.decode()


def test_form_section_for_category(auth_client, phones):
    response = auth_client.get(
        reverse("ads:form_section"),
        {"category": phones["category"].pk, "part": "category"},
        headers={"HX-Request": "true"},
    )

    html = response.content.decode()
    assert "<html" not in html
    assert ">Apple</option>" in html
    assert 'id="ad-condition-section"' in html
    assert 'hx-swap-oob="true"' in html


def test_form_section_for_model(auth_client, phones):
    response = auth_client.get(
        reverse("ads:form_section"),
        {
            "category": phones["category"].pk,
            "brand": phones["apple"].pk,
            "device_model": phones["iphone"].pk,
        },
    )

    html = response.content.decode()
    assert "Из справочника для Apple iPhone 13" in html
    assert "128 ГБ" in html
    assert "512 ГБ" not in html
    assert "hx-swap-oob" not in html


def test_edit_only_own_ad(auth_client):
    foreign = AdFactory()

    assert auth_client.get(reverse("ads:edit", args=[foreign.pk])).status_code == 404


def test_edit_price_keeps_active(auth_client, user, phones):
    pid = photo_id(upload(auth_client))
    auth_client.post(reverse("ads:create"), form_data(phones, [pid]))
    ad = Ad.objects.get(seller=user)
    ad.status = AdStatus.ACTIVE
    ad.save()

    page = auth_client.get(reverse("ads:edit", args=[ad.pk]))
    assert "Из справочника" in page.content.decode()

    response = auth_client.post(
        reverse("ads:edit", args=[ad.pk]), form_data(phones, [pid], price="39 000")
    )

    ad.refresh_from_db()
    assert response.status_code == 302
    assert ad.status == AdStatus.ACTIVE
    assert ad.price == 39_000
    assert ad.price_changes.count() == 1


def test_my_ads_tabs(auth_client, user):
    AdFactory(seller=user, title="Активный ноутбук")
    AdFactory(seller=user, status=AdStatus.REJECTED, rejection_reason="Фото из интернета")
    AdFactory(title="Чужое")

    active = auth_client.get(reverse("ads:my_ads")).content.decode()
    rejected = auth_client.get(reverse("ads:my_ads"), {"status": "rejected"}).content.decode()

    assert "Активный ноутбук" in active
    assert "Чужое" not in active
    assert "Фото из интернета" in rejected


@pytest.mark.parametrize(
    ("action", "status"),
    [("withdraw", AdStatus.ARCHIVED), ("sold", AdStatus.SOLD)],
)
def test_status_actions(auth_client, user, action, status):
    ad = AdFactory(seller=user)

    response = auth_client.post(reverse("ads:status", args=[ad.pk, action]))

    ad.refresh_from_db()
    assert ad.status == status
    assert response.url.endswith(f"status={status}")


def test_status_action_errors(auth_client, user):
    ad = AdFactory(seller=user)

    response = auth_client.post(reverse("ads:status", args=[ad.pk, "delete"]), follow=True)

    ad.refresh_from_db()
    assert not ad.is_deleted
    assert "Сначала снимите объявление" in response.content.decode()
    assert auth_client.post(reverse("ads:status", args=[ad.pk, "hack"])).status_code == 400
    assert auth_client.get(reverse("ads:status", args=[ad.pk, "sold"])).status_code == 405


def test_status_action_on_foreign_ad(auth_client):
    ad = AdFactory()

    assert auth_client.post(reverse("ads:status", args=[ad.pk, "sold"])).status_code == 404


@pytest.fixture
def admin_client(client):
    client.force_login(UserFactory(is_staff=True, is_superuser=True))
    return client


def test_admin_approve(admin_client):
    ad = AdFactory(status=AdStatus.PENDING, published_at=None, bumped_at=None)

    admin_client.post(
        reverse("admin:ads_ad_changelist"), {"action": "approve_ads", "_selected_action": [ad.pk]}
    )

    ad.refresh_from_db()
    assert ad.status == AdStatus.ACTIVE
    assert Notification.objects.filter(user=ad.seller).exists()


def test_admin_reject_asks_reason_then_rejects(admin_client):
    ad = AdFactory(status=AdStatus.PENDING)
    url = reverse("admin:ads_ad_changelist")

    page = admin_client.post(url, {"action": "reject_ads", "_selected_action": [ad.pk]})
    assert "Причина" in page.content.decode()

    admin_client.post(
        url,
        {
            "action": "reject_ads",
            "_selected_action": [ad.pk],
            "apply": "1",
            "reason": "Запрещённый товар",
            "comment": "Это не электроника",
        },
    )

    ad.refresh_from_db()
    assert ad.status == AdStatus.REJECTED
    assert ad.rejection_reason == "Запрещённый товар. Это не электроника"
