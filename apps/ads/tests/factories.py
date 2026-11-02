from io import BytesIO

import factory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from apps.accounts.tests.factories import UserFactory
from apps.ads.models import Ad, AdStatus, Condition, ConditionReport
from apps.ads.photos import upload_photo
from apps.catalog.tests.factories import CategoryFactory
from apps.core.models import City


def image_upload(size=(800, 600), color=(30, 90, 200), name="photo.jpg"):
    buffer = BytesIO()
    Image.new("RGB", size, color).save(buffer, "JPEG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/jpeg")


def make_photo(owner, **kwargs):
    return upload_photo(owner, image_upload(**kwargs))


class AdFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Ad
        skip_postgeneration_save = True

    seller = factory.SubFactory(UserFactory)
    category = factory.SubFactory(CategoryFactory)
    title = factory.Sequence(lambda n: f"Ноутбук {n}")
    slug = factory.Sequence(lambda n: f"noutbuk-{n}")
    description = "Работает отлично, батарея держит полдня, в комплекте зарядка."
    price = 25_000
    condition = Condition.USED
    city = factory.LazyFunction(lambda: City.objects.get(slug="vladivostok"))
    status = AdStatus.ACTIVE
    published_at = factory.LazyFunction(timezone.now)
    bumped_at = factory.SelfAttribute("published_at")

    @factory.post_generation
    def report(obj, create, extracted, **kwargs):
        if create:
            ConditionReport.objects.create(ad=obj, body_state="minor")
