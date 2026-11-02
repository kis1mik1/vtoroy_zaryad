import factory

from apps.accounts.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    first_name = factory.Faker("first_name", locale="ru_RU")
    password = factory.PostGenerationMethodCall("set_password", "Secret-pass-42")

    @factory.post_generation
    def _save(obj, create, extracted, **kwargs):
        if create:
            obj.save()
