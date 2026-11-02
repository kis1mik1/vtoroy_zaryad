import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.core.models import City

PASSWORD = "Secret-pass-42"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name", locale="ru_RU")
    city = factory.LazyFunction(lambda: City.objects.get(slug="vladivostok"))
    email_verified_at = factory.LazyFunction(timezone.now)
    password = factory.PostGenerationMethodCall("set_password", PASSWORD)

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):
        if create:
            obj.save()

    class Params:
        unverified = factory.Trait(email_verified_at=None)
