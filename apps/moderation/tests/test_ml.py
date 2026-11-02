import numpy as np
import pytest
from django.core.management import call_command
from django.test import override_settings
from PIL import Image

from apps.moderation.ml import images
from apps.moderation.ml.dataset import (
    DATASET_PATH,
    HARD_SET_PATH,
    DatasetBuilder,
    category_leaves,
    read_examples,
    write_examples,
)
from apps.moderation.ml.text import OTHER, TextClassifier
from apps.moderation.ml.training import evaluate, train

LABELS = {*category_leaves(), OTHER}


def test_dataset_is_reproducible_and_balanced():
    first, second = DatasetBuilder(1).build(), DatasetBuilder(1).build()

    assert first == second
    assert {example.label for example in first} == LABELS
    assert all(example.title and example.description for example in first)


def test_committed_datasets_are_valid():
    examples, hard = read_examples(DATASET_PATH), read_examples(HARD_SET_PATH)

    assert len(examples) > 4000
    assert len(hard) >= 100
    assert {example.label for example in hard} <= LABELS
    assert all(example.case for example in hard)


def test_training_saves_working_model(tmp_path):
    examples = DatasetBuilder(3).build()[:900]
    hard = read_examples(HARD_SET_PATH)

    result = train(examples, hard, test_size=0.25)
    path = tmp_path / "model.joblib"
    result.classifier.save(path)
    loaded = TextClassifier.load(path)

    prediction = loaded.predict("Шуба норковая", "Носила один сезон, размер 46.")
    assert prediction.label == OTHER
    assert prediction.electronics < 0.5
    assert result.holdout.accuracy > 0.9
    assert loaded.meta["hard"]["accuracy"] == round(evaluate(loaded, hard).accuracy, 4)


def test_training_command_prints_metrics(tmp_path, capsys):
    dataset = tmp_path / "ads.csv"
    write_examples(dataset, DatasetBuilder(5).build()[:700])
    output = tmp_path / "model.joblib"

    call_command("train_text_classifier", dataset=dataset, output=output)

    text = capsys.readouterr().out
    assert "Отложенная выборка" in text
    assert "Трудный набор" in text
    assert "опечатки и сленг" in text
    assert output.exists()


class FakeEncoder:
    def encode_texts(self, texts):
        vectors = np.zeros((len(texts), len(texts)))
        np.fill_diagonal(vectors, 1)
        return vectors

    def encode_images(self, pictures):
        size = len(images.ELECTRONICS) + len(images.NOT_ELECTRONICS)
        vectors = np.zeros((len(pictures), size))
        for row, picture in enumerate(pictures):
            vectors[row, 0 if picture.getpixel((0, 0))[0] > 128 else size - 1] = 1
        return vectors


def test_image_classifier_scores_prompts():
    classifier = images.ImageClassifier(FakeEncoder())

    phone, pills = classifier.score(
        [Image.new("RGB", (8, 8), "white"), Image.new("RGB", (8, 8), "black")]
    )

    assert phone.label == "смартфон"
    assert phone.electronics > 0.99
    assert pills.label == "таблетки"
    assert pills.electronics < 0.01


@override_settings(MODERATION_CLIP_ENABLED=False)
def test_disabled_clip_is_reported():
    assert images.availability() == (False, "Проверка фото отключена в настройках")


def test_missing_weights_are_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "libraries_installed", lambda: True)
    with override_settings(MODERATION_CLIP_DIR=tmp_path):
        ready, note = images.availability()

    assert not ready
    assert "download_models" in note


def test_real_open_clip_architecture_runs():
    pytest.importorskip("open_clip")
    encoder = images.OpenClipEncoder("ViT-B-32", None, threads=1)

    scores = images.ImageClassifier(encoder).score([Image.new("RGB", (300, 200), "gray")])

    assert 0 <= scores[0].electronics <= 1
