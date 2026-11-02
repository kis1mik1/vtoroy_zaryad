from django.core.files.base import ContentFile
from PIL import Image, ImageOps

from apps.core.images import open_image, to_webp

AVATAR_SIZE = 400


def make_avatar(uploaded) -> ContentFile:
    image = open_image(uploaded).convert("RGB")
    return to_webp(ImageOps.fit(image, (AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS), quality=85)
