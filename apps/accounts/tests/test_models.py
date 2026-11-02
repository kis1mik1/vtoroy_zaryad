import pytest
from django.contrib.auth import authenticate
from django.db import IntegrityError

from apps.accounts.models import User

pytestmark = pytest.mark.django_db


def test_create_user_normalizes_email():
    user = User.objects.create_user("  Ivan@Mail.RU ", "Secret-pass-42", first_name="Иван")

    assert user.email == "ivan@mail.ru"
    assert user.check_password("Secret-pass-42")
    assert not user.is_staff
    assert user.get_full_name() == "Иван"


def test_create_user_requires_email():
    with pytest.raises(ValueError, match="почту"):
        User.objects.create_user("", "Secret-pass-42")


def test_create_superuser_sets_flags():
    user = User.objects.create_superuser("admin@example.com", "Secret-pass-42", first_name="А")

    assert user.is_staff
    assert user.is_superuser


def test_email_is_unique_regardless_of_case():
    User.objects.create_user("same@example.com", "Secret-pass-42", first_name="А")

    with pytest.raises(IntegrityError):
        User.objects.create_user("SAME@example.com", "Secret-pass-42", first_name="Б")


def test_authenticate_by_email_in_any_case():
    User.objects.create_user("login@example.com", "Secret-pass-42", first_name="А")

    assert authenticate(username="LOGIN@example.com", password="Secret-pass-42") is not None
    assert authenticate(username="login@example.com", password="wrong") is None
