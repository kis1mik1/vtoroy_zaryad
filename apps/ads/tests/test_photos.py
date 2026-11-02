import pytest
from django.core.exceptions import ValidationError
from PIL import Image

from apps.accounts.tests.factories import UserFactory
from apps.ads.models import AdPhoto
from apps.ads.photos import resolve_photos, upload_photo

from .factories import AdFactory, image_upload, make_photo

pytestmark = pytest.mark.django_db


def test_upload_creates_webp_image_and_thumb():
    photo = upload_photo(UserFactory(), image_upload(size=(4000, 3000)))

    with photo.image.open() as stored:
        image = Image.open(stored)
        assert image.format == "WEBP"
        assert image.size == (1600, 1200)
    with photo.thumb.open() as stored:
        assert Image.open(stored).size == (480, 360)
    assert (photo.width, photo.height) == (1600, 1200)


def test_too_small_photo_rejected():
    with pytest.raises(ValidationError, match="маленькое"):
        upload_photo(UserFactory(), image_upload(size=(150, 150)))


def test_resolve_keeps_order_and_drops_duplicates():
    owner = UserFactory()
    first, second = make_photo(owner), make_photo(owner)

    photos = resolve_photos(owner, [str(second.pk), str(first.pk), str(second.pk)])

    assert photos == [second, first]


def test_resolve_rejects_foreign_and_attached_photos():
    owner = UserFactory()
    foreign = make_photo(UserFactory())
    attached = make_photo(owner)
    attached.ad = AdFactory(seller=owner)
    attached.save()

    with pytest.raises(ValidationError):
        resolve_photos(owner, [foreign.pk])
    with pytest.raises(ValidationError):
        resolve_photos(owner, [attached.pk])
    assert resolve_photos(owner, [attached.pk], ad=attached.ad) == [attached]


def test_resolve_limits_count():
    owner = UserFactory()
    photos = [make_photo(owner, size=(300, 300)) for _ in range(11)]

    with pytest.raises(ValidationError, match="не больше 10"):
        resolve_photos(owner, [p.pk for p in photos])


def test_files_deleted_with_photo(run_on_commit):
    photo = make_photo(UserFactory())
    storage, names = photo.image.storage, [photo.image.name, photo.thumb.name]

    with run_on_commit():
        AdPhoto.objects.filter(pk=photo.pk).delete()

    assert not any(storage.exists(name) for name in names)
