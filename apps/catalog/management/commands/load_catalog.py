from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.loader import CatalogError, CatalogLoader
from apps.catalog.selectors import clear_catalog_cache


class Command(BaseCommand):
    help = "Загружает справочник категорий, брендов и моделей из seed/catalog."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default=str(Path(settings.BASE_DIR) / "seed" / "catalog"),
            help="Папка с categories.json, brands.json и models/*.json",
        )

    def handle(self, *args, path, **options):
        try:
            stats = CatalogLoader(Path(path)).run()
        except CatalogError as exc:
            raise CommandError(str(exc)) from exc
        clear_catalog_cache()
        self.stdout.write(
            self.style.SUCCESS(
                "Справочник загружен: категорий {categories}, характеристик {attributes}, "
                "брендов {brands}, моделей {models}.".format(**stats)
            )
        )
