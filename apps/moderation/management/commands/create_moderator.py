import os
from getpass import getpass

from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.moderation.permissions import MODERATORS_GROUP, ensure_moderators_group

PASSWORD_ENV = "MODERATOR_PASSWORD"


class Command(BaseCommand):
    help = "Создаёт модератора или выдаёт права модератора существующему пользователю."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--name", default="Модератор", help="Имя для нового пользователя")

    def handle(self, *args, email, name, **options):
        User = get_user_model()
        email = User.objects.normalize_email(email).lower()
        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            user = User(email=email, first_name=name)
            user.set_password(self.password(user))
        user.is_staff = True
        user.is_active = True
        user.email_verified_at = user.email_verified_at or timezone.now()
        user.save()
        user.groups.add(ensure_moderators_group())
        action = "Создан модератор" if created else "Права модератора выданы"
        message = f"{action}: {user.email} (группа «{MODERATORS_GROUP}»)"
        self.stdout.write(self.style.SUCCESS(message))

    def password(self, user) -> str:
        password = os.environ.get(PASSWORD_ENV)
        if password is None:
            password = getpass("Пароль: ")
            if password != getpass("Пароль ещё раз: "):
                raise CommandError("Пароли не совпадают.")
        try:
            password_validation.validate_password(password, user)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        return password
