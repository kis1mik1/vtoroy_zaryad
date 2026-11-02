import re

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import User

from .factories import PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def login(client, email, password=PASSWORD, **extra):
    return client.post(
        reverse("accounts:login"), {"username": email, "password": password, **extra}
    )


def test_login_by_email_in_any_case(client):
    user = UserFactory(email="ivan@example.com")

    response = login(client, "IVAN@example.com", remember="on")

    assert response.status_code == 302
    assert int(client.session["_auth_user_id"]) == user.pk
    assert client.session.get_expire_at_browser_close() is False


def test_login_without_remember_ends_with_browser(client):
    UserFactory(email="ivan@example.com")

    login(client, "ivan@example.com")

    assert client.session.get_expire_at_browser_close() is True


def test_login_redirects_to_next(client):
    UserFactory(email="ivan@example.com")

    response = login(client, "ivan@example.com", next="/rules/")

    assert response.url == "/rules/"


def test_login_wrong_password(client):
    UserFactory(email="ivan@example.com")

    response = login(client, "ivan@example.com", "wrong-password")

    assert response.status_code == 200
    assert "Неверная почта или пароль" in response.content.decode()


def test_login_blocked_after_five_failures(client):
    UserFactory(email="ivan@example.com")
    for _ in range(5):
        login(client, "ivan@example.com", "wrong-password")

    response = login(client, "ivan@example.com")

    assert "_auth_user_id" not in client.session
    assert "Слишком много неудачных попыток" in response.content.decode()


def test_successful_login_resets_failures(client):
    UserFactory(email="ivan@example.com")
    for _ in range(4):
        login(client, "ivan@example.com", "wrong-password")
    login(client, "ivan@example.com")
    client.logout()

    for _ in range(4):
        login(client, "ivan@example.com", "wrong-password")
    response = login(client, "ivan@example.com")

    assert response.status_code == 302


def test_deleted_user_cannot_login(client):
    UserFactory(email="ivan@example.com", is_active=False)

    response = login(client, "ivan@example.com")

    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_logout_requires_post(auth_client):
    assert auth_client.get(reverse("accounts:logout")).status_code == 405

    auth_client.post(reverse("accounts:logout"))

    assert "_auth_user_id" not in auth_client.session


def test_login_page_redirects_authenticated(auth_client):
    response = auth_client.get(reverse("accounts:login"))

    assert response.status_code == 302


def test_password_reset_full_flow(client, run_on_commit):
    user = UserFactory(email="ivan@example.com")

    with run_on_commit():
        response = client.post(reverse("accounts:password_reset"), {"email": "Ivan@example.com"})

    assert response.url == reverse("accounts:password_reset_done")
    assert len(mail.outbox) == 1
    link = re.search(r"http://\S+/account/password/reset/\S+/", mail.outbox[0].body).group(0)
    path = link.removeprefix("http://localhost:8000")

    form_page = client.get(path, follow=True)
    assert form_page.context["validlink"]
    client.post(
        form_page.redirect_chain[-1][0],
        {"new_password1": "Nakhodka-2026", "new_password2": "Nakhodka-2026"},
    )

    user.refresh_from_db()
    assert user.check_password("Nakhodka-2026")
    reused = client.get(path, follow=True)
    assert not reused.context["validlink"]


def test_password_reset_unknown_email_sends_nothing(client, run_on_commit):
    with run_on_commit():
        response = client.post(reverse("accounts:password_reset"), {"email": "nobody@example.com"})

    assert response.status_code == 302
    assert mail.outbox == []


def test_password_change_keeps_session_and_notifies(auth_client, user, run_on_commit):
    with run_on_commit():
        response = auth_client.post(
            reverse("accounts:password_change"),
            {
                "old_password": PASSWORD,
                "new_password1": "Artem-new-2026",
                "new_password2": "Artem-new-2026",
            },
        )

    assert response.url == reverse("accounts:security")
    user.refresh_from_db()
    assert user.check_password("Artem-new-2026")
    assert auth_client.get(reverse("accounts:settings")).status_code == 200
    assert mail.outbox[0].subject == "Пароль изменён"
    assert user.notifications.filter(title="Пароль изменён").exists()


def test_password_change_wrong_old_password(auth_client, user):
    response = auth_client.post(
        reverse("accounts:password_change"),
        {"old_password": "nope", "new_password1": "Artem-2026", "new_password2": "Artem-2026"},
    )

    assert response.status_code == 200
    assert "old_password" in response.context["password_form"].errors
    assert User.objects.get(pk=user.pk).check_password(PASSWORD)
