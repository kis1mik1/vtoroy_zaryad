from collections import defaultdict
from dataclasses import asdict, dataclass, field

import sklearn
from django.utils import timezone
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split

from .dataset import Example
from .text import OTHER, TextClassifier, build_pipeline, join_text


@dataclass(frozen=True)
class ClassScore:
    label: str
    precision: float
    recall: float
    f1: float
    support: int


@dataclass
class Report:
    size: int
    accuracy: float
    classes: list[ClassScore]
    other_precision: float
    other_recall: float
    cases: dict[str, tuple[int, int]] = field(default_factory=dict)
    mistakes: list[tuple[Example, str]] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "size": self.size,
            "accuracy": round(self.accuracy, 4),
            "other_precision": round(self.other_precision, 4),
            "other_recall": round(self.other_recall, 4),
        }


def _texts(examples: list[Example]) -> list[str]:
    return [join_text(example.title, example.description) for example in examples]


def evaluate(classifier: TextClassifier, examples: list[Example]) -> Report:
    expected = [example.label for example in examples]
    predicted = classifier.predict_many(_texts(examples))
    labels = sorted(set(expected) | set(predicted))
    precision, recall, f1, support = precision_recall_fscore_support(
        expected, predicted, labels=labels, zero_division=0
    )
    classes = [
        ClassScore(label, float(p), float(r), float(f), int(s))
        for label, p, r, f, s in zip(labels, precision, recall, f1, support, strict=True)
    ]
    is_other = [label == OTHER for label in expected]
    said_other = [label == OTHER for label in predicted]
    other_precision, other_recall, _, _ = precision_recall_fscore_support(
        is_other, said_other, average="binary", zero_division=0
    )
    cases: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    mistakes = []
    for example, label in zip(examples, predicted, strict=True):
        if example.case:
            cases[example.case][1] += 1
            cases[example.case][0] += int(label == example.label)
        if label != example.label:
            mistakes.append((example, label))
    return Report(
        size=len(examples),
        accuracy=float(accuracy_score(expected, predicted)),
        classes=classes,
        other_precision=float(other_precision),
        other_recall=float(other_recall),
        cases={case: (right, total) for case, (right, total) in sorted(cases.items())},
        mistakes=mistakes,
    )


def fit(examples: list[Example], meta: dict | None = None) -> TextClassifier:
    pipeline = build_pipeline()
    pipeline.fit(_texts(examples), [example.label for example in examples])
    return TextClassifier(pipeline, meta)


@dataclass
class TrainingResult:
    classifier: TextClassifier
    holdout: Report
    hard: Report | None


def train(
    examples: list[Example],
    hard: list[Example] | None = None,
    *,
    test_size: float = 0.2,
    seed: int = 2026,
) -> TrainingResult:
    train_part, test_part = train_test_split(
        examples,
        test_size=test_size,
        random_state=seed,
        stratify=[example.label for example in examples],
    )
    holdout = evaluate(fit(train_part), test_part)
    final = fit(examples)
    hard_report = evaluate(final, hard) if hard else None
    final.meta = {
        "trained_at": timezone.now().isoformat(),
        "examples": len(examples),
        "labels": final.labels,
        "sklearn": sklearn.__version__,
        "holdout": holdout.summary(),
        "hard": hard_report.summary() if hard_report else None,
        "classes": [asdict(score) for score in holdout.classes],
    }
    return TrainingResult(final, holdout, hard_report)
