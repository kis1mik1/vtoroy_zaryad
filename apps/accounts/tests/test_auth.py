import re

import pytest
from django.core import mail
from django.urls import reverse

from apps.accounts.models import User
from apps.core.captcha import TEST_TOKEN

from .factories import PASSWORD, UserFactory

pytestmark = pytest.mark.django_db


def login(client, email, password=PASSWORD, ip="127.0.0.1", **extra):
    return client.post(
        reverse("accounts:login"),
        {"username": email, "password": password, **extra},
        REMOTE_ADDR=ip,
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


def fail_login(client, email, times, ip="127.0.0.1"):
    for _ in range(times):
        login(client, email, "wrong-password", ip=ip)


def test_no_captcha_before_three_failures(client):
    UserFactory(email="ivan@example.com")
    fail_login(client, "ivan@example.com", 1)

    response = login(client, "ivan@example.com", "wrong-password")

    assert not response.context["form"].captcha_required
    assert "smart-token" not in response.content.decode()


def test_captcha_and_reset_link_after_three_failures(client):
    UserFactory(email="ivan@example.com")
    fail_login(client, "ivan@example.com", 2)

    response = login(client, "ivan@example.com", "wrong-password")

    html = response.content.decode()
    assert response.context["form"].captcha_required
    assert 'name="smart-token"' in html
    assert "Не получается войти?" in html
    assert reverse("accounts:password_reset") in html


def test_correct_password_without_captcha_rejected_after_failures(client):
    UserFactory(email="ivan@example.com")
    fail_login(client, "ivan@example.com", 3)

    response = login(client, "ivan@example.com")

    assert "_auth_user_id" not in client.session
    assert "Подтвердите, что вы не робот" in response.content.decode()


def test_owner_logs_in_with_captcha_and_counter_resets(client):
    UserFactory(email="ivan@example.com")
    fail_login(client, "ivan@example.com", 5)

    response = login(client, "ivan@example.com", **{"smart-token": TEST_TOKEN})

    assert response.status_code == 302
    client.logout()
    assert not login(client, "ivan@example.com", "wrong").context["form"].captcha_required


def test_wrong_password_with_captcha_still_rejected(client):
    UserFactory(email="ivan@example.com")
    fail_login(client, "ivan@example.com", 3)

    response = login(client, "ivan@example.com", "wrong", **{"smart-token": TEST_TOKEN})

    assert "_auth_user_id" not in client.session
    assert "Неверная почта или пароль" in response.content.decode()


def test_failures_counted_per_email_and_ip(client):
    UserFactory(email="ivan@example.com")
    fail_login(client, "ivan@example.com", 3, ip="10.0.0.1")

    other_ip = login(client, "ivan@example.com", ip="10.0.0.2")
    assert other_ip.status_code == 302
    client.logout()

    other_email = login(client, "anna@example.com", "x", ip="10.0.0.1")
    assert not other_email.context["form"].captcha_required


def test_ip_limited_after_thirty_attempts(client):
    UserFactory(email="ivan@example.com")
    fail_login(client, "nobody@example.com", 30)

    response = login(client, "ivan@example.com", **{"smart-token": TEST_TOKEN})

    assert response.status_code == 429
    assert "_auth_user_id" not in client.session
    assert "Слишком много попыток. Повторите через" in response.content.decode()
    assert int(response["Retry-After"]) <= 15 * 60 + 1


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
