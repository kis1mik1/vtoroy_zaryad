from django.core.management.base import BaseCommand, CommandError

from apps.ads.demo import DEMO_DOMAIN, DemoBuilder
from apps.catalog.models import DeviceModel


class Command(BaseCommand):
    help = "Создаёт демонстрационных продавцов и объявления."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=30)
        parser.add_argument("--ads", type=int, default=300)
        parser.add_argument("--seed", type=int, default=2026, help="Начальное значение генератора")
        parser.add_argument(
            "--clear", action="store_true", help=f"Удалить прежние демо-данные (@{DEMO_DOMAIN})"
        )

    def handle(self, *args, users, ads, seed, clear, **options):
        if not DeviceModel.objects.exists():
            raise CommandError("Справочник пуст. Сначала выполните python manage.py load_catalog")
        builder = DemoBuilder(seed)
        if clear:
            removed = builder.clear()
            self.stdout.write(f"Удалено демо-пользователей: {removed}")
        sellers = builder.users(users)
        created = builder.ads(sellers, ads)
        history = builder.price_history(created)
        favorites = builder.favorites(sellers, created)
        stats = builder.finish(created)
        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: продавцов {len(sellers)}, объявлений {len(created)}, "
                f"изменений цены {history}, в избранном {favorites}, групп цен {stats}."
            )
        )
