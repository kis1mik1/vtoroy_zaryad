import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from PIL import Image

from apps.moderation.ml import images
from apps.moderation.ml.images import ImageScore
from apps.moderation.ml.thresholds import tune


def test_tune_respects_error_budgets():
    electronics = [0.2] + [0.9] * 98 + [0.95]
    other = [0.05] * 95 + [0.3] * 4 + [0.85]

    report = tune(electronics, other, max_false_pass=0.02, max_false_reject=0.01)

    assert report.photo_electronics == pytest.approx(0.301)
    assert report.other_passed == pytest.approx(0.01)
    assert report.electronics_passed == pytest.approx(0.99)
    assert report.photo_other == pytest.approx(0.199)
    assert report.electronics_caught == 0
    assert report.other_caught == pytest.approx(0.95)
    assert report.other_review == pytest.approx(0.04)
    assert 0.95 < report.auc <= 1


def test_other_threshold_stays_below_pass_threshold():
    report = tune([0.8, 0.9], [0.1, 0.2], max_false_pass=0.02, max_false_reject=0.01)

    assert report.photo_electronics == pytest.approx(0.201)
    assert report.photo_other == pytest.approx(0.191)
    assert report.electronics_passed == 1
    assert report.other_caught == pytest.approx(0.5)


def test_tune_needs_both_classes():
    with pytest.raises(ValueError, match="обоих классов"):
        tune([0.9], [], max_false_pass=0.02, max_false_reject=0.01)


class RedScorer:
    def score(self, photos):
        return [
            ImageScore(electronics=photo.getpixel((0, 0))[0] / 255, label="") for photo in photos
        ]


def save(folder, name, red):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (red, 0, 0)).save(folder / name)


def test_command_prints_thresholds_for_env(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(images, "availability", lambda: (True, "CLIP"))
    monkeypatch.setattr(images, "load_image_classifier", RedScorer)
    for index, red in enumerate((230, 240, 250, 220)):
        save(tmp_path / "техника", f"{index}.jpg", red)
    for index, red in enumerate((10, 20, 30, 40)):
        save(tmp_path / "не техника", f"{index}.png", red)
    (tmp_path / "техника" / "notes.txt").write_text("не фото")

    call_command("tune_clip_thresholds", str(tmp_path), "--show-mistakes")

    output = capsys.readouterr().out
    assert "Фото: техника 4, не техника 4" in output
    assert "ROC AUC: 1.000" in output
    assert "MODERATION_PHOTO_ELECTRONICS=0.158" in output
    assert "MODERATION_PHOTO_OTHER=0.148" in output
    assert "Техника с самой низкой оценкой:" in output


def test_command_explains_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "availability", lambda: (True, "CLIP"))
    monkeypatch.setattr(images, "load_image_classifier", RedScorer)
    save(tmp_path / "техника", "1.jpg", 200)

    with pytest.raises(CommandError, match="не техника"):
        call_command("tune_clip_thresholds", str(tmp_path))


def test_command_requires_model(tmp_path, monkeypatch):
    monkeypatch.setattr(images, "availability", lambda: (False, "Не скачаны веса CLIP"))

    with pytest.raises(CommandError, match="Не скачаны веса CLIP"):
        call_command("tune_clip_thresholds", str(tmp_path))
