import logging
import time
from dataclasses import dataclass, field

from django.conf import settings
from PIL import Image

from apps.ads.models import Ad

from .ml.images import ImageCheckUnavailable, ImageScore, load_image_classifier
from .ml.text import TextPrediction, load_text_classifier
from .models import RejectionReason, Verdict
from .rules import REJECT, Flag, check_rules

logger = logging.getLogger(__name__)

SELLER_HINTS = {
    RejectionReason.CONTACTS: "Уберите из текста телефон, почту, ссылки и мессенджеры: "
    "покупатели напишут вам через сайт, а телефон показывается по кнопке.",
    RejectionReason.FORBIDDEN: "Такие товары на сайте продавать нельзя, подробнее — в правилах.",
    RejectionReason.PRICE: "Укажите цену, за которую действительно готовы продать.",
    RejectionReason.NOT_ELECTRONICS: "На сайте продают только электронику и аксессуары к ней.",
}


@dataclass(frozen=True)
class PhotoResult:
    photo_id: int
    electronics: float
    label: str


@dataclass
class Inspection:
    flags: list[Flag]
    text: TextPrediction | None = None
    text_error: str = ""
    photos: list[PhotoResult] | None = None
    photo_error: str = ""
    duration_ms: int = 0


@dataclass
class Decision:
    verdict: str
    reasons: list[str] = field(default_factory=list)
    reason_code: str = ""
    message: str = ""
    flagged_photos: set[int] = field(default_factory=set)


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def inspect_text(ad: Ad) -> tuple[TextPrediction | None, str]:
    classifier = load_text_classifier()
    if classifier is None:
        return None, "модель не обучена (python manage.py train_text_classifier)"
    try:
        return classifier.predict(ad.title, ad.description), ""
    except Exception:
        logger.exception("Текстовый классификатор не справился с объявлением %s", ad.pk)
        return None, "ошибка классификатора"


def inspect_photos(ad: Ad) -> tuple[list[PhotoResult] | None, str]:
    if not settings.MODERATION_CLIP_ENABLED:
        return None, ""
    try:
        classifier = load_image_classifier()
    except ImageCheckUnavailable as exc:
        return None, str(exc)
    photos = list(ad.photos.order_by("position", "pk"))
    try:
        images = []
        for photo in photos:
            with photo.thumb.open("rb") as file, Image.open(file) as image:
                images.append(image.convert("RGB"))
        scores: list[ImageScore] = classifier.score(images)
    except Exception:
        logger.exception("Не удалось проверить фото объявления %s", ad.pk)
        return None, "ошибка при обработке фото"
    return [
        PhotoResult(photo.pk, score.electronics, score.label)
        for photo, score in zip(photos, scores, strict=True)
    ], ""


def inspect(ad: Ad) -> Inspection:
    started = time.monotonic()
    inspection = Inspection(flags=check_rules(ad))
    inspection.text, inspection.text_error = inspect_text(ad)
    inspection.photos, inspection.photo_error = inspect_photos(ad)
    inspection.duration_ms = int((time.monotonic() - started) * 1000)
    return inspection


def seller_message(reason_code: str, detail: str = "") -> str:
    parts = [RejectionReason(reason_code).label + "."]
    if detail:
        parts.append(detail)
    hint = SELLER_HINTS.get(reason_code)
    if hint:
        parts.append(hint)
    return " ".join(parts)


def _reject(reason_code: str, detail: str = "") -> Decision:
    return Decision(
        verdict=Verdict.REJECTED,
        reason_code=reason_code,
        message=seller_message(reason_code, detail),
    )


def _root(category):
    return category.parent if category.parent_id else category


def decide(ad: Ad, inspection: Inspection, category_names: dict[str, str]) -> Decision:
    limits = settings.MODERATION_THRESHOLDS
    blocking = [flag for flag in inspection.flags if flag.severity == REJECT]
    if blocking:
        flag = blocking[0]
        if flag.reason == RejectionReason.CONTACTS:
            return _reject(flag.reason, f"Нашли: «{flag.fragment}».")
        return _reject(flag.reason, f"{flag.text}.")

    text, photos = inspection.text, inspection.photos
    text_says_other = text is not None and 1 - text.electronics >= limits["text_other"]
    photos_say_other = bool(photos) and all(
        photo.electronics <= limits["photo_other"] for photo in photos
    )
    if text_says_other and photos_say_other:
        return _reject(RejectionReason.NOT_ELECTRONICS)

    decision = Decision(verdict=Verdict.APPROVED)
    for flag in inspection.flags:
        decision.reasons.append(f"{flag.text}: «{flag.fragment}»" if flag.fragment else flag.text)

    if text is None:
        decision.reasons.append(f"Текст не проверен: {_lower_first(inspection.text_error)}")
    elif text.electronics < limits["text_electronics"]:
        decision.reasons.append(
            f"По тексту не похоже на электронику: уверенность {_percent(1 - text.electronics)}"
        )
    else:
        root = _root(ad.category)
        best = text.best_category
        if best != root.slug and text.probability(root.slug) < limits["category_min"]:
            decision.reasons.append(
                f"По тексту похоже на раздел «{category_names.get(best, best)}», "
                f"а выбран «{root.name}»"
            )

    if photos is None and inspection.photo_error:
        decision.reasons.append(f"Фото не проверены: {_lower_first(inspection.photo_error)}")
    for index, photo in enumerate(photos or [], start=1):
        if photo.electronics < limits["photo_electronics"]:
            decision.flagged_photos.add(photo.photo_id)
            decision.reasons.append(
                f"Фото {index} не похоже на технику: скорее «{photo.label}», "
                f"техника {_percent(photo.electronics)}"
            )

    if decision.reasons:
        decision.verdict = Verdict.MANUAL
    return decision
