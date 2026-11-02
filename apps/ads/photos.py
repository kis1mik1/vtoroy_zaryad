import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.images import fit_within, open_image, to_webp

from .models import MAX_PHOTOS, AdPhoto

IMAGE_SIZE = 1600
THUMB_SIZE = 480
ORPHAN_TTL = timedelta(days=1)


def upload_photo(owner, uploaded) -> AdPhoto:
    image = open_image(uploaded)
    if min(image.size) < 200:
        raise ValidationError(
            "Фото слишком маленькое: нужно хотя бы 200 пикселей по короткой стороне."
        )
    name = f"{secrets.token_hex(10)}.webp"
    large = fit_within(image, IMAGE_SIZE)
    photo = AdPhoto(owner=owner, width=large.width, height=large.height)
    photo.image.save(name, to_webp(large), save=False)
    photo.thumb.save(name, to_webp(fit_within(image, THUMB_SIZE), quality=78), save=False)
    photo.save()
    return photo


def delete_photo_files(photo: AdPhoto) -> None:
    storage = photo.image.storage
    for name in (photo.image.name, photo.thumb.name):
        if name:
            transaction.on_commit(lambda name=name: storage.delete(name))


def resolve_photos(owner, ids, ad=None) -> list[AdPhoto]:
    try:
        ordered = list(dict.fromkeys(int(pk) for pk in ids))
    except (TypeError, ValueError) as exc:
        raise ValidationError("Не удалось прочитать список фото.") from exc
    if len(ordered) > MAX_PHOTOS:
        raise ValidationError(f"Можно добавить не больше {MAX_PHOTOS} фото.")
    photos = {
        photo.pk: photo
        for photo in AdPhoto.objects.filter(pk__in=ordered, owner=owner)
        if photo.ad_id is None or (ad is not None and photo.ad_id == ad.pk)
    }
    missing = [pk for pk in ordered if pk not in photos]
    if missing:
        raise ValidationError("Некоторые фото не найдены. Загрузите их ещё раз.")
    return [photos[pk] for pk in ordered]


def attach_photos(ad, photos: list[AdPhoto]) -> bool:
    keep = {photo.pk for photo in photos}
    before = list(ad.photos.values_list("pk", flat=True)) if ad.pk else []
    AdPhoto.objects.filter(ad=ad).exclude(pk__in=keep).delete()
    for position, photo in enumerate(photos):
        if photo.ad_id != ad.pk or photo.position != position:
            photo.ad = ad
            photo.position = position
            photo.save(update_fields=["ad", "position"])
    return set(before) != keep


def remove_orphans() -> int:
    deleted, _ = AdPhoto.objects.filter(
        ad__isnull=True, created_at__lt=timezone.now() - ORPHAN_TTL
    ).delete()
    return deleted
