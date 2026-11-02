import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.moderation.permissions import MODERATORS_GROUP, REVIEW_AD

pytestmark = pytest.mark.django_db


def test_create_moderator_from_scratch(monkeypatch):
    monkeypatch.setenv("MODERATOR_PASSWORD", "Krepkiy-parol-2026")

    call_command("create_moderator", "Mod@Example.com", name="Ирина")

    user = User.objects.get(email="mod@example.com")
    assert user.is_staff
    assert user.is_email_verified
    assert user.check_password("Krepkiy-parol-2026")
    assert user.groups.filter(name=MODERATORS_GROUP).exists()
    assert user.has_perm(REVIEW_AD)


def test_create_moderator_promotes_existing_user():
    user = UserFactory()

    call_command("create_moderator", user.email)

    user.refresh_from_db()
    assert user.is_staff
    assert user.has_perm(REVIEW_AD)
