from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF", "GIF", "MPO"}
MAX_PIXELS = 50_000_000


def open_image(uploaded) -> Image.Image:
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise ValidationError("Файл больше 15 МБ.", code="too_large")
    try:
        uploaded.seek(0)
        image = Image.open(uploaded)
        if image.format not in ALLOWED_FORMATS:
            raise ValidationError("Поддерживаются JPEG, PNG, WebP и HEIC.", code="invalid_format")
        if image.width * image.height > MAX_PIXELS:
            raise ValidationError("Слишком большое изображение.", code="too_large")
        image.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValidationError("Не удалось прочитать изображение.", code="invalid_image") from exc
    return ImageOps.exif_transpose(image)


def to_webp(image: Image.Image, *, quality: int = 82) -> ContentFile:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, "WEBP", quality=quality, method=6)
    return ContentFile(buffer.getvalue())


def fit_within(image: Image.Image, size: int) -> Image.Image:
    copy = image.copy()
    copy.thumbnail((size, size), Image.LANCZOS)
    return copy
