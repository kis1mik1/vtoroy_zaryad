from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
from django.conf import settings
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, Pipeline

from ..text import normalize

OTHER = "other"


@dataclass(frozen=True)
class TextPrediction:
    label: str
    confidence: float
    electronics: float
    probabilities: dict[str, float]

    def probability(self, label: str) -> float:
        return self.probabilities.get(label, 0.0)

    @property
    def best_category(self) -> str:
        categories = {k: v for k, v in self.probabilities.items() if k != OTHER}
        return max(categories, key=categories.get)


def build_pipeline() -> Pipeline:
    features = FeatureUnion(
        [
            (
                "words",
                TfidfVectorizer(
                    preprocessor=normalize, ngram_range=(1, 2), min_df=2, sublinear_tf=True
                ),
            ),
            (
                "chars",
                TfidfVectorizer(
                    preprocessor=normalize,
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    min_df=2,
                    sublinear_tf=True,
                ),
            ),
        ]
    )
    model = LogisticRegression(C=10, max_iter=3000, class_weight="balanced")
    return Pipeline([("features", features), ("model", model)])


def join_text(title: str, description: str) -> str:
    return f"{title}\n{description}"


class TextClassifier:
    def __init__(self, pipeline: Pipeline, meta: dict | None = None):
        self.pipeline = pipeline
        self.meta = meta or {}

    @property
    def labels(self) -> list[str]:
        return list(self.pipeline.classes_)

    def predict_many(self, texts: list[str]) -> list[str]:
        return list(self.pipeline.predict(texts))

    def predict(self, title: str, description: str) -> TextPrediction:
        row = self.pipeline.predict_proba([join_text(title, description)])[0]
        probabilities = {label: float(p) for label, p in zip(self.labels, row, strict=True)}
        label = max(probabilities, key=probabilities.get)
        return TextPrediction(
            label=label,
            confidence=probabilities[label],
            electronics=1.0 - probabilities.get(OTHER, 0.0),
            probabilities=probabilities,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": self.pipeline, "meta": self.meta}, path)

    @classmethod
    def load(cls, path: Path) -> "TextClassifier":
        bundle = joblib.load(path)
        return cls(bundle["pipeline"], bundle["meta"])


@lru_cache(maxsize=2)
def _load_cached(path: str, mtime: float) -> TextClassifier:
    return TextClassifier.load(Path(path))


def load_text_classifier() -> TextClassifier | None:
    path = Path(settings.MODERATION_TEXT_MODEL)
    if not path.exists():
        return None
    return _load_cached(str(path), path.stat().st_mtime)
