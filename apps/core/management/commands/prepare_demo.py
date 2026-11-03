import os
import secrets

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.ads.demo import DEMO_DOMAIN
from apps.moderation.ml import images


def _credential(name: str) -> str:
    return os.environ.get(name) or secrets.token_urlsafe(9)


class Command(BaseCommand):
    help = (
        "Готовит сайт к показу: миграции, справочник, классификатор, веса CLIP, демо-данные, "
        "модератор и администратор."
    )

    def add_arguments(self, parser):
        parser.add_argument("--skip-models", action="store_true", help="Не скачивать веса CLIP")
        parser.add_argument("--ads", type=int, default=300)

    def step(self, title: str) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n→ {title}"))

    def handle(self, *args, skip_models, ads, **options):
        self.step("Миграции")
        call_command("migrate", interactive=False, verbosity=0)
        self.step("Справочник")
        call_command("load_catalog")
        self.step("Текстовый классификатор")
        call_command("train_text_classifier")
        self.step("Веса CLIP для проверки фото")
        if skip_models:
            self.stdout.write("Пропущено (--skip-models).")
        elif not images.libraries_installed():
            self.stdout.write(self.style.WARNING("torch и open_clip не установлены, пропущено."))
        else:
            try:
                call_command("download_models")
            except CommandError as exc:
                message = f"Не удалось: {exc}. Фото будет проверять модератор."
                self.stdout.write(self.style.WARNING(message))

        demo_password = _credential("DEMO_USER_PASSWORD")
        self.step("Демо-данные")
        call_command("seed_demo", clear=True, ads=ads, password=demo_password)

        moderator_email = os.environ.get("DEMO_MODERATOR_EMAIL", "moder@example.com")
        moderator_password = _credential("DEMO_MODERATOR_PASSWORD")
        self.step("Модератор")
        os.environ["MODERATOR_PASSWORD"] = moderator_password
        call_command("create_moderator", moderator_email)
        self._set_password(moderator_email, moderator_password)

        admin_email = os.environ.get("DEMO_ADMIN_EMAIL", "admin@example.com")
        admin_password = _credential("DEMO_ADMIN_PASSWORD")
        self.step("Администратор")
        self._admin(admin_email, admin_password)

        self.stdout.write(self.style.SUCCESS("\nГотово. Входы для показа:"))
        rows = (
            ("Администратор", admin_email, admin_password),
            ("Модератор", moderator_email, moderator_password),
            ("Продавцы", f"seller01…seller30@{DEMO_DOMAIN}", demo_password),
        )
        for role, email, password in rows:
            self.stdout.write(f"  {role:<14} {email:<40} пароль: {password}")

    def _set_password(self, email: str, password: str) -> None:
        user = get_user_model().objects.get(email=email)
        user.set_password(password)
        user.save(update_fields=["password"])

    def _admin(self, email: str, password: str) -> None:
        User = get_user_model()
        user = User.objects.filter(email=email).first() or User(email=email, first_name="Админ")
        user.is_staff = user.is_superuser = user.is_active = True
        user.email_verified_at = user.email_verified_at or timezone.now()
        user.set_password(password)
        user.save()
        self.stdout.write(f"Администратор: {email}")
