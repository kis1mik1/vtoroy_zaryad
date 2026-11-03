import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.moderation.permissions import REVIEW_AD

pytestmark = pytest.mark.django_db


def test_prepare_demo_creates_accounts_and_data(monkeypatch, settings, tmp_path):
    settings.MODERATION_TEXT_MODEL = tmp_path / "text-classifier.joblib"
    monkeypatch.setenv("DEMO_ADMIN_PASSWORD", "Admin-pass-2026")
    monkeypatch.setenv("DEMO_MODERATOR_PASSWORD", "Moder-pass-2026")
    monkeypatch.setenv("DEMO_USER_PASSWORD", "Demo-pass-2026")

    call_command("prepare_demo", skip_models=True, ads=8)
    call_command("prepare_demo", skip_models=True, ads=8)

    admin = User.objects.get(email="admin@example.com")
    assert admin.is_superuser
    assert admin.check_password("Admin-pass-2026")
    moderator = User.objects.get(email="moder@example.com")
    assert moderator.has_perm(REVIEW_AD)
    assert moderator.check_password("Moder-pass-2026")
    seller = User.objects.get(email="seller01@demo.vtoroy-zaryad.ru")
    assert seller.check_password("Demo-pass-2026")
    assert User.objects.filter(email__endswith="@demo.vtoroy-zaryad.ru").count() == 30
    assert settings.MODERATION_TEXT_MODEL.exists()
