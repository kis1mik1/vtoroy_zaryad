from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from PIL import Image, UnidentifiedImageError
from pillow_heif import register_heif_opener

from apps.moderation.ml import images
from apps.moderation.ml.thresholds import tune

ELECTRONICS_DIRS = ("техника", "electronics")
OTHER_DIRS = ("не техника", "не_техника", "other")
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
BATCH = 16
WORST = 5


def _find(root: Path, names: tuple[str, ...]) -> Path:
    for name in names:
        if (root / name).is_dir():
            return root / name
    raise CommandError(f"В {root} нет папки «{names[0]}» (или {', '.join(names[1:])}).")


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


class Command(BaseCommand):
    help = "Подбирает пороги проверки фото CLIP по папкам «техника» и «не техника»."

    def add_arguments(self, parser):
        parser.add_argument("folder", type=Path, help="Папка с подпапками «техника» и «не техника»")
        parser.add_argument(
            "--max-false-pass",
            type=float,
            default=0.02,
            help="Какую долю «не техники» допустимо пропустить без модератора (0.02 = 2%%)",
        )
        parser.add_argument(
            "--max-false-reject",
            type=float,
            default=0.01,
            help="Какую долю техники допустимо счесть явно «не техникой» (0.01 = 1%%)",
        )
        parser.add_argument("--show-mistakes", action="store_true", help="Показать спорные фото")

    def handle(self, *args, folder, max_false_pass, max_false_reject, show_mistakes, **options):
        ready, note = images.availability()
        if not ready:
            raise CommandError(note)
        register_heif_opener()
        classifier = images.load_image_classifier()
        electronics = self.score(classifier, _find(folder, ELECTRONICS_DIRS))
        other = self.score(classifier, _find(folder, OTHER_DIRS))
        self.stdout.write(f"Фото: техника {len(electronics)}, не техника {len(other)}")
        try:
            report = tune(
                [score for _, score in electronics],
                [score for _, score in other],
                max_false_pass=max_false_pass,
                max_false_reject=max_false_reject,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(f"ROC AUC: {report.auc:.3f} (1.0 — классы разделяются идеально)\n")
        self.stdout.write(f"{'порог':>6} {'техника ≥ порога':>18} {'не техника ≥ порога':>21}")
        for threshold, electronics_share, other_share in report.table:
            self.stdout.write(
                f"{threshold:>6.2f} {_percent(electronics_share):>18} {_percent(other_share):>21}"
            )

        limits = settings.MODERATION_THRESHOLDS
        self.stdout.write("\nРекомендация:")
        self.stdout.write(
            f"  photo_electronics = {report.photo_electronics:.3f} "
            f"(сейчас {limits['photo_electronics']}): без модератора проходит "
            f"{_percent(report.electronics_passed)} техники и {_percent(report.other_passed)} "
            "не техники"
        )
        self.stdout.write(
            f"  photo_other = {report.photo_other:.3f} (сейчас {limits['photo_other']}): "
            f"явной «не техникой» считается {_percent(report.other_caught)} не техники и "
            f"{_percent(report.electronics_caught)} техники"
        )
        self.stdout.write(
            f"  остальное уйдёт модератору: {_percent(report.electronics_review)} техники и "
            f"{_percent(report.other_review)} не техники"
        )
        self.stdout.write("\nСтроки для .env:")
        self.stdout.write(f"MODERATION_PHOTO_ELECTRONICS={report.photo_electronics:.3f}")
        self.stdout.write(f"MODERATION_PHOTO_OTHER={report.photo_other:.3f}")

        if show_mistakes:
            self.stdout.write("\nТехника с самой низкой оценкой:")
            for path, score in sorted(electronics, key=lambda item: item[1])[:WORST]:
                self.stdout.write(f"  {score:.3f}  {path}")
            self.stdout.write("Не техника с самой высокой оценкой:")
            for path, score in sorted(other, key=lambda item: -item[1])[:WORST]:
                self.stdout.write(f"  {score:.3f}  {path}")

    def score(self, classifier, folder: Path) -> list[tuple[Path, float]]:
        paths = sorted(p for p in folder.rglob("*") if p.suffix.lower() in EXTENSIONS)
        results = []
        for start in range(0, len(paths), BATCH):
            batch, loaded = paths[start : start + BATCH], []
            for path in batch:
                try:
                    with Image.open(path) as image:
                        loaded.append((path, image.convert("RGB")))
                except (UnidentifiedImageError, OSError):
                    self.stderr.write(f"Пропущено, не изображение: {path}")
            scores = classifier.score([image for _, image in loaded])
            results.extend(
                (path, score.electronics) for (path, _), score in zip(loaded, scores, strict=True)
            )
        return results
