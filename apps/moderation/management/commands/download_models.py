import shutil
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image

from apps.moderation.ml import images


class Command(BaseCommand):
    help = "Скачивает веса CLIP для проверки фото и проверяет, что модель загружается."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Скачать заново")

    def handle(self, *args, force, **options):
        if not images.libraries_installed():
            raise CommandError("Не установлены torch и open_clip: см. requirements-ml.txt")
        existing = images.weights_path()
        if existing and not force:
            self.stdout.write(f"Веса уже скачаны: {existing}")
        else:
            self.download()
        started = time.monotonic()
        classifier = images.load_image_classifier()
        classifier.score([Image.new("RGB", (224, 224), "white")])
        elapsed = time.monotonic() - started
        self.stdout.write(self.style.SUCCESS(f"Модель загружена и работает ({elapsed:.1f} с)."))

    def download(self) -> None:
        import open_clip

        model, tag = settings.MODERATION_CLIP_MODEL, settings.MODERATION_CLIP_WEIGHTS
        config = open_clip.get_pretrained_cfg(model, tag)
        if not config:
            raise CommandError(f"Для {model} нет весов «{tag}», см. open_clip.list_pretrained()")
        target = Path(settings.MODERATION_CLIP_DIR)
        target.mkdir(parents=True, exist_ok=True)
        self.stdout.write(f"Скачиваю {model} ({tag})…")
        with tempfile.TemporaryDirectory(dir=target) as cache:
            source = Path(open_clip.download_pretrained(config, cache_dir=cache))
            suffix = ".safetensors" if source.suffix == ".safetensors" else ".bin"
            destination = target / f"{model}-{tag}{suffix}"
            shutil.copyfile(source, destination)
        size = destination.stat().st_size / 1024 / 1024
        self.stdout.write(f"Сохранено: {destination} ({size:.0f} МБ)")
