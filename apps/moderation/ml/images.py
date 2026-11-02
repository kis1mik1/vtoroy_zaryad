import importlib.util
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
from django.conf import settings
from PIL import Image

logger = logging.getLogger(__name__)

ELECTRONICS = (
    ("смартфон", "a photo of a smartphone"),
    ("кнопочный телефон", "a photo of a push-button mobile phone"),
    ("ноутбук", "a photo of a laptop computer"),
    ("системный блок", "a photo of a desktop computer case"),
    ("монитор", "a photo of a computer monitor"),
    ("клавиатура", "a photo of a computer keyboard"),
    ("компьютерная мышь", "a photo of a computer mouse"),
    ("видеокарта", "a photo of a graphics card"),
    ("комплектующие", "a photo of computer parts: a processor, memory or a motherboard"),
    ("накопитель", "a photo of a hard drive or an SSD"),
    ("планшет", "a photo of a tablet computer"),
    ("электронная книга", "a photo of an e-book reader"),
    ("наушники", "a photo of headphones or earbuds"),
    ("колонка", "a photo of a speaker"),
    ("телевизор", "a photo of a television"),
    ("проектор", "a photo of a video projector"),
    ("игровая приставка", "a photo of a video game console"),
    ("геймпад", "a photo of a gamepad"),
    ("игра", "a photo of a video game box or disc"),
    ("фотоаппарат", "a photo of a camera"),
    ("объектив", "a photo of a camera lens"),
    ("экшн-камера", "a photo of an action camera"),
    ("умные часы", "a photo of a smartwatch or a fitness band"),
    ("чехол или стекло", "a photo of a phone case or a screen protector"),
    ("зарядка или кабель", "a photo of a charger and a cable"),
    ("повербанк", "a photo of a power bank"),
    ("коробка от техники", "a photo of an electronics box"),
    ("экран устройства", "a photo of a device screen with settings"),
)

NOT_ELECTRONICS = (
    ("одежда", "a photo of clothes"),
    ("обувь", "a photo of shoes"),
    ("автомобиль", "a photo of a car"),
    ("автозапчасти", "a photo of car parts or tires"),
    ("квартира", "a photo of an apartment interior"),
    ("дом", "a photo of a house"),
    ("собака", "a photo of a dog"),
    ("кошка", "a photo of a cat"),
    ("мебель", "a photo of furniture"),
    ("бытовая техника", "a photo of a home appliance such as a fridge or a washing machine"),
    ("еда", "a photo of food"),
    ("растение", "a photo of a plant"),
    ("человек", "a photo of a person"),
    ("игрушки", "a photo of children's toys"),
    ("косметика", "a photo of cosmetics"),
    ("украшения", "a photo of jewelry"),
    ("велосипед", "a photo of a bicycle"),
    ("инструменты", "a photo of tools"),
    ("книги", "a photo of books"),
    ("документ или текст", "a photo of a document or a text"),
    ("пейзаж", "a photo of a landscape"),
    ("оружие", "a photo of a weapon"),
    ("таблетки", "a photo of pills"),
)

WEIGHT_SUFFIXES = (".safetensors", ".bin")


class ImageCheckUnavailable(Exception):
    pass


@dataclass(frozen=True)
class ImageScore:
    electronics: float
    label: str


class Encoder(Protocol):
    def encode_images(self, images: list[Image.Image]) -> np.ndarray: ...

    def encode_texts(self, texts: list[str]) -> np.ndarray: ...


def _unit(vectors: np.ndarray) -> np.ndarray:
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = np.exp(logits - logits.max(axis=1, keepdims=True))
    return shifted / shifted.sum(axis=1, keepdims=True)


class ImageClassifier:
    temperature = 100.0

    def __init__(self, encoder: Encoder):
        self.encoder = encoder
        prompts = ELECTRONICS + NOT_ELECTRONICS
        self.labels = [label for label, _ in prompts]
        self.electronics_mask = np.array(
            [index < len(ELECTRONICS) for index in range(len(prompts))]
        )
        self.text_features = _unit(self.encoder.encode_texts([text for _, text in prompts]))

    def score(self, images: list[Image.Image]) -> list[ImageScore]:
        if not images:
            return []
        features = _unit(self.encoder.encode_images(images))
        probabilities = _softmax(self.temperature * features @ self.text_features.T)
        return [
            ImageScore(
                electronics=float(row[self.electronics_mask].sum()),
                label=self.labels[int(row.argmax())],
            )
            for row in probabilities
        ]


class OpenClipEncoder:
    def __init__(self, model_name: str, weights: Path | None, threads: int):
        import open_clip
        import torch

        torch.set_num_threads(threads)
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name, pretrained=str(weights) if weights else None
        )
        model.eval()
        self.torch = torch
        self.model = model
        self.preprocess = preprocess
        self.tokenizer = open_clip.get_tokenizer(model_name)

    def encode_images(self, images: list[Image.Image]) -> np.ndarray:
        batch = self.torch.stack([self.preprocess(image.convert("RGB")) for image in images])
        with self.torch.inference_mode():
            return self.model.encode_image(batch).float().numpy()

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        with self.torch.inference_mode():
            return self.model.encode_text(self.tokenizer(texts)).float().numpy()


def libraries_installed() -> bool:
    return all(importlib.util.find_spec(name) for name in ("torch", "open_clip"))


def weights_path() -> Path | None:
    stem = f"{settings.MODERATION_CLIP_MODEL}-{settings.MODERATION_CLIP_WEIGHTS}"
    for suffix in WEIGHT_SUFFIXES:
        path = Path(settings.MODERATION_CLIP_DIR) / f"{stem}{suffix}"
        if path.exists():
            return path
    return None


def availability() -> tuple[bool, str]:
    if not settings.MODERATION_CLIP_ENABLED:
        return False, "Проверка фото отключена в настройках"
    if not libraries_installed():
        return False, "Не установлены torch и open_clip (requirements-ml.txt)"
    if weights_path() is None:
        return False, "Не скачаны веса CLIP: python manage.py download_models"
    return True, f"CLIP {settings.MODERATION_CLIP_MODEL} ({settings.MODERATION_CLIP_WEIGHTS})"


_lock = threading.Lock()
_classifier: ImageClassifier | None = None


def load_image_classifier() -> ImageClassifier:
    global _classifier
    if _classifier is not None:
        return _classifier
    ready, reason = availability()
    if not ready:
        raise ImageCheckUnavailable(reason)
    with _lock:
        if _classifier is None:
            try:
                encoder = OpenClipEncoder(
                    settings.MODERATION_CLIP_MODEL,
                    weights_path(),
                    settings.MODERATION_CLIP_THREADS,
                )
            except Exception as exc:
                logger.exception("Не удалось загрузить модель CLIP")
                raise ImageCheckUnavailable(
                    "Модель CLIP не загрузилась, подробности в логе"
                ) from exc
            _classifier = ImageClassifier(encoder)
    return _classifier
