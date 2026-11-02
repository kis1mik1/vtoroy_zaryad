import time

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts import tokens
from apps.accounts.models import User
from apps.notifications.models import Notification

from .factories import PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def registration_data(**overrides):
    return {
        "first_name": "Анна",
        "email": "Anna@Example.com",
        "city": "",
        "password1": "Primorye-2026",
        "password2": "Primorye-2026",
        "agree": "on",
        **overrides,
    }


@pytest.fixture
def ussuriysk():
    from apps.core.models import City

    return City.objects.get(slug="ussuriysk")


def test_register_creates_user_logs_in_and_sends_letter(client, ussuriysk, run_on_commit):
    with run_on_commit():
        response = client.post(reverse("accounts:register"), registration_data(city=ussuriysk.pk))

    assert response.status_code == 302
    assert response.url == reverse("accounts:verify_sent")
    user = User.objects.get(email="anna@example.com")
    assert user.city == ussuriysk
    assert not user.is_email_verified
    assert client.get(reverse("accounts:settings")).context["user"] == user

    assert len(mail.outbox) == 1
    letter = mail.outbox[0]
    assert letter.to == ["anna@example.com"]
    assert "Подтвердите почту" in letter.subject
    assert "/account/verify/" in letter.body
    assert letter.alternatives[0][1] == "text/html"


def test_register_requires_agreement_and_city(client):
    response = client.post(reverse("accounts:register"), registration_data(agree=""))

    form = response.context["form"]
    assert "agree" in form.errors
    assert "city" in form.errors
    assert not User.objects.exists()


def test_register_rejects_taken_email_in_any_case(client, ussuriysk):
    UserFactory(email="anna@example.com")

    response = client.post(reverse("accounts:register"), registration_data(city=ussuriysk.pk))

    assert "уже зарегистрирован" in str(response.context["form"].errors["email"])


def test_register_rejects_weak_password(client, ussuriysk):
    data = registration_data(city=ussuriysk.pk, password1="12345678", password2="12345678")

    response = client.post(reverse("accounts:register"), data)

    assert "password2" in response.context["form"].errors


def test_register_rate_limited(client, ussuriysk):
    for _ in range(5):
        client.post(reverse("accounts:register"), registration_data(agree=""))

    response = client.post(reverse("accounts:register"), registration_data(agree=""))

    assert response.status_code == 429
    assert "Слишком много попыток" in response.content.decode()


def test_verify_email_with_valid_token(client, run_on_commit):
    user = UserFactory(unverified=True)
    token = tokens.make_verification_token(user)

    with run_on_commit():
        response = client.get(reverse("accounts:verify_email", args=[token]))

    user.refresh_from_db()
    assert user.is_email_verified
    assert response.status_code == 302
    assert Notification.objects.filter(user=user, title="Почта подтверждена").exists()


def test_verify_email_twice_keeps_first_date(client):
    user = UserFactory(unverified=True)
    token = tokens.make_verification_token(user)
    client.get(reverse("accounts:verify_email", args=[token]))
    user.refresh_from_db()
    verified_at = user.email_verified_at

    client.get(reverse("accounts:verify_email", args=[token]))

    user.refresh_from_db()
    assert user.email_verified_at == verified_at


def test_verify_email_expired_token(client, monkeypatch):
    user = UserFactory(unverified=True)
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() - 4 * 24 * 3600)
    token = tokens.make_verification_token(user)
    monkeypatch.setattr(time, "time", real_time)

    response = client.get(reverse("accounts:verify_email", args=[token]))

    assert response.status_code == 400
    assert "истёк" in response.content.decode()
    user.refresh_from_db()
    assert not user.is_email_verified


def test_verify_email_token_for_old_address_rejected(client):
    user = UserFactory(unverified=True)
    token = tokens.make_verification_token(user)
    user.email = "new@example.com"
    user.save()

    response = client.get(reverse("accounts:verify_email", args=[token]))

    assert response.status_code == 400
    user.refresh_from_db()
    assert not user.is_email_verified


def test_verify_email_tampered_token(client):
    user = UserFactory(unverified=True)
    token = tokens.make_verification_token(user)

    response = client.get(reverse("accounts:verify_email", args=[token[:-2] + "xx"]))

    assert response.status_code == 400
    assert "повреждена" in response.content.decode()


def test_token_of_other_purpose_rejected(client):
    user = UserFactory(unverified=True)
    token = tokens.make_email_change_token(user, "x@example.com")

    response = client.get(reverse("accounts:verify_email", args=[token]))

    assert response.status_code == 400


def test_resend_verification_limited_to_once_a_minute(client, run_on_commit):
    user = UserFactory(unverified=True)
    client.force_login(user)

    with run_on_commit():
        first = client.post(reverse("accounts:verify_resend"))
        second = client.post(reverse("accounts:verify_resend"))

    assert first.status_code == 302
    assert second.status_code == 429
    assert len(mail.outbox) == 1


def test_verify_sent_redirects_verified_user(auth_client):
    response = auth_client.get(reverse("accounts:verify_sent"))

    assert response.url == reverse("accounts:settings")


def test_registered_user_can_login_with_password(client):
    user = UserFactory(email="login@example.com")

    assert client.login(username="login@example.com", password=PASSWORD)
    assert user.pk
