from dataclasses import dataclass, field

import pytest

from apps.accounts.tests.factories import UserFactory
from apps.ads.tests.conftest import phones  # noqa: F401
from apps.moderation import pipeline
from apps.moderation.ml.images import ImageCheckUnavailable, ImageScore
from apps.moderation.ml.text import OTHER, TextPrediction
from apps.moderation.permissions import ensure_moderators_group


@dataclass
class FakeModels:
    text: dict[str, float] = field(default_factory=lambda: {"phones-test": 0.95, OTHER: 0.05})
    photos: list[float] = field(default_factory=lambda: [0.95])
    photo_label: str = "смартфон"
    images_error: str = ""
    text_ready: bool = True

    def predict(self, title, description):
        label = max(self.text, key=self.text.get)
        return TextPrediction(
            label=label,
            confidence=self.text[label],
            electronics=1 - self.text.get(OTHER, 0.0),
            probabilities=dict(self.text),
        )

    def score(self, images):
        return [
            ImageScore(electronics=self.photos[index % len(self.photos)], label=self.photo_label)
            for index in range(len(images))
        ]


@pytest.fixture
def models(monkeypatch):
    fake = FakeModels()

    def load_text():
        return fake if fake.text_ready else None

    def load_images():
        if fake.images_error:
            raise ImageCheckUnavailable(fake.images_error)
        return fake

    monkeypatch.setattr(pipeline, "load_text_classifier", load_text)
    monkeypatch.setattr(pipeline, "load_image_classifier", load_images)
    return fake


@pytest.fixture
def moderator(db):
    user = UserFactory(is_staff=True, first_name="Ирина")
    user.groups.add(ensure_moderators_group())
    return user


@pytest.fixture
def moderator_client(client, moderator):
    client.force_login(moderator)
    return client
