from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand

from apps.moderation.ml.dataset import DATASET_PATH, DatasetBuilder, label_names, write_examples


class Command(BaseCommand):
    help = "Собирает обучающий набор объявлений для текстового классификатора."

    def add_arguments(self, parser):
        parser.add_argument("--seed", type=int, default=2026, help="Начальное значение генератора")
        parser.add_argument("--output", type=Path, default=DATASET_PATH)

    def handle(self, *args, seed, output, **options):
        examples = DatasetBuilder(seed).build()
        write_examples(output, examples)
        names = label_names()
        counts = Counter(example.label for example in examples)
        for label, count in sorted(counts.items()):
            self.stdout.write(f"  {names.get(label, label):<30} {count:>5}")
        self.stdout.write(self.style.SUCCESS(f"Записано {len(examples)} объявлений в {output}"))
