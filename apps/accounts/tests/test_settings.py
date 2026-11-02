import re
from io import BytesIO

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.accounts import tokens
from apps.accounts.models import ContactMode, User
from apps.accounts.signals import account_deleted
from apps.core.models import City

from .factories import PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def image_file(size=(1200, 800)):
    buffer = BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "Camera maker"
    Image.new("RGB", size, (200, 30, 30)).save(buffer, "JPEG", exif=exif.tobytes())
    return SimpleUploadedFile("photo.jpg", buffer.getvalue(), content_type="image/jpeg")


def profile_data(**overrides):
    return {
        "first_name": "Пётр",
        "city": City.objects.get(slug="nakhodka").pk,
        "phone": "8 (914) 700-11-22",
        "contact_mode": ContactMode.PHONE_AND_MESSAGES,
        "about": "Продаю технику после апгрейда.",
        **overrides,
    }


def test_settings_require_login(client):
    response = client.get(reverse("accounts:settings"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


def test_update_profile(auth_client, user):
    response = auth_client.post(reverse("accounts:settings"), profile_data())

    assert response.status_code == 302
    user.refresh_from_db()
    assert user.first_name == "Пётр"
    assert user.city.slug == "nakhodka"
    assert user.phone == "+79147001122"
    assert user.shows_phone


def test_phone_required_for_phone_contact_mode(auth_client, user):
    response = auth_client.post(reverse("accounts:settings"), profile_data(phone=""))

    assert "phone" in response.context["form"].errors
    user.refresh_from_db()
    assert user.first_name != "Пётр"


def test_avatar_is_cropped_converted_and_stripped(auth_client, user):
    auth_client.post(reverse("accounts:settings"), {**profile_data(), "avatar_file": image_file()})

    user.refresh_from_db()
    assert user.avatar.name.endswith(".webp")
    with user.avatar.open() as stored:
        image = Image.open(stored)
        assert image.format == "WEBP"
        assert image.size == (400, 400)
        assert not image.getexif()


def test_avatar_replacement_removes_old_file(auth_client, user):
    auth_client.post(reverse("accounts:settings"), {**profile_data(), "avatar_file": image_file()})
    user.refresh_from_db()
    old_name = user.avatar.name

    auth_client.post(reverse("accounts:settings"), {**profile_data(), "avatar_file": image_file()})

    user.refresh_from_db()
    assert user.avatar.name != old_name
    assert not user.avatar.storage.exists(old_name)


def test_avatar_rejects_non_image(auth_client, user):
    fake = SimpleUploadedFile("photo.jpg", b"not an image", content_type="image/jpeg")

    response = auth_client.post(
        reverse("accounts:settings"), {**profile_data(), "avatar_file": fake}
    )

    assert "avatar_file" in response.context["form"].errors
    user.refresh_from_db()
    assert not user.avatar


def test_remove_avatar(auth_client, user):
    auth_client.post(reverse("accounts:settings"), {**profile_data(), "avatar_file": image_file()})

    auth_client.post(reverse("accounts:settings"), {**profile_data(), "remove_avatar": "on"})

    user.refresh_from_db()
    assert not user.avatar


def test_notification_settings(auth_client, user):
    auth_client.post(
        reverse("accounts:settings_notifications"),
        {"email_on_messages": "on", "email_on_moderation": "on"},
    )

    user.refresh_from_db()
    assert user.email_on_messages
    assert user.email_on_moderation
    assert not user.email_on_price_drop
    assert not user.email_on_saved_search


def test_email_change_flow(auth_client, user, run_on_commit):
    old_email = user.email
    with run_on_commit():
        auth_client.post(
            reverse("accounts:email_change"),
            {"new_email": "New.Address@Example.com", "password": PASSWORD},
        )

    assert mail.outbox[0].to == ["new.address@example.com"]
    user.refresh_from_db()
    assert user.email == old_email

    path = re.search(r"/account/email/confirm/\S+/", mail.outbox[0].body).group(0)
    with run_on_commit():
        auth_client.get(path)

    user.refresh_from_db()
    assert user.email == "new.address@example.com"
    assert user.is_email_verified
    assert mail.outbox[1].to == [old_email]
    assert auth_client.get(path).status_code == 400


def test_email_change_requires_password(auth_client, user):
    response = auth_client.post(
        reverse("accounts:email_change"), {"new_email": "x@example.com", "password": "nope"}
    )

    assert "password" in response.context["email_form"].errors


def test_email_change_to_taken_address(auth_client, user):
    UserFactory(email="taken@example.com")

    response = auth_client.post(
        reverse("accounts:email_change"), {"new_email": "taken@example.com", "password": PASSWORD}
    )

    assert "new_email" in response.context["email_form"].errors


def test_email_change_confirm_fails_if_address_taken_meanwhile(client, user):
    token = tokens.make_email_change_token(user, "late@example.com")
    UserFactory(email="late@example.com")

    response = client.get(reverse("accounts:confirm_email_change", args=[token]))

    assert response.status_code == 400
    user.refresh_from_db()
    assert user.email != "late@example.com"


@pytest.fixture
def deleted_accounts():
    received = []

    def receiver(sender, user, **kwargs):
        received.append(user.pk)

    account_deleted.connect(receiver)
    yield received
    account_deleted.disconnect(receiver)


def test_delete_account_anonymizes_user(auth_client, user, deleted_accounts):
    auth_client.post(reverse("accounts:settings"), {**profile_data(), "avatar_file": image_file()})
    user.refresh_from_db()
    avatar_name = user.avatar.name

    response = auth_client.post(reverse("accounts:delete"), {"password": PASSWORD, "confirm": "on"})

    assert response.url == reverse("core:home")
    user.refresh_from_db()
    assert not user.is_active
    assert user.is_deleted
    assert user.email.endswith("@deleted.invalid")
    assert user.first_name == "Пользователь удалён"
    assert user.phone == ""
    assert not user.has_usable_password()
    assert not user.avatar.storage.exists(avatar_name)
    assert deleted_accounts == [user.pk]
    assert not user.notifications.exists()
    assert "_auth_user_id" not in auth_client.session


def test_deleted_email_can_register_again(client, user):
    from apps.accounts.services import delete_account

    email = user.email
    delete_account(user)

    assert not User.objects.filter(email=email).exists()


def test_delete_account_requires_password(auth_client, user):
    auth_client.post(reverse("accounts:delete"), {"password": "nope", "confirm": "on"})

    user.refresh_from_db()
    assert user.is_active
