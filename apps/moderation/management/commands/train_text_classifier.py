from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.moderation.ml.dataset import DATASET_PATH, HARD_SET_PATH, label_names, read_examples
from apps.moderation.ml.training import Report, train

CASE_NAMES = {
    "accessory": "аксессуары",
    "appliance": "бытовая техника",
    "bundle": "«продам всё за раз»",
    "car": "автоэлектроника",
    "english": "только латиница",
    "short": "короткие названия",
    "slang": "опечатки и сленг",
    "tech-words": "не техника, но со словами о технике",
    "everyday-words": "техника с бытовыми словами",
}


def percent(value: float) -> str:
    return f"{value * 100:5.1f}%"


class Command(BaseCommand):
    help = "Обучает текстовый классификатор объявлений и печатает метрики."

    def add_arguments(self, parser):
        parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
        parser.add_argument("--hard", type=Path, default=HARD_SET_PATH)
        parser.add_argument("--output", type=Path, default=Path(settings.MODERATION_TEXT_MODEL))
        parser.add_argument("--test-size", type=float, default=0.2)
        parser.add_argument("--seed", type=int, default=2026)
        parser.add_argument(
            "--show-mistakes", action="store_true", help="Показать ошибки на трудном наборе"
        )

    def handle(self, *args, dataset, hard, output, test_size, seed, show_mistakes, **options):
        if not dataset.exists():
            raise CommandError(
                f"Нет файла {dataset}. Соберите его: python manage.py build_moderation_dataset"
            )
        examples = read_examples(dataset)
        hard_examples = read_examples(hard) if hard.exists() else []
        self.stdout.write(f"Обучающий набор: {len(examples)} объявлений. Обучаю…")
        result = train(examples, hard_examples, test_size=test_size, seed=seed)

        self.names = label_names()
        self.report(f"Отложенная выборка ({int(test_size * 100)}% набора)", result.holdout)
        if result.hard:
            self.report("Трудный набор", result.hard)
            self.cases(result.hard)
            if show_mistakes:
                self.mistakes(result.hard)

        result.classifier.save(output)
        self.stdout.write(self.style.SUCCESS(f"Модель сохранена: {output}"))

    def report(self, title: str, report: Report) -> None:
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"{title}: {report.size} объявлений"))
        self.stdout.write(f"  {'Класс':<30} {'точность':>9} {'полнота':>9} {'F1':>7} {'кол-во':>7}")
        for score in report.classes:
            name = self.names.get(score.label, score.label)
            self.stdout.write(
                f"  {name:<30} {percent(score.precision):>9} {percent(score.recall):>9}"
                f" {score.f1:>7.3f} {score.support:>7}"
            )
        self.stdout.write(f"  Доля верных ответов: {percent(report.accuracy)}")
        self.stdout.write(
            f"  «Не электроника»: точность {percent(report.other_precision)},"
            f" полнота {percent(report.other_recall)}"
        )

    def cases(self, report: Report) -> None:
        self.stdout.write("  По типам случаев:")
        for case, (right, total) in report.cases.items():
            name = CASE_NAMES.get(case, case)
            self.stdout.write(f"    {name:<40} {right:>3} из {total:<3} {percent(right / total)}")

    def mistakes(self, report: Report) -> None:
        self.stdout.write("  Ошибки:")
        for example, predicted in report.mistakes:
            self.stdout.write(
                f"    «{example.title}»: ожидалось {self.names.get(example.label)},"
                f" модель — {self.names.get(predicted, predicted)}"
            )
